"""
READ-ONLY scan: which cells have #REF! baked into their FORMULA TEXT?

There are two very different things on a damaged sheet and conflating them
wastes a repair:

  DAMAGED  -- the formula text itself contains #REF!, e.g.
              =IF(#REF!="","",VLOOKUP(#REF!,FreighterData!$B:$D,2,FALSE))
              The reference was structurally deleted and Sheets rewrote the
              formula permanently. Only these need repair.

  CASCADE  -- the formula is intact and merely DISPLAYS #REF! because its
              range contains a damaged cell, e.g. =SUM(C5:C201).
              These fix themselves the moment the damaged cells are repaired.

This prints the damaged set, per row, so the repair is a known list rather
than a hunt -- and prints the cascade count separately so nobody "fixes" a
healthy SUM.

READ-ONLY. It fetches formulas and values and prints them. There is no
update, clear, resize or batch_update call in this file, and nothing here
constructs a write plan.

Run:  PYTHONIOENCODING=utf-8 python tests/one-offs/thinking/plugin-isolation/scan_broken_formulas.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

TOTALS = "Totals Tab"
SCAN = "A1:AC60"          # the region the workbook's own formulas live in
LINE = "=" * 78


def col_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def main() -> int:
    from APITool import settings
    from APITool.google import GoogleSheetsExporter

    sheet_id = settings.get_sheet_id(None)
    if not sheet_id:
        print("No sheet id configured.")
        return 1

    print(LINE)
    print(f"  READ-ONLY scan of '{TOTALS}' {SCAN}  (sheet ...{sheet_id[-6:]})")
    print(LINE)

    worksheet = (GoogleSheetsExporter()._get_client()
                 .open_by_key(sheet_id).worksheet(TOTALS))
    formulas = worksheet.get(SCAN, value_render_option="FORMULA")
    values = worksheet.get(SCAN)

    damaged: dict[int, list[str]] = defaultdict(list)
    cascade: dict[int, list[str]] = defaultdict(list)

    for r, row in enumerate(formulas):
        shown = values[r] if r < len(values) else []
        for c, formula in enumerate(row):
            value = shown[c] if c < len(shown) else ""
            cell = f"{col_name(c)}{r + 1}"
            if "#REF!" in str(formula):
                damaged[r + 1].append(cell)
            elif "#REF!" in str(value):
                cascade[r + 1].append(cell)

    print("\n  DAMAGED -- #REF! is inside the formula text. These need repair:")
    if not damaged:
        print("    none")
    for row in sorted(damaged):
        cells = damaged[row]
        print(f"    row {row:>3}: {len(cells):>2} cells  {', '.join(cells)}")

    print("\n  CASCADE -- formula intact, displays #REF! because its range")
    print("             contains a damaged cell. Self-healing; do NOT edit:")
    if not cascade:
        print("    none")
    for row in sorted(cascade):
        cells = cascade[row]
        print(f"    row {row:>3}: {len(cells):>2} cells  {', '.join(cells)}")

    total_damaged = sum(len(v) for v in damaged.values())
    total_cascade = sum(len(v) for v in cascade.values())
    print()
    print(LINE)
    print(f"  {total_damaged} damaged, {total_cascade} cascading, "
          f"across {len(damaged)} damaged row(s).")
    if len(damaged) == 1:
        row = next(iter(damaged))
        near = row - 1 if row > 5 else row + 1
        print(f"  One damaged row. Copying row {near}'s formulas down into")
        print(f"  row {row} would re-reference them to their own row.")
    print("  Nothing was written.")
    print(LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
