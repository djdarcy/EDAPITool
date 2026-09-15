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
from .settings import get_client_id

# Events that can invalidate the market tab. `Market` fires when the commodity
# screen is opened, `Docked`/`Location` place the commander, and the jump events
# mean the previous station's prices are no longer where you are.
MARKET_EVENTS = frozenset(
    {"Docked", "Undocked", "Location", "FSDJump", "CarrierJump", "Market"}
)
# Cargo.json is rewritten on every transfer; the game also logs an event.
CARGO_EVENTS = frozenset({"Cargo", "CargoTransfer", "Docked", "Undocked"})
# The depot event carries whole state and fires whenever the construction
# panel is touched, so docking at a site is the useful trigger rather than
# every reading of it.
CONSTRUCTION_EVENTS = frozenset(
    {"ColonisationConstructionDepot", "ColonisationContribution", "Docked"}
)
# What changes a fleet carrier's hold in a way the journal can see.
# `CargoTransfer` carries a Direction per item -- measured across 120
# journal files: 138 "tocarrier", 112 "toship" -- but BOTH change the
# carrier, so the direction is not worth branching on here. Buying and
# selling through the carrier's own market changes it too.
#
# What the journal CANNOT see: another commander filling a buy or sell
# order on your carrier. Nothing about that reaches your logs, which is
# why this publisher also carries a heartbeat.
CARRIER_EVENTS = frozenset(
    {"CargoTransfer", "MarketBuy", "MarketSell", "CarrierTradeOrder"}
)
# Frontier serves a CACHED payload rather than refusing an early call --
# measured: two requests one second apart both succeeded in ~1s and
# returned byte-identical data. So these are politeness, not compliance.
CARRIER_MIN_INTERVAL = 60.0      # at most once a minute while shifting cargo
CARRIER_MAX_INTERVAL = 900.0     # at least every 15 min, for other traders
# Keep asking, once a minute, until Frontier reflects a transfer the journal
# has already reported.
#
# Thirty, from the one lag measured end to end on 2026-09-15: a transfer at
# 03:30:16 was still absent from Frontier's payload at 03:44:40 and had
# landed by 04:01:14 -- somewhere between 14 and 31 minutes. An earlier
# value of 15 was set from the first half of that measurement alone and
# would have given up before the data arrived.
#
# The heartbeat remains the backstop past this cap. The retry's job is only
# to make the tab right in minutes rather than in quarter-hours.
CARRIER_CONFIRM_RETRIES = 30


@dataclass(frozen=True)
class PublishResult:
    """
    What one publish did.

    ``wrote`` is the half the loop reasons about; ``message`` is the half the
    person reads. They were one string until a carrier publish that wrote
    nothing was indistinguishable, to the loop, from one that did.
    """

    wrote: bool
    message: str

    @staticmethod
    def of(value) -> "PublishResult":
        """
        Normalise whatever a publisher returned.

        A bare string is read as "wrote": a publisher that does not declare
        confirm_retries is never asked, so its return value is only ever a log
        line. Every path that runs a publish goes through here -- the loop,
        `serve --once`, and the startup catch-up -- so none of them can start
        printing a dataclass repr at somebody.
        """
        if isinstance(value, PublishResult):
            return value
        return PublishResult(True, value)


