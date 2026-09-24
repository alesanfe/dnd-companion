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
