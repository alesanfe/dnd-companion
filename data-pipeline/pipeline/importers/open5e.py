"""Importer for the Open5e API (https://api.open5e.com).

Open5e hosts the WotC SRD plus third-party documents released under the
OGL (Tome of Beasts, Creature Codex, Deep Magic, …). Each API record
carries ``document__slug``/``document__title``/``document__license_url``
— we key sources by document so provenance stays per-book.

Licenses seen in the wild: OGL-1.0a and CC-BY-4.0 — both allow
redistribution with attribution, so entities are marked redistributable.
Non-open documents should be imported via import-file (private).

  python -m pipeline.cli import-open5e --document wotc-srd
  python -m pipeline.cli import-open5e --document tob   # Tome of Beasts
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import urllib.request
from collections.abc import Callable

from .. import db

BASE_URL = "https://api.open5e.com/v1"

# endpoint -> entity_type (v1 API)
ENDPOINTS = {
    "monsters": "monster",
    "spells": "spell",
    "backgrounds": "background",
    "feats": "feat",
    "races": "race",
    "classes": "class",
    "conditions": "condition",
    "magicitems": "magic-item",
    "weapons": "equipment",
    "armor": "equipment",
    "sections": "rule",
}

# known document slugs -> ruleset
_DOC_RULESET = {
    "wotc-srd": "dnd5e-2014",        # SRD 5.1
    "srd-2024": "dnd5e-2024",
    "wotc-srd-2024": "dnd5e-2024",
}


def _documents(fetch: Callable[[str], dict], base_url: str) -> dict:
    """Map slug -> {title, license} from /v1/documents/."""
    docs: dict[str, dict] = {}
    url = f"{base_url}/documents/?limit=500"
    while url:
        page = fetch(url)
        for d in page.get("results", []):
            docs[d["slug"]] = d
        url = page.get("next")
    return docs


def _fetch(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "dnd-companion-importer/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def import_open5e(
    conn: sqlite3.Connection,
    document: str | None = None,
    *,
    base_url: str = BASE_URL,
    fetch: Callable[[str], dict] = _fetch,
    ruleset: str | None = None,
) -> int:
    """Pull all endpoints for a document (or everything). Returns count."""
    docs = _documents(fetch, base_url)
    count = 0
    seen_sources: set[str] = set()
    for endpoint, entity_type in ENDPOINTS.items():
        url = f"{base_url}/{endpoint}/?limit=100"
        if document:
            url += f"&document__slug={document}"
        ep_count = 0
        while url:
            page = fetch(url)
            for row in page.get("results", []):
                doc_slug = row.get("document__slug") or document or "unknown"
                name = row.get("name") or row.get("slug")
                slug = row.get("slug") or name
                if not name or not slug:
                    continue
                doc = docs.get(doc_slug, {})
                lic = doc.get("license") or "OGL-1.0a"
                src_id = f"open5e-{doc_slug}"
                if src_id not in seen_sources:
                    db.upsert_source(
                        conn, source_id=src_id,
                        name=doc.get("title")
                        or row.get("document__title") or doc_slug,
                        version=None, license=lic,
                        attribution_text=(
                            f"{doc.get('title') or doc_slug} — "
                            f"{doc.get('organization') or ''} "
                            f"({lic})").strip(),
                        original_url=f"https://open5e.com",
                        distribution_allowed=True)
                    seen_sources.add(src_id)
                rs = ruleset or _DOC_RULESET.get(doc_slug, "mixed")
                db.insert_entity(
                    conn, source_id=src_id, index=str(slug),
                    entity_type=entity_type, name=str(name),
                    ruleset=rs, license=lic, data=row,
                    source_document=doc.get("title")
                        or row.get("document__title") or doc_slug,
                    source_version=hashlib.sha256(
                        json.dumps(row, sort_keys=True).encode()
                    ).hexdigest()[:16],
                    is_redistributable=True)
                count += 1
                ep_count += 1
            url = page.get("next")
        print(f"  {entity_type} ({document or 'all'}): {ep_count}")
    db.rebuild_fts(conn)
    conn.commit()
    return count


# ---------------------------------------------------------------------------
# V2 API — richer relational schema: document embeds licenses, publisher,
# gamesystem. /v2/creatures/?document__key=srd-2024 etc.
# ---------------------------------------------------------------------------

V2_BASE_URL = "https://api.open5e.com/v2"

V2_ENDPOINTS = {
    "creatures": "monster",
    "spells": "spell",
    "items": "equipment",
    "magicitems": "magic-item",
    "weapons": "equipment",
    "armor": "equipment",
    "backgrounds": "background",
    "feats": "feat",
    "species": "species",
    "classes": "class",
    "conditions": "condition",
    "rules": "rule",
    "rulesets": "rule",
    "languages": "language",
    "abilities": "ability-score",
    "skills": "skill",
    "alignments": "alignment",
    "damagetypes": "damage-type",
    "environments": "environment",
    "sizes": "size",
    "creaturetypes": "creature-type",
    "spellschools": "magic-school",
    "itemcategories": "equipment-category",
    "itemrarities": "item-rarity",
}

_V2_RULESET = {
    "5e": "dnd5e-2014",
    "5e-2014": "dnd5e-2014",
    "5e-2024": "dnd5e-2024",
    "5e-x": "dnd5e-2024",
}


def _v2_documents(fetch, base_url) -> dict:
    docs: dict[str, dict] = {}
    url = f"{base_url}/documents/?limit=500"
    while url:
        page = fetch(url)
        for d in page.get("results", []):
            docs[d["key"]] = d
        url = page.get("next")
    return docs


def import_open5e_v2(
    conn: sqlite3.Connection,
    document: str | None = None,
    *,
    base_url: str = V2_BASE_URL,
    fetch: Callable[[str], dict] = _fetch,
    ruleset: str | None = None,
) -> int:
    """Pull v2 endpoints. Each row's ``document`` embeds provenance."""
    docs = _v2_documents(fetch, base_url)
    count = 0
    seen_sources: set[str] = set()
    for endpoint, entity_type in V2_ENDPOINTS.items():
        url = f"{base_url}/{endpoint}/?limit=100"
        if document:
            url += f"&document__key={document}"
        ep_count = 0
        while url:
            page = fetch(url)
            for row in page.get("results", []):
                name = row.get("name")
                key = row.get("key") or row.get("slug") or name
                if not name or not key:
                    continue
                dref = row.get("document") or {}
                doc_key = (dref.get("key") if isinstance(dref, dict)
                           else None) or document or "unknown"
                doc = docs.get(doc_key, {})
                licenses = doc.get("licenses") or []
                lic = (licenses[0]["name"] if licenses else "unknown")
                src_id = f"open5e2-{doc_key}"
                if src_id not in seen_sources:
                    pub = (doc.get("publisher") or {}).get("name", "")
                    db.upsert_source(
                        conn, source_id=src_id,
                        name=doc.get("name") or doc_key,
                        version=doc.get("publication_date"),
                        license=lic,
                        attribution_text=(
                            f"{doc.get('name', doc_key)} — "
                            f"{doc.get('author') or pub} ({lic})"),
                        original_url=doc.get("permalink")
                        or "https://open5e.com",
                        distribution_allowed=True)
                    seen_sources.add(src_id)
                gs = (doc.get("gamesystem") or {}).get("key", "")
                rs = ruleset or _V2_RULESET.get(gs, "mixed")
                db.insert_entity(
                    conn, source_id=src_id, index=str(key),
                    entity_type=entity_type, name=str(name),
                    ruleset=rs, license=lic, data=row,
                    source_document=doc.get("name") or doc_key,
                    source_version=doc.get("publication_date"),
                    is_redistributable=True)
                count += 1
                ep_count += 1
            url = page.get("next")
        if ep_count:
            print(f"  {entity_type} ({document or 'all'}): {ep_count}")
    db.rebuild_fts(conn)
    conn.commit()
    return count
