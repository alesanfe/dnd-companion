"""Web Push (VAPID) — notificaciones PWA con la app en segundo plano.

Las claves VAPID se generan una vez y se guardan en app_meta (state
DB, nunca al repo). POST /subscribe guarda endpoint+claves del
navegador; send_push() se llama desde los handlers que quieren
notificar (p. ej. roll-request dirigido)."""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db.connections import state_db
from .auth import optional_user

log = logging.getLogger("push")
router = APIRouter(prefix="/api/push", tags=["push"])


def _vapid() -> tuple[str, str] | tuple[None, None]:
    """(private_pem, public_b64url) — genera y persiste si falta."""
    try:
        from py_vapid import Vapid  # dep opcional
    except ImportError:
        return None, None
    conn = state_db()
    rows = dict(conn.execute("SELECT k, v FROM app_meta").fetchall())
    priv, pub = rows.get("vapid_priv"), rows.get("vapid_pub")
    if not priv or not pub:
        v = Vapid()
        v.generate_keys()
        from cryptography.hazmat.primitives import serialization
        priv = v.private_pem().decode()
        pub_raw = v.public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint)
        pub = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode()
        conn.execute("INSERT OR REPLACE INTO app_meta (k,v) "
                     "VALUES ('vapid_priv',?),('vapid_pub',?)",
                     (priv, pub))
        conn.commit()
    return priv, pub


@router.get("/vapid-key")
def vapid_key():
    """La clave pública que el navegador pasa a PushManager.subscribe."""
    _, pub = _vapid()
    if pub is None:
        raise HTTPException(501, "pywebpush no instalado")
    return {"public_key": pub}


class SubIn(BaseModel):
    endpoint: str
    keys: dict                     # {"p256dh": "…", "auth": "…"}


@router.post("/subscribe", status_code=201)
def subscribe(body: SubIn, user: dict | None = Depends(optional_user)):
    if not body.keys.get("p256dh") or not body.keys.get("auth"):
        raise HTTPException(400, "faltan claves p256dh/auth")
    conn = state_db()
    conn.execute(
        """INSERT OR REPLACE INTO push_subscriptions
           (endpoint, user_id, p256dh, auth, created_at)
           VALUES (?,?,?,?,?)""",
        (body.endpoint[:2000], (user or {}).get("user_id"),
         body.keys["p256dh"], body.keys["auth"],
         datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return {"ok": True}


@router.post("/unsubscribe")
def unsubscribe(body: SubIn):
    conn = state_db()
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?",
                 (body.endpoint,))
    conn.commit()
    return {"ok": True}


def send_push(user_id: str | None, title: str, body: str,
              url: str = "/") -> int:
    """Envía a todas las suscripciones del usuario. Devuelve envíos.
    Las suscripciones muertas (410) se purgan — sin warning ruidoso."""
    priv, _ = _vapid()
    if priv is None or user_id is None:
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return 0
    conn = state_db()
    subs = conn.execute(
        "SELECT * FROM push_subscriptions WHERE user_id = ?",
        (user_id,)).fetchall()
    sent = 0
    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s["endpoint"],
                    "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                data=json.dumps({"title": title, "body": body,
                                 "url": url}),
                vapid_private_key=priv,
                vapid_claims={"sub": "mailto:dnd-companion@localhost"})
            sent += 1
        except WebPushException as e:
            # 404/410 = suscripción caducada → limpiarla
            if getattr(e.response, "status_code", 0) in (404, 410):
                conn.execute(
                    "DELETE FROM push_subscriptions WHERE endpoint = ?",
                    (s["endpoint"],))
                conn.commit()
            else:
                log.warning("push a %s falló: %s",
                            s["endpoint"][:40], e)
        except Exception as e:  # red caída — no romper el handler
            log.warning("push error: %s", e)
    return sent
