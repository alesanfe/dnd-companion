"""Render canónico de entidades (domain/render.py) + modelos de
procedencia — cubren los campos que la UI consume en /content/{id}/render
y la atribución obligatoria por fuente."""
import sys
from datetime import datetime
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import render                        # noqa: E402
from app.domain.provenance import ContentSource, Provenance  # noqa: E402


# ---------- clean() ----------


def test_clean_strips_tags_and_html():
    assert render.clean("{@spell fireball|x} quema") == "fireball quema"
    assert render.clean("<b>bold</b>") == "bold"
    assert render.clean(["a", "b"]) == "a b"
    assert render.clean(None) == ""
    assert render.clean("  espacios   raros  ") == "espacios raros"


# ---------- render() por tipo ----------


def test_render_spell_fields():
    d = {"name": "Bola de fuego", "level": 3,
         "school": {"name": "Evocación"},
         "casting_time": "1 acción",
         "range": {"normal": "150 pies"},
         "components": {"v": True, "s": True, "m": False},
         "concentration": "yes",
         "desc": ["Una esfera de fuego explota."],
         "higher_level": ["+1d6 por nivel extra."]}
    out = render.render("spell", d)
    labels = {f["label"]: f["value"] for f in out["fields"]}
    assert labels["Nivel"] == "nivel 3"
    assert labels["Escuela"] == "Evocación"
    assert labels["Concentración"] == "sí"
    assert labels["Componentes"] == "v, s"
    assert "explota" in out["desc"]
    assert "+1d6" in out["desc"]          # upcast añadido al desc


def test_render_spell_cantrip_and_5etools_duration():
    d = {"level": 0, "duration": [{"type": "instantaneo"}]}
    out = render.render("spell", d)
    labels = {f["label"]: f["value"] for f in out["fields"]}
    assert labels["Nivel"] == "truco"


def test_render_item_weapon():
    d = {"equipment_category": {"name": "Arma marcial"},
         "damage": {"damage_dice": "1d8",
                    "damage_type": {"name": "cortante"}},
         "weight": 3,
         "cost": {"quantity": 15, "unit": "po"},
         "rarity": {"name": "común"},
         "desc": "Espada versátil."}
    out = render.render("item", d)
    labels = {f["label"]: f["value"] for f in out["fields"]}
    assert labels["Tipo"] == "Arma marcial"
    assert labels["Daño"] == "1d8 cortante"
    assert labels["Rareza"] == "común"
    assert labels["Peso"] == "3 lb"
    assert "15 po" in labels["Coste"]


def test_render_species_race():
    d = {"speed": 30, "size": "M",
         "ability_bonuses": [{"ability_score": {"name": "CON"},
                              "bonus": 2}],
         "languages": [{"name": "Común"}, {"name": "Enano"}],
         "traits": [{"name": "Visión en la oscuridad"}]}
    out = render.render("race", d)
    labels = {f["label"]: f["value"] for f in out["fields"]}
    assert labels["Velocidad"] == "30 pies"
    assert labels["Bonificadores"] == "CON +2"
    assert labels["Idiomas"] == "Común, Enano"
    assert "Visión" in labels["Rasgos"]


def test_render_class_uses_classinfo():
    d = {"hit_die": 10,
         "proficiency_choices": [],
         "proficiencies": [{"name": "Armaduras"}],
         "subclasses": [{"name": "Campeón"}],
         "starting_equipment_options": [{"desc": "(a) escudo"}],
         "multi_classing": {"prerequisites": [
             {"ability_score": {"name": "STR"}, "minimum_score": 13}]}}
    out = render.render("class", d)
    labels = {f["label"]: f["value"] for f in out["fields"]}
    assert labels["Dado de golpe"] == "d10"
    assert labels["Multiclase"] == "STR 13"


def test_render_level_and_prerequisite():
    d = {"level": 5, "prof_bonus": 3,
         "features": [{"name": "Ataque extra"}],
         "class_specific": {"rage_count": 4}}
    out = render.render("level", d)
    labels = {f["label"]: f["value"] for f in out["fields"]}
    assert labels["Bon. competencia"] == "+3"
    assert "Ataque extra" in labels["Rasgos nuevos"]
    assert "rage count: 4" in labels["Detalles"]

    d2 = {"prerequisite": [{"ability_score": {"name": "WIS"},
                            "minimum_score": 13}]}
    out2 = render.render("feat", d2)
    assert out2["fields"][0]["label"] == "Requisito"
    assert out2["fields"][0]["value"] == "WIS 13"


def test_render_unknown_type_fallback():
    out = render.render("feat", {"desc": "Texto plano."})
    assert out["kind"] == "feat"
    assert out["desc"] == "Texto plano."
    assert out["fields"] == []


def test_field_chip_truncates_paragraphs():
    long_text = "x" * 200
    out = render.render("background", {"ability_scores": [long_text]})
    for f in out["fields"]:
        assert len(f["value"]) <= 140


# ---------- provenance ----------


def test_provenance_defaults():
    src = ContentSource(id="srd-2014", name="SRD", license="CC-BY-4.0")
    assert src.distribution_allowed is False
    assert src.version is None
    p = Provenance(source_id="srd-2014", license="CC-BY-4.0")
    assert p.is_redistributable is False
    p2 = Provenance(source_id="pkg:x", license="OGL",
                    is_redistributable=True,
                    source_page="p.42")
    assert p2.source_page == "p.42"
    src2 = ContentSource(id="x", name="X", license="MIT",
                         imported_at=datetime(2024, 1, 1))
    assert src2.imported_at.year == 2024
