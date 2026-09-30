"""Sync model — every state change is an identifiable, idempotent,
reversible operation; WS carries small typed events. §10 of ARCHITECTURE."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OperationStatus(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    REJECTED = "rejected"
    CONFLICT = "conflict"
    # resolución manual desde la UI de conflictos
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Operation(BaseModel):
    """Client-submitted state change. entity_version gives optimistic
    locking; operation_id gives idempotency on reconnect/retry."""
    operation_id: str
    entity_id: str
    entity_version: int
    client_id: str
    user_id: str
    timestamp: datetime
    operation_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class EventType(str, Enum):
    CHARACTER_HP_CHANGED = "character.hp.changed"
    CHARACTER_CONDITION_APPLIED = "character.condition.applied"
    CHARACTER_CONDITION_REMOVED = "character.condition.removed"
    CHARACTER_CONDITION_IMMUNE = "character.condition.immune"
    COMBAT_TURN_ADVANCED = "combat.turn.advanced"
    COMBAT_STARTED = "combat.started"
    COMBAT_ENDED = "combat.ended"
    DICE_ROLL_CREATED = "dice.roll.created"
    INVENTORY_ITEM_TRANSFERRED = "inventory.item.transferred"
    RESOURCE_USAGE_CHANGED = "resource.usage.changed"
    ROLL_REQUESTED = "dice.roll.requested"          # DM pide tirada a jugador
    ENTITY_REVEALED = "campaign.entity.revealed"    # DM revela entidad
    ENTITY_UPDATED = "campaign.entity.updated"      # alta/cambio/borrado
    MAP_PING = "campaign.map.ping"                      # ping efímero VTT
    PRESENT = "campaign.present"          # el DM proyecta una entidad
    # restauraciones de undo + cargas de objetos — emitidas por el
    # engine (ops.py / combat_ops.py); sin el miembro el constructor
    # EventType(...) lanzaba ValueError → 500 tras rollback
    INVENTORY_ITEM_CHARGED = "inventory.item.charged"
    CHARACTER_STATE_RESTORED = "character.state.restored"
    COMBAT_STATE_RESTORED = "combat.state.restored"
    COMBATANT_DELEGATED = "combatant.delegated"      # DM cede un NPC
    # PATCH/DELETE de ficha (nombre, campaña, player_id): sin él los
    # otros sockets (misma ficha en otro dispositivo, lista del DM)
    # no se enteraban del cambio
    CHARACTER_UPDATED = "character.updated"


class Event(BaseModel):
    event_id: str
    type: EventType
    campaign_id: str
    aggregate_id: str
    aggregate_version: int
    actor_id: str
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class Role(str, Enum):
    OWNER = "owner"                # propietario de la campaña
    CO_DM = "co_dm"                # codirector
    PLAYER = "player"
    GUEST = "guest"
    SPECTATOR = "spectator"
    DELEGATED_NPC = "delegated_npc"  # NPC controlado por un jugador
