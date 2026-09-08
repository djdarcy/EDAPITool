#!/usr/bin/env python
"""
Compare the two candidate market sources for the SAME station:
  - local journal Market.json   (366 items at Ryman Enterprise)
  - Frontier CAPI /market        (92 commodities at Ryman Enterprise)

Question it settles: which source do we trust for "is this commodity buyable
here, and how much stock", and do they disagree on overlapping entries?

Offline. Reads the journal Market.json plus a CAPI dump written by
probe_capi_market.py --dump.

Usage:
    python tests/one-offs/compare_market_sources.py <capi_market.json> <totals_tab.json>
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


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def parse_qty(raw):
    t = str(raw).strip().replace(",", "")
    if not t:
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def main() -> int:
    capi = json.load(open(sys.argv[1], encoding="utf-8"))
    dump = json.load(open(sys.argv[2], encoding="utf-8"))
    jm = json.load(open(JOURNAL_DIR / "Market.json", encoding="utf-8"))

    jitems = {i["id"]: i for i in jm["Items"]}
    citems = {c["id"]: c for c in capi["commodities"]}

    print(f"journal items : {len(jitems)}")
    print(f"CAPI  items   : {len(citems)}")
    print()

    # How many journal items have any actual trade signal?
    j_tradeable = {
        i for i, v in jitems.items()
        if v.get("Stock", 0) > 0 or v.get("Demand", 0) > 0
        or v.get("BuyPrice", 0) > 0
    }
    j_stocked = {i for i, v in jitems.items() if v.get("Stock", 0) > 0}
    print(f"journal items with Stock>0                 : {len(j_stocked)}")
    print(f"journal items with Stock/Demand/BuyPrice >0 : {len(j_tradeable)}")
    c_stocked = {i for i, v in citems.items() if v.get("stock", 0) > 0}
    print(f"CAPI    items with stock>0                  : {len(c_stocked)}")
    print()

    print("=== Does CAPI's 92 == journal's stocked set? ===")
    print(f"  journal Stock>0 not in CAPI : {len(j_stocked - set(citems))}")
    print(f"  CAPI ids not in journal     : {sorted(set(citems) - set(jitems))}")
    for cid in sorted(set(citems) - set(jitems)):
        print(f"    {cid}: {citems[cid].get('locName')!r} "
              f"stock={citems[cid].get('stock')} buy={citems[cid].get('buyPrice')}")
    print()

    print("=== Disagreements on overlapping ids (stock or buyPrice) ===")
    both = set(jitems) & set(citems)
    print(f"  overlapping ids: {len(both)}")
    disagree = 0
    for cid in sorted(both):
        j, c = jitems[cid], citems[cid]
        if j.get("Stock", 0) != c.get("stock", 0) or j.get("BuyPrice", 0) != c.get("buyPrice", 0):
            disagree += 1
            if disagree <= 15:
                print(f"    {j.get('Name_Localised')!r:30} "
                      f"journal stock={j.get('Stock'):>8} buy={j.get('BuyPrice'):>7} | "
                      f"CAPI stock={c.get('stock'):>8} buy={c.get('buyPrice'):>7}")
    print(f"  total disagreeing: {disagree} of {len(both)}")
    print()

    # Now the decisive test: our 13 outstanding commodities under each source.
    values = dump["values"]
    hdr = values[2]
    ltb = next(i for i, h in enumerate(hdr) if str(h).strip() == "Left to buy")
    reqs = []
    for r in range(5, len(values) + 1):
        row = values[r - 1]
        name = str(row[1] if len(row) > 1 else "").strip()
        if not name:
            continue
        q = parse_qty(row[ltb] if len(row) > ltb else "")
        if (q or 0) > 0:
            reqs.append((r, name, q))

    j_by_disp = {norm(i.get("Name_Localised") or i.get("Name")): i for i in jm["Items"]}
    c_by_disp = {norm(c.get("locName") or c.get("name")): c for c in capi["commodities"]}
    c_by_sym = {norm(c.get("name")): c for c in capi["commodities"]}

    print("=== The 13 outstanding rows under each source ===")
    head = (f"{'commodity':26} {'need':>5} | {'J stock':>9} {'J buy':>7} {'J state':8}"
            f" | {'C stock':>9} {'C buy':>7} {'C state':8}")
    print(head)
    print("-" * len(head))

    def state(stock, buy, need):
        if stock is None:
            return "ABSENT"
        if stock <= 0 or buy <= 0:
            return "NONE"
        return "PARTIAL" if stock < need else "ENOUGH"

    mismatches = []
    for r, name, need in reqs:
        n = norm(name)
        j = j_by_disp.get(n)
        c = c_by_disp.get(n) or c_by_sym.get(n)
        js = j.get("Stock") if j else None
        jb = j.get("BuyPrice") if j else None
        cs = c.get("stock") if c else None
        cb = c.get("buyPrice") if c else None
        jst = state(js, jb or 0, need)
        cst = state(cs, cb or 0, need)
        if jst != cst:
            mismatches.append((name, jst, cst))
        print(f"{name:26} {need:>5} | {str(js):>9} {str(jb):>7} {jst:8}"
              f" | {str(cs):>9} {str(cb):>7} {cst:8}")
    print()
    if mismatches:
        print(f"!! {len(mismatches)} rows where the two sources give a DIFFERENT verdict:")
        for name, jst, cst in mismatches:
            print(f"   {name!r}: journal={jst} CAPI={cst}")
    else:
        print("Both sources agree on the verdict for every outstanding row.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
