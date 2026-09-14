"""Is BGS and contribution history retroactively recoverable from the journal?

The market probe found that stock/demand is NOT retained -- Market.json is
overwritten and the journal's Market event is only a pointer. This probe asks
the same question of two other things the maintainer wants to track:

  1. BGS -- faction influence, states, happiness per system. Carried on
     FSDJump / Location / CarrierJump as a Factions[] array?
  2. CONTRIBUTION -- ColonisationContribution records what *I* handed over.
     Paired with the depot's whole-state ProvidedAmount, a delta that exceeds
     my own contributions is somebody else's work.

If (1) is retained per jump, BGS history IS recoverable retroactively, which is
the opposite of the market answer and would change what a store is for.

Run:  python tests/one-offs/thinking/market-history/bgs_probe.py [journal-dir]
"""

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_DIR = Path(
    os.path.expanduser("~/Saved Games/Frontier Developments/Elite Dangerous")
)

BGS_EVENTS = ("FSDJump", "Location", "CarrierJump")
COLONISATION = ("ColonisationContribution", "ColonisationConstructionDepot")


def main(journal_dir):
    files = sorted(journal_dir.glob("Journal.*.log"))
    print(f"files: {len(files)}")

    counts = Counter()
    with_factions = 0
    faction_keys = Counter()
    systems_with_bgs = set()
    influence_samples = []
    contrib_keys = Counter()
    contrib_by_market = defaultdict(list)
    depot_by_market = defaultdict(list)

    for path in files:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                name = ev.get("event")

                if name in BGS_EVENTS:
                    counts[name] += 1
                    factions = ev.get("Factions")
                    if factions:
                        with_factions += 1
                        systems_with_bgs.add(ev.get("StarSystem"))
                        for f in factions:
                            faction_keys.update(f.keys())
                        if len(influence_samples) < 2:
                            influence_samples.append(
                                (ev.get("timestamp"), ev.get("StarSystem"), factions)
                            )

                elif name in COLONISATION:
                    counts[name] += 1
                    mid = ev.get("MarketID")
                    if name == "ColonisationContribution":
                        contrib_keys.update(ev.keys())
                        contrib_by_market[mid].append(ev)
                    else:
                        total = sum(
                            r.get("ProvidedAmount", 0)
                            for r in ev.get("ResourcesRequired", [])
                        )
                        depot_by_market[mid].append((ev.get("timestamp"), total))

    print("\nevent counts:")
    for name, n in counts.most_common():
        print(f"  {name:32} {n}")

    print(f"\nBGS: events carrying a Factions[] array : {with_factions}")
    print(f"BGS: distinct systems with faction data : {len(systems_with_bgs)}")
    print("\nper-faction keys seen:")
    for key, n in faction_keys.most_common(14):
        print(f"  {key:22} {n}")

    if influence_samples:
        ts, system, factions = influence_samples[0]
        print(f"\nsample BGS snapshot: {system} at {ts}")
        for f in factions[:4]:
            print(
                f"  {f.get('Name','?')[:34]:34} "
                f"inf={f.get('Influence')} state={f.get('FactionState')}"
            )

    print("\nColonisationContribution keys:")
    for key, n in contrib_keys.most_common():
        print(f"  {key:22} {n}")

    # The decisive test: does the depot's provided total move more than my
    # own contributions account for? That difference is other commanders.
    print("\ndepot progression per site (provided tonnage over time):")
    for mid, rows in list(depot_by_market.items())[:6]:
        rows.sort()
        first, last = rows[0], rows[-1]
        mine = len(contrib_by_market.get(mid, []))
        print(
            f"  {mid}: {len(rows)} depot events, "
            f"{first[1]} -> {last[1]} t provided, "
            f"{mine} contribution events of my own"
        )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    main(target)
