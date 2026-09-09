"""
A1 notation: column letters, indices, and rectangular ranges.

Generic spreadsheet mechanics. Nothing here knows about Elite Dangerous, about
Google, or about any particular workbook -- an Excel or ODS writer would use
exactly this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# A1 notation
# ---------------------------------------------------------------------------

_A1_CELL = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")


def column_to_index(letters: str) -> int:
    """'A' -> 0, 'Z' -> 25, 'AA' -> 26."""
    total = 0
    for char in letters.upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"not a column reference: {letters!r}")
        total = total * 26 + (ord(char) - 64)
    return total - 1


def index_to_column(index: int) -> str:
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA'."""
    if index < 0:
        raise ValueError(f"negative column index: {index}")
    letters = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


@dataclass(frozen=True)
class CellRange:
    """
    A rectangular region in A1 notation, with open ends allowed.

    ``None`` for a bound means unbounded in that direction, so ``L5:L``
    (everything in column L from row 5 down) is expressible.
    """

    first_col: Optional[int]
    first_row: Optional[int]
    last_col: Optional[int]
    last_row: Optional[int]

    @classmethod
    def parse(cls, a1: str) -> "CellRange":
        text = a1.strip().replace("$", "")
        if not text:
            raise ValueError("empty range")
        if ":" not in text:
            match = _A1_CELL.match(text)
            if not match:
                raise ValueError(f"not a cell reference: {a1!r}")
            col, row = column_to_index(match.group(1)), int(match.group(2))
            return cls(col, row, col, row)

        start, _, end = text.partition(":")
        first_col, first_row = cls._parse_corner(start, a1)
        last_col, last_row = cls._parse_corner(end, a1)
        if (first_col, first_row, last_col, last_row) == (None, None, None, None):
            # ":" would otherwise parse as a fully unbounded range, which
            # contains every cell -- an allowlist entry of ":" would silently
            # permit writing anywhere. Refuse it.
            raise ValueError(f"not a range: {a1!r}")
        return cls(first_col, first_row, last_col, last_row)

    @staticmethod
    def _parse_corner(text: str, original: str) -> tuple[Optional[int], Optional[int]]:
        if not text:
            return None, None
        match = re.match(r"^([A-Za-z]{1,3})?(\d+)?$", text)
        if not match or (match.group(1) is None and match.group(2) is None):
            raise ValueError(f"not a range: {original!r}")
        col = column_to_index(match.group(1)) if match.group(1) else None
        row = int(match.group(2)) if match.group(2) else None
        return col, row

    def contains(self, other: "CellRange") -> bool:
        """Is ``other`` entirely inside this range?"""
        return (
            self._covers(self.first_col, self.last_col, other.first_col, other.last_col)
            and self._covers(self.first_row, self.last_row, other.first_row, other.last_row)
        )

    @staticmethod
    def _covers(lo, hi, other_lo, other_hi) -> bool:
        if lo is not None:
            if other_lo is None or other_lo < lo:
                return False
        if hi is not None:
            if other_hi is None or other_hi > hi:
                return False
        return True

