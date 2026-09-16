"""
Two measurements the carrier-reconciliation design ASSERTED rather than ran.

Written because the design pass was asked "what else can we measure to
double-check ourselves?", and the honest answer was that one claim had been
refuted by measurement (Direction) while two load-bearing ones had not been
touched at all.

M1 -- HOW MUCH TONNAGE DOES THE ATTRIBUTION GATE ACTUALLY MOVE?
    probe_directions.py proved that 42% of `toship` transfers did not happen
    at a carrier. It counted EVENTS. What the overlay applies is TONNES, and
    a rare event moving 840 t matters more than forty moving 2 t each. This
    converts the refutation into the unit the design actually uses.

    PREDICTION: the gate removes a large absolute tonnage, because the
    non-carrier transfers are SRV salvage in ones and twos while the carrier
    ones are construction freight in the hundreds -- so the EVENT split (42%)
    should OVERSTATE the TONNAGE error. If tonnage error is also ~42%, my
    reading of why those transfers are non-carrier is wrong.

M2 -- IS THE WRITE QUOTA REALLY A NON-ISSUE?
    Stage 1 pruned "optimization" from the consequence dimensions on the
    claim that "the API quota is nowhere near a constraint at these rates".
    That was asserted. Google allows 60 writes/min/user. The design adds a
    metadata write on every check. This replays real journal event density
    through the daemon's own debounce to bound publishes per minute.

    PREDICTION: peak sustained publish rate stays under 20/min, leaving the
    added metadata write comfortably inside budget. If it exceeds 40/min the
    pruning was wrong and the metadata write needs its own floor.

Run:  python tests/one-offs/thinking/carrier-overlay/measure_gate_and_quota.py
"""

from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import os
import sys

JOURNAL_DIR = os.path.expanduser(
    "~/Saved Games/Frontier Developments/Elite Dangerous"
)

# Straight from APITool/daemon.py, so this measures the shipped behaviour
# rather than a restatement of it.
MARKET_EVENTS = frozenset(
    {"Docked", "Undocked", "Location", "FSDJump", "CarrierJump", "Market"})
CARGO_EVENTS = frozenset({"Cargo", "CargoTransfer", "Docked", "Undocked"})
CONSTRUCTION_EVENTS = frozenset(
    {"ColonisationConstructionDepot", "ColonisationContribution", "Docked"})
CARRIER_EVENTS = frozenset(
    {"CargoTransfer", "MarketBuy", "MarketSell", "CarrierTradeOrder"})
DEBOUNCE = 5.0          # Daemon.debounce default
CARRIER_FLOOR = 60.0    # CARRIER_MIN_INTERVAL


