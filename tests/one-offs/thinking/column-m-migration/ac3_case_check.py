"""
AC-3b: is Google Sheets' exact-match VLOOKUP case-INSENSITIVE?

The whole column-M migration rests on this. The sheet spells two commodities
differently from the catalog:

    sheet: "Building fabricators"     ShipCargo: "Building Fabricators"
    sheet: "Structural regulators"    ShipCargo: "Structural Regulators"

If VLOOKUP(..., FALSE) is case-SENSITIVE, those two rows resolve to 0 through
IFERROR, column M loses 156 of its 227 tonnes, "Left to buy" inflates by the
same amount, and the marker column starts recommending purchases already in
the hold. The simulation in ac3_simulate.py assumes insensitivity; this asks
the product.

Writes only to scratch cells in the ShipCargo tab -- a tab this tool generates
and rewrites wholesale -- and clears them afterwards. Touches nothing else.

Run: python tests/one-offs/thinking/column-m-migration/ac3_case_check.py <sheet-id>
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from APITool.gsheet import GoogleSheetsExporter  # noqa: E402

SCRATCH = "G1:G4"

# Each probe: (label, lookup key, expected quantity if case-insensitive)
PROBES = [
    ("exact case (CONTROL -- must hit either way)", "Biowaste", 62),
    ("sheet's lowercase 'fabricators'", "Building fabricators", 40),
    ("sheet's lowercase 'regulators'", "Structural regulators", 116),
    ("a commodity not aboard (CONTROL -- must MISS)", "Tritium", "MISS"),
]


def main(sheet_id: str) -> int:
    ws = GoogleSheetsExporter().open_spreadsheet(sheet_id).worksheet("ShipCargo")

    formulas = [
        [f'=IFERROR(VLOOKUP("{key}", $B:$C, 2, FALSE), "MISS")']
        for _, key, _ in PROBES
    ]
    ws.update(formulas, SCRATCH, value_input_option="USER_ENTERED")
    try:
        results = ws.get(SCRATCH, value_render_option="FORMATTED_VALUE")
    finally:
        ws.batch_clear([SCRATCH])

    print("VLOOKUP(key, $B:$C, 2, FALSE) against the live ShipCargo tab\n")
    ok = True
    for i, (label, key, expected) in enumerate(PROBES):
        got = results[i][0] if i < len(results) and results[i] else ""
        got_norm = got if got == "MISS" else int(got) if str(got).isdigit() else got
        verdict = "OK" if got_norm == expected else "*** UNEXPECTED ***"
        if got_norm != expected:
            ok = False
        print(f"  {label:<46} {key!r:<26} -> {got!r:<8} {verdict}")

    print()
    if not ok:
        print("AC-3b FAILS. Do NOT paste the column-M formula:")
        print("  either VLOOKUP is case-sensitive here, or the control arms")
        print("  disagree, which means this probe is not measuring what it claims.")
        return 1

    print("AC-3b PASSES -- exact-match VLOOKUP is case-insensitive, and both")
    print("control arms behaved (the exact-case hit, the absent commodity missed).")
    print("The two case-divergent rows resolve correctly, so the migration is safe.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
