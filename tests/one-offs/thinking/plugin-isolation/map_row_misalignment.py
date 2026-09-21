"""
READ-ONLY: which rows' formulas reference the WRONG row, and where does it stop?

Every healthy row on 'Totals Tab' is self-referential:

    B<n>  =IF($AA<n>="", ...)      -- B reads its own row's AA
    C<n>  =IF($B<n>="", ...)       -- C reads its own row's B

A structural edit (a deleted row, a drag, a cut-and-paste that moved cells
between rows) leaves survivors pointing at a neighbour's row instead of
their own -- and any formula whose target was inside the deleted region
becomes a permanent #REF! in the formula text.

So the OFFSET per row is the fingerprint. A single local edit shows as a
short run of non-zero offsets with zeros either side. A larger structural
change shows as a long run, or a step that never returns to zero.

This tells us the SHAPE of what happened. It cannot tell us who did it or
when -- only the spreadsheet's version history can date it.

READ-ONLY: one ranged read, parsed locally. No update, clear, resize or
batch_update call exists in this file.

Run:  PYTHONIOENCODING=utf-8 python tests/one-offs/thinking/plugin-isolation/map_row_misalignment.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

TOTALS = "Totals Tab"
FIRST, LAST = 5, 60
LINE = "=" * 78


def referenced_row(formula: str, anchor: str) -> int | None:
    """The row number this formula reads through `anchor`, e.g. '$AA' or '$B'."""
    match = re.search(re.escape(anchor) + r"(\d+)", str(formula))
    return int(match.group(1)) if match else None


def main() -> int:
    from APITool import settings
    from APITool.google import GoogleSheetsExporter

    sheet_id = settings.get_sheet_id(None)
    worksheet = (GoogleSheetsExporter()._get_client()
                 .open_by_key(sheet_id).worksheet(TOTALS))
    formulas = worksheet.get(f"A{FIRST}:M{LAST}", value_render_option="FORMULA")

    print(LINE)
    print(f"  Row-reference offsets on '{TOTALS}', rows {FIRST}-{LAST}")
    print("  offset 0 = healthy (formula reads its own row)")
    print(LINE)
    print(f"\n  {'row':>5}  {'B reads $AA':>12} {'off':>5}   {'C reads $B':>11} {'off':>5}   note")

    anomalies = []
    for i, row in enumerate(formulas):
        n = FIRST + i
        b = row[1] if len(row) > 1 else ""
        c = row[2] if len(row) > 2 else ""
        if not str(b).strip() and not str(c).strip():
            continue

        b_ref = referenced_row(b, "$AA")
        c_ref = referenced_row(c, "$B")
        b_off = None if b_ref is None else b_ref - n
        c_off = None if c_ref is None else c_ref - n

        broken_b = "#REF!" in str(b)
        broken_c = "#REF!" in str(c)

        note = ""
        if broken_c or broken_b:
            note = "<<< #REF! baked into formula text"
        elif (b_off not in (None, 0)) or (c_off not in (None, 0)):
            note = "<<< points at a neighbour's row"

        if note:
            anomalies.append(n)
            print(f"  {n:>5}  {str(b_ref):>12} {str(b_off):>5}   "
                  f"{str(c_ref):>11} {str(c_off):>5}   {note}")

    print()
    print(LINE)
    if not anomalies:
        print("  No anomalies. Every row reads its own row.")
    else:
        lo, hi = min(anomalies), max(anomalies)
        print(f"  {len(anomalies)} anomalous row(s): {anomalies}")
        print(f"  Span: rows {lo}-{hi}. Rows {FIRST}-{lo - 1} and {hi + 1}-{LAST} are healthy.")
        print()
        if hi - lo <= 2:
            print("  A SHORT, LOCAL run bounded by healthy rows on both sides.")
            print("  That is the shape of a one-off manual edit -- a deleted row or a")
            print("  drag/paste that moved cells by one row -- not of a programmatic")
            print("  write, which would affect a whole column uniformly or not at all.")
        else:
            print("  A LONG run. That is NOT a one-off local edit; look for a bulk")
            print("  operation (sort, large delete, or a paste over many rows).")
    print("  Nothing was written.")
    print(LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
