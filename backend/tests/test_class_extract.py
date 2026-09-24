"""Extracción de hit_die/saves multi-schema en create_from_options."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.characters import _hit_die, _save_profs    # noqa: E402


def test_hit_die_schemas():
    assert _hit_die({"hit_die": 12}) == 12                  # 5e-bits
    assert _hit_die({"hd": {"number": 1, "faces": 12}}) == 12  # 5etools
    assert _hit_die({"hit_dice": "1d10"}) == 10             # open5e v1
    assert _hit_die({"hitDie": "8"}) == 8                   # codexMUNDI
    assert _hit_die({"properties": {"Hit Dice": "d6"}}) == 6   # dnd-data
    assert _hit_die({}) == 8                                # fallback


def test_save_profs_schemas():
    # 5e-bits
    assert _save_profs({"saving_throws": [{"index": "str"},
                                          {"index": "con"}]}) \
        == ["str", "con"]
    # 5etools
    assert _save_profs({"proficiency": ["str", "con"]}) == ["str", "con"]
    # open5e v1 (string separada por comas)
    assert _save_profs({"prof_saving_throws": "Strength, Constitution"}) \
        == ["str", "con"]
    # codexMUNDI
    assert _save_profs({"saves": "Str, Con"}) == ["str", "con"]
    assert _save_profs({}) == []
