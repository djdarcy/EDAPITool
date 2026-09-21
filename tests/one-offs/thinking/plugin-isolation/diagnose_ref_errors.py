"""
READ-ONLY diagnostic: what do the #REF! cells on 'Totals Tab' actually contain?

The maintainer reports #REF! across row 4's headers and in row 28, noticed
after tonight's `serve` run on the v0.7.5 build. #REF! means a reference is
invalid -- a deleted row/column/sheet, or a VLOOKUP/INDEX whose column index
exceeds its range's width. Guessing between those is pointless; the formula
text says which.

This script READS ONLY. It opens the spreadsheet, fetches the formulas (not
the rendered values) for a few small ranges, and prints them. It performs no
update, no clear, no resize, and touches no tab but the two it reads.

Safety, explicitly: there is no call here that can write. `worksheet.get`
with value_render_option='FORMULA' is a read. Nothing constructs a write
plan, and the write guard is not involved because no write is attempted.

Run:  python tests/one-offs/thinking/plugin-isolation/diagnose_ref_errors.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

TOTALS = "Totals Tab"
LINE = "=" * 78


def show(worksheet, label: str, a1: str) -> None:
    """Print one range twice: as formulas, and as the values a reader sees."""
    print()
    print(f"--- {label}  ({a1}) ---")
    try:
        formulas = worksheet.get(a1, value_render_option="FORMULA")
    except Exception as exc:  # noqa: BLE001 -- diagnostic, report and continue
        print(f"    could not read formulas: {type(exc).__name__}: {exc}")
        return
    try:
        rendered = worksheet.get(a1)
    except Exception:  # noqa: BLE001
        rendered = []

    for r, row in enumerate(formulas):
        shown = rendered[r] if r < len(rendered) else []
        for c, cell in enumerate(row):
            value = shown[c] if c < len(shown) else ""
            if not str(cell).strip() and not str(value).strip():
                continue
            flag = "  <<< #REF!" if "#REF" in str(value) or "#REF" in str(cell) else ""
            print(f"    [{r},{c}] value={value!r}")
            print(f"          formula={str(cell)[:180]!r}{flag}")


def main() -> int:
    from APITool import settings
    from APITool.google import GoogleSheetsExporter

    sheet_id = settings.get_sheet_id(None)
    if not sheet_id:
        print("No sheet id configured.")
        return 1
    print(LINE)
    print(f"  READ-ONLY diagnostic against sheet ...{sheet_id[-6:]}")
    print(LINE)

    exporter = GoogleSheetsExporter()
    client = exporter._get_client()
    spreadsheet = client.open_by_key(sheet_id)

    print("\n  Tabs present:")
    for ws in spreadsheet.worksheets():
        print(f"    {ws.title!r}  {ws.row_count} rows x {ws.col_count} cols")

    totals = spreadsheet.worksheet(TOTALS)
    show(totals, "row 4 headers", "A4:N4")
    show(totals, "row 28", "A28:N28")
    show(totals, "rows 1-3, for contrast", "A1:H3")
    show(totals, "a working data row, for contrast", "A16:N16")

    print()
    print(LINE)
    print("  Read complete. Nothing was written.")
    print(LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
