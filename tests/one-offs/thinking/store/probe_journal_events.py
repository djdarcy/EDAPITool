"""
The population the store's design rests on: what the commander's journal
directory actually holds, by event type, and how much of it the criteria
of #22 name. Read-only. Run from the repository root.

    python tests/one-offs/thinking/store/probe_journal_events.py [--dir DIR] [--top N]
"""

import argparse
import json
import os
from collections import Counter
from pathlib import Path

# The events #22's criteria and the custody design name, by what they feed.
NAMED = {
    "bgs": {"FSDJump", "Location", "CarrierJump", "Docked"},
    "construction": {"ColonisationConstructionDepot", "ColonisationContribution"},
    "transactions": {"MarketBuy", "MarketSell", "CargoTransfer"},
    "identity": {"LoadGame", "Commander", "Fileheader"},
    "market_side_files": {"Market", "Cargo", "Shipyard", "Outfitting"},
    "carrier": {"CarrierStats", "CarrierTradeOrder", "CarrierDepositFuel", "CarrierFinance"},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous"))
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    root = Path(args.dir)
    files = sorted(root.glob("Journal*.log"))
    counts: Counter = Counter()
    per_file_events = 0
    bad = 0
    first = last = None
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            counts[ev.get("event", "?")] += 1
            per_file_events += 1
            ts = ev.get("timestamp")
            if ts:
                first = ts if first is None or ts < first else first
                last = ts if last is None or ts > last else last
    sizes = sum(p.stat().st_size for p in files)
    print(f"{len(files)} journal files, {sizes/1e6:.1f} MB, {per_file_events} events, {bad} unparsable lines")
    print(f"span: {first} .. {last}")
    print("side files present:", [n for n in ("Market.json", "Cargo.json", "Status.json", "Shipyard.json", "Outfitting.json", "NavRoute.json") if (root / n).exists()])
    print(f"\ntop {args.top} event types:")
    for name, n in counts.most_common(args.top):
        print(f"  {name:<36} {n:>7}")
    print("\nnamed by #22 / the custody design:")
    for group, names in NAMED.items():
        total = sum(counts[n] for n in names)
        print(f"  {group:<18} {total:>7}  " + ", ".join(f"{n}={counts[n]}" for n in sorted(names) if counts[n]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
