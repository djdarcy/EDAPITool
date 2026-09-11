"""
Keep the generated tabs current while the game is running.

The tool publishes data tabs; the spreadsheet's own formulas decide what they
mean. So "keeping the sheet up to date" is entirely a matter of republishing
``MarketData`` and ``ShipCargo`` when the game state changes -- the VLOOKUPs
that read them recalculate on their own.

That is why this is small. An earlier design (issue #2) had the daemon writing
marker glyphs into the sheet and polling the requirement column to notice edits,
because a *written* marker goes stale silently and nothing recalculates it. With
both computed columns now formulas, that whole half disappears: editing a
requirement updates the sheet without this process being involved at all.

What remains is: watch the journal, coalesce the bursts, republish. Nothing here
writes to a range the user maintains -- only to tabs this tool owns.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .journal import JournalWatcher
from .service import MarketRefreshService, market_data_rows
from .sheets import SheetLayout

# Events that can invalidate the market tab. `Market` fires when the commodity
# screen is opened, `Docked`/`Location` place the commander, and the jump events
# mean the previous station's prices are no longer where you are.
MARKET_EVENTS = frozenset(
    {"Docked", "Undocked", "Location", "FSDJump", "CarrierJump", "Market"}
)
# Cargo.json is rewritten on every transfer; the game also logs an event.
CARGO_EVENTS = frozenset({"Cargo", "CargoTransfer", "Docked", "Undocked"})


@dataclass
class ServeStats:
    polls: int = 0
    events: int = 0
    market_publishes: int = 0
    cargo_publishes: int = 0
    errors: int = 0
    last_error: Optional[str] = None


@dataclass
class Daemon:
    """
    The publish loop, with the clock and the sheet injected.

    ``sleep`` and ``publish_*`` are parameters rather than imports so the loop
    can be driven deterministically in a test: real time and real Google calls
    are the two things that would otherwise make this untestable.
    """

    watcher: JournalWatcher
    publish_market: Callable[[], str]
    publish_cargo: Callable[[], str]
    interval: float = 2.0
    debounce: float = 5.0
    log: Callable[[str], None] = print
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic
    stats: ServeStats = field(default_factory=ServeStats)

    # Set when an event arrives; cleared when the publish actually happens.
    _market_due: Optional[float] = None
    _cargo_due: Optional[float] = None

    def note(self, events: list[dict]) -> None:
        """Record that a publish is owed, and when it may happen.

        Deliberately a DEADLINE rather than a counter: 19 `Market` events were
        observed in one play session, and publishing per event would be both
        useless and a quota problem. Each new event pushes the deadline out, so
        a burst results in exactly one publish once the burst stops.
        """
        deadline = self.now() + self.debounce
        for event in events:
            name = event.get("event")
            if name in MARKET_EVENTS:
                self._market_due = deadline
            if name in CARGO_EVENTS:
                self._cargo_due = deadline

    def due(self) -> list[str]:
        """Which publishes have waited out their debounce."""
        now = self.now()
        ready = []
        if self._market_due is not None and now >= self._market_due:
            ready.append("market")
        if self._cargo_due is not None and now >= self._cargo_due:
            ready.append("cargo")
        return ready

    def tick(self) -> list[str]:
        """One poll. Returns what was published, for tests and for logging."""
        self.stats.polls += 1
        events = self.watcher.poll()
        if events:
            self.stats.events += len(events)
            self.note(events)

        published = []
        for what in self.due():
            try:
                if what == "market":
                    self._market_due = None
                    message = self.publish_market()
                    self.stats.market_publishes += 1
                else:
                    self._cargo_due = None
                    message = self.publish_cargo()
                    self.stats.cargo_publishes += 1
                published.append(what)
                self.log(message)
            except Exception as exc:
                # One failed publish must not end the session. The sheet being
                # briefly stale is recoverable; the daemon exiting while the
                # commander keeps playing is not noticed until much later.
                self.stats.errors += 1
                self.stats.last_error = str(exc)
                self.log(f"  ! {what} publish failed: {exc}")
        return published

    def run(self, stop_after: Optional[int] = None) -> ServeStats:
        """Loop until interrupted. ``stop_after`` bounds it for tests."""
        ticks = 0
        while stop_after is None or ticks < stop_after:
            self.tick()
            ticks += 1
            if stop_after is None or ticks < stop_after:
                self.sleep(self.interval)
        return self.stats


def build(
    sheet_id: str,
    journal_dir: Optional[Path] = None,
    layout: Optional[SheetLayout] = None,
    ship_tab: str = "ShipCargo",
    # Default OFF. The location cells want to be spreadsheet formulas reading
    # MarketData's own header block -- the tool publishes, the sheet decides --
    # and a run that writes literals into them would overwrite those formulas
    # with a snapshot. Kept as opt-in scaffolding for a sheet that has not
    # migrated yet; deleted outright once the formula migration is everywhere.
    write_location: bool = False,
    log: Callable[[str], None] = print,
    **kwargs,
) -> Daemon:
    """Wire a Daemon against the real journal and a real spreadsheet."""
    from . import ship as ship_mod
    from .google import GoogleSheetsExporter

    layout = layout or SheetLayout()
    service = MarketRefreshService(journal_dir=journal_dir, layout=layout)
    watcher = JournalWatcher.create(journal_dir)
    exporter = GoogleSheetsExporter()

    # The cheapest quota protection there is: do not write a grid identical to
    # the one already up there. The Sheets API allows 60 writes/min per user and
    # the debounce alone could reach 24; but the events that survive debouncing
    # are frequently a SECOND `Market` at the same station, whose grid is byte
    # for byte what was published a minute ago. Skipping those costs one hash.
    last: dict[str, str] = {}

    def _fingerprint(grid) -> str:
        import hashlib

        # Row 1 carries a generated "Updated (UTC)" stamp that changes every
        # run, so hashing the whole grid would make every publish look new and
        # defeat the check entirely. The data rows are what matter.
        body = repr(grid[1:]) if len(grid) > 1 else repr(grid)
        return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()

    # The Totals Tab handle, opened once, only when location cells are wanted.
    totals_ws = None
    if write_location:
        totals_ws = exporter.worksheet(sheet_id, layout.totals_tab)

    def publish_market() -> str:
        # Publishing MarketData alone is NOT enough, and the sheet says so.
        # The generated marker formula guards itself with
        #     IF(MarketData!$C$1 <> $G$2, "?", ...)
        # -- "this market data is for a different station than the sheet thinks
        # you are at". So a run that refreshes the data without also refreshing
        # the location cells turns the whole column into question marks. That is
        # the formula being honest, not a bug in it.
        #
        # `include_markers=False` is the --no-markers path: the plan carries C2
        # and G2 and drops the marker range entirely, so nothing is painted over
        # the formulas that do the actual work.
        result = service.refresh(
            worksheet=totals_ws,
            write=totals_ws is not None,
            include_markers=False,
        )
        grid = market_data_rows(result)
        where = result.station or "unknown station"

        mark = _fingerprint(grid)
        if last.get("market") == mark:
            return f"  MarketData unchanged ({where}) -- not written"
        rows = exporter.export_grid(grid, sheet_id=sheet_id)
        last["market"] = mark
        located = " + location cells" if totals_ws is not None else ""
        return f"  MarketData <- {rows} rows ({where}){located}"

    def publish_cargo() -> str:
        from .catalog import load_catalog

        raw = service.reader.read_cargo_json()
        cargo = ship_mod.from_journal(raw, load_catalog()) if raw else None
        # An absent or unreadable Cargo.json publishes the deliberately-empty
        # grid rather than leaving the tab alone: a hold that still lists the
        # last run's cargo, with nothing saying it is stale, feeds column M a
        # number that looks current and silently changes what "Left to buy"
        # says you still need.
        grid = (
            ship_mod.sheet_grid(cargo)
            if cargo is not None
            else ship_mod.empty_sheet_grid()
        )
        held = f"{len(cargo)} commodities" if cargo is not None else "no cargo data"
        mark = _fingerprint(grid)
        if last.get("cargo") == mark:
            return f"  {ship_tab} unchanged ({held}) -- not written"
        rows = exporter.export_grid(grid, sheet_id=sheet_id, tab_name=ship_tab)
        last["cargo"] = mark
        return f"  {ship_tab} <- {rows} rows ({held})"

    return Daemon(
        watcher=watcher,
        publish_market=publish_market,
        publish_cargo=publish_cargo,
        log=log,
        **kwargs,
    )


__all__ = ["Daemon", "ServeStats", "build", "MARKET_EVENTS", "CARGO_EVENTS"]
