"""Auth — cuentas locales con tokens opacos.

- register/login emiten un token Bearer (auth_tokens, expira a 30 días).
- `current_user` resuelve el token; `optional_user` no exige login
  (la app sigue funcionando local/anónima offline).
- Roles de campaña en `members` (owner|co_dm|player|guest|spectator).
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from ..db.connections import state_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

_TOKEN_TTL_DAYS = 30
# OWASP ~600k para PBKDF2-HMAC-SHA256 (era 100k) — los hashes viejos
# se migran perezosamente al primer login correcto
_HASH_ITER = 600_000
_HASH_ITER_LEGACY = 100_000


def _hash(password: str, salt: str,
          iterations: int = _HASH_ITER) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), iterations
    ).hex()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def _trimmed(cls, v: str) -> str:
        # el min_length valida el valor EN BRUTO — "  a" (4 chars)
        # pasaba y quedaba almacenado un username de 1 char
        v = v.strip()
        if len(v) < 3:
            raise ValueError("username demasiado corto")
        return v


@router.post("/register", status_code=201)
def register(body: Credentials, request: Request):
    # DND_ALLOW_REGISTRATION=0 cierra el alta (servidor expuesto) —
    # sin el flag cualquiera creaba cuentas en una instancia privada
    if os.environ.get("DND_ALLOW_REGISTRATION", "1").lower() \
            not in ("1", "true", "yes"):
        raise HTTPException(403, "registro desactivado")
    _throttle(f"reg:{request.client.host if request.client else '?'}")
    username = body.username
    conn = state_db()
    if conn.execute("SELECT 1 FROM users WHERE username = ?",
                    (username,)).fetchone():
        raise HTTPException(409, "username already taken")
    uid, salt = uuid.uuid4().hex, secrets.token_hex(16)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, salt, created_at) "
        "VALUES (?,?,?,?,?)",
        (uid, username, _hash(body.password, salt), salt, _now()))
    conn.commit()
    return {"user_id": uid, "token": _issue(conn, uid)}


# throttle persistente en state DB: max 5 intentos/min por clave
# (usuario en login, IP en register). En memoria se reseteaba al
# reiniciar y era por-proceso → N workers = 5×N intentos reales.
def _throttle(key: str) -> None:
    # TestClient comparte una única IP: sin el bypass la suite de
    # tests tropezaría con su propio rate-limit
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    now = time.time()
    conn = state_db()
    row = conn.execute(
        "SELECT tries, window_start FROM auth_throttle WHERE k = ?",
        (key,)).fetchone()
    fresh = row is None or now - row["window_start"] > 60
    if not fresh and row["tries"] >= 5:
        raise HTTPException(429, "demasiados intentos; espera un minuto")
    conn.execute(
        "INSERT OR REPLACE INTO auth_throttle"
        " (k, tries, window_start) VALUES (?,?,?)",
        (key, 1 if fresh else row["tries"] + 1,
         now if fresh else row["window_start"]))
    # GC perezosa: purga ventanas viejas para que la tabla no crezca
    conn.execute(
        "DELETE FROM auth_throttle WHERE ? - window_start > 300",
        (now,))
    conn.commit()


@router.post("/login")
def login(body: Credentials, request: Request):
    # dos cubos: por usuario (normalizado — " admin" no evade el de
    # "admin") y por IP (rotar usernames tampoco evade)
    _throttle(f"login:{body.username.lower()}")
    _throttle(
        f"login-ip:{request.client.host if request.client else '?'}")
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (body.username,)
    ).fetchone()
    ok = row is not None and secrets.compare_digest(
        row["password_hash"], _hash(body.password, row["salt"]))
    if not ok and row is not None:
        # hashes anteriores al bump de iteraciones: verifica con el
        # factor viejo y migra perezosamente al nuevo
        if secrets.compare_digest(
                row["password_hash"],
                _hash(body.password, row["salt"], _HASH_ITER_LEGACY)):
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (_hash(body.password, row["salt"]), row["id"]))
            conn.commit()
            ok = True
    if not ok:
        raise HTTPException(401, "invalid credentials")
    return {"user_id": row["id"], "token": _issue(conn, row["id"])}


@router.post("/logout")
def logout(authorization: str | None = Header(None)):
    """Revoca el token actual."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token:
        conn = state_db()
        conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
        conn.commit()
    return {"ok": True}


def _issue(conn, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    # GC perezosa: cada emisión barre los tokens caducados — la tabla
    # no crece sin límite con sesiones abandonadas
    conn.execute("DELETE FROM auth_tokens WHERE expires_at <= ?",
                 (_now(),))
    conn.execute(
        "INSERT INTO auth_tokens (token, user_id, created_at, expires_at) "
        "VALUES (?,?,?,?)",
        (token, user_id, _now(),
         (datetime.now(timezone.utc)
          + timedelta(days=_TOKEN_TTL_DAYS)).isoformat()))
    conn.commit()
    return token


def user_from_token(token: str | None) -> dict | None:
    if not token:
        return None
    conn = state_db()
    row = conn.execute(
        """SELECT t.user_id, u.username FROM auth_tokens t
           JOIN users u ON u.id = t.user_id
           WHERE t.token = ? AND t.expires_at > ?""",
        (token, _now())).fetchone()
    return dict(row) if row else None


def current_user(authorization: str | None = Header(None)) -> dict:
    """Dependencia: exige Bearer token válido."""
    token = (authorization or "").removeprefix("Bearer ").strip() or None
    user = user_from_token(token)
    if user is None:
        raise HTTPException(401, "authentication required")
    return user


def optional_user(authorization: str | None = Header(None)) -> dict | None:
    token = (authorization or "").removeprefix("Bearer ").strip() or None
    return user_from_token(token)


def member_role(campaign_id: str, user_id: str | None) -> str | None:
    """Rol del usuario en la campaña (None si no es miembro / anónimo)."""
    if not user_id:
        return None
    conn = state_db()
    row = conn.execute(
        "SELECT role FROM members WHERE campaign_id = ? AND user_id = ?",
        (campaign_id, user_id)).fetchone()
    if row:
        return row["role"]
    owner = conn.execute(
        "SELECT owner_id FROM campaigns WHERE id = ?",
        (campaign_id,)).fetchone()
    if owner and owner["owner_id"] == user_id:
        return "owner"
    return None


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user
