"""
Generic spreadsheet mechanics -- vendor-neutral and workbook-neutral.

Nothing in this package knows about Google, about Excel, or about any
particular workbook's conventions. A second backend (an Excel or ODS writer)
belongs beside ``APITool.google``, not here, and would reuse everything here
unchanged. That is what the name is reserved for.

What lives where:
    a1           column letters, indices, and rectangular ranges
    destination  a tab, and the rectangle on it a writer owns
    guard        the deny-by-default write allowlist
    layout       the shape a layout must have, and how quantities are read

This is also the **shared library the destination plugins build on**. When a
second plugin needs something the first already wrote, it moves here rather
than being copied -- a copy is two things that must agree with nothing making
them agree. The test for admission is "would any sheet want this?": A1
arithmetic and the write guard pass it; which tab, which header and which row
do not, and belong with the sheet that means them.
"""

from .a1 import CellRange, column_to_index, index_to_column
from .destination import Destination
from .guard import WriteGuard, WriteRefused
from .layout import (
    SIGN_NEGATIVE,
    SIGN_POSITIVE,
    LayoutLike,
    SheetLayoutError,
    WorksheetLike,
    parse_quantity,
)

__all__ = [
    "CellRange",
    "Destination",
    "LayoutLike",
    "SIGN_NEGATIVE",
    "SIGN_POSITIVE",
    "SheetLayoutError",
    "WorksheetLike",
    "WriteGuard",
    "WriteRefused",
    "column_to_index",
    "index_to_column",
    "parse_quantity",
]
