"""
This workbook's Totals Tab: reading its requirements, writing its markers.

DEMOTED. Everything here encodes one particular spreadsheet's conventions --
a Totals Tab, a marker column, a "Left to buy" header. The tool's supported
path is to publish a generated data tab and let the sheet's own formulas
decide what it means; this module is how sheet writes get tested, and how the
workbook was driven before both computed columns became formulas.

It is kept, not deleted, and it is kept here rather than beside the generic
mechanics so that its status is visible in an import line. See the retirement
ledger in private/claude/ for the condition that would remove it.

Everything this module builds on lives in ``APITool.sheets`` and is generic;
the dependency points one way and a layering test enforces it.

As of v0.7.3 the reader and the writer themselves live there too --
:class:`APITool.sheets.RequirementsReader` and :class:`APITool.sheets.MarkerWriter`
-- because they touched nothing but a layout and a renderer, and a second
plugin would have rewritten them. What stays here is the one thing only this
plugin may know: which layout to use when the caller names none.
"""

from __future__ import annotations

from typing import Optional

from ...catalog import CommodityCatalog
from ...sheets.guard import WriteGuard
from ...sheets.layout import WorksheetLike
from ...sheets.reader import RequirementSnapshot, RequirementsReader
from ...sheets.writer import CellRenderer, MarkerPlan, MarkerWriter
from .layout import SheetLayout

__all__ = [
    "CellRenderer",
    "MarkerPlan",
    "RequirementSnapshot",
    "TotalsTabReader",
    "TotalsTabWriter",
]


class TotalsTabReader(RequirementsReader):
    """The generic reader, defaulting to this workbook's layout."""

    def __init__(
        self,
        worksheet: WorksheetLike,
        layout: Optional[SheetLayout] = None,
        catalog: Optional[CommodityCatalog] = None,
        *,
        target: str = "",
    ):
        super().__init__(worksheet, layout or SheetLayout(), catalog, target=target)


class TotalsTabWriter(MarkerWriter):
    """The generic writer, defaulting to this workbook's layout."""

    def __init__(
        self,
        worksheet: WorksheetLike,
        renderer: CellRenderer,
        layout: Optional[SheetLayout] = None,
        *,
        guard: WriteGuard,
        ledger=None,
    ):
        super().__init__(worksheet, renderer, layout or SheetLayout(), guard=guard,
                         ledger=ledger)
