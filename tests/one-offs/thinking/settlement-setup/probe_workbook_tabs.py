#!/usr/bin/env python
"""
READ-ONLY probe for the settlement setup command (board U43): what the live
workbook holds that the command would read from and copy.

Writes NOTHING to the sheet. Prints every worksheet with its hidden flag and
size, then the first rows of the tabs the command cares about -- `Base` (the
settlement list), one settlement tab as the template's source, and any tab
whose name looks like a template or a "next" scratch tab. Values only; the
template source's first rows are also shown as formulas, because a copied
tab must keep them.

Usage:
    python tests/one-offs/thinking/settlement-setup/probe_workbook_tabs.py [--sheet-id ID] [--rows 40] [--dump-json PATH]

The maintainer approved this read on 2026-10-02 (design of U43). Run it only
with that word; the dump, if any, goes outside the repository.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from APITool.google import GoogleSheetsExporter  # noqa: E402

DEFAULT_SHEET_ID = "1WACbf6u81fLIWsJVXsxUqYyIGZ0OCckN-Qb1FBgHAy0"
SOURCE_TAB = "Agri Lrg. (ex)"


def col_letter(idx0: int) -> str:
    s, n = "", idx0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def show_rows(label, values, upto):
    print(f"=== {label}: rows 1-{upto} (non-empty cells) ===")
    for r in range(min(upto, len(values))):
        cells = [(col_letter(c), v) for c, v in enumerate(values[r]) if str(v).strip()]
        if cells:
            print(f"  row {r + 1}: {cells}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    ap.add_argument("--rows", type=int, default=40)
    ap.add_argument("--source", default=SOURCE_TAB)
    ap.add_argument("--dump-json")
    args = ap.parse_args()

    ss = GoogleSheetsExporter()._get_client().open_by_key(args.sheet_id)
    print(f"Spreadsheet: {ss.title}\n")
    print("=== Worksheets (hidden?) ===")
    sheets = ss.worksheets()
    for ws in sheets:
        flag = "HIDDEN " if ws.isSheetHidden else "       "
        print(f"  {flag}{ws.title!r:32} id={ws.id:<12} {ws.row_count}r x {ws.col_count}c")
    print()

    titles = [ws.title for ws in sheets]
    wanted = ["Base", args.source]
    wanted += [t for t in titles if any(k in t.lower() for k in ("template", "next", "tmpl"))
               and t not in wanted]
    dump = {}
    for title in wanted:
        if title not in titles:
            print(f"!! no tab named {title!r}\n")
            continue
        ws = ss.worksheet(title)
        values = ws.get_values(f"A1:AD{args.rows}")
        show_rows(title, values, args.rows)
        dump[title] = {"values": values}
        if title == args.source:
            formulas = ws.get_values("A1:AD8", value_render_option="FORMULA")
            print(f"=== {title}: rows 1-8 formulas (where they differ) ===")
            for r, frow in enumerate(formulas):
                vrow = values[r] if r < len(values) else []
                cells = [(col_letter(c), f) for c, f in enumerate(frow)
                         if str(f).startswith("=") and f != (vrow[c] if c < len(vrow) else "")]
                if cells:
                    print(f"  row {r + 1}: {cells}")
            print()
            dump[title]["formulas_1_8"] = formulas

    if args.dump_json:
        Path(args.dump_json).write_text(json.dumps(dump, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Dumped to {args.dump_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
