"""
Does the new FreighterData metadata row survive a REAL write to Sheets?

This is the check the human checklist (v0.6.4__Feature__...) calls HV.1-HV.4,
done by API instead of by eye -- and it is strictly better that way, because
`get_values` can ask for the FORMULA and the UNFORMATTED value, which is
exactly the distinction a person squinting at a formula bar is trying to make.

THE OPEN QUESTION IT SETTLES
----------------------------
`export_cargo` is the ONLY generated-tab writer using
`value_input_option="USER_ENTERED"` (exporter.py:555); `export_grid` and
`_write_region` both use RAW. USER_ENTERED is required here, because this grid
carries `=SUM(...)` and `=C4*D4` that must arrive as live formulas -- but it
also means Sheets PARSES everything else in the payload, including the ISO
timestamp U1 just added.

So: does `C1` come back as the literal string, or as a parsed date serial?
MarketData cannot answer it -- its stamp goes through RAW and is stored
verbatim. Nobody has ever written a timestamp to this tab through this door.

WHY IT MATTERS RATHER THAN BEING A CURIOSITY
--------------------------------------------
Sheets has no timezone-aware datetime. If it parses `+00:00`, it stores a
NAIVE serial in the SPREADSHEET's timezone, and the offset is gone. This
project has already eaten that exact bug once: MarketData!C2 holds a correct
UTC stamp, `NOW()` is spreadsheet-local, and a naive age formula under-reported
by the offset -- measured 16.03h where the truth was ~20h. A parsed stamp here
would reintroduce it on a new surface.

PREDICTION, written before running: Sheets PARSES it into a date serial,
because USER_ENTERED is the "as if a human typed it" path and a human typing
an ISO-8601 string into Sheets gets a datetime. If that holds, text is the
safer outcome and the write needs forcing.

WHAT IT DOES
------------
1. Reads FreighterData A1:F8 and a settlement tab's lookup column BEFORE.
2. Runs the real export through the working-tree code.
3. Reads both back AFTER, in three render modes.
4. Diffs the settlement column -- the 476-VLOOKUP check -- and reports.

SAFETY
------
- Writes ONLY to FreighterData, a tab the tool generates in full and rewrites
  on every publish. No hand-entered work is in its blast radius, and the write
  allowlist refuses anything else.
- Reads the settlement tab; never writes to it.
- The commander's own `serve`, if running, holds the PRE-EDIT code in memory
  and will overwrite this row on its next carrier publish. That is harmless --
  it just means the "after" read should happen promptly, which it does.

Run:  python tests/one-offs/thinking/carrier-overlay/probe_live_metadata_row.py
      [--settlement-tab "Agri Lrg. (ex)"] [--lookup-col D]
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from APITool.auth import FrontierAuth                       # noqa: E402
from APITool.capi import CAPIClient                         # noqa: E402
from APITool.google import GoogleSheetsExporter             # noqa: E402
from APITool.models import FleetCarrier                     # noqa: E402
from APITool.settings import get_client_id, get_sheet_id    # noqa: E402

BLOCK = "A1:F8"


def read_modes(ws, rng):
    """The same range three ways -- what is stored, shown, and underneath."""
    out = {}
    for label, opt in (("FORMULA", "FORMULA"),
                       ("FORMATTED", "FORMATTED_VALUE"),
                       ("UNFORMATTED", "UNFORMATTED_VALUE")):
        try:
            out[label] = ws.get_values(rng, value_render_option=opt)
        except Exception as exc:                       # noqa: BLE001
            out[label] = [[f"<read failed: {exc}>"]]
    return out


def show(title, grid):
    print(f"\n  -- {title} --")
    for i, row in enumerate(grid[:4], start=1):
        cells = " | ".join(f"{str(c)[:26]:<26}" for c in row[:6])
        print(f"    r{i}: {cells}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settlement-tab", default="Agri Lrg. (ex)")
    ap.add_argument("--lookup-col", default="D",
                    help="the column whose VLOOKUPs read FreighterData")
    args = ap.parse_args()

    sheet_id = get_sheet_id(None)
    if not sheet_id:
        print("no sheet id configured -- nothing to do")
        return 2
    client_id = get_client_id()
    if not client_id:
        print("no Frontier client id configured -- nothing to do")
        return 2
    auth = FrontierAuth(client_id)
    if not auth.is_authenticated:
        print("not authenticated -- run `edapitool auth` first")
        return 2

    exporter = GoogleSheetsExporter()
    fd = exporter.worksheet(sheet_id, "FreighterData")
    lookup_range = f"{args.lookup_col}5:{args.lookup_col}60"

    # ---- BEFORE -------------------------------------------------------
    print("=" * 72)
    print("BEFORE")
    before = read_modes(fd, BLOCK)
    show("FreighterData, as FORMULA", before["FORMULA"])
    try:
        settle = exporter.worksheet(sheet_id, args.settlement_tab)
        before_lookup = settle.get_values(lookup_range)
    except Exception as exc:                            # noqa: BLE001
        print(f"\n  settlement tab unreadable ({exc}) -- skipping the "
              f"VLOOKUP check")
        settle, before_lookup = None, None

    # ---- THE WRITE ----------------------------------------------------
    print("\n" + "=" * 72)
    print("WRITING FreighterData through the working-tree code")
    raw = CAPIClient(auth).get_fleet_carrier()
    carrier = FleetCarrier.from_capi(raw)
    from datetime import datetime, timezone
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    exporter.export_cargo(
        carrier, sheet_id=sheet_id,
        checked_at=checked_at,
        changed_at="",          # a one-shot has no memory of a prior reading
    )
    print(f"  sent checked_at = {checked_at!r}")

    # ---- AFTER --------------------------------------------------------
    print("\n" + "=" * 72)
    print("AFTER")
    after = read_modes(fd, BLOCK)
    for mode in ("FORMULA", "FORMATTED", "UNFORMATTED"):
        show(f"FreighterData, as {mode}", after[mode])

    # ---- the verdicts --------------------------------------------------
    print("\n" + "=" * 72)

    def cell(grid, r, c):
        try:
            return grid[r][c]
        except (IndexError, TypeError):
            return ""

    formula_c1 = cell(after["FORMULA"], 0, 2)
    unform_c1 = cell(after["UNFORMATTED"], 0, 2)
    print(f"C1 as FORMULA     : {formula_c1!r}")
    print(f"C1 as UNFORMATTED : {unform_c1!r}")
    if formula_c1 == checked_at:
        print("[TEXT]   Sheets stored the ISO string verbatim. The offset "
              "survives; an age formula must parse it deliberately.")
        print("         -> the SAFER outcome; prediction was WRONG.")
    elif isinstance(unform_c1, (int, float)) or str(unform_c1).replace(
            ".", "", 1).isdigit():
        print("[PARSED] Sheets converted it to a date serial. The +00:00 "
              "offset is GONE and the value is naive in the sheet's "
              "timezone -- the 16.03h bug's shape.")
        print("         -> prediction HELD; forcing text is the fix.")
    else:
        print("[OTHER]  Neither verbatim nor numeric. Inspect by hand.")

    print(f"\nB1 label          : {cell(after['FORMULA'], 0, 1)!r}")
    print(f"B2 (header row)   : {cell(after['FORMULA'], 1, 1)!r} "
          f"(must be 'Commodity')")
    print(f"B3 (totals row)   : {cell(after['FORMULA'], 2, 1)!r} "
          f"(must be 'TOTAL')")
    print(f"C3 (sum formula)  : {cell(after['FORMULA'], 2, 2)!r} "
          f"(must start at row 4)")
    print(f"B4 (first commodity): {cell(after['FORMULA'], 3, 1)!r}")

    # ---- the 476-VLOOKUP check ----------------------------------------
    if settle is not None and before_lookup is not None:
        after_lookup = settle.get_values(lookup_range)
        b = [r[0] if r else "" for r in before_lookup]
        a = [r[0] if r else "" for r in after_lookup]
        diffs = [(i + 5, x, y) for i, (x, y) in enumerate(zip(b, a)) if x != y]
        print(f"\n{args.settlement_tab}!{lookup_range}: "
              f"{len(diffs)} of {len(b)} cells changed")
        if not diffs:
            print("[OK]     every lookup returned what it returned before -- "
                  "the metadata row did not shift the contract")
        else:
            for row, x, y in diffs[:10]:
                print(f"    row {row}: {x!r} -> {y!r}")
            print("  NOTE: a change here is only a FAILURE if the carrier's "
                  "hold did not actually change. #N/A or #REF! is a failure "
                  "either way.")
            if any("#" in str(y) for _, _, y in diffs):
                print("[FAIL]   an error value appeared -- the lookup broke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
