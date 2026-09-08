"""
AC-3 (issue #6 / the ship-cargo DWP): before pasting anything into the live
sheet, prove that

    M5 = IFERROR(VLOOKUP($B5, ShipCargo!$B:$C, 2, FALSE), 0)

would reproduce today's hand-typed column M exactly.

READ-ONLY. Opens the workbook, reads column B and column M, and computes what
the formula WOULD return from the ShipCargo grid the tool builds. Writes
nothing anywhere.

If this disagrees with the sheet, the migration is unsafe and the fallback
(candidate F: ship the data, leave M manual) is what happens instead.

Run: python tests/one-offs/thinking/column-m-migration/ac3_simulate.py <sheet-id>
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from APITool.catalog import load_catalog, normalize          # noqa: E402
from APITool.gsheet import GoogleSheetsExporter               # noqa: E402
from APITool.journal import JournalReader                     # noqa: E402
from APITool import ship as ship_mod                          # noqa: E402


def simulated_vlookup(grid: list[list], key: str) -> int:
    """
    What Google Sheets' VLOOKUP(key, B:C, 2, FALSE) would return.

    Sheets' exact-match VLOOKUP is case-INSENSITIVE, which matters here: the
    sheet spells two commodities differently from the catalog ("Building
    fabricators" vs "Building Fabricators"). This mirrors that assumption --
    and ac3_case_check.py verifies it against the real product rather than
    trusting this comment.
    """
    wanted = normalize(key)
    for row in grid:
        if len(row) >= 3 and normalize(str(row[1])) == wanted:
            value = row[2]
            return int(value) if str(value).strip().isdigit() else 0
    return 0  # the IFERROR(..., 0) arm


def main(sheet_id: str) -> int:
    raw = JournalReader().read_cargo_json()
    if raw is None:
        print("No Cargo.json; cannot simulate.")
        return 2
    cargo = ship_mod.from_journal(raw, load_catalog())
    grid = ship_mod.sheet_grid(cargo)

    book = GoogleSheetsExporter().open_spreadsheet(sheet_id)
    totals = book.worksheet("Totals Tab")

    names = [r[0] if r else "" for r in totals.get("B5:B201")]
    current = totals.get("M5:M201", value_render_option="FORMULA")

    print(f"Simulating against {len(names)} commodity rows\n")
    print(f"  {'row':>4}  {'commodity':<28} {'M now':>8}  {'VLOOKUP':>8}  verdict")
    print("  " + "-" * 66)

    mismatches, checked, nonzero = [], 0, 0
    for i, name in enumerate(names):
        if not str(name).strip():
            continue
        row_no = i + 5
        raw_m = current[i][0] if i < len(current) and current[i] else ""
        hand = int(raw_m) if str(raw_m).strip().lstrip("-").isdigit() else 0
        predicted = simulated_vlookup(grid, name)
        checked += 1
        if hand or predicted:
            nonzero += 1
            ok = "OK" if hand == predicted else "*** MISMATCH ***"
            print(f"  {row_no:>4}  {str(name)[:28]:<28} {hand:>8}  {predicted:>8}  {ok}")
        if hand != predicted:
            mismatches.append((row_no, name, hand, predicted))

    print()
    print(f"Rows checked          : {checked}")
    print(f"Rows with a value     : {nonzero}")
    print(f"Mismatches            : {len(mismatches)}")
    print(f"Sheet M4 total        : {totals.acell('M4').value}")
    print(f"Cargo.json total      : {cargo.total}")
    print()
    if mismatches:
        print("AC-3 FAILS -- do NOT paste the formula. Mismatched rows:")
        for row_no, name, hand, predicted in mismatches:
            print(f"  row {row_no}: {name!r} sheet={hand} formula={predicted}")
        return 1

    print("AC-3 PASSES -- the formula reproduces column M exactly.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
