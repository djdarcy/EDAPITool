"""
The deny-by-default write allowlist.

Generic spreadsheet mechanics: which cell ranges a tool is permitted to write.
Vendor-neutral and workbook-neutral -- the ranges are supplied by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .a1 import CellRange, index_to_column

# ---------------------------------------------------------------------------
# B-2: the write allowlist
# ---------------------------------------------------------------------------

class WriteRefused(Exception):
    """A write was attempted outside the allowlist."""


@dataclass(frozen=True)
class WriteGuard:
    """
    Deny-by-default gate on every spreadsheet write.

    The previous guard in ``gsheet.py`` was an allow-by-default DENY list --
    ``PROTECTED_TABS = ["Base", "1st", "2", "3", "Sheet3"]`` -- which named
    three tabs that do not exist in the real workbook while leaving every tab
    that holds irreplaceable hand-entered work (``Totals Tab``,
    ``Agri Lrg. (ex)``, ``Sat. (ex)``, ``Extr. (ex)``) unprotected. A deny list
    fails open: any tab nobody thought of is writable. This fails closed.
    """

    allowed: dict[str, tuple[CellRange, ...]] = field(default_factory=dict)

    @classmethod
    def build(cls, permissions: dict[str, Sequence[str]]) -> "WriteGuard":
        return cls(
            allowed={
                tab: tuple(CellRange.parse(r) for r in ranges)
                for tab, ranges in permissions.items()
            }
        )

    def allows(self, tab: str, a1: str) -> bool:
        ranges = self.allowed.get(tab)
        if not ranges:
            return False
        try:
            target = CellRange.parse(a1)
        except ValueError:
            return False
        return any(allowed.contains(target) for allowed in ranges)

    def check(self, tab: str, a1: str) -> None:
        """Raise :class:`WriteRefused` unless the write is allowlisted."""
        if not self.allows(tab, a1):
            permitted = ", ".join(
                f"{t}!{r}" for t, rs in self.allowed.items() for r in self._render(rs)
            ) or "(nothing)"
            raise WriteRefused(
                f"refusing to write {tab}!{a1}: outside the allowlist. Permitted: {permitted}"
            )

    @staticmethod
    def _render(ranges: Iterable[CellRange]) -> list[str]:
        out = []
        for r in ranges:
            start = f"{index_to_column(r.first_col) if r.first_col is not None else ''}" \
                    f"{r.first_row if r.first_row is not None else ''}"
            end = f"{index_to_column(r.last_col) if r.last_col is not None else ''}" \
                  f"{r.last_row if r.last_row is not None else ''}"
            out.append(start if start == end else f"{start}:{end}")
        return out