def ts(raw):
    try:
        return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def main() -> int:
    files = sorted(glob.glob(os.path.join(JOURNAL_DIR, "Journal*.log")))
    print(f"scanning {len(files)} journal files\n")

    # --- M1 state ---
    docked_type = None
    naive_in = naive_out = gated_in = gated_out = 0
    misattributed = 0
    by_reason = collections.Counter()
    biggest = []

    # --- M2 state ---
    # event name -> list of timestamps, for the four trigger sets
    fires = collections.defaultdict(list)

    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"event"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                name = e.get("event")
                when = ts(e.get("timestamp"))

                # ---- M2: every event that would wake a publisher ----
                if when:
                    for tgt, trig in (("market", MARKET_EVENTS),
                                      ("cargo", CARGO_EVENTS),
                                      ("region", CONSTRUCTION_EVENTS),
                                      ("carrier", CARRIER_EVENTS)):
                        if name in trig:
                            fires[tgt].append(when)

                # ---- M1: docking state ----
                if name == "Docked":
                    docked_type = e.get("StationType") or "?"
                    continue
                if name in ("Location", "CarrierJump"):
                    docked_type = (e.get("StationType") or "?") \
                        if e.get("Docked") else None
                    continue
                if name in ("Undocked", "FSDJump", "StartJump", "Shutdown"):
                    docked_type = None
                    continue
                if name != "CargoTransfer":
                    continue

                at_carrier = (docked_type == "FleetCarrier")
                for t in e.get("Transfers", []):
                    d = t.get("Direction")
                    n = int(t.get("Count") or 0)

                    # NAIVE: the rule the design was handed -- both directions
                    # change the carrier, so apply both.
                    if d == "tocarrier":
                        naive_in += n
                    elif d == "toship":
                        naive_out += n

                    # GATED: tocarrier is unambiguous; toship only counts at a
                    # carrier; tosrv never counts.
                    if d == "tocarrier":
                        gated_in += n
                    elif d == "toship" and at_carrier:
                        gated_out += n
                    else:
                        if d != "tocarrier":
                            misattributed += n if d == "toship" else 0
                            by_reason[
                                f"{d} @ {docked_type or 'not docked'}"] += n
                            if d == "toship" and n >= 20:
                                biggest.append(
                                    (n, t.get("Type"),
                                     str(e.get("timestamp"))[:10]))

    # ================= M1 =================
    print("=" * 72)
    print("M1 -- what the attribution gate moves, in TONNES")
    print("=" * 72)
    naive_net = naive_in - naive_out
    gated_net = gated_in - gated_out
    print(f"  naive (Direction only) : +{naive_in:,} in  -{naive_out:,} out "
          f"-> net {naive_net:+,} t")
    print(f"  gated (at own carrier) : +{gated_in:,} in  -{gated_out:,} out "
          f"-> net {gated_net:+,} t")
    print(f"  tonnage wrongly SUBTRACTED from the carrier by the naive rule: "
          f"{misattributed:,} t")
    if naive_out:
        print(f"  as a share of all 'toship' tonnage: "
              f"{misattributed / naive_out:.1%}")
    print(f"  net error the gate removes: {abs(gated_net - naive_net):,} t")
    print("\n  where the misattributed tonnage came from:")
    for reason, n in by_reason.most_common(6):
        print(f"      {reason:<34} {n:>7,} t")
    if biggest:
        print("\n  single non-carrier transfers of 20 t or more:")
        for n, what, day in sorted(biggest, reverse=True)[:5]:
            print(f"      {n:>5} t  {what:<24} {day}")
    else:
        print("\n  no single non-carrier transfer reached 20 t")

    # ================= M2 =================
    print("\n" + "=" * 72)
    print("M2 -- publishes per minute, replayed through the real debounce")
    print("=" * 72)
    worst_overall = 0
    for tgt, stamps in fires.items():
        stamps.sort()
        floor = CARRIER_FLOOR if tgt == "carrier" else 0.0
        # A publish happens when a burst goes quiet for `debounce`, and never
        # sooner than `floor` after the previous publish -- Daemon.due().
        publishes, last_pub = [], None
        for i, t in enumerate(stamps):
            quiet = (i + 1 == len(stamps)
                     or (stamps[i + 1] - t).total_seconds() > DEBOUNCE)
            if not quiet:
                continue
            due = t + dt.timedelta(seconds=DEBOUNCE)
            if last_pub and (due - last_pub).total_seconds() < floor:
                continue
            publishes.append(due)
            last_pub = due
        # Densest 60-second window.
        peak, j = 0, 0
        for i, p in enumerate(publishes):
            while (p - publishes[j]).total_seconds() > 60:
                j += 1
            peak = max(peak, i - j + 1)
        worst_overall += peak
        print(f"  {tgt:<9} {len(stamps):>7,} trigger events -> "
              f"{len(publishes):>6,} publishes, peak {peak:>2}/min")
    print(f"\n  worst case if every target peaked together: "
          f"{worst_overall}/min against a 60/min quota")

    # ---- verdicts ----
    print("\n" + "=" * 72)
    if naive_out and misattributed / naive_out < 0.30:
        print("[SURVIVED] M1 prediction: event error (42%) OVERSTATES tonnage "
              f"error ({misattributed / naive_out:.1%}) -- the non-carrier "
              "transfers really are small salvage.")
    else:
        print("[CHECK] M1: tonnage error is NOT smaller than the event error. "
              "The reading of WHY those transfers are non-carrier needs revisiting.")
    if worst_overall < 20:
        print(f"[SURVIVED] M2 prediction: peak {worst_overall}/min is well "
              "under 60/min. Pruning 'optimization' was justified; the added "
              "metadata write fits.")
    elif worst_overall < 40:
        print(f"[MARGINAL] M2: peak {worst_overall}/min. Fits, but the metadata "
              "write should carry its own floor.")
    else:
        print(f"[REFUTED] M2: peak {worst_overall}/min. The pruning was wrong.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
