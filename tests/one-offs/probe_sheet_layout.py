#!/usr/bin/env python
"""
READ-ONLY probe of the live Google Sheet to discover the actual layout of
"Totals Tab" (and neighbours) before any integration code is written.

Writes NOTHING. Prints:
  - every worksheet title, id, and grid size
  - for "Totals Tab": rows 1..8 raw values, and column B from row 5 down
  - header row detection: which row/column holds "Left to buy", "Commodity", etc.

Usage:
    python tests/one-offs/probe_sheet_layout.py [--sheet-id ID] [--dump-json PATH]
"""

import argparse
import json
import sys
from pathlib import Path

# Make the package importable when run from the repo root without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from APITool.gsheet import GoogleSheetsExporter  # noqa: E402

DEFAULT_SHEET_ID = "1WACbf6u81fLIWsJVXsxUqYyIGZ0OCckN-Qb1FBgHAy0"
TOTALS_TAB = "Totals Tab"


def col_letter(idx0: int) -> str:
    """0-based column index -> spreadsheet column letter."""
    s = ""
    n = idx0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    ap.add_argument("--tab", default=TOTALS_TAB)
    ap.add_argument("--dump-json", help="Write the probed values to this JSON file")
    args = ap.parse_args()

    exporter = GoogleSheetsExporter()
    client = exporter._get_client()
    ss = client.open_by_key(args.sheet_id)

    print(f"Spreadsheet: {ss.title}")
    print()
    print("=== Worksheets ===")
    for ws in ss.worksheets():
        print(f"  {ws.title!r:32} id={ws.id:<12} {ws.row_count}r x {ws.col_count}c")
    print()

    titles = [ws.title for ws in ss.worksheets()]
    if args.tab not in titles:
        print(f"!! Tab {args.tab!r} not found. Available: {titles}")
        return 1

    ws = ss.worksheet(args.tab)

    # Pull a generous block once (one API call) rather than many cell reads.
    values = ws.get_values("A1:AZ400")
    formulas = ws.get_values("A1:AZ400", value_render_option="FORMULA")

    print(f"=== {args.tab}: rows 1-10 (values) ===")
    for r in range(min(10, len(values))):
        row = values[r]
        cells = [(col_letter(c), v) for c, v in enumerate(row) if str(v).strip()]
        print(f"  row {r+1}: {cells}")
    print()

    print(f"=== {args.tab}: rows 1-10 (formulas, only where different) ===")
    for r in range(min(10, len(formulas))):
        frow = formulas[r]
        vrow = values[r] if r < len(values) else []
        cells = []
        for c, f in enumerate(frow):
            v = vrow[c] if c < len(vrow) else ""
            if str(f).startswith("=") and f != v:
                cells.append((col_letter(c), f))
        if cells:
            print(f"  row {r+1}: {cells}")
    print()

    # Header hunt: find rows that look like headers.
    print("=== Header candidates (rows 1-8, non-empty cells) ===")
    wanted = ["left to buy", "commodity", "need", "total", "have", "cargo", "cost"]
    for r in range(min(8, len(values))):
        for c, v in enumerate(values[r]):
            lv = str(v).strip().lower()
            if lv and any(w in lv for w in wanted):
                print(f"  {col_letter(c)}{r+1} = {v!r}")
    print()

    # Column B from row 5 down.
    print("=== Column B, rows 5+ (commodity names) ===")
    b_vals = []
    for r in range(4, len(values)):
        row = values[r]
        b = row[1] if len(row) > 1 else ""
        if str(b).strip():
            b_vals.append((r + 1, b))
    print(f"  {len(b_vals)} non-empty B cells from row 5")
    for rownum, name in b_vals[:80]:
        # show the whole row alongside so we can see which column holds quantities
        row = values[rownum - 1]
        rest = [
            f"{col_letter(c)}={v!r}"
            for c, v in enumerate(row)
            if c != 1 and str(v).strip()
        ]
        print(f"  B{rownum} = {name!r:34} | {' '.join(rest)}")
    if len(b_vals) > 80:
        print(f"  ... {len(b_vals) - 80} more")
    print()

    # First empty row after the block, to see where the list ends.
    if b_vals:
        last = b_vals[-1][0]
        print(f"=== Rows {last}..{last + 4} (tail / summary rows) ===")
        for r in range(last - 1, min(last + 4, len(values))):
            row = values[r]
            cells = [(col_letter(c), v) for c, v in enumerate(row) if str(v).strip()]
            print(f"  row {r+1}: {cells}")

    if args.dump_json:
        Path(args.dump_json).write_text(
            json.dumps(
                {"tab": args.tab, "values": values, "formulas": formulas},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\nDumped raw values+formulas to {args.dump_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
