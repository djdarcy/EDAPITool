"""
Can the carrier manifest be kept live from the journal, with the CAPI as a
rare baseline rather than a dependency?

THE CLAIM UNDER TEST, in three parts:

  baseline   the CAPI (or the last published FreighterData) gives a manifest
  deltas     `CargoTransfer` events are itemized, so they can be applied to it
  checksum   `CarrierStats.SpaceUsage.Cargo` is a running TOTAL, so a derived
             manifest can be checked against it without another CAPI call

If that holds, the daemon can publish an accurate carrier hold continuously and
call the CAPI only when the checksum says it has drifted -- rather than on a
15-minute timer and hoping.

THE FALSIFIER: derive a manifest from (sheet baseline + journal deltas), then
fetch the real one from the CAPI and diff them per commodity. If they disagree
by anything the checksum did not predict, the method does not work.

Run:  python tests/one-offs/thinking/carrier-delta/poc.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from APITool.catalog import load_catalog          # noqa: E402
from APITool.catalog import normalize             # noqa: E402

# Resolved the way the tool resolves it -- ED_SHEET_ID, then the config file --
# so the probe runs against whoever's workbook is configured rather than being
# welded to one. Not a secrecy measure: the maintainer's sheet is deliberately
# public and linked from the README as a template for other commanders. The
# reason is simply that a probe nobody else can run is a probe nobody else
# will re-run when they want to check whether its finding still holds.
def _sheet_id() -> str:
    env = os.environ.get("ED_SHEET_ID")
    if env:
        return env
    cfg = pathlib.Path(os.path.expanduser("~")) / ".ed_capi_config.json"
    if cfg.exists():
        try:
            value = json.loads(cfg.read_text(encoding="utf-8")).get("sheet_id")
            if value:
                return value
        except Exception:
            pass
    raise SystemExit(
        "No spreadsheet id. Set ED_SHEET_ID, or add \"sheet_id\" to "
        "~/.ed_capi_config.json, then re-run."
    )


SHEET = _sheet_id()
JOURNALS = (
    pathlib.Path(os.path.expanduser("~"))
    / "Saved Games" / "Frontier Developments" / "Elite Dangerous"
)


def journal_events(limit_files: int = 12):
    """Every event from the most recently MODIFIED journals.

    Sorted by mtime, not by name: the filename format changed between
    `Journal.220219184025.01.log` and `Journal.2026-09-10T205537.01.log`, and
    alphabetically the 2022 files sort LAST. Sorting by name silently reads
    four-year-old logs, which is how the first pass at this measured nothing.
    """
    files = sorted(JOURNALS.glob("Journal.*.log"), key=lambda f: f.stat().st_mtime)
    for f in files[-limit_files:]:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                yield json.loads(line)
            except Exception:
                continue


def main() -> int:
    from APITool.google import GoogleSheetsExporter

    print("=" * 70)
    print("STEP 1  the baseline: FreighterData as it stands on the sheet")
    print("=" * 70)
    ws = GoogleSheetsExporter().worksheet(SHEET, "FreighterData")
    rows = ws.get_values("B3:D400")
    baseline: Counter = Counter()
    for r in rows:
        if not r or not r[0].strip() or r[0].strip().upper() == "TOTAL":
            continue
        try:
            baseline[normalize(r[0])] = int(str(r[1]).replace(",", "") or 0)
        except (ValueError, IndexError):
            continue
    base_total = sum(baseline.values())
    print(f"  {len(baseline)} commodities, {base_total} t")

    print()
    print("=" * 70)
    print("STEP 2  anchor it: which CarrierStats does that total match?")
    print("=" * 70)
    stats, transfers = [], []
    for ev in journal_events():
        n = ev.get("event")
        if n == "CarrierStats":
            stats.append((ev["timestamp"], ev.get("SpaceUsage", {}).get("Cargo")))
        elif n == "CargoTransfer":
            transfers.append(ev)
    anchor = None
    for ts, cargo in stats:
        if cargo == base_total:
            anchor = ts          # keep the LATEST match
    print(f"  {len(stats)} CarrierStats, {len(transfers)} CargoTransfer events")
    if anchor is None:
        print(f"  !! no CarrierStats reports {base_total} t -- cannot anchor.")
        print("     Either the sheet predates these journals, or it already drifted.")
        print(f"     closest totals seen: {sorted({c for _, c in stats})[-6:]}")
        return 2
    print(f"  baseline anchored at {anchor} (cargo == {base_total})")

    print()
    print("=" * 70)
    print("STEP 3  apply the deltas recorded since that moment")
    print("=" * 70)
    derived = Counter(baseline)
    applied = 0
    for ev in transfers:
        if ev["timestamp"] <= anchor:
            continue
        for t in ev.get("Transfers", []):
            key = normalize(t["Type"])
            count = int(t["Count"])
            # `tocarrier` moves cargo INTO the hold this manifest describes.
            derived[key] += count if t["Direction"] == "tocarrier" else -count
            applied += 1
            print(f"  {ev['timestamp']}  {t['Direction']:<10} {count:>6} x {t['Type']}")
    if not applied:
        print("  (none since the anchor -- the sheet should still be accurate)")
    derived_total = sum(derived.values())
    print(f"\n  derived total: {derived_total} t   (was {base_total})")

    print()
    print("=" * 70)
    print("STEP 4  the checksum: does the journal agree with the derivation?")
    print("=" * 70)
    latest_ts, latest_cargo = stats[-1]
    print(f"  latest CarrierStats  {latest_ts}  cargo = {latest_cargo}")
    later = [t for t in transfers if t["timestamp"] > latest_ts]
    print(f"  transfers after it   {len(later)}")
    # Only comparable when nothing moved after the last stats event.
    if not later:
        ok = derived_total == latest_cargo
        print(f"  checksum {'AGREES' if ok else 'DISAGREES'}: "
              f"derived {derived_total} vs reported {latest_cargo}")
    else:
        print("  (transfers happened after the last CarrierStats, so the checksum")
        print("   is older than the derivation -- not comparable this run)")

    print()
    print("=" * 70)
    print("STEP 5  THE FALSIFIER: what does the CAPI actually say?")
    print("=" * 70)
    from APITool.auth import FrontierAuth
    from APITool.capi import CAPIClient
    from APITool.cli import get_client_id
    from APITool.models import FleetCarrier

    auth = FrontierAuth(get_client_id())
    if not auth.is_authenticated:
        print("  !! not authenticated -- run `edapitool auth`. Steps 1-4 still stand.")
        return 3
    carrier = FleetCarrier.from_capi(CAPIClient(auth).get_fleet_carrier())
    truth: Counter = Counter()
    for item in carrier.cargo:
        truth[normalize(item.localized_name or item.commodity)] += item.quantity
    print(f"  CAPI reports {len(truth)} commodities, {sum(truth.values())} t")

    print()
    print("-" * 70)
    print("  DERIVED vs TRUTH, per commodity")
    print("-" * 70)
    names = sorted(set(derived) | set(truth))
    diffs = [(n, derived.get(n, 0), truth.get(n, 0)) for n in names
             if derived.get(n, 0) != truth.get(n, 0)]
    if not diffs:
        print("  IDENTICAL. The method reproduces the CAPI manifest exactly.")
    else:
        for n, d, t in diffs:
            print(f"  {n[:34]:<34} derived={d:>7}  capi={t:>7}  diff={d - t:>+7}")
        print(f"\n  {len(diffs)} commodities disagree; "
              f"total derived={sum(derived.values())} capi={sum(truth.values())}")
    print()
    print("VERDICT:", "method holds" if not diffs else "method does NOT reproduce truth")
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())
