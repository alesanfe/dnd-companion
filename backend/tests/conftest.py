"""Shared fixtures: a temp state DB per session, content DB optional."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_tmpdirs = []


def _tmpdir() -> Path:
    d = Path(tempfile.mkdtemp())
    _tmpdirs.append(d)
    return d


# cada sesión copiaba ~1,3 GB (content DB) y ~MB de state a un tmp
# sin borrar — 22 runs dejaban 19 GB de basura en el disco del usuario
@atexit.register
def _cleanup_tmpdirs():
    for d in _tmpdirs:
        shutil.rmtree(d, ignore_errors=True)


os.environ.setdefault(
    "DND_STATE_DB", str(_tmpdir() / "state.sqlite3"))
if "DND_CONTENT_DB" not in os.environ:
    # los tests instalan/desinstalan packs (pkg:*): NUNCA sobre la DB
    # del usuario — se copia el corpus real una vez por sesión
    real = (Path(__file__).resolve().parents[2] / "data"
            / "content.sqlite3")
    tmp_cdb = _tmpdir() / "content.sqlite3"
    if real.exists():
        shutil.copy(real, tmp_cdb)
    os.environ["DND_CONTENT_DB"] = str(tmp_cdb)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
