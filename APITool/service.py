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
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence

from . import market as market_mod
from .catalog import CommodityCatalog, load_catalog
from .journal import NOT_DOCKED, JournalReader, LocationState
from .market import Market
from .matcher import ComparisonSummary, Match, compare
from .registry import Refresh, merge_suppliers
from .sheets.writer import MarkerPlan
from .sheets import (
    LayoutLike,
)

if TYPE_CHECKING:
    # Type-checker only -- deliberately never imported at run time.
    #
    # `from __future__ import annotations` above makes every annotation in
    # this module a string, so the dataclass machinery never resolves these
    # names and the class works without them. Two of the four are annotations
    # and nothing else (RefreshResult.snapshot, RefreshResult.plan); the other
    # two are resolved at call time by the helpers below.
    #
    # Importing them for real here is the defect this arrangement removes: a
    # module-scope edge into the destination layer makes `import
    # APITool.service` -- and so `serve`, the daemon and the carrier path --
    # fail outright when that layer is absent, none of which is one
    # workbook's code (issue #18, requirement 3).
    from .sheets.reader import RequirementSnapshot

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
        layout: LayoutLike,
        journal_dir: Optional[Path] = None,
        catalog: Optional[CommodityCatalog] = None,
        capi_client=None,
        renderer=None,
        guard=None,
        plugin=None,
        target: str = "",
    ):
        # Required, and first, on purpose. This used to default to a layout
        # that silently meant one particular person's spreadsheet -- a default
        # is an opinion about whose sheet this is, and a general-purpose
        # exporter has no such opinion. The caller knows which destination it
        # is talking to; this layer does not and must not.
        #
        # Annotated against the Protocol rather than any concrete class, so
        # this module names no plugin even in a type.
        self.layout = layout
        self.reader = JournalReader(journal_dir)
        self.catalog = catalog or load_catalog()
        self.capi_client = capi_client
        self.renderer = renderer
        # The write guard is CORE's, built from the destination's own
        # declaration of what it writes -- never the destination's to build.
        # The composition root builds it with the target's kind and passes it
        # in; a caller that passes none gets the same construction, here, for
        # the kind this service is bound to (it takes a worksheet).
        if guard is None:
            from .loader import GSHEET, build_enforcer

            guard = build_enforcer(GSHEET, layout.writes())
        self.guard = guard

        # The plugin is the composition root's to name; this layer takes
        # whatever it is handed and asks it two things -- what it SUPPLIES
        # and what it SUBSCRIBES to -- through the registry. Nothing here
        # imports a plugin, so the whole destination layer can be pulled and
        # this module still imports. With no plugin the refresh still reports
        # location and market; there is simply nothing to read requirements
        # from and nothing to publish.
        self.plugin = plugin
        # The configured target's name, or "". It rides on every refresh so
        # a supplier can say which target a value was read from.
        self.target = target
        offered = [("core", {
            "location": lambda ctx: self.read_location(),
            "market": lambda ctx: self.current_market(ctx.get("location")),
        })]
        supplies = getattr(plugin, "supplies", None)
        if callable(supplies):
            offered.append((getattr(plugin, "__name__", "plugin"), supplies()))
        self.suppliers = merge_suppliers(offered)
        subscribes = getattr(plugin, "subscribes", None)
        self.subscriptions = list(subscribes()) if callable(subscribes) else []

    def _ledger(self):
        """
        The writes ledger for this refresh, bound to the target by NAME (#25).

        Core builds it, as core builds the guard: a plugin is handed its memory
        of what the tool wrote, it does not open one. One ``run_id`` per
        refresh groups a publish's rows. No target name, no ledger -- the rule
        then reduces to v0.7.6's skip-if-occupied, never to overwriting.
        ``ED_NO_STORE`` is honoured inside the store itself.
        """
        if not self.target:
            return None
        import uuid

        from .store.writes import StoreLedger

        return StoreLedger(self.target, run_id=uuid.uuid4().hex[:12])

    def _context(self, worksheet, **options) -> Refresh:
        """One refresh's context: the suppliers, and what every consumer may reach."""
        return Refresh(
            self.suppliers,
            worksheet=worksheet,
            layout=self.layout,
            guard=self.guard,
            ledger=self._ledger(),
            catalog=self.catalog,
            renderer=self.renderer,
            options=options,
            target=self.target,
            result=None,
            checked_at="",
        )

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
        options: Optional[Mapping[str, Any]] = None,
    ) -> RefreshResult:
        """
        Run one comparison.

        ``worksheet`` is the handle for the tab the layout names as its
        source of requirements. Without it the service still reports location
        and market state, which is what ``--no-sheet`` and the health
        endpoint use.

        ``options`` travels to the subscribers unread by this layer. It holds
        the words the loaded plugin declared as its flags -- whether to force
        a write over an occupied cell, whether to paint the location cells --
        and core deciding what any of them means is exactly the courier
        mistake the contract exists to prevent. ``write`` is the one word
        core owns: whether the plan is applied at all.
        """
        if not self.reader.exists():
            return RefreshResult(location=LocationState(), reason=REASON_NO_JOURNAL)

        ctx = self._context(worksheet, write=write, **dict(options or {}))
        location = ctx.get("location")

        if not location.docked:
            return self._finish(RefreshResult(location=location, reason=REASON_NOT_DOCKED), ctx)

        if location.market_id is not None and not location.has_commodity_market:
            return self._finish(
                RefreshResult(location=location, reason=REASON_NO_COMMODITY_MARKET), ctx
            )

        market, reason = ctx.get("market")
        if market is None:
            return self._finish(RefreshResult(location=location, reason=reason), ctx)

        # Whatever the game called these commodities is a valid lookup key.
        market_mod.learn_names(self.catalog, [market])

        result = RefreshResult(location=location, reason=REASON_OK, market=market)
        if worksheet is None or not ctx.has("requirements"):
            # No handle, or no plugin supplying requirements: there is nothing
            # to COMPARE against, and that is a complete answer for the
            # comparison. It is not an answer for the subscribers -- whether a
            # destination can publish is its own question, and a plugin whose
            # destination is a file has no worksheet to begin with. So this
            # falls through to _finish rather than returning.
            return self._finish(result, ctx)

        # Pulled ONCE. The comparison below and the marker writer in _finish
        # both consume this snapshot, and neither reads the sheet again.
        snapshot = ctx.get("requirements")
        result.snapshot = snapshot
        # Every row, covered or not. Whether a covered row is SHOWN is a
        # destination's choice, made in its own words (the settlement plugin
        # has a flag for it); the comparison itself does not take sides.
        result.matches = compare(snapshot.requirements, market, include_satisfied=True)
        return self._finish(result, ctx)

    def _finish(self, result: RefreshResult, ctx: Refresh) -> RefreshResult:
        """
        Push every subscription, then record what the first plan-shaped one did.

        Runs even when the comparison failed: an undocked commander still needs
        the station cell set to "Not docked" and the stale markers cleared, or
        the sheet keeps showing the previous station's answer as if current.
        The plugin's subscriber decides what that means for its sheet; this
        layer only hands it the refresh.

        It also runs when there is no worksheet. ``worksheet`` is one kind's
        handle -- a file destination has none -- and this layer used to skip
        every subscription without it, which made a second kind impossible
        before it was ever written. A subscriber that needs a handle it has
        not been given says so itself.
        """
        if result.snapshot is None and ctx.has("requirements"):
            result.snapshot = ctx.get("requirements")

        checked_at = ""
        if result.market is not None and result.market.timestamp is not None:
            checked_at = result.market.timestamp.strftime("%Y-%m-%d %H:%M UTC")
        elif result.ok:
            checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        ctx.env["result"] = result
        ctx.env["checked_at"] = checked_at

        statuses = ctx.run(self.subscriptions)
        for status in statuses.values():
            if isinstance(status, MarkerPlan):
                result.plan = status
                break
        if result.plan is not None and ctx.options["write"]:
            result.written = True
        return result


def market_data_rows(result: "RefreshResult") -> list[list]:
    """
    The market as a lookup grid, ready for a generated tab.

    Returns the "no current market" grid rather than None when there is nothing
    to report, so a caller writing the tab actively clears it. A tab left
    holding the previous station's prices under a stale-looking header is the
    same failure the market freshness gate prevents, on a different surface.

    Module-level, and here rather than in the CLI, because this is the seam this
    module's docstring already claims: "the CLI, the journal watcher, and
    (later) the HTTP API all call it." It existed as an uncalled method while
    the CLI carried a byte-identical private copy, and the daemon -- not finding
    this one -- imported the CLI's. Two callers of a duplicated helper is how
    the location-cell write went missing from one path and not the other.
    """
    if result.market is None:
        # The journal knows where the commander is even when there is no
        # market to report, so the location half of the header stays true.
        return market_mod.empty_sheet_grid(
            result.advice() or "No market data",
            station=result.station or "",
            system=result.system or "",
            market_id=getattr(result.location, "market_id", "") or "",
        )
    return market_mod.sheet_grid(result.market)


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
