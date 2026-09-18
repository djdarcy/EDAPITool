"""
What a layout must look like, without knowing whose sheet it describes.

Generic spreadsheet mechanics. A layout says which columns hold what, and
headers are found by text so moving a column needs no code change -- but which
tab, which header and which row are facts about one person's sheet, so the
concrete class lives with that sheet's other conventions and only its *shape*
is here.
"""

from __future__ import annotations

from typing import Optional, Protocol

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

SIGN_POSITIVE = "positive"
SIGN_NEGATIVE = "negative"


class LayoutLike(Protocol):
    """
    What this layer needs of a layout, without knowing whose sheet it is.

    The concrete class moved out. ``SheetLayout`` describes ONE spreadsheet --
    its tab, its headers, the row its commodities start on -- and a module
    whose docstring opens "generic spreadsheet mechanics" has no business
    carrying those. It now lives with the rest of that sheet's conventions, in
    ``APITool/plugins/settlement/``.

    This Protocol is what remains: a shape core can annotate against, so
    ``service`` and ``daemon`` can say "I take a layout" without naming the one
    that ships. Structural, so a plugin satisfies it by having the right
    attributes -- there is nothing to subclass, import, or register.

    Deliberately minimal. Every attribute added here is another thing a second
    sheet's author must supply, and another thread to cut when the plug is
    pulled (issue #18, requirement 3).
    """

    totals_tab: str
    cargo_tab: str
    header_row: int
    first_data_row: int
    name_column: str
    need_header: str
    need_sign: str
    marker_column: str
    marker_header: str
    system_cell: str
    station_cell: str
    max_scan_row: int
    markers: Optional[dict]

    def marker_map(self) -> Optional[dict]: ...
    def marker_range(self, last_row: int) -> str: ...
    def marker_header_cell(self) -> str: ...
    # A DECLARATION of what may be written, tab -> A1 ranges. Core builds the
    # guard from it; a layout never builds its own.
    def writes(self) -> dict[str, list[str]]: ...


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

class WorksheetLike(Protocol):
    """The slice of gspread's Worksheet this module needs."""

    def get_values(self, range_name: str, **kwargs) -> list[list[str]]: ...
    def batch_update(self, data: list[dict], **kwargs): ...


class SheetLayoutError(Exception):
    """The sheet does not look the way the configuration says it should."""


def parse_quantity(raw: object) -> Optional[int]:
    """
    Parse a quantity as the sheet renders it.

    Sheets returns display strings, so thousands separators and currency-ish
    decoration are normal: '1,716' -> 1716. Returns None for blanks and for
    error values -- a formula mid-recalculation shows '#N/A', and treating
    that as zero would silently drop a real requirement.
    """
    text = str(raw).strip()
    if not text or text.startswith("#"):
        return None
    text = text.replace(",", "").replace(" ", "").replace(" ", "")
    if text in ("-", "--", "—"):
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None

