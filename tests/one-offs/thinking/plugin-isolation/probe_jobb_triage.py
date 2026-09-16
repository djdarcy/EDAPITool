"""
Count who actually reads each name in the destination layer.

#18's Job B asks for a triage pass sorting every piece into dead /
superseded / still-needed. Its discriminator:

    "generated tabs can replace anything the tool itself produced, and
     nothing a person types."

That rule needs one fact per name that argument cannot supply: WHO READS IT.
A name with no reader outside its own definition is dead regardless of what
anyone believes about it. This counts, so the table is measured.

Three counts per name, deliberately separate -- collapsing them is how
"nothing uses this" gets said about something only the tests use, and how
"this is used" gets said about something only its own module mentions:

    self    references inside APITool/workbook/ itself
    prod    references elsewhere in APITool/  (the real consumers)
    tests   references under tests/

Run:  python tests/one-offs/thinking/plugin-isolation/probe_jobb_triage.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PKG = ROOT / "APITool"
TESTS = ROOT / "tests"
DESTINATION = PKG / "workbook"

# Every public-ish name defined in the destination layer, in file order.
NAMES = [
    # workbook/totals.py
    ("totals", "RequirementSnapshot"),
    ("totals", "TotalsTabReader"),
    ("totals", "MarkerPlan"),
    ("totals", "CellRenderer"),
    ("totals", "TotalsTabWriter"),
    # workbook/markers.py -- glyphs
    ("markers", "MARKER_ENOUGH"),
    ("markers", "MARKER_THREE_QUARTER"),
    ("markers", "MARKER_HALF"),
    ("markers", "MARKER_QUARTER"),
    ("markers", "MARKER_EMPTY"),
    ("markers", "MARKER_BLANK"),
    ("markers", "MARKER_COVERED"),
    ("markers", "MARKER_EMPTY_SMALL"),
    ("markers", "MARKER_EMPTY_DOTTED"),
    ("markers", "MARKER_PARTIAL"),
    ("markers", "MARKER_FOR_STATE"),
    ("markers", "_PARTIAL_SCALE"),
    # workbook/markers.py -- colour
    ("markers", "_rgb"),
    ("markers", "COLOUR_ENOUGH"),
    ("markers", "COLOUR_THREE_QUARTER"),
    ("markers", "COLOUR_HALF"),
    ("markers", "COLOUR_QUARTER"),
    ("markers", "COLOUR_TEXT_ON_DARK"),
    ("markers", "COLOUR_TEXT_ON_LIGHT"),
    ("markers", "COLOUR_TEXT_INERT"),
    ("markers", "FILL_FOR_MARKER"),
    ("markers", "LIGHT_TEXT_MARKERS"),
    # workbook/markers.py -- the write side
    ("markers", "coverage"),
    ("markers", "marker_for"),
    ("markers", "_fill_glyph"),
    ("markers", "_cell_format"),
    ("markers", "marker_note"),
    ("markers", "MarketRenderer"),
    # workbook/markers.py -- the formula side
    ("markers", "_threshold"),
    ("markers", "marker_formula"),
    ("markers", "MARKER_LEGEND"),
    ("markers", "marker_formula_help"),
]


def _count(name: str, paths: list[Path], skip: set[Path]) -> int:
    """Whole-word references to `name`, excluding its own definition line."""
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    definition = re.compile(
        rf"^\s*(def|class)\s+{re.escape(name)}\b|^{re.escape(name)}\s*[:=]"
    )
    hits = 0
    for path in paths:
        if path in skip:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if definition.match(line):
                continue
            hits += len(pattern.findall(line))
    return hits


def main() -> None:
    destination_files = sorted(DESTINATION.rglob("*.py"))
    prod_files = [
        p for p in sorted(PKG.rglob("*.py"))
        if DESTINATION not in p.parents and p != DESTINATION
    ]
    test_files = [
        p for p in sorted(TESTS.rglob("*.py"))
        if "__pycache__" not in str(p)
    ]

    print(f"{'name':<26} {'module':<9} {'self':>5} {'prod':>5} {'tests':>6}  "
          f"signal")
    print("-" * 78)

    for module, name in NAMES:
        own = _count(name, destination_files, skip=set())
        prod = _count(name, prod_files, skip=set())
        tests = _count(name, test_files, skip=set())

        if prod == 0 and tests == 0 and own == 0:
            signal = "NO READER ANYWHERE"
        elif prod == 0 and own == 0:
            signal = "tests only"
        elif prod == 0:
            signal = "internal to the layer"
        else:
            signal = "reached from outside"

        print(f"{name:<26} {module:<9} {own:>5} {prod:>5} {tests:>6}  {signal}")

    print()
    print("`prod` counts references in APITool/ OUTSIDE the destination layer.")
    print("A zero there does not mean dead -- it may be reached only through")
    print("the layer's own public entry points. Read `self` alongside it.")


if __name__ == "__main__":
    main()
