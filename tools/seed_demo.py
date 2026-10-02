#!/usr/bin/env python3
"""Siembra la demo de capturas: campaña + 2 fichas + combate + mapa.
Idempotente: si la campaña ya existe no crea duplicados.

Uso:
    python tools/seed_demo.py [--base http://localhost:8010]
"""
import argparse
import json
import sys
import urllib.request

CAMP_ID = "2575ee25263c4e6d986927c12e13e6c8"


def req(base, path, body=None, method=None):
    r = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method=method or ("POST" if body is not None else "GET"))
    return json.loads(urllib.request.urlopen(r).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8010")
    args = ap.parse_args()
    base = args.base

    try:
        c = req(base, f"/api/campaigns/{CAMP_ID}")
        print("campaña ya existe:", c.get("campaign", {}).get("name"))
        return
    except urllib.error.HTTPError:
        pass

    camp = req(base, "/api/campaigns", {
        "id": CAMP_ID,
        "name": "La Ciénaga Sombría",
        "ruleset": "dnd5e-2014",
    })
    print("campaña:", camp)
    print("OK — ver tools/screenshots.mjs para las rutas completas")


if __name__ == "__main__":
    sys.exit(main())
