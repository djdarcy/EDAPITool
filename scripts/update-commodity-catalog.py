#!/usr/bin/env python
"""
Regenerate the bundled commodity catalog from the EDCD/FDevIDs upstream tables.

This is a DEVELOPMENT-TIME script. It is deliberately not called at runtime:
EDAPITool must keep working when GitHub is unreachable, so the generated CSV is
committed and shipped with the package.

Sources (both required -- ordinary commodities and rares are separate files):
    https://github.com/EDCD/FDevIDs/blob/master/commodity.csv
    https://github.com/EDCD/FDevIDs/blob/master/rare_commodity.csv

Output:
    APITool/data/fdev_commodities.csv   (id, symbol, category, name, rare)

Usage:
    python scripts/update-commodity-catalog.py [--check]

    --check   Fetch and compare against the bundled file without writing.
              Exits 1 if they differ, so CI can flag a stale catalog.
"""

import argparse
import csv
import io
import sys
from pathlib import Path

import requests

BASE = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/"
SOURCES = [("commodity.csv", False), ("rare_commodity.csv", True)]

OUTPUT = Path(__file__).resolve().parents[1] / "APITool" / "data" / "fdev_commodities.csv"
FIELDS = ["id", "symbol", "category", "name", "rare"]


def fetch(name: str) -> list[dict]:
    resp = requests.get(BASE + name, timeout=30)
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def build_rows() -> list[dict]:
    seen: dict[int, dict] = {}
    for filename, is_rare in SOURCES:
        for row in fetch(filename):
            try:
                cid = int(row["id"])
            except (KeyError, ValueError):
                continue
            symbol = (row.get("symbol") or "").strip()
            name = (row.get("name") or "").strip()
            if not symbol or not name:
                continue
            # commodity.csv wins on a collision -- rares carry a market_id
            # column that makes them station-specific, and the ordinary table
            # is the one both CAPI and the journal agree with.
            if cid in seen and not is_rare:
                seen[cid].update(
                    {"symbol": symbol, "category": row.get("category", ""), "name": name}
                )
                continue
            if cid in seen:
                continue
            seen[cid] = {
                "id": cid,
                "symbol": symbol,
                "category": (row.get("category") or "").strip(),
                "name": name,
                "rare": "1" if is_rare else "0",
            }
    return [seen[k] for k in sorted(seen)]


def render(rows: list[dict]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare only, do not write")
    args = ap.parse_args()

    rows = build_rows()
    text = render(rows)
    rare_count = sum(1 for r in rows if r["rare"] == "1")
    print(f"Built catalog: {len(rows)} commodities ({rare_count} rare)")

    if args.check:
        if not OUTPUT.exists():
            print(f"MISSING: {OUTPUT}")
            return 1
        current = OUTPUT.read_text(encoding="utf-8")
        if current == text:
            print("Bundled catalog is up to date.")
            return 0
        print(f"STALE: {OUTPUT} differs from upstream.")
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
