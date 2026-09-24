"""Auth — cuentas locales con tokens opacos.

- register/login emiten un token Bearer (auth_tokens, expira a 30 días).
- `current_user` resuelve el token; `optional_user` no exige login
  (la app sigue funcionando local/anónima offline).
- Roles de campaña en `members` (owner|co_dm|player|guest|spectator).
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from ..db.connections import state_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

_TOKEN_TTL_DAYS = 30


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 100_000
    ).hex()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Credentials(BaseModel):
    username: str
    password: str


@router.post("/register", status_code=201)
def register(body: Credentials):
    conn = state_db()
    if conn.execute("SELECT 1 FROM users WHERE username = ?",
                    (body.username,)).fetchone():
        raise HTTPException(409, "username already taken")
    uid, salt = uuid.uuid4().hex, secrets.token_hex(16)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, salt, created_at) "
        "VALUES (?,?,?,?,?)",
        (uid, body.username, _hash(body.password, salt), salt, _now()))
    conn.commit()
    return {"user_id": uid, "token": _issue(conn, uid)}


# throttle de login en memoria: max 5 intentos/min por usuario
_login_attempts: dict[str, list[float]] = {}


def _throttle(username: str) -> None:
    import time
    now = time.time()
    tries = [t for t in _login_attempts.get(username, [])
             if now - t < 60]
    if len(tries) >= 5:
        raise HTTPException(429, "demasiados intentos; espera un minuto")
    tries.append(now)
    _login_attempts[username] = tries


@router.post("/login")
def login(body: Credentials):
    _throttle(body.username)
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (body.username,)
    ).fetchone()
    if row is None or row["password_hash"] != _hash(body.password,
                                                  row["salt"]):
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
