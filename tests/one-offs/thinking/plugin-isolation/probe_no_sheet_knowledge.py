"""
Does any layer above the destination still know one particular spreadsheet?

The north star says no logic specific to any one spreadsheet belongs in this
tool. `APITool/plugins/` is where that logic is allowed to live -- one
subpackage per sheet. Everything
else -- core, the `sheets/` toolkit, the `google/` vendor adapter -- must name
nothing a person typed into their own sheet.

THE DISCRIMINATOR, taken from #18 rather than invented here:

    "generated tabs can replace anything the tool itself produced,
     and nothing a person types."

So the test is not "does this string name a tab" -- it is "does this string
name something a PERSON maintains". `FreighterData`, `MarketData` and
`ShipCargo` are tabs the tool GENERATES, so their names are its own to choose
and they are NOT leaks. `Totals Tab`, `Left to buy` and `At Current Station`
name a tab and columns a person types into, and they are.

COMMENTS COUNT, and that is deliberate. A comment in `ship.py` explaining what
"column M subtracts into 'Left to buy'" is the generic layer knowing one
workbook's semantics. No import graph sees it, no layering test catches it, and
no type checker cares -- which is exactly why these outlive every refactor.
They are not all deletable; some explain a real hazard. But each one has to be
either rewritten generically or moved to the destination, and counting them is
how that decision stops being optional.

Run:  python tests/one-offs/thinking/plugin-isolation/probe_no_sheet_knowledge.py

Exit code is the leak count, so CI or a loop can gate on it.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PKG = ROOT / "APITool"
# Every destination lives under here, and every one of them is allowed to
# hardcode its own sheet -- that is what a plugin IS. Naming the parent rather
# than any single plugin means a second destination is excluded the moment it
# is added, with nothing to remember.
#
# This pointed at `APITool/workbook/` until that package was renamed, and for
# one run the probe scanned the plugin's own files and reported its concrete
# values as leaks. An exclusion path that no longer exists excludes nothing.
DESTINATION = PKG / "plugins"

# Strings naming something a PERSON maintains in their own spreadsheet.
PERSON_TYPED = [
    "Totals Tab",
    "Left to buy",
    "At Current Station",
    "ALL SETTLEMENTS",
    "Extra next rnd",
    "In Carrier Now",
    "Left to deliver",
]

# Named here so the exclusion is a stated decision rather than an oversight:
# the tool generates these tabs, so their names are its own to choose. They
# are a configurability question (#12), not a contamination one.
TOOL_GENERATED = ["FreighterData", "MarketData", "ShipCargo"]

# `SheetLayout` fields whose defaults describe one workbook's geometry. Checked
# separately from the string scan because an integer like `header_row = 3`
# carries no searchable text, and is no less workbook-specific for that.
GEOMETRY_FIELDS = [
    "totals_tab", "need_header", "marker_header",
    "system_cell", "station_cell",
    "header_row", "first_data_row", "name_column",
    "marker_column", "max_scan_row",
]


def _files() -> list[Path]:
    """Every module above the destination layer."""
    return [
        p for p in sorted(PKG.rglob("*.py"))
        if DESTINATION not in p.parents
    ]


def _comment_lines(path: Path, text: str) -> set[int]:
    """Line numbers that are comments or inside a docstring."""
    lines: set[int] = set()
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            lines.add(n)
    try:
        tree = ast.parse(text)
    except SyntaxError:  # pragma: no cover -- defensive
        return lines
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str) and node.value.end_lineno:
                lines.update(range(node.value.lineno, node.value.end_lineno + 1))
    return lines


def scan() -> list[tuple[str, int, str, str, str]]:
    """Return (path, line, kind, literal, text) for every leak."""
    found = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        comments = _comment_lines(path, text)
        for n, line in enumerate(text.splitlines(), 1):
            for literal in PERSON_TYPED:
                if literal in line:
                    kind = "comment" if n in comments else "CODE"
                    rel = path.relative_to(ROOT).as_posix()
                    found.append((rel, n, kind, literal, line.strip()))
    return found


def geometry_defaults() -> list[tuple[str, object]]:
    """
    Layout fields in the TOOLKIT still carrying one workbook's value.

    The end state is that ``APITool.sheets`` exposes no concrete layout class
    at all -- only a Protocol describing the shape, with the real class living
    beside the sheet it describes. So the class being ABSENT is success, not an
    error, and this returns an empty list for it.

    Defaults on the plugin's own class are not counted and never will be: that
    package is allowed -- required, even -- to hardcode the real sheet.
    """
    sys.path.insert(0, str(ROOT))
    import dataclasses

    try:
        from APITool.sheets import SheetLayout  # type: ignore[attr-defined]
    except ImportError:
        return []

    out = []
    for f in dataclasses.fields(SheetLayout):
        if f.name in GEOMETRY_FIELDS and f.default is not dataclasses.MISSING:
            out.append((f.name, f.default))
    return out


def main() -> int:
    leaks = scan()
    geometry = geometry_defaults()

    print("=" * 78)
    print("Person-typed spreadsheet knowledge ABOVE the destination layer")
    print("=" * 78)

    if leaks:
        code = [row for row in leaks if row[2] == "CODE"]
        comment = [row for row in leaks if row[2] == "comment"]
        for label, rows in (("CODE", code), ("COMMENT", comment)):
            if not rows:
                continue
            print(f"\n  -- {label} ({len(rows)}) --")
            for rel, n, _kind, literal, line in rows:
                snippet = line if len(line) <= 58 else line[:55] + "..."
                print(f"    {rel}:{n:<5} {literal:<20} {snippet}")
    else:
        print("\n  none")

    print()
    print("-" * 78)
    print("`SheetLayout` defaults describing one workbook's geometry")
    print("-" * 78)
    if geometry:
        for name, default in geometry:
            print(f"    {name:<18} = {default!r}")
    else:
        print("    none -- the mechanism carries no workbook's values")

    total = len(leaks) + len(geometry)
    print()
    print("=" * 78)
    print(f"{total} leaks   ({len(leaks)} literal, {len(geometry)} layout default)")
    if total:
        print()
        print("Each must be rewritten generically, or moved into")
        print("APITool/plugins/<name>/, the layer allowed to know these.")
        print("Tool-generated tab names are deliberately NOT counted:")
        print(f"  {', '.join(TOOL_GENERATED)}")
    print("=" * 78)
    return total


if __name__ == "__main__":
    sys.exit(min(main(), 125))
