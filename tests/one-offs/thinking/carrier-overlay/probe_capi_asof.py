"""
U4a: does Frontier's fleet-carrier payload carry an AS-OF timestamp?

THE QUESTION AND WHY IT DECIDES A DESIGN
----------------------------------------
The carrier-reconciliation design (2026-09-15__17-47-31__dev-workflow-process__
carrier-reconciliation-and-the-declaration-layer.md) weighed two candidates:

  C-3  derive the overlay from the journal, storing only a WATERMARK -- the
       moment the last confirmed reading actually describes. Simplest by far.
       Needs an as-of timestamp, because "when we fetched it" is 14-31 minutes
       later than "what it describes", and replaying from the fetch time would
       double-count everything that happened during the lag.

  C-4  a per-commodity delta ledger retired by observed movement. Needs no
       as-of timestamp -- it only ever asks what the payload says NOW.

C-4 was recommended BECAUSE it is correct without this fact. If the fact turns
out to be available, C-3 is simpler and should win. Decision ledger entry L-2.

PREDICTION, written before the call: no as-of field. Frontier's CAPI is a
cache-backed read and nothing in the tool or in EDMarketConnector's handling
suggests one is exposed. If that prediction is wrong, a subsystem disappears.

PASS CRITERION: a top-level or near-top-level field whose value is a timestamp
EARLIER than the moment of the call, by something in the region of the measured
lag. A field equal to "now" is a response stamp, not an as-of -- it would say
when Frontier answered, not when the data was true, and is NOT sufficient.

SAFETY
------
- Credentials are reached only through the tool's own resolver. This script
  never opens ~/.ed_capi_config.json or ~/.ed_capi_tokens.json itself.
- The payload carries the commander's carrier finances. It is written OUTSIDE
  the repository -- to --out, or to a temp directory -- and never printed.
  Only key NAMES and timestamp-shaped values reach stdout.
- One request. Frontier does not enforce a cooldown (measured 2026-09-15), and
  `_last_fc_query_time` is per-instance, so a running `serve` is unaffected.

Run:  python tests/one-offs/thinking/carrier-overlay/probe_capi_asof.py [--out DIR]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from APITool.auth import FrontierAuth           # noqa: E402
from APITool.capi import CAPIClient             # noqa: E402
from APITool.settings import get_client_id      # noqa: E402

# Anything that looks like a date. Deliberately loose: the point is to find a
# candidate, not to validate a format we have guessed in advance.
TIMESTAMPISH = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"          # 2026-09-15T18:20
    r"|^\d{10}$"                                   # unix seconds
    r"|^\d{13}$"                                   # unix millis
)
NAMEISH = re.compile(
    r"time|date|stamp|updated|refresh|asof|as_of|fetched|cached|expiry|expires",
    re.I,
)


def walk(node, path="", depth=0, max_depth=4):
    """Yield (path, value) for every scalar, breadth-limited."""
    if depth > max_depth:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else str(k), depth + 1, max_depth)
    elif isinstance(node, list):
        # One representative element is enough to learn the shape.
        if node:
            yield from walk(node[0], f"{path}[0]", depth + 1, max_depth)
    else:
        yield path, node


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None,
                    help="directory for the raw payload. Defaults to a "
                         "temp directory OUTSIDE the repository -- the "
                         "payload carries the commander's carrier finances "
                         "and must never default to a path under version "
                         "control")
    args = ap.parse_args()

    client_id = get_client_id()
    if not client_id:
        print("no Frontier client id configured -- nothing to do")
        return 2
    auth = FrontierAuth(client_id)
    if not auth.is_authenticated:
        print("not authenticated -- run `edapitool auth` first")
        return 2

    called_at = dt.datetime.now(dt.timezone.utc)
    client = CAPIClient(auth)
    raw = client.get_fleet_carrier()
    returned_at = dt.datetime.now(dt.timezone.utc)

    print(f"call issued  : {called_at.isoformat()}")
    print(f"call returned: {returned_at.isoformat()} "
          f"({(returned_at - called_at).total_seconds():.2f}s)")
    print(f"top-level keys: {sorted(raw.keys())}\n")

    # ---- the search ------------------------------------------------------
    by_name, by_value = [], []
    for path, value in walk(raw):
        text = str(value).strip()
        if NAMEISH.search(path.split(".")[-1]):
            by_name.append((path, text[:60]))
        if text and TIMESTAMPISH.match(text):
            by_value.append((path, text[:60]))

    print("fields whose NAME suggests a time:")
    for p, v in by_name or [("(none)", "")]:
        print(f"    {p:<50} {v}")

    print("\nfields whose VALUE looks like a timestamp:")
    for p, v in by_value or [("(none)", "")]:
        print(f"    {p:<50} {v}")

    # ---- verdict ---------------------------------------------------------
    print("\n" + "=" * 70)
    candidates = {p for p, _ in by_name} | {p for p, _ in by_value}
    if not candidates:
        print("[SURVIVED] prediction held: NO as-of timestamp in the payload.")
        print("    -> L-2 resolved: C-3 is not available. Build C-4 (the ledger).")
    else:
        print("[CHECK BY HAND] candidate time-like fields found:")
        for p in sorted(candidates):
            print(f"    {p}")
        print("\n    A field equal to the call time is a RESPONSE stamp and does")
        print("    NOT settle this. It qualifies only if it is EARLIER than the")
        print("    call by roughly the measured lag (14-31 min). Compare against")
        print(f"    call time {called_at.isoformat()}.")

    # ---- the payload, out of the repo ------------------------------------
    # Default outside the repository. Not because the credits are money --
    # they are in-game numbers and nobody's bank is involved -- but because
    # this is one commander's account state (callsign, current system, ships
    # owned, standing market orders), and because a raw API capture sitting
    # in a tree becomes a fixture somebody later trusts as current. Keeping
    # it out is cheap; noticing it went in is not.
    out_dir = pathlib.Path(args.out) if args.out else \
        pathlib.Path(tempfile.gettempdir()) / "edapitool-carrier-payloads"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"fleetcarrier_{called_at:%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(f"\nraw payload written to: {out}")
    print("  (carries carrier finances -- do NOT commit it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
