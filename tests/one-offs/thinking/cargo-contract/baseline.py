"""
AC-2 for the cargo tab contract (#11): capture, then compare.

Snapshots the VALUES every cross-tab formula currently resolves to, so a
reshape of the generated tabs can be proved not to have changed meaning.

Values, not formulas, on purpose. A formula that still looks right while
returning a different number is exactly the failure this guards against --
and it is the shape Google Sheets produces when a column is inserted left
of a VLOOKUP index, since the range auto-widens and the index literal does
not.

  capture:  python baseline.py <sheet-id> capture
  compare:  python baseline.py <sheet-id> compare

Read-only in both modes. Writes one JSON file next to this script.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from APITool.google import GoogleSheetsExporter  # noqa: E402

SNAPSHOT = Path(__file__).with_name("baseline.json")

# Every column that reads a generated tab, per the measured reference survey.
TARGETS = [
    ("Totals Tab",     "B5:B201",  {"D": "D5:D201", "I": "I5:I201",
                                    "M": "M5:M201", "G": "G5:G201"}),
    ("Agri Lrg. (ex)", "B4:B60",   {"D": "D4:D60",  "H": "H4:H60"}),
    ("Sat. (ex)",      "B4:B60",   {"D": "D4:D60",  "H": "H4:H60"}),
    ("Extr. (ex)",     "B4:B60",   {"D": "D4:D60",  "H": "H4:H60"}),
]


def grab(book) -> dict:
    out = {}
    for tab, key_range, cols in TARGETS:
        ws = book.worksheet(tab)
        keys = [r[0] if r else "" for r in ws.get(key_range)]
        cells = {}
        for label, rng in cols.items():
            vals = ws.get(rng, value_render_option="UNFORMATTED_VALUE")
            cells[label] = [
                (v[0] if v else "") for v in vals
            ] + [""] * (len(keys) - len(vals))
        for i, name in enumerate(keys):
            if not str(name).strip():
                continue
            for label in cols:
                raw = cells[label][i] if i < len(cells[label]) else ""
                out[f"{tab}!{label}{i}|{name}"] = "" if raw is None else str(raw)
    return out


def main(sheet_id: str, mode: str) -> int:
    book = GoogleSheetsExporter().open_spreadsheet(sheet_id)
    now = grab(book)

    if mode == "capture":
        SNAPSHOT.write_text(json.dumps(now, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"captured {len(now)} cell values -> {SNAPSHOT.name}")
        return 0

    if not SNAPSHOT.is_file():
        print("No baseline captured. Run 'capture' first.")
        return 2
    before = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    added = set(now) - set(before)
    removed = set(before) - set(now)
    changed = {k: (before[k], now[k]) for k in set(before) & set(now)
               if before[k] != now[k]}

    print(f"  baseline cells : {len(before)}")
    print(f"  current cells  : {len(now)}")
    print(f"  changed values : {len(changed)}")
    print(f"  disappeared    : {len(removed)}")
    print(f"  appeared       : {len(added)}")
    for k, (a, b) in list(changed.items())[:20]:
        print(f"    {k}\n        was {a!r}  now {b!r}")
    for k in list(removed)[:10]:
        print(f"    GONE: {k}  (was {before[k]!r})")
    print()
    ok = not changed and not removed
    print("AC-2", "PASSES -- every cross-tab value is unchanged" if ok
          else "FAILS -- the reshape changed what the sheet computes")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[2] not in ("capture", "compare"):
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
