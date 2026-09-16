"""
Point the tests' layout construction at the destination package.

`SheetLayout` no longer defaults to one particular spreadsheet -- the values
moved to `APITool/workbook/layout.py`, which is the package allowed to know
them. Tests that said `SheetLayout()` were relying on those defaults, so they
were always exercising the settlement workbook; they now say so out loud by
calling `settlement_layout()`.

This is a bulk transformation -- the same substitution across 17 call sites in
two files -- which is the case where a script beats seventeen edits. It asserts
before it writes, and prints what it changed, so the diff is reviewable rather
than trusted.

Run:  python tests/one-offs/thinking/plugin-isolation/retarget_test_layouts.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

TARGETS = [
    ROOT / "tests" / "test_sheets.py",
    ROOT / "tests" / "test_service.py",
]

IMPORT_LINE = "from APITool.plugins.settlement.layout import settlement_layout\n"


def retarget(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    before = text

    # Constructor calls only. A bare `SheetLayout` naming the type -- in an
    # annotation or an isinstance -- must keep its name, so the paren is
    # required in the pattern.
    text, count = re.subn(r"\bSheetLayout\(", "settlement_layout(", text)

    if count and IMPORT_LINE not in text:
        # Insert BEFORE the first APITool import, never after the last.
        #
        # The first version placed it after the last matching line, which in
        # test_sheets.py was the opening line of a PARENTHESISED import -- so
        # the new import landed between `from ... import (` and its contents
        # and the file stopped parsing. A line starting with `from APITool` is
        # only reliably at module level when it is the first one; anything
        # later may be the head of a multi-line block.
        lines = text.splitlines(keepends=True)
        first = min(
            i for i, line in enumerate(lines)
            if line.startswith("from APITool")
        )
        lines.insert(first, IMPORT_LINE)
        text = "".join(lines)

    if text != before:
        path.write_text(text, encoding="utf-8")
    return count


def main() -> int:
    total = 0
    for path in TARGETS:
        if not path.exists():
            print(f"  MISSING: {path}")
            return 1
        n = retarget(path)
        total += n
        print(f"  {path.relative_to(ROOT).as_posix():<28} {n} call sites")

    print(f"\n{total} constructor calls retargeted to settlement_layout()")
    print("`SheetLayout` remains imported where it is still named as a type.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
