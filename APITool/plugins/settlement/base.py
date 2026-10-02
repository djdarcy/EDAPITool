"""
The construction requirements matrix, as a workbook keeps it.

A ``Base`` tab holds the forum's matrix: commodity names down column A, one
settlement type per column across a header row, and the quantity each type
needs in the cells. The header row is the one whose first cell starts with
``PLANETARY``; the types in it carry a leading space and the quantities a
trailing zero-width space, because that is how the matrix pasted in, and a
parser that assumed clean text would read every one of them as missing.
Nothing here names a row number: the row is found, not assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

ZERO_WIDTH_SPACE = "​"
HEADER_MARK = "PLANETARY"
TITLE_PREFIX = "settlement "


def normalise_type(text: object) -> str:
    """
    One spelling for a settlement type, from any of the ways the workbook
    says it: ``' agricultural large'`` in the matrix's header, ``'Settlement
    agricultural large'`` in a settlement tab's title cell, or what a person
    typed on the command line.
    """
    value = str(text).replace(ZERO_WIDTH_SPACE, "").strip().lower()
    if value.startswith(TITLE_PREFIX):
        value = value[len(TITLE_PREFIX):]
    return " ".join(value.split())


def quantity(cell: object) -> Optional[int]:
    """A matrix cell as a count, or None when it holds no count."""
    text = str(cell).replace(ZERO_WIDTH_SPACE, "").replace(",", "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class Matrix:
    """The matrix parsed: the types, and each commodity's count per type."""

    types: tuple[str, ...]
    rows: tuple[tuple[str, tuple[Optional[int], ...]], ...]

    def requirements(self, type_name: object) -> list[tuple[str, int]]:
        """
        What one settlement type needs: ``(commodity, count)`` for every
        commodity with a count above zero, in the matrix's order.

        An unknown type is refused naming every type the matrix offers, so a
        typo is answered with the list rather than an empty tab.
        """
        key = normalise_type(type_name)
        if key not in self.types:
            raise ValueError(
                f"unknown settlement type {str(type_name)!r}; the matrix offers: "
                f"{', '.join(self.types)}"
            )
        column = self.types.index(key)
        return [
            (name, counts[column])
            for name, counts in self.rows
            if column < len(counts) and counts[column] is not None and counts[column] > 0
        ]


def parse_matrix(grid: Sequence[Sequence[object]]) -> Matrix:
    """
    Read the matrix out of a tab's values.

    The header row is the first whose column A starts with ``PLANETARY``;
    every non-empty cell after column A on it is a type. Each later row with
    a name in column A is a commodity, its counts read from the type columns.
    """
    header_at = next(
        (i for i, row in enumerate(grid)
         if row and str(row[0]).strip().upper().startswith(HEADER_MARK)),
        None,
    )
    if header_at is None:
        raise ValueError(
            f"no header row found: the matrix's header starts with {HEADER_MARK!r} in column A"
        )
    header = grid[header_at]
    columns: list[int] = []
    types: list[str] = []
    for index, cell in enumerate(header):
        if index == 0:
            continue
        name = normalise_type(cell)
        if name:
            columns.append(index)
            types.append(name)

    rows: list[tuple[str, tuple[Optional[int], ...]]] = []
    for row in grid[header_at + 1:]:
        name = str(row[0]).replace(ZERO_WIDTH_SPACE, "").strip() if row else ""
        if not name:
            continue
        counts = tuple(quantity(row[c]) if c < len(row) else None for c in columns)
        rows.append((name, counts))
    return Matrix(types=tuple(types), rows=tuple(rows))
