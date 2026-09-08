"""
Pure comparison: what the spreadsheet still needs, against what a station sells.

This module performs NO I/O -- no network, no filesystem, no Google Sheets. That
is deliberate and load-bearing. Phase 2's route planner is this same function
applied to N candidate stations instead of one, so anything entangled here would
have to be rewritten there.

The output vocabulary is four states, not two, because the measured data
supports four. At Ryman Enterprise on 2026-09-08, of 13 outstanding
requirements:

    ENOUGH   Biowaste 70,192 in stock against a need of 229
    PARTIAL  (none that day -- stock either dwarfed the need or was zero)
    EMPTY    Land Enrichment Systems: buy price 3,404, stock 0
             -- the station sells this, it is just out right now
    NONE     Grain: no buy price, not traded here

Collapsing EMPTY into NONE would throw away the distinction between "come back
later" and "wrong station", which is exactly what a route planner needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Sequence

from .catalog import Commodity, CommodityCatalog
from .market import Market, MarketItem


class MatchState(str, Enum):
    """How well a station covers one outstanding requirement."""

    ENOUGH = "ENOUGH"    # stock >= need
    PARTIAL = "PARTIAL"  # 0 < stock < need
    EMPTY = "EMPTY"      # station trades it, but has none right now
    NONE = "NONE"        # station does not trade it
    UNKNOWN = "UNKNOWN"  # we could not identify the commodity at all

    @property
    def is_buyable(self) -> bool:
        """True when a commander can put units in the hold right now."""
        return self in (MatchState.ENOUGH, MatchState.PARTIAL)


@dataclass(frozen=True)
class Requirement:
    """One outstanding commodity row read from the spreadsheet."""

    row: int
    name: str
    need: int
    commodity: Optional[Commodity] = None

    @property
    def is_outstanding(self) -> bool:
        return self.need > 0

    @property
    def is_resolved(self) -> bool:
        """False when the name matched nothing in the commodity catalog."""
        return self.commodity is not None


@dataclass(frozen=True)
class Match:
    """The verdict for one requirement at one station."""

    requirement: Requirement
    state: MatchState
    item: Optional[MarketItem] = None
    buyable_qty: int = 0
    estimated_cost: int = 0

    @property
    def row(self) -> int:
        return self.requirement.row

    @property
    def name(self) -> str:
        return self.requirement.name

    @property
    def need(self) -> int:
        return self.requirement.need

    @property
    def stock(self) -> int:
        return self.item.stock if self.item else 0

    @property
    def unit_price(self) -> int:
        return self.item.buy_price if self.item else 0

    @property
    def is_covered(self) -> bool:
        """
        Nothing outstanding for this commodity -- already in the hold.

        Distinct from every market state: it is a fact about the requirement,
        not about the station. A covered row is never something to buy, even
        where the station has plenty.
        """
        return self.need <= 0

    @property
    def is_sold_here(self) -> bool:
        """The station trades this commodity, whether or not it has stock."""
        return self.item is not None and (
            self.item.is_purchasable or self.item.is_stocked_when_available
        )

    @property
    def should_mark(self) -> bool:
        """
        Whether this row earns a marker in the spreadsheet.

        EMPTY is included: the commander wants to know the station trades it.
        UNKNOWN is not -- we must never imply availability we cannot verify.
        Covered rows are not marked on this scale; they get their own glyph,
        because "you need none of this" is not a point on a how-much-can-I-buy
        axis.
        """
        if self.is_covered:
            return False
        return self.state in (MatchState.ENOUGH, MatchState.PARTIAL, MatchState.EMPTY)


def classify(need: int, item: Optional[MarketItem]) -> MatchState:
    """
    Decide the state for one requirement against one market item.

    ``item is None`` means the commodity was absent from the market response.
    Callers distinguish "absent because untraded" from "absent because
    unidentifiable" by checking :attr:`Requirement.is_resolved` first.
    """
    if item is None:
        return MatchState.NONE
    if item.is_stocked_when_available:
        # The station sells this and is simply out right now.
        return MatchState.EMPTY
    if not item.is_purchasable:
        # No buy price means the station will not sell it, whatever the stock
        # figure says -- stations also list commodities they only BUY.
        return MatchState.NONE
    return MatchState.ENOUGH if item.stock >= need else MatchState.PARTIAL


def compare_one(requirement: Requirement, market: Market) -> Match:
    """Compare a single requirement against a market. Pure."""
    commodity = requirement.commodity
    item = market.find(
        commodity_id=commodity.id if commodity else None,
        symbol=commodity.symbol if commodity else None,
        name=requirement.name,
    )

    if item is None and not requirement.is_resolved:
        # The catalog does not know this name and the market does not list it.
        # We cannot tell "not sold here" from "we misread the name", so we say
        # so explicitly rather than implying the station does not stock it.
        return Match(requirement=requirement, state=MatchState.UNKNOWN)

    state = classify(requirement.need, item)
    if not state.is_buyable or item is None:
        return Match(requirement=requirement, state=state, item=item)

    buyable = min(item.stock, requirement.need)
    return Match(
        requirement=requirement,
        state=state,
        item=item,
        buyable_qty=buyable,
        estimated_cost=buyable * item.buy_price,
    )


def compare(
    requirements: Iterable[Requirement],
    market: Market,
    include_satisfied: bool = False,
) -> list[Match]:
    """
    Compare every outstanding requirement against one station's market.

    Rows whose need is zero or negative are skipped by default: a commodity
    already covered must never be marked, even when the station sells it.
    """
    results = []
    for requirement in requirements:
        if not include_satisfied and not requirement.is_outstanding:
            continue
        results.append(compare_one(requirement, market))
    return results


def build_requirements(
    rows: Iterable[tuple[int, str, int]],
    catalog: Optional[CommodityCatalog] = None,
) -> list[Requirement]:
    """Turn ``(row, name, need)`` triples into resolved Requirements."""
    built = []
    for row, name, need in rows:
        commodity = catalog.by_name(name) if catalog is not None else None
        built.append(
            Requirement(row=row, name=str(name).strip(), need=int(need), commodity=commodity)
        )
    return built


@dataclass(frozen=True)
class ComparisonSummary:
    """Aggregate view of a comparison, for status messages and logging."""

    matches: Sequence[Match]

    def _count(self, state: MatchState) -> int:
        return sum(1 for m in self.matches if m.state is state)

    @property
    def enough(self) -> int:
        return self._count(MatchState.ENOUGH)

    @property
    def partial(self) -> int:
        return self._count(MatchState.PARTIAL)

    @property
    def empty(self) -> int:
        return self._count(MatchState.EMPTY)

    @property
    def none(self) -> int:
        return self._count(MatchState.NONE)

    @property
    def unknown(self) -> list[Match]:
        return [m for m in self.matches if m.state is MatchState.UNKNOWN]

    @property
    def buyable(self) -> list[Match]:
        return [m for m in self.matches if m.state.is_buyable]

    @property
    def marked(self) -> list[Match]:
        return [m for m in self.matches if m.should_mark]

    @property
    def total_estimated_cost(self) -> int:
        return sum(m.estimated_cost for m in self.matches)

    def describe(self) -> str:
        """One line a human can read in a toast or a log."""
        parts = [
            f"{self.enough} in stock",
            f"{self.partial} partial",
            f"{self.empty} sold here but empty",
        ]
        if self.unknown:
            parts.append(f"{len(self.unknown)} unrecognized")
        cost = self.total_estimated_cost
        line = ", ".join(parts)
        if cost:
            line += f"; est. {cost:,} cr"
        return line


__all__ = [
    "ComparisonSummary",
    "Match",
    "MatchState",
    "Requirement",
    "build_requirements",
    "classify",
    "compare",
    "compare_one",
]
