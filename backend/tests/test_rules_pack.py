"""Rules pack: los valores oficiales del SRD viven en
app/rules/srd_core.json — estos tests los anclan contra la fuente."""
from fastapi.testclient import TestClient

from app.main import app
from app.domain.xp import (cr_to_xp, encounter_multiplier,
                           encounter_threshold, level_xp_table)
from app.domain.conditions import canon, mods_for, INCAPACITATED
from app.rules import rules

client = TestClient(app)


def test_cr_xp_matches_srd():
    for cr, xp in [("0", 10), ("1/4", 50), ("1/2", 100), ("1", 200),
                   ("5", 1800), ("10", 5900), ("20", 25000),
                   ("30", 155000)]:
        assert cr_to_xp(cr) == xp
    assert cr_to_xp(0.5) == 100        # float normalizado
    assert cr_to_xp("99") == 0         # CR desconocido


def test_encounter_thresholds_matches_dmg():
    assert encounter_threshold(1) == (25, 50, 75, 100)
    assert encounter_threshold(5) == (250, 500, 750, 1100)
    assert encounter_threshold(20) == (2800, 5700, 8500, 12700)
    assert encounter_threshold(99) == encounter_threshold(20)


def test_encounter_multipliers():
    assert encounter_multiplier(1) == 1.0
    assert encounter_multiplier(2) == 1.5
    assert encounter_multiplier(5) == 2.0
    assert encounter_multiplier(9) == 2.5
    assert encounter_multiplier(13) == 3.0
    assert encounter_multiplier(30) == 4.0


def test_level_xp_table():
    t = level_xp_table()
    assert t[0] == 0 and t[1] == 300 and t[4] == 6500 \
        and t[19] == 355000 and len(t) == 20


def test_conditions_from_pack():
    assert "stunned" in INCAPACITATED and "prone" not in INCAPACITATED
    adv, dis, fail, _ = mods_for(["envenenado"], "attack")
    assert dis and not adv        # alias ES → poisoned
    adv, dis, fail, _ = mods_for(["stunned"], "save:dex")
    assert fail
    assert canon("aturdido") == "stunned"


def test_combat_constants_documented():
    c = rules()["combat"]
    assert c["death_save_dc"] == 10 and c["death_save_crit_fail"] == 1 \
        and c["attunement_max"] == 3 and c["spell_dc_base"] == 8 \
        and c["concentration_dc_floor"] == 10


def test_tables_endpoint_serves_pack():
    r = client.get("/api/rules/tables")
    assert r.status_code == 200
    d = r.json()
    assert d["meta"]["license"] == "CC-BY-4.0"
    assert d["ability_skills"]["strength"] == ["athletics"]
    assert "stunned" in d["conditions"]
    assert d["level_xp"][19] == 355000
