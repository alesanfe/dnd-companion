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
from .importers import five_e_bits

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

    args = p.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(args.db)

    if args.cmd == "import-srd":
        n = five_e_bits.import_srd(conn, args.edition, args.source_dir)
        print(f"Done: {n} entities -> {args.db}")
    elif args.cmd == "import-file":
        rows = json.loads(args.path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise SystemExit("expected a JSON array of entities")
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


if __name__ == "__main__":
    main()
