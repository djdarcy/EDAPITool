#!/usr/bin/env python
"""
Offline summary of the Totals Tab dump produced by probe_sheet_layout.py.
No network. Prints only the facts the integration design depends on.

Usage:
    python tests/one-offs/summarize_totals_tab.py <totals_tab.json>
"""

import json
import sys


def col_letter(idx0: int) -> str:
    s = ""
    n = idx0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def cell(rows, r1, c0):
    """1-based row, 0-based col."""
    if r1 - 1 >= len(rows):
        return ""
    row = rows[r1 - 1]
    return row[c0] if c0 < len(row) else ""


def main() -> int:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    values = data["values"]
    formulas = data["formulas"]

    print("### Rows 1-4: values")
    for r in range(1, 5):
        cells = [
            f"{col_letter(c)}{r}={v!r}"
            for c, v in enumerate(values[r - 1])
            if str(v).strip()
        ]
        print(f"  {' '.join(cells)}")
    print()

    print("### Rows 1-4: formulas")
    for r in range(1, 5):
        cells = [
            f"{col_letter(c)}{r}={f!r}"
            for c, f in enumerate(formulas[r - 1])
            if str(f).startswith("=")
        ]
        if cells:
            print(f"  {' '.join(cells)}")
    print()

    # Header row is row 3 per the probe.
    hdr = values[2]
    print("### Row 3 headers (col -> header)")
    for c, h in enumerate(hdr):
        if str(h).strip():
            print(f"  {col_letter(c)} = {h!r}")
    print()

    # Which columns are entirely empty in rows 3..end (candidates for the marker)
    print("### Column occupancy, rows 3..last commodity row")
    # find last commodity row: last row with non-empty B beyond row 4
    last = 4
    for r in range(5, len(values) + 1):
        if str(cell(values, r, 1)).strip():
            last = r
    print(f"  last non-empty B row = {last}")
    for c in range(0, 29):
        nonempty = 0
        samples = []
        for r in range(3, last + 1):
            v = cell(values, r, c)
            if str(v).strip():
                nonempty += 1
                if len(samples) < 3:
                    samples.append(f"{col_letter(c)}{r}={v!r}")
        f_nonempty = sum(
            1 for r in range(3, last + 1) if str(cell(formulas, r, c)).startswith("=")
        )
        flag = "  <-- EMPTY" if nonempty == 0 else ""
        print(
            f"  {col_letter(c):>2}: {nonempty:>4} values, {f_nonempty:>4} formulas{flag}"
            + (f"   {samples}" if samples else "")
        )
    print()

    # The commodity block: B name, G "Left to buy"
    gi = None
    for c, h in enumerate(hdr):
        if str(h).strip().lower() == "left to buy":
            gi = c
    print(f"### 'Left to buy' column = {col_letter(gi)} (index {gi})")
    print()

    rows = []
    for r in range(5, last + 1):
        name = str(cell(values, r, 1)).strip()
        if not name:
            continue
        raw = str(cell(values, r, gi)).strip()
        req = str(cell(values, r, 2)).strip()
        rows.append((r, name, req, raw))

    print(f"### {len(rows)} commodity rows (B5..B{last})")
    pos = [x for x in rows if x[3] not in ("", "0", "-") and not x[3].startswith("0")]
    print(f"  rows with a non-blank/non-zero 'Left to buy': {len(pos)}")
    print()
    print(f"{'row':>4}  {'B (commodity)':34} {'C Required':>11} {'G Left to buy':>14}")
    for r, name, req, raw in rows:
        print(f"{r:>4}  {name:34} {req:>11} {raw:>14}")
    print()

    # Formula shapes in the commodity block, one sample per column
    print("### Sample formula per column at row 5 and row 6")
    for c in range(0, 29):
        f5 = cell(formulas, 5, c)
        if str(f5).startswith("="):
            print(f"  {col_letter(c)}5 = {f5}")
    print()

    # P/Q/X/Y/Z config block
    print("### Config block rows 4..20, columns P..AC")
    for r in range(4, 21):
        cells = [
            f"{col_letter(c)}{r}={cell(values, r, c)!r}"
            for c in range(15, 29)
            if str(cell(values, r, c)).strip()
        ]
        if cells:
            print(f"  {' '.join(cells)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
