"""Extractores multi-schema de clase/especie/trasfondo
(domain/classinfo.py) — cada fuente importada guarda el mismo dato
con claves distintas; estos tests fijan el comportamiento."""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import classinfo                     # noqa: E402


def test_hit_die_multi_schema():
    assert classinfo.hit_die({"hit_die": 12}) == 12          # 5e-bits
    assert classinfo.hit_die({"hd": {"faces": 8}}) == 8      # 5etools
    assert classinfo.hit_die({"hit_dice": "1d10"}) == 10     # open5e
    assert classinfo.hit_die({"hitDie": "d6"}) == 6          # codexMUNDI
    assert classinfo.hit_die({}) == 8                        # fallback


def test_save_profs_multi_schema():
    d = {"saving_throws": [{"index": "str"}, {"name": "Wisdom"}]}
    assert classinfo.save_profs(d) == ["str", "wis"]
    d2 = {"prof_saving_throws": "STR, CON"}
    assert classinfo.save_profs(d2) == ["str", "con"]
    assert classinfo.save_profs({"saves": "dex"}) == ["dex"]
    assert classinfo.save_profs({}) == []


def test_species_asi():
    d = {"ability_bonuses": [
            {"ability_score": {"index": "con"}, "bonus": 2}],
         "ability": [{"str": 1, "choose": 1}]}
    assert classinfo.species_asi(d) == {"con": 2, "str": 1}
    assert classinfo.species_asi({}) == {}


def test_spellcasting_ability():
    assert classinfo.spellcasting_ability(
        {"spellcasting": {"spellcasting_ability": {"index": "wis"}}}
    ) == "wis"
    assert classinfo.spellcasting_ability(
        {"spellcastingAbility": "int"}) == "int"
    assert classinfo.spellcasting_ability(
        {"casting_ability": "Charisma"}) == "cha"
    assert classinfo.spellcasting_ability({}) is None
    assert classinfo.spellcasting_ability(
        {"spellcasting": {"spellcasting_ability": {"index": "??"}}}
    ) is None


def test_species_traits():
    d = {"traits": [{"name": "Visión nocturna"}, "Olímpico"],
         "entries": [{"name": "Sentidos agudos"}, {"noName": 1}]}
    assert classinfo.species_traits(d) == [
        "Visión nocturna", "Olímpico", "Sentidos agudos"]


def test_background_languages_and_skills():
    bg = {"languageProficiencies": [{"common": True, "choose": 1}],
          "languages": ["Orco"]}
    assert classinfo.background_languages(bg) == ["common", "Orco"]
    bg2 = {"starting_proficiencies": [{"name": "Skill: Persuasión"}],
           "skillProficiencies": [{"stealth": True, "choose": 2}]}
    assert classinfo.background_skills(bg2) == ["persuasión", "stealth"]