@dataclass(frozen=True)
class Publisher:
    """
    One thing the daemon keeps current, and what wakes it up.

    The loop used to hold exactly two of these as named fields, which made a
    third a question of editing the loop rather than adding an entry -- and it
    is why the daemon could publish two of the three generated tabs without
    anything being obviously missing. A list makes the set of targets
    something the daemon can be asked about, and `describe_targets` is what
    it answers with.
    """

    name: str
    triggers: frozenset
    # Returns a PublishResult. A bare string is accepted and read as "wrote",
    # which is what the test doubles use and what any target with no
    # confirm_retries can safely be.
    publish: Callable[[], "PublishResult"]

    # Most targets read a local file: free, instant, and worth doing the
    # moment the debounce clears. A target that costs a network round-trip
    # to somebody else's API needs two more numbers.
    #
    # min_interval -- never publish more often than this, however many events
    #   arrive. Transferring a hold's worth of cargo emits dozens of events;
    #   one call covers all of them.
    # max_interval -- publish at least this often even with no events at all.
    #   Required for anything whose state can change without the journal
    #   saying so: another commander filling a buy order on your carrier
    #   appears nowhere in your own logs.
    min_interval: float = 0.0
    max_interval: Optional[float] = None

    # How many further attempts to make when an EVENT said something changed
    # and the source still reports the old contents.
    #
    # Zero for every target that reads a local file: the game wrote the file
    # before it wrote the event, so the source cannot lag its own trigger.
    # Frontier's fleet-carrier endpoint CAN: measured 2026-09-14, it served
    # pre-transfer contents fourteen minutes after the journal recorded
    # `biowaste x840 toship`. Without this, that first stale read looks
    # identical to "nothing changed", the event is discarded, and the tab
    # keeps the wrong number until the heartbeat happens to catch a fresher
    # copy -- which is exactly how FreighterData showed 840 t on the carrier
    # while the same 840 t sat in the ship's hold.
    #
    # A publisher declaring this MUST return a PublishResult, because the
    # loop has to know whether anything was actually written. One that does
    # not is only ever logged.
    confirm_retries: int = 0


@dataclass
class ServeStats:
    polls: int = 0
    events: int = 0
    market_publishes: int = 0
    cargo_publishes: int = 0
    errors: int = 0
    last_error: Optional[str] = None
    # Every other target, counted by name. The two above predate regions and
    # stay as they are so a reader of the summary line is not surprised.
    by_target: dict = field(default_factory=dict)

    def count(self, name: str) -> None:
        if name == "market":
            self.market_publishes += 1
        elif name == "cargo":
            self.cargo_publishes += 1
        self.by_target[name] = self.by_target.get(name, 0) + 1


