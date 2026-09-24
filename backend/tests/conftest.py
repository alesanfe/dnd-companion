"""Shared fixtures: a temp state DB per session, content DB optional."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault(
    "DND_STATE_DB", str(Path(tempfile.mkdtemp()) / "state.sqlite3"))
os.environ.setdefault(
    "DND_CONTENT_DB",
    str(Path(__file__).resolve().parents[2] / "data" / "content.sqlite3"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
