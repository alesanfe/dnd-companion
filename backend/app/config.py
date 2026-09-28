"""Settings via environment. Content DB (rules) and state DB (games)
are separate on purpose — see docs/ARCHITECTURE.md §1."""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DND_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
CONTENT_DB = Path(os.environ.get("DND_CONTENT_DB", DATA_DIR / "content.sqlite3"))
STATE_DB = Path(os.environ.get("DND_STATE_DB", DATA_DIR / "state.sqlite3"))

# versión de la app — los packs declaran required_app_version y el
# install la contrasta aquí (semver simple "x.y.z")
APP_VERSION = os.environ.get("DND_APP_VERSION", "0.1.0")
