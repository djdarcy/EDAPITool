"""What does the journal retain about markets after you leave them?

`market` reads Market.json, which the game overwrites on every dock. So the
current command can only ever describe where the commander is standing. The
question this probe answers is what a HISTORY view could honestly offer:

  1. Market events   -- identity + location of every market visited?
  2. MarketBuy/Sell  -- prices actually transacted, per commodity, per market?
  3. Commodity lists -- does anything in the journal carry a full market's
                        stock/demand, or is Market.json the only copy?

Run:  python tests/one-offs/thinking/market-history/probe.py [journal-dir]
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_DIR = Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous"

INTERESTING = (
    "Market",
    "MarketBuy",
    "MarketSell",
    "Docked",
)


def main(journal_dir):
    files = sorted(journal_dir.glob("Journal.*.log"))
    print(f"journal dir : {journal_dir}")
    print(f"files       : {len(files)}")
    if not files:
        print("no journal files found")
        return

    counts = Counter()
    market_keys = Counter()
    buy_keys = Counter()
    markets = {}                      # MarketID -> (name, system)
    traded = defaultdict(Counter)     # MarketID -> commodity -> transactions
    carries_commodities = 0
    first_ts = last_ts = None

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
                if name not in INTERESTING:
                    continue
                counts[name] += 1
                ts = ev.get("timestamp")
                if ts:
                    first_ts = ts if first_ts is None else min(first_ts, ts)
                    last_ts = ts if last_ts is None else max(last_ts, ts)

                if name == "Market":
                    market_keys.update(ev.keys())
                    mid = ev.get("MarketID")
                    if mid is not None:
                        markets[mid] = (
                            ev.get("StationName"),
                            ev.get("StarSystem"),
                        )
                    # the decisive question: is the stock list inline?
                    if "Items" in ev:
                        carries_commodities += 1

                elif name in ("MarketBuy", "MarketSell"):
                    buy_keys.update(ev.keys())
                    mid = ev.get("MarketID")
                    commodity = ev.get("Type_Localised") or ev.get("Type")
                    if mid is not None and commodity:
                        traded[mid][commodity] += 1

                elif name == "Docked":
                    mid = ev.get("MarketID")
                    if mid is not None and mid not in markets:
                        markets[mid] = (
                            ev.get("StationName"),
                            ev.get("StarSystem"),
                        )

    print(f"span        : {first_ts} .. {last_ts}")
    print()
    print("event counts:")
    for name, n in counts.most_common():
        print(f"  {name:12} {n}")

    print()
    print(f"distinct MarketIDs seen : {len(markets)}")
    print(f"Market events carrying an inline 'Items' list: {carries_commodities}")

    print()
    print("keys present on Market events:")
    for key, n in market_keys.most_common():
        print(f"  {key:24} {n}")

    print()
    print("keys present on MarketBuy/MarketSell events:")
    for key, n in buy_keys.most_common():
        print(f"  {key:24} {n}")

    print()
    print(f"markets with at least one transaction: {len(traded)}")
    top = sorted(traded.items(), key=lambda kv: -sum(kv[1].values()))[:8]
    for mid, commodities in top:
        name, system = markets.get(mid, ("(unknown)", "(unknown)"))
        total = sum(commodities.values())
        print(f"  {mid}  {name} / {system}")
        print(f"      {total} transactions across {len(commodities)} commodities")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    main(target)