@dataclass
class Daemon:
    """
    The publish loop, with the clock and the sheet injected.

    ``sleep`` and ``publish_*`` are parameters rather than imports so the loop
    can be driven deterministically in a test: real time and real Google calls
    are the two things that would otherwise make this untestable.
    """

    watcher: JournalWatcher
    publish_market: Callable[[], "PublishResult"]
    publish_cargo: Callable[[], "PublishResult"]
    interval: float = 2.0
    debounce: float = 5.0
    log: Callable[[str], None] = print
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic
    stats: ServeStats = field(default_factory=ServeStats)

    # Regions of tabs the tool does not own outright -- settlement trackers
    # and the like. Empty by default: the core ships no destination.
    regions: list = field(default_factory=list)

    # name -> deadline. Set when an event arrives, cleared when the publish
    # happens.
    _due: dict = field(default_factory=dict)
    # name -> when it last actually published. Only the floor and the
    # heartbeat consult it; the event path does not care.
    _last_published: dict = field(default_factory=dict)
    # name -> attempts still owed, while waiting for a lagging source to
    # catch up with an event that has already been reported.
    _confirming: dict = field(default_factory=dict)

    # The fleet-carrier publisher, when one could be built. Absent when there
    # are no Frontier credentials, because every other target here reads a
    # local file and works with nothing configured -- losing that for all of
    # them because one needs a login would be the wrong trade.
    carrier: Optional[Publisher] = None

    def publishers(self) -> list:
        """Everything this daemon keeps current, in publish order.

        The carrier goes last deliberately: it is the only one that leaves
        the machine, so a slow or failing network call cannot delay the three
        that were ready immediately.
        """
        return [
            Publisher("market", MARKET_EVENTS, self.publish_market),
            Publisher("cargo", CARGO_EVENTS, self.publish_cargo),
            *self.regions,
            *([self.carrier] if self.carrier else []),
        ]

    # Generated tabs this loop does NOT keep current, and why in one clause.
    # Stated rather than left to inference: the whole failure this addresses
    # is that a publisher covering part of a sheet looks exactly like one
    # covering all of it, and the difference only surfaces when somebody acts
    # on a number that stopped being true days ago.
    def describe_targets(self) -> str:
        """What this daemon will keep current."""
        names = [p.name for p in self.publishers()]
        return f"Publishing {len(names)}: " + ", ".join(names)

    def describe_gaps(self) -> list[str]:
        """
        What it will NOT keep current, named out loud.

        The counterpart to :meth:`describe_targets`, and the more important
        half. Knowing that two things are current tells you nothing about the
        third unless somebody says the third exists.
        """
        gaps = []
        if self.carrier is None:
            gaps.append(
                "NOT published: FreighterData -- no Frontier credentials, so "
                "the carrier cannot be read. Run `edapitool auth`, or refresh "
                "it by hand with `edapitool carrier --export google`")
        return gaps

    def note(self, events: list[dict]) -> None:
        """Record that a publish is owed, and when it may happen.

        Deliberately a DEADLINE rather than a counter: 19 `Market` events were
        observed in one play session, and publishing per event would be both
        useless and a quota problem. Each new event pushes the deadline out, so
        a burst results in exactly one publish once the burst stops.
        """
        deadline = self.now() + self.debounce
        targets = self.publishers()
        for event in events:
            name = event.get("event")
            for target in targets:
                if name in target.triggers:
                    self._due[target.name] = deadline

    def due(self) -> list[str]:
        """
        Which publishes are ready, in publish order.

        Three ways to become ready, checked in this order because the floor
        overrides both of the others -- a target that has just run is not
        ready no matter what else is true:

        1. the floor has not elapsed -> not ready, whatever else says
        2. an event arrived and its debounce has passed -> ready
        3. nothing has happened but the heartbeat is overdue -> ready
        """
        now = self.now()
        ready = []
        for p in self.publishers():
            last = self._last_published.get(p.name)
            if p.min_interval and last is not None \
                    and now - last < p.min_interval:
                continue
            if p.name in self._due and now >= self._due[p.name]:
                ready.append(p.name)
            elif p.max_interval and (last is None
                                     or now - last >= p.max_interval):
                ready.append(p.name)
        return ready

    def _rearm_for_confirmation(self, what: str, target) -> None:
        """
        An event said this changed and the source still says otherwise.

        Put the deadline back, at the target's own floor, so the next attempt
        is the soonest one allowed rather than the heartbeat. Attempts are
        counted down so a source that is simply never going to change -- a
        transfer the commander undid, say -- cannot leave the loop asking
        forever.
        """
        left = self._confirming.get(what, target.confirm_retries)
        if left <= 0:
            self._confirming.pop(what, None)
            return
        self._confirming[what] = left - 1
        # Owed again, as of now. NOT "owed in min_interval seconds" -- `due`
        # already refuses a target whose floor has not elapsed, so setting a
        # future deadline here decided nothing and stated the floor in a
        # second place. A mutation run proved it: replacing this expression
        # with the debounce changed no observable behaviour.
        self._due[what] = self.now()

    def tick(self) -> list[str]:
        """One poll. Returns what was published, for tests and for logging."""
        self.stats.polls += 1
        events = self.watcher.poll()
        if events:
            self.stats.events += len(events)
            self.note(events)

        by_name = {p.name: p for p in self.publishers()}
        published = []
        for what in self.due():
            try:
                target = by_name[what]
                # Whether an EVENT asked for this, as opposed to the
                # heartbeat. Read before the pop, because the pop is what
                # destroys the distinction.
                asked_for = what in self._due
                self._due.pop(what, None)
                result = PublishResult.of(target.publish())
                self._last_published[what] = self.now()
                wrote, message = result.wrote, result.message
                if wrote or not asked_for:
                    self._confirming.pop(what, None)
                else:
                    self._rearm_for_confirmation(what, target)
                if wrote:
                    self.stats.count(what)
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


