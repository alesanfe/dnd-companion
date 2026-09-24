"""Settings via environment. Content DB (rules) and state DB (games)
are separate on purpose — see docs/ARCHITECTURE.md §1."""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DND_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
CONTENT_DB = Path(os.environ.get("DND_CONTENT_DB", DATA_DIR / "content.sqlite3"))
STATE_DB = Path(os.environ.get("DND_STATE_DB", DATA_DIR / "state.sqlite3"))
