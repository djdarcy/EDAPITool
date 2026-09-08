#!/usr/bin/env python
"""
READ-ONLY probe of the Frontier CAPI /market endpoint, to compare its shape
against the local journal Market.json.

Question it settles: does CAPI /market give us commodity id + display name in a
form we can match the sheet against, and does it agree with the journal about
which station we are at?

Usage:
    python tests/one-offs/probe_capi_market.py [--dump PATH]
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from APITool.auth import FrontierAuth  # noqa: E402
from APITool.capi import CAPIClient, CAPIError  # noqa: E402

JOURNAL_DIR = (
    Path(os.environ.get("USERPROFILE", Path.home()))
    / "Saved Games"
    / "Frontier Developments"
    / "Elite Dangerous"
)


def get_client_id():
    cfg = Path.home() / ".ed_capi_config.json"
    if cfg.exists():
        return json.loads(cfg.read_text()).get("client_id")
    return os.environ.get("ED_CLIENT_ID")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump")
    args = ap.parse_args()

    auth = FrontierAuth(get_client_id())
    if not auth.is_authenticated:
        print("Not authenticated; run `edapitool auth` first.")
        return 1

    client = CAPIClient(auth)
    try:
        market = client.get_market()
    except CAPIError as e:
        print(f"CAPI error: {e}")
        return 1

    print("=== CAPI /market top-level keys ===")
    for k, v in market.items():
        if isinstance(v, (dict, list)):
            print(f"  {k}: {type(v).__name__} len={len(v)}")
        else:
            print(f"  {k} = {v!r}")
    print()

    commodities = market.get("commodities", [])
    print(f"=== commodities: {len(commodities)} ===")
    if commodities:
        print("first entry:")
        print(json.dumps(commodities[0], indent=2))
    print()

    # Compare against journal Market.json
    jm_path = JOURNAL_DIR / "Market.json"
    if jm_path.exists():
        jm = json.load(open(jm_path, encoding="utf-8"))
        print("=== Agreement with journal Market.json ===")
        print(f"  journal: marketId={jm['MarketID']} station={jm['StationName']!r} "
              f"system={jm['StarSystem']!r} items={len(jm['Items'])} ts={jm['timestamp']}")
        print(f"  CAPI   : id={market.get('id')} name={market.get('name')!r} "
              f"commodities={len(commodities)}")
        same = str(market.get("id")) == str(jm["MarketID"])
        print(f"  SAME MARKET: {same}")
        print()

        jids = {i["id"] for i in jm["Items"]}
        cids = {c.get("id") for c in commodities}
        print(f"  ids only in journal: {len(jids - cids)}")
        print(f"  ids only in CAPI   : {len(cids - jids)}")
        print()

        # Do CAPI names look like display names or symbols?
        print("  CAPI 'name' vs journal display for the tricky ones:")
        jbyid = {i["id"]: i for i in jm["Items"]}
        tricky = [128049232, 128049208, 128049220, 128682048, 128673873, 128672314]
        for cid in tricky:
            c = next((x for x in commodities if x.get("id") == cid), None)
            j = jbyid.get(cid)
            if c and j:
                print(f"    id={cid}: CAPI name={c.get('name')!r:32} "
                      f"journal symbol={j.get('Name')!r:38} "
                      f"display={j.get('Name_Localised')!r}")

    if args.dump:
        Path(args.dump).write_text(
            json.dumps(market, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nDumped CAPI market to {args.dump}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
