"""
The application service: one refresh, from game state to spreadsheet markers.

This is the seam the CLI, the journal watcher, and (later) the HTTP API all
call. It exists so those three never invoke each other as subprocesses and
never re-implement the ordering rules.

The ordering rules that matter:

1. Establish where the commander is, from the journal.
2. Refuse to compare unless the market data belongs to the station we are
   docked at RIGHT NOW (see :meth:`RefreshResult.ok` and AC-5). Market.json is
   written only when the commodity screen is opened, so it routinely describes
   somewhere already left.
3. Read the sheet's requirements and write the markers against ONE snapshot,
   because a settlement-tab edit re-sorts the commodity block underneath us.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from . import market as market_mod
from .catalog import CommodityCatalog, load_catalog
from .journal import NOT_DOCKED, JournalReader, LocationState
from .market import Market
from .matcher import ComparisonSummary, Match, compare
from .sheets import (
    MarkerPlan,
    RequirementSnapshot,
    SheetLayout,
    TotalsTabReader,
    TotalsTabWriter,
)

# Why a comparison could not be produced. Each maps to one user action.
REASON_OK = "ok"
REASON_NOT_DOCKED = "not_docked"
REASON_NO_MARKET_DATA = "no_market_data"
REASON_STALE_MARKET = "stale_market"
REASON_NO_COMMODITY_MARKET = "no_commodity_market"
REASON_NO_JOURNAL = "no_journal"

_ADVICE = {
    REASON_NOT_DOCKED: "Dock at a station to compare its market.",
    REASON_NO_MARKET_DATA: (
        "No Market.json found. Dock and open the station's Commodity Market "
        "screen once so the game writes it."
    ),
    REASON_STALE_MARKET: (
        "Market.json still describes a different station. Open the Commodity "
        "Market screen here so the game refreshes it."
    ),
    REASON_NO_COMMODITY_MARKET: "This station has no commodity market.",
    REASON_NO_JOURNAL: (
        "No Elite Dangerous journal directory found. Set ED_JOURNAL_DIR if your "
        "Saved Games folder is in a non-standard location."
    ),
}


@dataclass
class RefreshResult:
    """Everything one refresh produced, whether or not it succeeded."""

    location: LocationState
    reason: str = REASON_OK
    market: Optional[Market] = None
    matches: list[Match] = field(default_factory=list)
    snapshot: Optional[RequirementSnapshot] = None
    plan: Optional[MarkerPlan] = None
    written: bool = False

    @property
    def ok(self) -> bool:
        return self.reason == REASON_OK

    @property
    def summary(self) -> ComparisonSummary:
        return ComparisonSummary(self.matches)

    @property
    def system(self) -> str:
        return self.location.system

    @property
    def station(self) -> str:
        return self.location.station_display

    def advice(self) -> str:
        return _ADVICE.get(self.reason, "")

    def describe(self) -> str:
        """One line suitable for a log, a toast, or an API status message."""
        where = f"{self.system or 'Unknown system'} / {self.station}"
        if not self.ok:
            return f"{where}: {self.advice()}"
        return f"{where}: {self.summary.describe()}"


class MarketRefreshService:
    """
    Produces (and optionally writes) the current-station comparison.

    Holds no network connection of its own: the spreadsheet handle is supplied
    by the caller, so the same service works against a live worksheet, a fake
    one in tests, or not at all in ``--no-sheet`` mode.
    """

    def __init__(
        self,
        journal_dir: Optional[Path] = None,
        catalog: Optional[CommodityCatalog] = None,
        layout: Optional[SheetLayout] = None,
        capi_client=None,
    ):
        self.reader = JournalReader(journal_dir)
        self.catalog = catalog or load_catalog()
        self.layout = layout or SheetLayout()
        self.capi_client = capi_client

    # -- market acquisition -------------------------------------------------

    def read_location(self) -> LocationState:
        return self.reader.read_state()

    def journal_market(self, location: LocationState) -> tuple[Optional[Market], str]:
        """
        Read Market.json, gated on it belonging to the current station.

        Returns ``(market, reason)``. The reason is what the user needs to do.
        """
        raw = self.reader.read_market_json()
        if raw is None:
            return None, REASON_NO_MARKET_DATA
        if not location.market_is_current(raw.get("MarketID")):
            return None, REASON_STALE_MARKET
        return market_mod.from_journal(raw, self.catalog), REASON_OK

    def capi_market(self, location: LocationState) -> Optional[Market]:
        """
        Fetch the live CAPI market, if a client was supplied.

        CAPI is the fresher source for stock and price and carries a handful of
        commodities the journal omits, but it does not report the star system
        and it drops rows the station is currently out of -- so it supplements
        the journal rather than replacing it.
        """
        if self.capi_client is None:
            return None
        try:
            raw = self.capi_client.get_market()
        except Exception:
            # CAPI being unavailable must never block a journal-based answer.
            return None
        if not raw:
            return None
        candidate = market_mod.from_capi(raw, self.catalog, system=location.system)
        if not location.market_is_current(candidate.market_id):
            return None
        return candidate

    def current_market(self, location: LocationState) -> tuple[Optional[Market], str]:
        """
        The best available view of the current station's market.

        CAPI is primary where present (live stock and price); the journal
        supplements it (broader coverage, and buy prices for out-of-stock
        rows). Either alone is a valid answer.
        """
        journal_market, reason = self.journal_market(location)
        capi_market = self.capi_market(location)

        if capi_market is not None and journal_market is not None:
            return market_mod.merge(capi_market, journal_market), REASON_OK
        if capi_market is not None:
            return capi_market, REASON_OK
        if journal_market is not None:
            return journal_market, reason
        return None, reason

    # -- the refresh --------------------------------------------------------

    def refresh(
        self,
        worksheet=None,
        write: bool = False,
        write_header: bool = False,
        show_covered: bool = True,
        apply_colour: bool = True,
    ) -> RefreshResult:
        """
        Run one comparison.

        ``worksheet`` is the Totals Tab handle. Without it the service still
        reports location and market state, which is what ``--no-sheet`` and the
        health endpoint use.
        """
        if not self.reader.exists():
            return RefreshResult(location=LocationState(), reason=REASON_NO_JOURNAL)

        location = self.read_location()

        if not location.docked:
            result = RefreshResult(location=location, reason=REASON_NOT_DOCKED)
            return self._finish(
                result, worksheet, write, write_header, show_covered, apply_colour
            )

        if location.market_id is not None and not location.has_commodity_market:
            result = RefreshResult(location=location, reason=REASON_NO_COMMODITY_MARKET)
            return self._finish(
                result, worksheet, write, write_header, show_covered, apply_colour
            )

        market, reason = self.current_market(location)
        if market is None:
            result = RefreshResult(location=location, reason=reason)
            return self._finish(
                result, worksheet, write, write_header, show_covered, apply_colour
            )

        # Whatever the game called these commodities is a valid lookup key.
        market_mod.learn_names(self.catalog, [market])

        result = RefreshResult(location=location, reason=REASON_OK, market=market)
        if worksheet is None:
            return result

        snapshot = TotalsTabReader(worksheet, self.layout, self.catalog).read()
        result.snapshot = snapshot
        # Covered rows are needed in the match list only when they will be
        # rendered; otherwise they are dropped as early as possible.
        result.matches = compare(
            snapshot.requirements, market, include_satisfied=show_covered
        )
        return self._finish(
                result, worksheet, write, write_header, show_covered, apply_colour
            )

    def _finish(
        self,
        result: RefreshResult,
        worksheet,
        write: bool,
        write_header: bool,
        show_covered: bool = True,
        apply_colour: bool = True,
    ) -> RefreshResult:
        """
        Build (and optionally apply) the write plan.

        Runs even when the comparison failed: an undocked commander still needs
        the station cell set to "Not docked" and the stale markers cleared, or
        the sheet keeps showing the previous station's answer as if current.
        """
        if worksheet is None:
            return result

        if result.snapshot is None:
            result.snapshot = TotalsTabReader(worksheet, self.layout, self.catalog).read()

        writer = TotalsTabWriter(worksheet, self.layout)
        checked_at = ""
        if result.market is not None and result.market.timestamp is not None:
            checked_at = result.market.timestamp.strftime("%Y-%m-%d %H:%M UTC")
        elif result.ok:
            checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        result.plan = writer.build_plan(
            matches=result.matches,
            snapshot=result.snapshot,
            system=result.location.system,
            station=result.location.station_display,
            checked_at=checked_at,
            write_header=write_header,
            show_covered=show_covered,
            apply_colour=apply_colour,
        )
        if write:
            writer.apply(result.plan)
            result.written = True
        return result


def format_table(matches: Sequence[Match]) -> str:
    """Render a comparison as a fixed-width table for the terminal."""
    if not matches:
        return "  (nothing outstanding)"

    width = max(len(m.name) for m in matches)
    header = (
        f"  {'row':>4}  {'commodity':<{width}}  {'need':>7}  {'state':<8}"
        f"  {'stock':>10}  {'unit':>7}  {'buy now':>8}  {'est. cost':>12}"
    )
    lines = [header, "  " + "-" * (len(header) - 2)]
    for m in sorted(matches, key=lambda x: x.row):
        lines.append(
            f"  {m.row:>4}  {m.name:<{width}}  {m.need:>7,}  {m.state.value:<8}"
            f"  {m.stock:>10,}  {m.unit_price:>7,}  {m.buyable_qty:>8,}"
            f"  {m.estimated_cost:>12,}"
        )
    return "\n".join(lines)


__all__ = [
    "MarketRefreshService",
    "REASON_NOT_DOCKED",
    "REASON_NO_COMMODITY_MARKET",
    "REASON_NO_JOURNAL",
    "REASON_NO_MARKET_DATA",
    "REASON_OK",
    "REASON_STALE_MARKET",
    "RefreshResult",
    "format_table",
    "NOT_DOCKED",
]
