"""
Where a generated grid is published.

Generic spreadsheet mechanics: a tab, and the rectangle on it that the writer
owns. Vendor-neutral and workbook-neutral -- it names no tab of ours, carries
no default, and holds no client, worksheet or credential. A ``Destination`` is
a value you can write down, store, and hand to a writer later; turning one into
something writable happens at the edge, in the vendor layer.

Why bounds are required
-----------------------
Everything else here rests on this one choice, so it is worth stating plainly.
A region cannot be cleared correctly without knowing its extent, and clearing
is not optional -- a generated surface that nothing actively wipes keeps
whatever a larger earlier write left behind, and no later reader can tell the
stale cells from the fresh ones.

Measured, rather than assumed (``tests/one-offs/thinking/region-bounds/poc.py``,
whose control arm orphaned 1533 cells as predicted):

    strategy                        orphans   api calls
    derived extent, no clear           1533          10   <- the control
    derived + read the sheet back         0          24
    declared bounds                       0          19
    derived + remembered extent         471          13

The last row is the trap. It is the cheapest and it is clean in four scenarios
out of five; it fails only when the process restarts between publishes, which
is precisely what a daemon does. Its 471 orphans are unrecoverable in practice,
because nothing afterwards knows they are there.

So bounds are declared, never derived, and nothing here remembers what was
written last time.

Why there is no read path
-------------------------
Bounds exist because *clearing* needs to know what to wipe. A read has nothing
to wipe, so a read needs no bounds and no guard. Reading two cells a person
typed is a plain range read, and deliberately does not come through here --
the symmetry would be tidy and would give reads a concept they do not need.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .a1 import CellRange, index_to_column

__all__ = ["Destination"]


@dataclass(frozen=True)
class Destination:
    """
    A tab, and the rectangle on it this writer owns.

    Construct through :meth:`region` or :meth:`whole_tab` rather than calling
    this directly -- both arguments are positional and neither has a default,
    so a destination cannot come into being without someone deciding what it
    owns.

    ``bounds`` is ``None`` only for :meth:`whole_tab`, which means "everything
    on this tab is mine" -- the shape the tool's own generated tabs have always
    had. It is reachable only through that named constructor, so it can never
    be arrived at by omission.
    """

    tab: str
    bounds: Optional[CellRange]

    # -- construction --------------------------------------------------

    @classmethod
    def region(cls, tab: str, bounds: str | CellRange) -> "Destination":
        """A rectangle inside a tab that holds other content too."""
        if not tab or not str(tab).strip():
            raise ValueError("a destination needs a tab name")
        rect = CellRange.parse(bounds) if isinstance(bounds, str) else bounds
        if rect is None:
            raise ValueError(
                "a region needs bounds; use Destination.whole_tab(tab) to "
                "declare that the whole tab is owned"
            )
        for corner in (rect.first_col, rect.first_row, rect.last_col, rect.last_row):
            if corner is None:
                raise ValueError(
                    f"region bounds must be a closed rectangle, got {bounds!r}: "
                    f"an open-ended reserve cannot be cleared to its own extent"
                )
        return cls(tab=str(tab), bounds=rect)

    @classmethod
    def whole_tab(cls, tab: str) -> "Destination":
        """The degenerate case: this writer owns every cell on the tab."""
        if not tab or not str(tab).strip():
            raise ValueError("a destination needs a tab name")
        return cls(tab=str(tab), bounds=None)

    # -- what it says --------------------------------------------------

    @property
    def owns_whole_tab(self) -> bool:
        return self.bounds is None

    @property
    def anchor(self) -> str:
        """Top-left cell the grid is written from. Derived, never stored."""
        if self.bounds is None:
            return "A1"
        return f"{index_to_column(self.bounds.first_col)}{self.bounds.first_row}"

    @property
    def reserved_rows(self) -> Optional[int]:
        if self.bounds is None:
            return None
        return self.bounds.last_row - self.bounds.first_row + 1

    @property
    def reserved_cols(self) -> Optional[int]:
        if self.bounds is None:
            return None
        return self.bounds.last_col - self.bounds.first_col + 1

    def range_a1(self) -> Optional[str]:
        """The reserve in A1 notation, or ``None`` for a whole tab."""
        if self.bounds is None:
            return None
        b = self.bounds
        return (
            f"{index_to_column(b.first_col)}{b.first_row}:"
            f"{index_to_column(b.last_col)}{b.last_row}"
        )

    def fits(self, rows: int, cols: int) -> bool:
        """Would a grid of this shape sit entirely inside the reserve?"""
        if self.bounds is None:
            return True
        if rows < 0 or cols < 0:
            raise ValueError("a grid cannot have negative extent")
        return rows <= self.reserved_rows and cols <= self.reserved_cols

    def describe(self) -> str:
        if self.bounds is None:
            return f"{self.tab} (whole tab)"
        return f"{self.tab}!{self.range_a1()}"

    # -- serialization -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {"tab": self.tab, "bounds": self.range_a1()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Destination":
        if "tab" not in data:
            raise ValueError("a destination needs a tab name")
        bounds = data.get("bounds")
        if bounds is None:
            return cls.whole_tab(data["tab"])
        return cls.region(data["tab"], bounds)
