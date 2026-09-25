"""
This settlement workbook's shape -- concrete, measured, and deliberately not general.

``SheetLayout`` lives here rather than in ``APITool/sheets/`` because it
describes **one** spreadsheet. The generic layer keeps the mechanics every
sheet needs -- ``WriteGuard``, ``CellRange``, the A1 helpers, ``parse_quantity``
-- and knows nothing about which tab, which headers, or which row any of it
lands on. Those are facts about a sheet a person maintains, and this is the
package allowed to know them.

Issue #18 states the split: *"SheetLayout's values are misplaced, not its
mechanism."* The maintainer chose the stronger form -- move the class itself,
values attached -- for a reason worth recording, because it was a defect in the
first attempt:

    An earlier version left the class in the generic layer with its defaults
    stripped, and put the values here in a ``dict[str, object]`` keyed by field
    name. That is a stringly-typed mirror of a structure that already exists.
    Rename a field on the dataclass and the dict still carries the old key --
    no type checker objects, and nothing fails until ``SheetLayout(**values)``
    raises at run time. Two things that must agree, with nothing making them
    agree.

    Keeping the values as field defaults on the class they belong to removes
    the mirror. There is one definition and nothing to drift.

**Nothing here is configurable, on purpose.** This module hardcodes the real
sheet. It is not a template, not a schema, and not a configuration format --
the point of the isolated package is that it may be utterly specific. A fork
pointing the tool at a different sheet writes its own module beside this one
and never touches anything above this layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ...sheets.a1 import column_to_index
from ...sheets.layout import SIGN_POSITIVE


@dataclass(frozen=True)
class SheetLayout:
    """
    Where things live in the settlement tracking spreadsheet.

    Defaults match the measured live layout (2026-09-08): headers on row 3,
    commodity rows from 5, "Left to buy" in column G, column L empty.

    ``need_sign`` supports the planned merge of "Left to buy" and "Extra next
    rnd" into a single signed column: with ``SIGN_NEGATIVE`` a value of -229
    means "buy 229" and +40 means "40 spare".

    ``max_scan_row`` is a read bound rather than a fact about the sheet -- it
    caps how far down the tab one read reaches, and 400 was comfortably past
    the last populated row when it was set.
    """

    totals_tab: str = "Totals"
    cargo_tab: str = "FreighterData"
    header_row: int = 3
    first_data_row: int = 5
    name_column: str = "B"
    need_header: str = "Left to buy"
    need_sign: str = SIGN_POSITIVE
    marker_column: str = "L"
    marker_header: str = "At Current Station"
    system_cell: str = "C2"
    station_cell: str = "G2"
    max_scan_row: int = 400
    # Overridable glyphs; see the MARKER_* constants for the alternatives.
    markers: Optional[dict] = None

    def marker_map(self) -> Optional[dict]:
        """Glyph overrides for the renderer, or None for its defaults."""
        return self.markers

    @property
    def name_column_index(self) -> int:
        return column_to_index(self.name_column)

    @property
    def marker_column_index(self) -> int:
        return column_to_index(self.marker_column)

    def marker_range(self, last_row: int) -> str:
        return f"{self.marker_column}{self.first_data_row}:{self.marker_column}{last_row}"

    def marker_header_cell(self) -> str:
        return f"{self.marker_column}{self.header_row}"

    def writes(self) -> dict[str, list[str]]:
        """
        What this plugin DECLARES it writes: tab -> A1 ranges, nothing else.

        A declaration, not a guard. The plugin says where; core builds the
        enforcer from this and decides whether -- a plugin trusted to build
        its own guard did not catch its own transposed constant, and one
        built by core from this same declaration did (measured, 2026-09-16).
        The shape is the ``gsheet`` kind's vocabulary; a file target would
        declare a path instead, and its kind would enforce that.
        """
        return {
            self.totals_tab: [
                self.system_cell,
                self.station_cell,
                # The header cell, which `--write-glyph-marker-header` may label.
                self.marker_header_cell(),
                # The marker column from the first data row downward.
                #
                # Declared as two ranges rather than one `L3:L` so the TOTAL
                # row between them -- L4 here -- is NOT permitted. The plan
                # has never written it; the old declaration merely allowed
                # it. L4 is empty on the workbook this was measured against,
                # but every other cell in row 4 is a `=SUM(...)`, so a
                # declaration wider than the behaviour is a guard that would
                # wave through the one write nobody intended. Where a layout
                # puts its data immediately under its header the two ranges
                # are contiguous and nothing is excluded.
                f"{self.marker_column}{self.first_data_row}:{self.marker_column}",
            ],
            # FreighterData is fully generated by this tool; a whole-tab
            # rewrite there is the existing, intended behaviour.
            self.cargo_tab: ["A1:Z1000"],
        }
