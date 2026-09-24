"""CLI: build the content DB from JSON sources.

  python -m pipeline.cli import-srd --edition 2014
  python -m pipeline.cli import-srd --edition 2024 --source-dir ./5e-database/src
  python -m pipeline.cli import-file --path x.json --source-id homebrew \
      --license CC-BY-4.0 --type spell --ruleset dnd5e-2014
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import db
from .importers import five_e_bits, fiveetools, foundry, open5e
from .importers import dnddata

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "content.sqlite3"


def main() -> None:
    p = argparse.ArgumentParser(prog="dnd-pipeline")
    p.add_argument("--db", default=str(DEFAULT_DB), help="content DB path")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("import-srd", help="Import 5e-bits SRD edition")
    s.add_argument("--edition", choices=["2014", "2024"], required=True)
    s.add_argument(
        "--source-dir", type=Path, default=None,
        help="local clone of 5e-bits/5e-database 'src' dir (default: fetch)")

    f = sub.add_parser("import-file", help="Import a private/homebrew JSON")
    f.add_argument("--path", type=Path, required=True)
    f.add_argument("--source-id", required=True)
    f.add_argument("--source-name", default=None)
    f.add_argument("--license", required=True)
    f.add_argument("--type", dest="entity_type", required=True)
    f.add_argument("--ruleset", default="dnd5e-2014",
                   choices=["dnd5e-2014", "dnd5e-2024", "mixed"])
    f.add_argument("--redistributable", action="store_true",
                   help="assert you hold redistribution rights")
    f.add_argument("--key", default=None,
                   help="JSON key holding the array in wrapped files "
                        "(e.g. 'monsters' for srd-5.2.1 data)")

    o = sub.add_parser("import-open5e", help="Import Open5e API docs")
    o.add_argument("--document", default=None,
                   help="document slug (wotc-srd, tob, cc…) — all if omitted")
    o.add_argument("--base-url", default=None,
                   help="override API base (default per --api)")
    o.add_argument("--ruleset", default=None,
                   choices=["dnd5e-2014", "dnd5e-2024", "mixed"],
                   help="override ruleset for all entities")
    o.add_argument("--api", default="v1", choices=["v1", "v2"],
                   help="v2 = richer relational schema (srd-2024 etc.)")

    t = sub.add_parser("import-5etools",
                       help="Import a local 5etools-src clone (non-free)")
    t.add_argument("--path", type=Path, required=True,
                   help="path to the clone's data/ directory")
    t.add_argument("--ruleset", default="mixed",
                   choices=["dnd5e-2014", "dnd5e-2024", "mixed"])
    t.add_argument("--source-id", default="5etools",
                   help="e.g. '5etools-homebrew' or '5etools-ua' for "
                        "TheGiddyLimit/homebrew or unearthed-arcana clones")
    t.add_argument("--license", default=fiveetools.LICENSE)
    t.add_argument("--redistributable", action="store_true")

    fo = sub.add_parser("import-foundry",
                        help="Import a local foundryvtt/dnd5e clone "
                             "(CC-BY-4.0 packs/_source YAML)")
    fo.add_argument("--path", type=Path, required=True,
                    help="path to packs/_source")
    fo.add_argument("--ruleset", default="mixed",
                    choices=["dnd5e-2014", "dnd5e-2024", "mixed"])

    dd = sub.add_parser("import-dnddata",
                        help="Import nick-aschenbach/dnd-data (non-free)")
    dd.add_argument("--path", type=Path, default=None,
                    help="local clone's data/ dir (default: fetch raw)")
    dd.add_argument("--ruleset", default="dnd5e-2014",
                    choices=["dnd5e-2014", "dnd5e-2024", "mixed"])

    args = p.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(args.db)

    if args.cmd == "import-srd":
        n = five_e_bits.import_srd(conn, args.edition, args.source_dir)
        print(f"Done: {n} entities -> {args.db}")
    elif args.cmd == "import-file":
        data = json.loads(args.path.read_text(encoding="utf-8"))
        if args.key:
            data = data.get(args.key) if isinstance(data, dict) else None
        if not isinstance(data, list):
            raise SystemExit(
                "expected a JSON array of entities (use --key for "
                "wrapped files like {\"monsters\": [...]})")
        rows = data
        db.upsert_source(
            conn, source_id=args.source_id,
            name=args.source_name or args.source_id,
            version=None, license=args.license,
            distribution_allowed=args.redistributable,
        )
        for row in rows:
            db.insert_entity(
                conn, source_id=args.source_id,
                index=str(row.get("index") or row.get("name")),
                entity_type=args.entity_type,
                name=str(row.get("name")),
                ruleset=args.ruleset, license=args.license,
                data=row, is_redistributable=args.redistributable,
            )
        db.rebuild_fts(conn)
        conn.commit()
        print(f"Done: {len(rows)} entities -> {args.db}")
    elif args.cmd == "import-open5e":
        fn = (open5e.import_open5e_v2 if args.api == "v2"
              else open5e.import_open5e)
        base = args.base_url or (open5e.V2_BASE_URL if args.api == "v2"
                                 else open5e.BASE_URL)
        n = fn(conn, args.document, base_url=base, ruleset=args.ruleset)
        print(f"Done: {n} entities -> {args.db}")
    elif args.cmd == "import-5etools":
        n = fiveetools.import_5etools(
            conn, args.path, ruleset=args.ruleset,
            source_id=args.source_id, license=args.license,
            distribution_allowed=args.redistributable)
        print(f"Done: {n} entities (non-redistributable) -> {args.db}")
    elif args.cmd == "import-foundry":
        n = foundry.import_foundry(conn, args.path, ruleset=args.ruleset)
        print(f"Done: {n} entities -> {args.db}")
    elif args.cmd == "import-dnddata":
        n = dnddata.import_dnddata(conn, args.path,
                                   ruleset=args.ruleset)
        print(f"Done: {n} entities (non-redistributable) -> {args.db}")


if __name__ == "__main__":
    main()
