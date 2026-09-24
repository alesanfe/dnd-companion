"""Normalizador de stat blocks — todos los schemas de fuente."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import statblock                    # noqa: E402


def test_5e_bits_schema():
    d = {"name": "Aboleth", "hit_points": 135,
         "armor_class": [{"type": "natural", "value": 17}],
         "strength": 21, "dexterity": 9, "constitution": 15,
         "intelligence": 18, "wisdom": 15, "charisma": 18,
         "challenge_rating": 10, "wisdom_save": 6,
         "speed": {"walk": "10 ft."},
         "actions": [{"name": "Tentacle", "desc": "hit stuff"}]}
    b = statblock.normalize(d)
    assert b["hp"] == 135 and b["ac"] == 17 and b["cr"] == 10
    assert b["abilities"]["str"] == 21
    assert b["saves"]["wis"] == 6            # save explícita
    assert b["saves"]["str"] == 5            # mod por defecto
    assert b["initiative_mod"] == -1
    assert b["actions"][0]["text"] == "hit stuff"
    assert b["raw"] is d


def test_open5e_v1_schema():
    d = {"name": "Nihilith", "hit_points": 135, "armor_class": 17,
         "strength": 21, "dexterity": 9, "constitution": 15,
         "intelligence": 18, "wisdom": 15, "charisma": 18,
         "cr": 12.0, "speed": {"walk": 10, "swim": 40}}
    b = statblock.normalize(d)
    assert (b["hp"], b["ac"], b["cr"]) == (135, 17, 12.0)
    assert b["speed"] == "walk 10 ft., swim 40 ft."


def test_open5e_v2_schema():
    d = {"name": "Aboleth", "hit_points": 150, "armor_class": 17,
         "challenge_rating": 10.0,
         "ability_scores": {"strength": 21, "dexterity": 9,
                            "constitution": 15, "intelligence": 18,
                            "wisdom": 15, "charisma": 18},
         "saving_throws": {"intelligence": 8}}
    b = statblock.normalize(d)
    assert b["abilities"]["int"] == 18
    assert b["saves"]["int"] == 8            # total de v2
    assert b["saves"]["cha"] == 4            # mod derivado


def test_5etools_schema():
    d = {"name": "Oracle", "hp": {"average": 18, "formula": "4d8"},
         "ac": [12], "str": 10, "dex": 14, "con": 12, "int": 16,
         "wis": 13, "cha": 11, "cr": "1",
         "save": {"dex": "+4"},
         "speed": {"walk": 30},
         "action": [{"name": "Dagger",
                     "entries": ["{@atk mw} {@hit 2} to hit. "
                                 "{@h}2 ({@damage 1d4}) piercing."]}]}
    b = statblock.normalize(d)
    assert (b["hp"], b["ac"], b["cr"]) == (18, 12, 1.0)
    assert b["saves"]["dex"] == 4            # "+4" explícito
    assert b["initiative_mod"] == 2
    assert "1d4" in b["actions"][0]["text"]
    assert "{@" not in b["actions"][0]["text"]     # tags expandidos


def test_codexmundi_schema():
    d = {"name": "Aarakocra", "hp": "13 (3d8)", "ac": "12",
         "str": 10, "dex": 14, "con": 10, "int": 11, "wis": 12,
         "cha": 11, "cr": "1/4", "speed": "20 ft., fly 50 ft.",
         "action": [{"name": "Talon", "text": "+4 to hit."}]}
    b = statblock.normalize(d)
    assert (b["hp"], b["ac"], b["cr"]) == (13, 12, 0.25)
    assert b["speed"] == "20 ft., fly 50 ft."


def test_dnd_data_schema():
    d = {"name": "A-mi-kuk", "properties": {
        "Challenge Rating": 7, "Hit Points": "95",
        "Armor Class": "15"}}
    b = statblock.normalize(d)
    assert (b["hp"], b["ac"], b["cr"]) == (95, 15, 7.0)
    assert b["abilities"]["str"] == 10       # default


def test_normalize_empty():
    assert statblock.normalize(None) is None
    assert statblock.normalize({}) is None
