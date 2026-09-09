"""
Generic spreadsheet mechanics -- vendor-neutral and workbook-neutral.

Nothing in this package knows about Google, about Excel, or about any
particular workbook's conventions. A second backend (an Excel or ODS writer)
belongs beside ``APITool.google``, not here, and would reuse everything here
unchanged. That is what the name is reserved for.

What lives where:
    a1      column letters, indices, and rectangular ranges
    guard   the deny-by-default write allowlist
    layout  where things are on a sheet, discovered by header text
"""

from .a1 import CellRange, column_to_index, index_to_column
from .guard import WriteGuard, WriteRefused
from .layout import (
    SIGN_NEGATIVE,
    SIGN_POSITIVE,
    SheetLayout,
    SheetLayoutError,
    WorksheetLike,
    parse_quantity,
)

__all__ = [
    "CellRange",
    "SIGN_NEGATIVE",
    "SIGN_POSITIVE",
    "SheetLayout",
    "SheetLayoutError",
    "WorksheetLike",
    "WriteGuard",
    "WriteRefused",
    "column_to_index",
    "index_to_column",
    "parse_quantity",
]
