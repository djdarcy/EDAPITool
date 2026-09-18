"""
Reading a requirements block from a worksheet, by header discovery.

Generic spreadsheet mechanics. Which column holds the names and which the
quantities is the layout's to say, and the layout is the caller's: nothing
here knows whose sheet it is reading. The tab, the header text and the first
data row are attributes of the layout it is handed, never literals.

Moved here from the settlement plugin, where it had been filed as that
workbook's reader. It touches nothing but its layout and the catalog, and a
second plugin would have rewritten it line for line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..catalog import CommodityCatalog
from ..matcher import Requirement, build_requirements
from .a1 import index_to_column
from .layout import (
    SIGN_NEGATIVE,
    LayoutLike,
    SheetLayoutError,
    WorksheetLike,
    parse_quantity,
)


@dataclass(frozen=True)
class RequirementSnapshot:
    """
    One consistent read of the requirements tab.

    Everything downstream keys off this single snapshot, because the row
    numbering it describes is only guaranteed valid for this read.
    """

    requirements: list[Requirement]
    last_data_row: int
    need_column_index: int
    header_row: int
    unparsed_rows: list[tuple[int, str, str]] = field(default_factory=list)

    @property
    def outstanding(self) -> list[Requirement]:
        return [r for r in self.requirements if r.is_outstanding]


class RequirementsReader:
    """Reads commodity names and outstanding quantities by header discovery."""

    def __init__(
        self,
        worksheet: WorksheetLike,
        layout: LayoutLike,
        catalog: Optional[CommodityCatalog] = None,
        *,
        target: str = "",
    ):
        self.worksheet = worksheet
        # Required. The toolkit has no sheet of its own to default to; the
        # plugin that knows one supplies it.
        self.layout = layout
        self.catalog = catalog
        # The configured target's name, when the refresh carries one. It
        # prefixes every requirement's origin, so a locator names which
        # target it was read from and not only which tab.
        self.target = target

    def find_column(self, header_row_values: Sequence[str], header: str) -> int:
        """
        Locate a column by exact header text.

        Fails loudly on both missing and duplicate headers. Guessing at either
        would put markers in an arbitrary column.
        """
        wanted = header.strip().casefold()
        hits = [
            i for i, value in enumerate(header_row_values)
            if str(value).strip().casefold() == wanted
        ]
        if not hits:
            present = [str(v).strip() for v in header_row_values if str(v).strip()]
            raise SheetLayoutError(
                f"header {header!r} not found in row {self.layout.header_row} "
                f"of {self.layout.totals_tab!r}. Headers present: {present}"
            )
        if len(hits) > 1:
            columns = ", ".join(index_to_column(i) for i in hits)
            raise SheetLayoutError(
                f"header {header!r} appears in multiple columns ({columns}) "
                f"of {self.layout.totals_tab!r}; cannot choose one safely"
            )
        return hits[0]

    def read(self) -> RequirementSnapshot:
        """Read the whole commodity block in a single API call."""
        layout = self.layout
        grid = self.worksheet.get_values(f"A1:AZ{layout.max_scan_row}")
        if len(grid) < layout.header_row:
            raise SheetLayoutError(
                f"{layout.totals_tab!r} has fewer than {layout.header_row} rows; "
                "is the tab name or header row misconfigured?"
            )

        header_values = grid[layout.header_row - 1]
        need_col = self.find_column(header_values, layout.need_header)
        name_col = layout.name_column_index

        rows: list[tuple[int, str, int]] = []
        unparsed: list[tuple[int, str, str]] = []
        last_row = layout.first_data_row - 1

        for row_number in range(layout.first_data_row, len(grid) + 1):
            row = grid[row_number - 1]
            name = str(row[name_col]).strip() if len(row) > name_col else ""
            if not name:
                continue
            last_row = row_number

            raw = row[need_col] if len(row) > need_col else ""
            quantity = parse_quantity(raw)
            if quantity is None:
                # Blank is a legitimate "nothing needed"; an error value is
                # not, and the caller should hear about it.
                if str(raw).strip():
                    unparsed.append((row_number, name, str(raw).strip()))
                quantity = 0
            rows.append((row_number, name, self._apply_sign(quantity)))

        # Where each requirement came from, as a locator: the tab and the cell
        # its name sits in, prefixed with the target's name when the refresh
        # carries one -- "<target>!<tab>!<column><row>".
        prefix = f"{self.target}!" if self.target else ""

        def origin_for(row_number: int) -> str:
            return f"{prefix}{layout.totals_tab}!{layout.name_column}{row_number}"

        return RequirementSnapshot(
            requirements=build_requirements(rows, self.catalog, origin_for=origin_for),
            last_data_row=last_row,
            need_column_index=need_col,
            header_row=layout.header_row,
            unparsed_rows=unparsed,
        )

    def _apply_sign(self, quantity: int) -> int:
        """
        Normalize the sheet's convention to "positive means still to buy".

        With ``SIGN_NEGATIVE`` the column is the planned combined
        "What's left", where negative means outstanding and positive means
        surplus.
        """
        if self.layout.need_sign == SIGN_NEGATIVE:
            return -quantity
        return quantity
