"""Content provenance — every spell/monster/rule knows where it came from
and whether it may be redistributed. See docs/ARCHITECTURE.md §2."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ContentSource(BaseModel):
    id: str
    name: str
    version: str | None = None
    license: str
    attribution_text: str | None = None
    original_url: str | None = None
    imported_at: datetime | None = None
    content_hash: str | None = None
    distribution_allowed: bool = False


class Provenance(BaseModel):
    source_id: str
    source_document: str | None = None
    source_version: str | None = None
    source_page: str | None = None
    license: str
    is_redistributable: bool = False
