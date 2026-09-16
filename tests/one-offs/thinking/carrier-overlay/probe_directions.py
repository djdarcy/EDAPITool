"""
PROBE: is `CargoTransfer.Direction` enough to know a transfer touched the CARRIER?

Written for the carrier-reconciliation design pass (2026-09-15). The daemon's
own comment says:

    # `CargoTransfer` carries a Direction per item -- measured across 120
    # journal files: 138 "tocarrier", 112 "toship" -- but BOTH change the
    # carrier, so the direction is not worth branching on here.

That is safe for a *trigger* (a spurious wake-up costs one CAPI call). It is
NOT obviously safe for an *overlay*, which applies the tonnage arithmetically:
a transfer misattributed to the carrier moves the published number by its full
Count, and nothing afterwards says it was wrong.

THE HYPOTHESIS UNDER TEST (H1):
    `Direction` alone partitions transfers into carrier / not-carrier.

THE FALSIFIER:
    Find any Direction value that is not "tocarrier"/"toship", OR any "toship"
    that happened while the commander was demonstrably not at a fleet carrier.
    Either kills H1.

THE CONTROL (H0):
    The docking tracker must be able to report a NON-carrier station for at
    least one transfer. If every transfer in eight years of logs resolves to a
    fleet carrier, the instrument cannot distinguish the two cases and no
    result here means anything.

Run:  python tests/one-offs/thinking/carrier-overlay/probe_directions.py
"""

from __future__ import annotations

import collections
import glob
import json
import os
import sys

JOURNAL_DIR = os.path.expanduser(
    "~/Saved Games/Frontier Developments/Elite Dangerous"
)


def journals(limit: int | None = None) -> list[str]:
    files = sorted(glob.glob(os.path.join(JOURNAL_DIR, "Journal*.log")))
    return files if limit is None else files[-limit:]


def main() -> int:
    files = journals()
    print(f"scanning {len(files)} journal files")

    directions = collections.Counter()
    # Direction -> what the commander was docked at when it happened.
    context = collections.Counter()
    # Commodity types seen per direction, to show what is actually moving.
    types_by_direction = collections.defaultdict(collections.Counter)
    station_types_seen = collections.Counter()
    transfer_events = 0
    samples: list[str] = []

    # Rolling docking state. `Docked` gives StationType; `Undocked` clears it.
    # `SupercruiseExit`/`FSDJump` also clear it -- a transfer in flight cannot
    # be at a station at all.
    docked_type: str | None = None
    docked_name: str | None = None
    srv_events = collections.Counter()
    last_srv_ts: str | None = None
    # A "toship" with no carrier in sight, and whether an SRV was out.
    orphan_toship = collections.Counter()

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

                if name == "Docked":
                    docked_type = e.get("StationType") or "?"
                    docked_name = e.get("StationName") or "?"
                    station_types_seen[docked_type] += 1
                    continue
                # A session that RESUMES while already docked emits `Location`
                # with Docked:true rather than a fresh `Docked`. Without this,
                # every transfer made after a relog reads as "NOT DOCKED" and
                # the probe manufactures the very finding it is testing for.
                if name in ("Location", "CarrierJump"):
                    if e.get("Docked"):
                        docked_type = e.get("StationType") or "?"
                        docked_name = e.get("StationName") or "?"
                        station_types_seen[docked_type] += 1
                    else:
                        docked_type = None
                        docked_name = None
                    continue
                if name in ("Undocked", "FSDJump", "StartJump", "Shutdown"):
                    docked_type = None
                    docked_name = None
                    continue
                # SRV activity, tracked so a "toship" can be attributed to the
                # SRV rather than left as an unexplained non-carrier transfer.
                if name in ("LaunchSRV", "DockSRV", "SRVDestroyed"):
                    srv_events[name] += 1
                    last_srv_ts = e.get("timestamp")
                    continue
                if name != "CargoTransfer":
                    continue

                transfer_events += 1
                where = docked_type or "NOT DOCKED"
                for t in e.get("Transfers", []):
                    d = t.get("Direction", "<missing>")
                    directions[d] += 1
                    context[(d, where)] += 1
                    types_by_direction[d][t.get("Type", "?")] += 1
                    if d == "toship" and where != "FleetCarrier":
                        orphan_toship[
                            "srv seen earlier in log" if last_srv_ts
                            else "no srv seen at all"
                        ] += 1
                if len(samples) < 6:
                    samples.append(
                        f"    {e.get('timestamp')}  at {where}/{docked_name}  "
                        f"{json.dumps(e.get('Transfers'))[:160]}"
                    )

    print(f"\n{transfer_events} CargoTransfer events\n")

    print("Directions observed:")
    for d, n in directions.most_common():
        print(f"    {d:<12} {n:>6}")

    print("\nDirection x docking context:")
    for (d, where), n in sorted(context.items(), key=lambda kv: -kv[1]):
        print(f"    {d:<12} {where:<28} {n:>6}")

    print("\nWhat moves, per direction (top 5):")
    for d, counter in types_by_direction.items():
        top = ", ".join(f"{k}={v}" for k, v in counter.most_common(5))
        print(f"    {d:<12} {top}")

    print("\nSample events:")
    for s in samples:
        print(s)

    print(f"\nSRV events seen: {dict(srv_events)}")
    print(f'"toship" with no carrier present: {dict(orphan_toship)}')

    # ---- verdicts ---------------------------------------------------------
    print("\n" + "=" * 70)

    expected = {"tocarrier", "toship"}
    unexpected = set(directions) - expected
    if unexpected:
        print("[REFUTED]  H1: Direction alone partitions carrier transfers")
        print(f"    predicted : only {sorted(expected)}")
        print(f"    observed  : also {sorted(unexpected)}")
        print("    fallback  : the overlay must key on the COUNTERPARTY, not "
              "the direction alone")
    else:
        print("[SURVIVED] H1: only tocarrier/toship observed")

    # The control: can this instrument tell a carrier from a non-carrier?
    non_carrier_contexts = {
        where for (_, where) in context
        if where not in ("FleetCarrier",)
    }
    if non_carrier_contexts:
        print(f"\n[CONTROL FIRED] the tracker distinguished non-carrier "
              f"contexts: {sorted(non_carrier_contexts)}")
        print("    -> the instrument can detect the failure it looked for")
    else:
        print("\n[CONTROL DEAD] every transfer resolved to a FleetCarrier; "
              "this probe cannot distinguish the cases and proves nothing")

    print(f"\nStationTypes seen while docking (top 10): "
          f"{station_types_seen.most_common(10)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
