"""
Can we detect two plugins claiming the same cells, before either writes?

The maintainer's framing:

    "That just sounds like if we can pre-detect that we issue a WARNING
     bordering on an ERROR or we just outright refuse to load those plugins
     till they resolve the overlap (letting the user choose the warning / error
     threshold is very similar to how in Visual Studio with 'cl.exe' users can
     weaken a warning or strengthen it as is appropriate for their project).
     This could be configurable as maybe some users would genuinely want
     overlap for some reason (maybe they enable / disable one of the plugins
     every so often and the other is meant to cover it in which case we could
     just ignore one of the writes as a possible option?)"

`CellRange` already has `contains()` -- full containment. It does NOT have
`overlaps()`, and the two differ exactly where it matters: `L5:L24` and
`L20:L30` overlap while neither contains the other, so `contains` answers
False for the case we most need to catch.

THE HARD PART IS OPEN-ENDED RANGES, which is why this is a probe rather than
an assumption. The write guard's own allowlist is built open-ended --
`f"{marker_column}{header_row}:{marker_column}"` produces `L3:L`, whose
`last_row` is None meaning "to the bottom of the sheet". Interval arithmetic
with an unbounded end is where this will be wrong if it is wrong.

Run:  python tests/one-offs/thinking/plugin-isolation/poc_region_overlap.py
Pure computation. No sheet, no network, nothing written anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from APITool.sheets import CellRange  # noqa: E402


def overlaps(a: CellRange, b: CellRange) -> bool:
    """
    Do two ranges share at least one cell?

    Two intervals intersect unless one ends before the other starts. `None`
    means unbounded on that side, so it can never be the reason they miss:
    an unbounded end extends past any bounded start.
    """
    def axis(a_lo, a_hi, b_lo, b_hi) -> bool:
        # a ends before b starts?
        if a_hi is not None and b_lo is not None and a_hi < b_lo:
            return False
        # b ends before a starts?
        if b_hi is not None and a_lo is not None and b_hi < a_lo:
            return False
        return True

    return (axis(a.first_col, a.last_col, b.first_col, b.last_col)
            and axis(a.first_row, a.last_row, b.first_row, b.last_row))


# (a, b, should_overlap, why)
CASES = [
    ("L5:L24",  "L5:L24",   True,  "identical"),
    ("L5:L24",  "L20:L30",  True,  "partial -- `contains` says False for this"),
    ("L5:L24",  "L25:L40",  False, "adjacent, one row apart"),
    ("L5:L24",  "B5:B24",   False, "same rows, different column"),
    ("L5:L24",  "L10:L15",  True,  "b inside a"),
    ("L10:L15", "L5:L24",   True,  "a inside b -- must be symmetric"),
    ("L3:L",    "L100:L200",True,  "OPEN-ENDED a swallows a late range"),
    ("L3:L",    "L1:L2",    False, "open-ended a starts after b ends"),
    ("L3:L",    "B5:B9",    False, "open-ended, wrong column"),
    ("A1:Z100", "L5:L24",   True,  "wide block contains a column slice"),
    ("C2",      "C2",       True,  "single cell, identical"),
    ("C2",      "G2",       False, "single cells, different columns"),
    ("C2:G2",   "G2",       True,  "row span touching its own end"),
]


def main() -> int:
    print("=" * 74)
    print("CellRange overlap -- including the open-ended case the guard uses")
    print("=" * 74)
    print()
    print(f"  {'a':<10} {'b':<11} {'want':<6} {'got':<6} {'contains?':<10} note")
    print("  " + "-" * 70)

    wrong = 0
    contains_disagrees = 0
    for a_s, b_s, want, why in CASES:
        a, b = CellRange.parse(a_s), CellRange.parse(b_s)
        got = overlaps(a, b)
        # what the EXISTING method would have said, either direction
        contained = a.contains(b) or b.contains(a)
        flag = "" if got == want else "   <-- WRONG"
        if got != want:
            wrong += 1
        if want and not contained:
            contains_disagrees += 1
        print(f"  {a_s:<10} {b_s:<11} {str(want):<6} {str(got):<6} "
              f"{str(contained):<10} {why}{flag}")

    print()
    print("-" * 74)
    print(f"  {len(CASES) - wrong}/{len(CASES)} cases correct")
    print(f"  {contains_disagrees} real overlap(s) that `contains()` alone would MISS")
    print("-" * 74)
    print()

    if wrong:
        print("  Overlap detection is NOT correct as written. Do not build on it.")
    else:
        print("  Detection is cheap and total: pure interval arithmetic on four")
        print("  bounds, no sheet access, and it handles the open-ended ranges")
        print("  the write guard actually builds. Adding `overlaps()` to")
        print("  `CellRange` is a toolkit addition any sheet writer would want.")
    print()
    print("  What it does NOT answer: whether an overlap is a mistake or")
    print("  deliberate. That needs a severity setting and a declared")
    print("  precedence -- two knobs, not one, because 'ignore' must not be")
    print("  the only way to get a deterministic winner.")
    return wrong


if __name__ == "__main__":
    sys.exit(main())
