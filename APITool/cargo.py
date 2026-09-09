"""
The shared column contract for every generated cargo tab.

An inventory tab -- the fleet carrier's hold, the ship's hold, and whatever
comes next -- publishes the same three columns in the same three places:

    A          margin, always empty
    B          Commodity     <- the lookup key
    C          Quantity      <- VLOOKUP index 2
    D          Unit Price    <- VLOOKUP index 3

**Everything right of D is that tab's own business.** The carrier carries a
total value because it has real prices and someone reads that tab by eye; the
ship carries symbol and stolen flags. Neither needs the other's tail, and
forcing one would mean emitting columns a producer cannot fill.

Why the first three are fixed, and why this module exists to fix them:

A spreadsheet reads these tabs with ``VLOOKUP($B5, <tab>!$B:$D, 3, FALSE)``.
That ``3`` is a LITERAL, not a reference. Insert a column left of D and Google
Sheets widens the range to ``$B:$E`` automatically -- and leaves the literal
alone. Measured 2026-09-08 on a throwaway tab: after inserting one column,
index 2 returned the newly inserted column and index 3 returned Quantity.
Every lookup shifted one column right, silently, with no error anywhere.

There were 476 such formulas in the live workbook when this was written. So
the constraint is not "keep the columns tidy" -- it is **never insert a column
left of D**, and the test that asserts these indices is the only thing
standing between a refactor and several hundred quietly wrong numbers.

Adding a column to the RIGHT of D is always safe, which is where a future
``Category`` belongs if it is ever wanted.
"""

from __future__ import annotations

from typing import Iterable, Sequence

# Column A is left empty as a margin, matching FreighterData and MarketData.
MARGIN = ""

# The three columns every cargo tab shares, in order, starting at column B.
CONTRACT_HEADERS = ["Commodity", "Quantity", "Unit Price"]

# What a spreadsheet passes as VLOOKUP's index argument against $B:$D.
# These are the numbers that appear as literals in the sheet's formulas, so
# they are part of the published contract and cannot change without editing
# every formula that uses them.
INDEX_COMMODITY = 1
INDEX_QUANTITY = 2
INDEX_UNIT_PRICE = 3

# The A1 range a consumer should look up against.
LOOKUP_RANGE = "$B:$D"


def header_row(extra: Sequence[str] = ()) -> list:
    """
    The header row: margin, the three contract headers, then this tab's own.

    ``extra`` lands right of Unit Price, where adding columns is safe.
    """
    return [MARGIN, *CONTRACT_HEADERS, *extra]


def data_row(
    commodity: str,
    quantity: object,
    unit_price: object = "",
    extra: Sequence[object] = (),
) -> list:
    """
    One commodity row.

    ``unit_price`` defaults to empty rather than zero. A blank cell reads as
    "not known" and sums as nothing; a zero reads as "worthless", which is a
    different and wrong claim about cargo whose price this tool has no source
    for. Sheets coerces the empty string to 0 in arithmetic, so a SUM over the
    column still works.
    """
    return [MARGIN, commodity, quantity, unit_price, *extra]


def lookup_formula(key_cell: str, tab: str, index: int) -> str:
    """
    The formula a sheet should use against a cargo tab.

    Rendered here so the documentation, the README and any --show-formula
    output cannot drift from the contract they describe.

    IFNA rather than IFERROR: IFNA blanks a commodity that is not in the tab,
    but still surfaces a #REF! if the tab is renamed or deleted. IFERROR hides
    that too, and a silently blank column feeds the sheet's arithmetic a
    number that looks deliberate.
    """
    return f'=IFNA(VLOOKUP({key_cell}, {tab}!{LOOKUP_RANGE}, {index}, FALSE), "")'


def verify_contract(grid: Iterable[Sequence], header_row_index: int) -> None:
    """
    Raise unless a built grid honours the contract.

    Cheap enough to call from a producer before writing, and the thing a test
    asserts. Checks the header text and, crucially, that the contract columns
    sit at the offsets the published VLOOKUP indices name.
    """
    rows = list(grid)
    if header_row_index >= len(rows):
        raise ValueError(f"no header row at index {header_row_index}")
    header = list(rows[header_row_index])

    if not header or header[0] != MARGIN:
        raise ValueError(f"column A must be an empty margin, found {header[:1]!r}")

    # Check the INDICES, not the header list. Comparing the B-D slice against
    # CONTRACT_HEADERS would be equivalent -- and was, in the first draft --
    # but it reports "the headers differ" when what actually broke is "index 3
    # no longer means Unit Price". The index is what the user's formulas carry
    # as a literal, so it is what the error should name.
    #
    # VLOOKUP index N against $B:$D is header[N], because the margin is at 0.
    for index, expected in (
        (INDEX_COMMODITY, "Commodity"),
        (INDEX_QUANTITY, "Quantity"),
        (INDEX_UNIT_PRICE, "Unit Price"),
    ):
        found = header[index] if index < len(header) else None
        if found != expected:
            raise ValueError(
                f"VLOOKUP index {index} must address {expected!r}, found {found!r}. "
                f"Cargo tabs expose {CONTRACT_HEADERS} in columns B-D; a column "
                f"was inserted or renamed left of D, which shifts every lookup "
                f"in the workbook without raising anything in the sheet."
            )


__all__ = [
    "CONTRACT_HEADERS",
    "INDEX_COMMODITY",
    "INDEX_QUANTITY",
    "INDEX_UNIT_PRICE",
    "LOOKUP_RANGE",
    "MARGIN",
    "data_row",
    "header_row",
    "lookup_formula",
    "verify_contract",
]
