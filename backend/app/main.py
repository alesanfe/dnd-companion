"""D&D Companion backend — FastAPI entrypoint."""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    campaigns, characters, combat, content, dice, encounters,
    inventory, operations, packages, rules,
)
from .api.operations import OperationIn, apply_to_store
from .ws.rooms import manager

app = FastAPI(title="D&D Companion", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(content.router)
app.include_router(characters.router)
app.include_router(campaigns.router)
app.include_router(operations.router)
app.include_router(combat.router)
app.include_router(encounters.router)
app.include_router(inventory.router)
app.include_router(packages.router)
app.include_router(rules.router)
app.include_router(dice.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/campaign/{campaign_id}")
async def campaign_ws(websocket: WebSocket, campaign_id: str):
    """Sala de campaña. Protocolo:
      → {"type": "operation", "operation": {...OperationIn}}
      → {"type": "ping"}
      ← {"type": "event", "event": {...}}  broadcast a la sala
      ← {"type": "ack", "operation_id", "version"} | {"type": "error", ...}
    """
    await manager.join(campaign_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps({"type": "error", "detail": "invalid json"}))
                continue

            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            if msg.get("type") == "operation":
                try:
                    op = OperationIn(**msg["operation"])
                    result = apply_to_store(op)
                except HTTPException as exc:
                    await websocket.send_text(json.dumps(
                        {"type": "error", "detail": exc.detail}))
                    continue
                except (KeyError, ValueError) as exc:
                    await websocket.send_text(json.dumps(
                        {"type": "error", "detail": str(exc)}))
                    continue
                await websocket.send_text(json.dumps(
                    {"type": "ack", "operation_id": result["operation_id"],
                     "version": result["version"],
                     "duplicate": result["duplicate"]}))
                for event in result.pop("_event_objs", []):
                    await manager.broadcast(campaign_id, event)
                continue

            await websocket.send_text(
                json.dumps({"type": "error", "detail": "unknown message"}))
    except WebSocketDisconnect:
        manager.leave(campaign_id, websocket)
