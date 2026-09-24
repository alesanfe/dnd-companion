"""Importers de fuentes externas — con fixtures locales, sin red."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                     / "data-pipeline"))
from pipeline import db                      # noqa: E402
from pipeline.importers import fiveetools, open5e  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "content.sqlite3")
    yield c
    c.close()


def test_5etools_importer_marks_non_redistributable(conn, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "bestiary-mm.json").write_text(json.dumps({
        "monster": [{"name": "Adult Red Dragon", "source": "MM",
                     "cr": "17"}]}), encoding="utf-8")
    (data / "spells-phb.json").write_text(json.dumps({
        "spell": [{"name": "Fireball", "source": "PHB",
                   "level": 3}]}), encoding="utf-8")
    (data / "items.json").write_text(json.dumps({
        "item": [{"name": "Bag of Holding", "source": "DMG"}]}),
        encoding="utf-8")

    n = fiveetools.import_5etools(conn, data)
    assert n == 3

    row = conn.execute(
        "SELECT * FROM content_entities WHERE name = 'Adult Red Dragon'"
    ).fetchone()
    assert row["entity_type"] == "monster"
    assert row["source_id"] == "5etools"
    assert row["is_redistributable"] == 0          # clave: no libre
    assert "non-free" in row["license"]

    src = conn.execute(
        "SELECT * FROM content_sources WHERE id = '5etools'").fetchone()
    assert src["distribution_allowed"] == 0

    # FTS indexado
    hit = conn.execute(
        "SELECT entity_id FROM content_fts WHERE content_fts MATCH ?",
        ("fireball",)).fetchone()
    assert hit["entity_id"] == "5etools:spell:fireball|phb"


def test_open5e_importer_per_document_sources(conn):
    pages = {
        "https://x/v1/documents/?limit=500": {
            "next": None,
            "results": [{"slug": "wotc-srd", "title": "5e Core Rules",
                         "license": "Open Gaming License"}],
        },
        "https://x/v1/monsters/?limit=100&document__slug=wotc-srd": {
            "next": None,
            "results": [{
                "slug": "goblin", "name": "Goblin",
                "document__slug": "wotc-srd",
                "document__title": "Systems Reference Document",
                "document__license_url":
                    "https://creativecommons.org/licenses/by/4.0/",
            }],
        },
    }

    def fetch(url):
        return pages.get(url, {"next": None, "results": []})

    n = open5e.import_open5e(conn, "wotc-srd", base_url="https://x/v1",
                             fetch=fetch)
    assert n == 1
    row = conn.execute(
        "SELECT * FROM content_entities WHERE name = 'Goblin'"
    ).fetchone()
    assert row["id"] == "open5e-wotc-srd:goblin"
    assert row["license"] == "Open Gaming License"
    assert row["ruleset"] == "dnd5e-2014"
    assert row["is_redistributable"] == 1
    src = conn.execute(
        "SELECT * FROM content_sources WHERE id='open5e-wotc-srd'"
    ).fetchone()
    assert src["name"] == "5e Core Rules"


def test_open5e_pagination_follows_next(conn):
    pages = {
        "https://x/v1/documents/?limit=500": {
            "next": None,
            "results": [{"slug": "tob", "title": "Tome of Beasts",
                         "license": "Open Gaming License"}],
        },
        "https://x/v1/spells/?limit=100": {
            "next": "https://x/v1/spells/?page=2",
            "results": [{"slug": "a", "name": "A",
                         "document__slug": "tob"}],
        },
        "https://x/v1/spells/?page=2": {
            "next": None,
            "results": [{"slug": "b", "name": "B",
                         "document__slug": "tob"}],
        },
    }
    n = open5e.import_open5e(conn, base_url="https://x/v1",
                             fetch=lambda u: pages.get(
                                 u, {"next": None, "results": []}))
    assert n == 2
    rows = conn.execute(
        "SELECT id FROM content_entities WHERE source_id='open5e-tob'"
    ).fetchall()
    assert len(rows) == 2
    assert all(r["id"].startswith("open5e-tob:") for r in rows)
