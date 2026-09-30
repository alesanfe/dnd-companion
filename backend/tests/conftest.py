"""Shared fixtures: a temp state DB per session, content DB optional."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault(
    "DND_STATE_DB", str(Path(tempfile.mkdtemp()) / "state.sqlite3"))
if "DND_CONTENT_DB" not in os.environ:
    # los tests instalan/desinstalan packs (pkg:*): NUNCA sobre la DB
    # del usuario — se copia el corpus real una vez por sesión
    real = (Path(__file__).resolve().parents[2] / "data"
            / "content.sqlite3")
    tmp_cdb = Path(tempfile.mkdtemp()) / "content.sqlite3"
    if real.exists():
        shutil.copy(real, tmp_cdb)
    os.environ["DND_CONTENT_DB"] = str(tmp_cdb)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
