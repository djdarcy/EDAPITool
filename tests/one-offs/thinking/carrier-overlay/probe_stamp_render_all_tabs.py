"""
READ-ONLY: what do the three generated tabs' timestamp cells ACTUALLY hold?

THE CLAIM UNDER SUSPICION
-------------------------
An acceptance check against issue #19 concluded that its criterion 3 --
"a formula can read it without string parsing (same format as the other two
tabs)" -- is self-contradictory, because all three tabs store ISO strings as
TEXT and text always needs parsing.

That conclusion was only MEASURED for FreighterData. For MarketData and
ShipCargo it was INFERRED from the write path (`export_grid` uses
value_input_option="RAW"). Inference dressed as measurement is exactly the
overclaim worth catching, and here it is load-bearing: if either of those
tabs holds a real date SERIAL rather than text, then "same format as the
other two tabs" is achievable, criterion 3 is satisfiable, and the
acceptance check was wrong.

THE TEST
--------
Read each stamp cell three ways. `UNFORMATTED_VALUE` is the discriminator:
  - a str  -> the cell holds text; a formula must parse it
  - a float/int -> the cell holds a date serial; `=NOW()-C2` works directly

SAFETY: reads only. Writes nothing to any tab. The commander's own `serve`
may be running and is unaffected.

Run:  python tests/one-offs/thinking/carrier-overlay/probe_stamp_render_all_tabs.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from APITool.google import GoogleSheetsExporter          # noqa: E402
from APITool.settings import get_sheet_id                # noqa: E402

# tab -> (label cell, value cell, where the layout says it lives)
TARGETS = {
    "MarketData":    ("B2", "C2", "market.py sheet_grid row 2"),
    "ShipCargo":     ("D1", "E1", "ship.py sheet_grid row 1"),
    "FreighterData": ("B1", "C1", "exporter.py carrier_grid row 1"),
}

MODES = ("FORMULA", "FORMATTED_VALUE", "UNFORMATTED_VALUE")


def main() -> int:
    sheet_id = get_sheet_id(None)
    if not sheet_id:
        print("no sheet id configured -- nothing to do")
        return 2

    exporter = GoogleSheetsExporter()
    verdicts = {}

    for tab, (label_cell, value_cell, where) in TARGETS.items():
        print(f"\n=== {tab}  ({where}) ===")
        try:
            ws = exporter.worksheet(sheet_id, tab)
        except Exception as exc:                        # noqa: BLE001
            print(f"  unreadable: {exc}")
            verdicts[tab] = "UNREADABLE"
            continue

        for cell, kind in ((label_cell, "label"), (value_cell, "value")):
            row = []
            for mode in MODES:
                try:
                    got = ws.get_values(cell, value_render_option=mode)
                    v = got[0][0] if got and got[0] else ""
                except Exception as exc:                # noqa: BLE001
                    v = f"<{exc}>"
                row.append((mode, v))
            print(f"  {cell} ({kind}):")
            for mode, v in row:
                print(f"      {mode:<18} {type(v).__name__:<6} {v!r}")

            if kind == "value":
                _, unformatted = row[2]
                if isinstance(unformatted, (int, float)):
                    verdicts[tab] = "DATE SERIAL"
                elif isinstance(unformatted, str) and unformatted.strip():
                    verdicts[tab] = "TEXT"
                else:
                    verdicts[tab] = "EMPTY/UNKNOWN"

    print("\n" + "=" * 68)
    for tab, v in verdicts.items():
        print(f"  {tab:<16} {v}")

    kinds = {v for v in verdicts.values() if v in ("TEXT", "DATE SERIAL")}
    print()
    if kinds == {"TEXT"}:
        print("[CONFIRMED] All three tabs store TEXT. 'Same format as the other")
        print("            two tabs' and 'without string parsing' cannot both")
        print("            hold. Criterion 3 is unsatisfiable as written.")
    elif "DATE SERIAL" in kinds and "TEXT" in kinds:
        print("[REFUTED]   The tabs DISAGREE with each other. The acceptance")
        print("            check was wrong: criterion 3 is satisfiable, and")
        print("            FreighterData is the odd one out.")
    elif kinds == {"DATE SERIAL"}:
        print("[REFUTED]   All are date serials -- including, apparently,")
        print("            FreighterData. Re-read the earlier measurement.")
    else:
        print("[INCONCLUSIVE] Not enough readable stamps to judge.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
