"""
Whose cell is it? The rule that decides what a plan may overwrite (#25, slice 4).

v0.7.6 answered "anything that holds something is a person's", which kept
formulas safe and froze every sheet the tool paints: its own glyph from the
last station counted as occupied. The ledger answers it properly. A cell the
tool wrote, still holding exactly what read back after that write, is the
tool's own and is refreshed. A cell the tool never wrote is written only
when it is empty. Anything else -- a formula, a note, a value a person typed,
one of the tool's cells a person has since changed -- is held and reported.
``--force`` writes all of them, and what reads back after a forced write is
recorded, so one forced run adopts old paint for good.

This module is pure: it knows nothing of sqlite or Google. Core hands the
writer a :class:`WriteLedger` bound to one target (the store's
``StoreLedger`` in production, :class:`MemoryLedger` in tests); with no
ledger at all -- ``ED_NO_STORE``, a store that will not open -- nothing is
recorded, so nothing is ever "ours", and the rule reduces to v0.7.6's.

Values are compared as the strings a FORMULA read returns, never as what a
cell displays: a glyph formula shows nothing at a station that does not
sell the commodity, and a displayed-value compare would call it empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Protocol


def is_empty(value) -> bool:
    """Empty or whitespace only -- v0.7.6's definition, kept so the two agree."""
    return value is None or str(value).strip() == ""


def as_text(value) -> str:
    """A cell's value as the ledger stores it: the FORMULA read, as a string."""
    return "" if value is None else str(value)


@dataclass
class Classification:
    """Every planned cell, in exactly one list, in the order it was planned."""

    refresh: list[str] = field(default_factory=list)   # ours: holds what we last wrote
    fill: list[str] = field(default_factory=list)      # empty: written as before
    held: list[str] = field(default_factory=list)      # someone else's: left and reported
    forced: list[str] = field(default_factory=list)    # --force: written despite the rule


def classify(current: Mapping[str, object], recorded: Mapping[str, str],
             planned: Iterable[str], *, force: bool = False,
             readable: bool = True) -> Classification:
    """
    Sort each planned cell into refresh, fill, held or forced.

    ``current`` is what each cell holds now, read as formulas; a cell missing
    from it is empty. ``recorded`` is what the ledger says the tool last
    wrote there; a cell missing from it was never written (or the ledger is
    off). ``readable=False`` means the read itself failed: nothing is known
    about any cell, so every one is held -- the safe direction -- unless
    forced.
    """
    out = Classification()
    for a1 in planned:
        if force:
            out.forced.append(a1)
            continue
        if not readable:
            out.held.append(a1)
            continue
        now = current.get(a1)
        if is_empty(now):
            out.fill.append(a1)
        elif a1 in recorded and as_text(now) == recorded[a1]:
            out.refresh.append(a1)
        else:
            out.held.append(a1)
    return out


class WriteLedger(Protocol):
    """What the writer asks of a ledger already bound to one target."""

    def recorded(self, tab: str, a1s: Iterable[str]) -> dict[str, str]: ...

    def record(self, tab: str, values: Mapping[str, str]) -> bool: ...


class MemoryLedger:
    """A ledger in a dict, for tests and for callers with no store."""

    def __init__(self, cells: Optional[Mapping[tuple[str, str], str]] = None):
        self.cells: dict[tuple[str, str], str] = dict(cells or {})
        self.records: list[tuple[str, dict[str, str]]] = []

    def recorded(self, tab: str, a1s: Iterable[str]) -> dict[str, str]:
        return {a1: self.cells[(tab, a1)] for a1 in a1s if (tab, a1) in self.cells}

    def record(self, tab: str, values: Mapping[str, str]) -> bool:
        if not values:
            return False
        self.records.append((tab, dict(values)))
        for a1, value in values.items():
            self.cells[(tab, a1)] = as_text(value)
        return True
