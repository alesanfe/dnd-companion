"""Calculadora de dificultad de encuentro (api/encounters + domain/xp):
umbrales 2014, multiplicador por nº de monstruos y avisos de diseño."""
from fastapi.testclient import TestClient

from app.main import app
from app.domain.xp import (cr_to_xp, encounter_multiplier,
                           encounter_threshold, level_xp_table)

client = TestClient(app)


def test_difficulty_budget_and_rating():
    # 4×PJ nv.1: easy 100 / medium 200 / hard 300 / deadly 400
    r = client.post("/api/encounters/difficulty",
                    json={"party_levels": [1, 1, 1, 1],
                          "monster_crs": ["1", "1"]})
    d = r.json()
    assert d["budget"]["easy"] == 100 and d["budget"]["deadly"] == 400
    # 2 monstruos CR1 = 200×2 = 400 raw → ×1.5 = 600 ajustado → deadly
    assert d["raw_xp"] == 400
    assert d["adjusted_xp"] == 600
    assert d["rating"] == "deadly"


def test_difficulty_trivial_and_warnings():
    r = client.post("/api/encounters/difficulty",
                    json={"party_levels": [10], "monster_crs": ["0"]})
    assert r.json()["rating"] == "trivial"
    # economía de acciones + dispersión de niveles
    r = client.post("/api/encounters/difficulty",
                    json={"party_levels": [1, 12],
                          "monster_crs": ["1/8"] * 8})
    d = r.json()
    assert len(d["warnings"]) == 2


def test_cr_and_multiplier_tables():
    assert cr_to_xp("1") == 200
    assert cr_to_xp("1/4") == 50
    assert cr_to_xp(0.25) == 50          # float → "1/4"
    assert encounter_multiplier(1) == 1.0
    assert encounter_multiplier(3) > encounter_multiplier(2)
    assert encounter_threshold(1) < encounter_threshold(20)
    assert len(level_xp_table()) == 20
