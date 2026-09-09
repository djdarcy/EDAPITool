"""
What a property-based test would assert about the A1 arithmetic, brute-forced.

`hypothesis` is not installed, so this exhausts the input space by hand rather
than sampling it. That is not what property-based testing normally does -- the
point of the library is that it SEARCHES, and shrinks a failure to its minimal
case -- but the properties themselves are exactly the ones a Hypothesis test
would state, and exhausting a small space is a stronger check than sampling it.

Run:  python tests/one-offs/thinking/property-probe/a1_properties.py
"""

import itertools
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from APITool.sheets import CellRange, column_to_index, index_to_column  # noqa: E402


def check(name, failures, checked):
    status = "PASS" if not failures else "FAIL"
    print(f"  [{status}] {name}  ({checked} cases)")
    for f in failures[:5]:
        print(f"         counterexample: {f}")
    if len(failures) > 5:
        print(f"         ... and {len(failures) - 5} more")
    return not failures


print("Properties of the A1 column arithmetic\n")
results = []

# ---------------------------------------------------------------------------
# P1. Round trip, index -> letters -> index.
#     For every column index, converting to letters and back is the identity.
# ---------------------------------------------------------------------------
failures = []
LIMIT = 20000                      # ~ column 'ACOJ', far past Sheets' real max
for i in range(LIMIT):
    back = column_to_index(index_to_column(i))
    if back != i:
        failures.append(f"index {i} -> {index_to_column(i)!r} -> {back}")
results.append(check("P1  column_to_index(index_to_column(i)) == i", failures, LIMIT))

# ---------------------------------------------------------------------------
# P2. Round trip, letters -> index -> letters.
#     Every 1-3 letter column reference survives the journey unchanged.
# ---------------------------------------------------------------------------
failures = []
checked = 0
for width in (1, 2, 3):
    for letters in itertools.product(string.ascii_uppercase, repeat=width):
        ref = "".join(letters)
        checked += 1
        back = index_to_column(column_to_index(ref))
        if back != ref:
            failures.append(f"{ref!r} -> {column_to_index(ref)} -> {back!r}")
results.append(check("P2  index_to_column(column_to_index(s)) == s", failures, checked))

# ---------------------------------------------------------------------------
# P3. Order is preserved.
#     A later column must have a larger index -- this is what makes "never
#     insert a column left of D" checkable arithmetically rather than by eye.
# ---------------------------------------------------------------------------
failures = []
for i in range(LIMIT - 1):
    if not column_to_index(index_to_column(i)) < column_to_index(index_to_column(i + 1)):
        failures.append(f"{index_to_column(i)} !< {index_to_column(i + 1)}")
results.append(check("P3  order preserved across the mapping", failures, LIMIT - 1))

# ---------------------------------------------------------------------------
# P4. Reflexivity: every range contains itself.
#     If this ever fails, WriteGuard would reject a write to exactly the range
#     it was told to permit.
# ---------------------------------------------------------------------------
failures = []
samples = []
for col in ("A", "B", "L", "Z", "AA", "ZZ"):
    for row in (1, 2, 5, 100, 1000):
        samples.append(f"{col}{row}")
        samples.append(f"{col}{row}:{col}{row + 10}")
    samples.append(f"{col}:{col}")
for a1 in samples:
    r = CellRange.parse(a1)
    if not r.contains(r):
        failures.append(f"{a1!r} does not contain itself")
results.append(check("P4  r.contains(r) for every range", failures, len(samples)))

# ---------------------------------------------------------------------------
# P5. Transitivity: containment composes.
#     WriteGuard's whole safety argument is that an allowlisted range contains
#     the target. If containment is not transitive, nesting reasoning breaks.
# ---------------------------------------------------------------------------
failures = []
checked = 0
ranges = [CellRange.parse(a1) for a1 in samples]
for a, b, c in itertools.product(ranges[:14], repeat=3):
    checked += 1
    if a.contains(b) and b.contains(c) and not a.contains(c):
        failures.append(f"{a} > {b} > {c} but not a > c")
results.append(check("P5  contains is transitive", failures, checked))

# ---------------------------------------------------------------------------
# P6. A whole-column range contains every cell in that column.
#     This is the exact shape the cargo contract relies on ($B:$D).
# ---------------------------------------------------------------------------
failures = []
checked = 0
whole = CellRange.parse("B:D")
for col in ("B", "C", "D"):
    for row in (1, 5, 200, 100000):
        checked += 1
        if not whole.contains(CellRange.parse(f"{col}{row}")):
            failures.append(f"B:D does not contain {col}{row}")
for col in ("A", "E"):
    for row in (1, 5, 200):
        checked += 1
        if whole.contains(CellRange.parse(f"{col}{row}")):
            failures.append(f"B:D wrongly contains {col}{row}")
results.append(check("P6  B:D contains exactly columns B..D", failures, checked))

print()
print(f"{sum(results)} of {len(results)} properties hold.")
sys.exit(0 if all(results) else 1)