def site_fingerprint(site) -> str:
    """
    What would have to change for a republish to be worth making.

    Deliberately computed from the site's NUMBERS rather than from the grid
    those numbers get rendered into. The grid carries the game's timestamp,
    which moves every time the construction panel is opened even when nothing
    about the build has changed -- and the whole-tab publishers' trick of
    skipping row 1 does not transfer, because this block puts its headers
    in row 1 and its timestamp in row 2.

    That is exactly how this went wrong once: the block's layout gained a
    header row, the positional skip kept skipping row 1, and every publish
    looked new. A fingerprint over the data cannot drift when the
    presentation does, which is the only version of this that stays correct
    without anyone remembering to check it.
    """
    import hashlib

    body = repr((
        site.market_id,
        site.progress,
        bool(site.complete),
        bool(site.failed),
        [(r.symbol, r.required, r.provided, r.payment) for r in site.resources],
    ))
    return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()


def _select_site(sites: dict, places: dict, hint: Optional[str], reader):
    """
    Which build a region is bound to.

    With a hint, match it: a market id, or any name the place has ever had --
    sites are renamed mid-build and a tracker declared under the old name has
    to keep matching, which is the whole reason name history is kept.

    Without one, the site the commander is currently docked at. That suits a
    region used as a general readout, and is wrong for a tracker devoted to
    one settlement -- which is why binding a name is the documented form.
    """
    if hint:
        text = str(hint).strip()
        if text.isdigit() and int(text) in sites:
            return sites[int(text)]
        for market_id, where in places.items():
            if market_id in sites and where.answers_to(text):
                return sites[market_id]
        return None

    here = reader.read_state(scan_files=3)
    if here.market_id and here.market_id in sites:
        return sites[here.market_id]
    return None


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
    # Regions of tabs the tool does not own. Each entry is a
    # (Destination, site-hint) pair; the hint may be None, meaning
    # 'whichever site the commander is at'. Empty by default: the core
    # ships no destination.
    construction_regions: Optional[list] = None,
    construction_scan_files: int = 120,
    # Off by default is wrong here: the whole complaint in #20 is that
    # the daemon quietly covered a subset. On by default, and silently
    # skipped when there are no credentials to use.
    publish_carrier: bool = True,
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

    def publish_market() -> PublishResult:
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
            return PublishResult(
                False, f"  MarketData unchanged ({where}) -- not written")
        rows = exporter.export_grid(grid, sheet_id=sheet_id)
        last["market"] = mark
        located = " + location cells" if totals_ws is not None else ""
        return PublishResult(
            True, f"  MarketData <- {rows} rows ({where}){located}")

    def publish_cargo() -> PublishResult:
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
            return PublishResult(
                False, f"  {ship_tab} unchanged ({held}) -- not written")
        rows = exporter.export_grid(grid, sheet_id=sheet_id, tab_name=ship_tab)
        last["cargo"] = mark
        return PublishResult(True, f"  {ship_tab} <- {rows} rows ({held})")

    def _make_construction_publisher(destination, site_hint, scan_files):
        """One region, bound to one site. Closes over nothing mutable."""
        from .construction import locations_from_events, sites_from_events
        from .export import (CONSTRUCTION_REGION_TABLE_ROW,
                             construction_region_rows)
        from .journal import iter_events
        from .sheets import WriteGuard

        guard = WriteGuard.build({destination.tab: [destination.range_a1()]})
        # A guard per region rather than one shared: a region's authorization
        # is the person naming it, so widening one must not widen another.
        region_exporter = GoogleSheetsExporter(region_guard=guard)
        label = destination.describe()

        def publish() -> PublishResult:
            from .catalog import load_catalog

            all_files = service.reader.journal_files()
            depth = len(all_files) if scan_files == 0 else max(1, scan_files)
            events = []
            for path in all_files[-depth:]:
                events.extend(iter_events(path))
            sites = sites_from_events(events, load_catalog())
            if not sites:
                return PublishResult(
                    False,
                    f"  {label} -- no construction site in the journal")

            places = locations_from_events(events, market_ids=sites.keys())
            chosen = _select_site(sites, places, site_hint, service.reader)
            if chosen is None:
                # Deliberately NOT publishing an empty block here. A site the
                # daemon cannot find is far more likely to be a typo in the
                # binding than a build that vanished, and wiping a tracker on
                # a typo is not a recoverable mistake.
                return PublishResult(
                    False,
                    f"  {label} -- no site matching {site_hint!r}; left alone")

            grid = construction_region_rows(chosen, places.get(chosen.market_id))
            mark = site_fingerprint(chosen)
            if last.get(label) == mark:
                return PublishResult(
                    False, f"  {label} unchanged -- not written")
            region_exporter.export_grid(
                grid, sheet_id=sheet_id, tab_name=destination
            )
            last[label] = mark
            where = places.get(chosen.market_id)
            name = (where.short_station if where else None) or chosen.market_id
            leading = CONSTRUCTION_REGION_TABLE_ROW - 1
            return PublishResult(
                True,
                f"  {label} <- {len(grid) - leading} commodities "
                f"({name})")

        return Publisher(label, CONSTRUCTION_EVENTS, publish)

    regions = [
        _make_construction_publisher(dest, hint, construction_scan_files)
        for dest, hint in (construction_regions or [])
    ]

    def _make_carrier_publisher():
        """
        Keep FreighterData current, or return None and say nothing.

        The only target here that leaves the machine. Everything else reads a
        file the game already wrote; this one needs a Frontier login, so it is
        the one target that can be genuinely unavailable -- and when it is,
        the rest must carry on. ``serve`` works with no credentials at all.

        Access tokens last about four hours and the refresh token about 25
        days, and ``is_authenticated`` spends the refresh token on its own, so
        a session started today keeps working for weeks without anyone
        clicking through a browser.
        """
        from .auth import FrontierAuth
        from .capi import CAPIClient
        from .models import FleetCarrier

        client_id = get_client_id()
        if not client_id:
            return None
        auth = FrontierAuth(client_id)
        try:
            if not auth.is_authenticated:
                return None
        except Exception:
            # A revoked or malformed token must not stop the journal-driven
            # publishers from running.
            return None

        # One client for the daemon's life, with its cooldown set to the floor
        # we actually intend. Built per call, its 15-minute guard restarted
        # from zero every time and so never once applied -- the limit was
        # being skipped by accident rather than lowered on purpose.
        client = CAPIClient(auth, fleet_carrier_cooldown=CARRIER_MIN_INTERVAL)

        def publish() -> PublishResult:
            raw = client.get_fleet_carrier()
            carrier = FleetCarrier.from_capi(raw)
            mark = _fingerprint([["carrier"]] + sorted(
                [c.commodity, c.quantity] for c in carrier.cargo
                if c.quantity > 0))
            if last.get("carrier") == mark:
                return PublishResult(
                    False, "  FreighterData unchanged -- not written")
            exporter.export_cargo(carrier, sheet_id=sheet_id)
            last["carrier"] = mark
            held = sum(c.quantity for c in carrier.cargo if c.quantity > 0)
            return PublishResult(
                True,
                f"  FreighterData <- {held} t on {carrier.identity.callsign}")

        return Publisher("carrier", CARRIER_EVENTS, publish,
                         min_interval=CARRIER_MIN_INTERVAL,
                         max_interval=CARRIER_MAX_INTERVAL,
                         confirm_retries=CARRIER_CONFIRM_RETRIES)

    carrier_publisher = _make_carrier_publisher() if publish_carrier else None

    return Daemon(
        watcher=watcher,
        publish_market=publish_market,
        publish_cargo=publish_cargo,
        regions=regions,
        carrier=carrier_publisher,
        log=log,
        **kwargs,
    )


__all__ = ["Daemon", "ServeStats", "build", "MARKET_EVENTS", "CARGO_EVENTS"]
