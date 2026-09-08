#!/usr/bin/env python
"""
POC: match the sheet's outstanding commodities against the live station market.

Falsifiable question: does naive normalization (lowercase + strip non-alnum) of
the sheet's display names match the journal Market.json entries, or do we need
the EDCD/FDevIDs canonical table?

Reads ONLY local files. Writes nothing.
  - Market.json from the ED journal directory (current docked station)
  - the Totals Tab dump from probe_sheet_layout.py

Usage:
    python tests/one-offs/poc_market_match.py <totals_tab.json>
"""

import json
import os
import re
import sys
from pathlib import Path

JOURNAL_DIR = (
    Path(os.environ.get("USERPROFILE", Path.home()))
    / "Saved Games"
    / "Frontier Developments"
    / "Elite Dangerous"
)

LEFT_TO_BUY_HEADER = "Left to buy"
HEADER_ROW = 3
FIRST_DATA_ROW = 5


def norm(s: str) -> str:
    """Naive normalization: lowercase, drop everything but a-z0-9."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def parse_qty(raw: str):
    """Sheet values arrive as display strings like '1,716'. Return int or None."""
    t = str(raw).strip().replace(",", "")
    if not t:
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def load_requirements(dump_path: Path):
    data = json.load(open(dump_path, encoding="utf-8"))
    values = data["values"]

    hdr = values[HEADER_ROW - 1]
    try:
        ltb_col = next(
            i for i, h in enumerate(hdr) if str(h).strip() == LEFT_TO_BUY_HEADER
        )
    except StopIteration:
        raise SystemExit(f"header {LEFT_TO_BUY_HEADER!r} not found in row {HEADER_ROW}")

    reqs = []
    for r in range(FIRST_DATA_ROW, len(values) + 1):
        row = values[r - 1]
        name = str(row[1] if len(row) > 1 else "").strip()
        if not name:
            continue
        qty = parse_qty(row[ltb_col] if len(row) > ltb_col else "")
        reqs.append({"row": r, "name": name, "left_to_buy": qty})
    return reqs, ltb_col


def load_market():
    p = JOURNAL_DIR / "Market.json"
    m = json.load(open(p, encoding="utf-8"))
    return m


def main() -> int:
    dump = Path(sys.argv[1])
    reqs, ltb_col = load_requirements(dump)
    market = load_market()

    items = market.get("Items", [])
    print(f"Market: {market['StationName']} ({market['StationType']}) "
          f"in {market['StarSystem']}  marketId={market['MarketID']}")
    print(f"        timestamp={market['timestamp']}  items={len(items)}")
    print()

    # Build market indexes
    by_id = {}
    by_symbol = {}
    by_dispname = {}
    for it in items:
        by_id[it["id"]] = it
        sym = str(it.get("Name", "")).strip("$;").removesuffix("_name")
        by_symbol[norm(sym)] = it
        disp = it.get("Name_Localised") or sym
        by_dispname[norm(disp)] = it

    outstanding = [r for r in reqs if (r["left_to_buy"] or 0) > 0]
    print(f"Sheet rows: {len(reqs)} total, {len(outstanding)} with Left to buy > 0")
    print()

    hdr = f"{'row':>4} {'commodity':26} {'need':>6} {'match via':11} {'stock':>8} {'buy':>8} {'state':8}"
    print(hdr)
    print("-" * len(hdr))

    unmatched = []
    for r in outstanding:
        n = norm(r["name"])
        via, it = "", None
        if n in by_dispname:
            via, it = "displayname", by_dispname[n]
        elif n in by_symbol:
            via, it = "symbol", by_symbol[n]

        if it is None:
            unmatched.append(r)
            print(f"{r['row']:>4} {r['name']:26} {r['left_to_buy']:>6} "
                  f"{'** NONE **':11} {'-':>8} {'-':>8} {'?':8}")
            continue

        stock = it.get("Stock", 0)
        buy = it.get("BuyPrice", 0)
        need = r["left_to_buy"]
        if stock <= 0 or buy <= 0:
            state = "NONE"
        elif stock < need:
            state = "PARTIAL"
        else:
            state = "ENOUGH"
        print(f"{r['row']:>4} {r['name']:26} {need:>6} {via:11} "
              f"{stock:>8} {buy:>8} {state:8}")

    print()
    if unmatched:
        print(f"!! {len(unmatched)} outstanding rows did NOT match the market by name:")
        for r in unmatched:
            print(f"   - {r['name']!r} (norm={norm(r['name'])!r})")
            # Try to find near matches to show what the canonical name looks like
            near = [
                (it.get("Name_Localised") or it.get("Name"), it.get("Name"))
                for it in items
                if norm(r["name"])[:6] in norm(it.get("Name_Localised") or "")
                or norm(it.get("Name_Localised") or "")[:6] in norm(r["name"])
            ]
            for disp, sym in near[:5]:
                print(f"       near: display={disp!r} symbol={sym!r}")
    else:
        print("All outstanding rows matched the market by name.")

    print()
    print("=== Also check: ALL 28 sheet rows resolvable (not just outstanding) ===")
    bad = []
    for r in reqs:
        n = norm(r["name"])
        if n not in by_dispname and n not in by_symbol:
            bad.append(r["name"])
    print(f"  {len(bad)} of {len(reqs)} sheet names have no counterpart in THIS market:")
    for name in bad:
        print(f"   - {name!r}")
    print()
    print("  (absence here can mean 'station does not trade it' OR 'name mismatch' -")
    print("   that ambiguity is exactly why a canonical catalog is needed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
