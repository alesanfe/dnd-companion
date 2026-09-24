"""D&D Companion backend — FastAPI entrypoint."""
from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .api import campaigns, characters, content, dice, operations
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
app.include_router(dice.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/campaign/{campaign_id}")
async def campaign_ws(websocket: WebSocket, campaign_id: str):
    await manager.join(campaign_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            # TODO: parse Operation, apply via engine, persist, broadcast Event
            await websocket.send_text(raw)
    except WebSocketDisconnect:
        manager.leave(campaign_id, websocket)
