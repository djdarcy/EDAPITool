"""
Tests for the publish loop.

These are guards, not anchors: `serve` is new, so there is no prior behaviour to
revert. They fence the three things that would make a background publisher worse
than running the commands by hand -- writing on every event, publishing the wrong
tab, and dying silently partway through a session.

The Daemon takes its clock and its publishers as parameters precisely so this
file never sleeps and never touches a spreadsheet.
"""

import pytest

from APITool.daemon import (CARRIER_EVENTS, Daemon, PublishResult,
                            Publisher, ServeStats)


class FakeWatcher:
    """Yields a scripted batch of events per poll."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.polls = 0

    def poll(self):
        self.polls += 1
        return self.batches.pop(0) if self.batches else []


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def build(batches, **kwargs):
    clock = Clock()
    published = []
    daemon = Daemon(
        watcher=FakeWatcher(batches),
        publish_market=lambda: published.append("market") or "market ok",
        publish_cargo=lambda: published.append("cargo") or "cargo ok",
        debounce=5.0,
        log=lambda msg: None,
        sleep=lambda s: None,
        now=clock,
        **kwargs,
    )
    return daemon, clock, published


def test_a_burst_of_events_produces_one_publish_not_one_per_event():
    """
    The contract: publishing is debounced, so a burst costs one write.

    Measured on a real session, the game emitted 19 `Market` events. Writing
    per event would be 19 Google API calls describing the same station, which
    is both pointless and a quota problem.
    """
    burst = [{"event": "Market"} for _ in range(19)]
    daemon, clock, published = build([burst, [], []])

    daemon.tick()                      # burst arrives, nothing due yet
    assert published == [], "published during the burst instead of waiting"

    clock.advance(2.0)                 # still inside the debounce window
    daemon.tick()
    assert published == []

    clock.advance(4.0)                 # window has now elapsed
    daemon.tick()
    assert published.count("market") == 1, f"expected one publish, got {published}"


def test_a_new_event_extends_the_quiet_period_rather_than_starting_a_second():
    """
    A deadline, not a timer: an event during the window pushes it out.

    Scoped to the market tab deliberately. `Docked` arms BOTH tabs -- docking is
    when you look at the sheet, so column M should be current -- so the cargo
    deadline here runs its own course and is not what this test is about.
    """
    daemon, clock, published = build([[{"event": "Docked"}], [{"event": "Market"}], []])

    daemon.tick()
    clock.advance(4.0)
    daemon.tick()                      # second event re-arms the market deadline
    assert "market" not in published

    clock.advance(4.0)                 # 8s since the first event, 4s since the last
    daemon.tick()
    assert "market" not in published, "published 4s after an event, inside the window"

    clock.advance(2.0)
    daemon.tick()
    assert published.count("market") == 1


def test_cargo_and_market_publish_independently():
    """A cargo change must not force a market write, or vice versa."""
    daemon, clock, published = build([[{"event": "Cargo"}], []])

    daemon.tick()
    clock.advance(6.0)
    daemon.tick()

    assert "cargo" in published
    assert "market" not in published, "a cargo event published the market tab"


def test_one_failed_publish_does_not_end_the_session():
    """
    The loop outlives a transient error.

    A stale sheet is recoverable; a daemon that exited hours ago while the
    commander kept playing is not noticed until the sheet is already wrong.
    """
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient API failure (probe)")
        return "market ok"

    clock = Clock()
    daemon = Daemon(
        watcher=FakeWatcher([[{"event": "Docked"}], [], [{"event": "Docked"}], []]),
        publish_market=flaky,
        publish_cargo=lambda: "cargo ok",
        debounce=5.0,
        log=lambda msg: None,
        sleep=lambda s: None,
        now=clock,
    )

    daemon.tick()
    clock.advance(6.0)
    daemon.tick()                      # first publish raises
    assert daemon.stats.errors == 1
    assert "transient API failure" in (daemon.stats.last_error or "")

    daemon.tick()                      # loop is still alive and still polling
    clock.advance(6.0)
    daemon.tick()
    assert daemon.stats.market_publishes == 1, "did not recover after the error"


def test_an_idle_session_never_writes():
    """No events, no writes. The daemon is not a polling writer."""
    daemon, clock, published = build([[], [], []])

    for _ in range(3):
        clock.advance(30.0)
        daemon.tick()

    assert published == []
    assert daemon.stats.market_publishes == 0
    assert daemon.stats.cargo_publishes == 0


def test_run_stops_after_the_requested_number_of_ticks():
    daemon, clock, published = build([[], [], []])
    stats = daemon.run(stop_after=3)
    assert isinstance(stats, ServeStats)
    assert stats.polls == 3


# --- regions: targets beyond the tabs this tool owns ---------------------
#
# The loop used to hold exactly two publishers as named fields. A third meant
# editing the loop, which is why the daemon could cover two of the three
# generated tabs without anything looking wrong (#20). These pin the list
# shape, and that a region behaves like any other target.

from APITool.daemon import CONSTRUCTION_EVENTS, Publisher  # noqa: E402


def build_with_regions(batches, region_names, **kwargs):
    clock = Clock()
    published = []

    def make(name):
        return Publisher(
            name,
            CONSTRUCTION_EVENTS,
            lambda n=name: published.append(n) or f"{n} ok",
        )

    daemon = Daemon(
        watcher=FakeWatcher(batches),
        publish_market=lambda: published.append("market") or "market ok",
        publish_cargo=lambda: published.append("cargo") or "cargo ok",
        regions=[make(n) for n in region_names],
        debounce=5.0,
        log=lambda msg: None,
        sleep=lambda s: None,
        now=clock,
        **kwargs,
    )
    return daemon, clock, published


def test_a_region_publishes_on_a_construction_event():
    daemon, clock, published = build_with_regions(
        [[{"event": "ColonisationConstructionDepot"}]], ["Tab!R1:AC60"]
    )
    daemon.tick()
    assert published == []            # still inside the debounce
    clock.advance(6)
    daemon.tick()
    assert published == ["Tab!R1:AC60"]


def test_a_market_only_event_does_not_wake_a_region():
    """FSDJump moves you; it says nothing about a build's progress."""
    daemon, clock, published = build_with_regions(
        [[{"event": "FSDJump"}]], ["Tab!R1:AC60"]
    )
    daemon.tick()
    clock.advance(6)
    daemon.tick()
    assert published == ["market"]


def test_docking_wakes_everything_because_it_changes_everything():
    daemon, clock, published = build_with_regions(
        [[{"event": "Docked"}]], ["Tab!R1:AC60"]
    )
    daemon.tick()
    clock.advance(6)
    daemon.tick()
    assert published == ["market", "cargo", "Tab!R1:AC60"]


def test_two_regions_publish_independently():
    daemon, clock, published = build_with_regions(
        [[{"event": "ColonisationConstructionDepot"}]],
        ["A!R1:AC60", "B!R1:AC60"],
    )
    daemon.tick()
    clock.advance(6)
    daemon.tick()
    assert published == ["A!R1:AC60", "B!R1:AC60"]


def test_a_failing_region_does_not_stop_the_others():
    """The rule that already held for the two tabs must hold for regions."""
    clock = Clock()
    published = []
    daemon = Daemon(
        watcher=FakeWatcher([[{"event": "Docked"}]]),
        publish_market=lambda: published.append("market") or "market ok",
        publish_cargo=lambda: published.append("cargo") or "cargo ok",
        regions=[
            Publisher("bad", CONSTRUCTION_EVENTS,
                      lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
            Publisher("good", CONSTRUCTION_EVENTS,
                      lambda: published.append("good") or "good ok"),
        ],
        debounce=5.0, log=lambda m: None, sleep=lambda s: None, now=clock,
    )
    daemon.tick()
    clock.advance(6)
    daemon.tick()
    assert "good" in published
    assert daemon.stats.errors == 1
    assert "boom" in daemon.stats.last_error


def test_describe_targets_names_every_one():
    """#20: a publisher covering a subset must say so, not look complete."""
    daemon, _, _ = build_with_regions([[]], ["Agri!R1:AC60", "Sat!R1:AC60"])
    described = daemon.describe_targets()
    assert "4" in described
    for name in ("market", "cargo", "Agri!R1:AC60", "Sat!R1:AC60"):
        assert name in described


def test_with_no_regions_the_daemon_is_exactly_what_it_was():
    daemon, _, _ = build([[]])
    assert [p.name for p in daemon.publishers()] == ["market", "cargo"]
    assert "Publishing 2" in daemon.describe_targets()


def test_stats_count_regions_by_name_without_disturbing_the_old_counters():
    daemon, clock, _ = build_with_regions(
        [[{"event": "Docked"}]], ["Tab!R1:AC60"]
    )
    daemon.tick()
    clock.advance(6)
    daemon.tick()
    assert daemon.stats.market_publishes == 1
    assert daemon.stats.cargo_publishes == 1
    assert daemon.stats.by_target["Tab!R1:AC60"] == 1


def test_a_publish_clears_its_own_deadline_so_it_does_not_repeat():
    """
    Found by a surviving mutant, not by design.

    Removing the line that clears a target's deadline broke no test, yet it
    would leave every target permanently due: one event, then a publish on
    every poll for the rest of the session. At a 2s interval that is 30
    writes a minute against a 60/minute quota, from a single dock.

    The burst test above ticks once after the debounce and so never looked.
    """
    daemon, clock, published = build_with_regions(
        [[{"event": "Docked"}]], ["Tab!R1:AC60"]
    )
    daemon.tick()
    clock.advance(6)
    daemon.tick()
    assert published == ["market", "cargo", "Tab!R1:AC60"]

    # Nothing new happens. Several more polls must write nothing at all.
    for _ in range(5):
        clock.advance(10)
        assert daemon.tick() == []
    assert published == ["market", "cargo", "Tab!R1:AC60"]
    assert daemon.stats.market_publishes == 1


# --- the fingerprint that decides whether a republish is worth making ----
#
# Found in production, not by design. The construction block's layout gained
# a header row, which moved its timestamp from row 1 to row 2. The generic
# grid fingerprint skips row 1 -- correct for the whole-tab publishers whose
# timestamp lives there -- so it began hashing the timestamp instead of
# skipping it. The game emits a depot event every time the construction panel
# is open, so every one of them looked like a change and republished: five
# writes from six events, against a 60/minute quota.
#
# The fix is to fingerprint the site's NUMBERS rather than the rendered grid,
# because a semantic fingerprint cannot drift when the presentation does.

from dataclasses import dataclass, field  # noqa: E402

from APITool.daemon import site_fingerprint  # noqa: E402


@dataclass
class FakeResource:
    symbol: str
    required: int
    provided: int
    payment: int = 100


@dataclass
class FakeSite:
    market_id: int = 4312376579
    progress: float = 0.6
    complete: bool = False
    failed: bool = False
    timestamp: object = "2026-09-15T02:13:00+00:00"
    resources: list = field(default_factory=lambda: [
        FakeResource("aluminium", 1677, 1148),
        FakeResource("biowaste", 840, 0),
    ])


def test_a_later_reading_of_an_unchanged_site_fingerprints_the_same():
    """The exact regression: the timestamp moves, nothing else does."""
    before = FakeSite(timestamp="2026-09-15T02:13:00+00:00")
    after = FakeSite(timestamp="2026-09-15T02:19:44+00:00")
    assert site_fingerprint(before) == site_fingerprint(after)


def test_a_delivery_changes_the_fingerprint():
    before = FakeSite()
    after = FakeSite(resources=[
        FakeResource("aluminium", 1677, 1677),      # 529 delivered
        FakeResource("biowaste", 840, 0),
    ])
    assert site_fingerprint(before) != site_fingerprint(after)


def test_progress_alone_changes_the_fingerprint():
    assert site_fingerprint(FakeSite(progress=0.6)) != \
        site_fingerprint(FakeSite(progress=0.61))


def test_completion_changes_the_fingerprint():
    assert site_fingerprint(FakeSite(complete=False)) != \
        site_fingerprint(FakeSite(complete=True))


def test_a_different_site_never_collides():
    assert site_fingerprint(FakeSite(market_id=1)) != \
        site_fingerprint(FakeSite(market_id=2))


def test_the_fingerprint_does_not_read_the_rendered_grid():
    """
    Structural: it must take the site, not a grid. A grid-shaped argument is
    how the positional row-skip got in, and how it survived a layout change.
    """
    import inspect

    sig = inspect.signature(site_fingerprint)
    assert list(sig.parameters) == ["site"]
    source = inspect.getsource(site_fingerprint)
    assert "grid" not in source.split('"""')[-1]


# --- a target that costs a network call needs different scheduling -------
#
# Every other publisher reads a local file: free, instant, fire as soon as the
# debounce clears. The carrier is read from Frontier's API, so it carries two
# more numbers -- a floor it will not exceed however many events arrive, and a
# heartbeat that fires with no events at all.
#
# The heartbeat is not belt-and-braces. Another commander filling a buy order
# on your carrier changes its hold and appears NOWHERE in your journal, so an
# event-driven publisher alone would never notice.

from APITool.daemon import CARRIER_EVENTS  # noqa: E402


def build_with_carrier(batches, *, min_interval=60.0, max_interval=900.0):
    clock = Clock()
    published = []
    daemon = Daemon(
        watcher=FakeWatcher(batches),
        publish_market=lambda: published.append("market") or "m",
        publish_cargo=lambda: published.append("cargo") or "c",
        carrier=Publisher("carrier", CARRIER_EVENTS,
                          lambda: published.append("carrier") or "fc",
                          min_interval=min_interval,
                          max_interval=max_interval),
        debounce=5.0, log=lambda m: None, sleep=lambda s: None, now=clock,
    )
    return daemon, clock, published


def test_a_cargo_transfer_wakes_the_carrier():
    daemon, clock, published = build_with_carrier(
        [[{"event": "CargoTransfer"}]])
    daemon.tick()
    clock.advance(6)
    daemon.tick()
    assert "carrier" in published


def test_the_floor_stops_a_burst_of_transfers_becoming_a_burst_of_calls():
    """Shifting a full hold emits dozens of events. One call covers them."""
    daemon, clock, published = build_with_carrier(
        [[{"event": "CargoTransfer"}]] * 6)
    for _ in range(6):
        daemon.tick()
        clock.advance(6)
        daemon.tick()
    assert published.count("carrier") == 1


def test_the_floor_lifts_once_it_has_elapsed():
    daemon, clock, published = build_with_carrier(
        [[{"event": "CargoTransfer"}], [{"event": "CargoTransfer"}]])
    daemon.tick(); clock.advance(6); daemon.tick()
    assert published.count("carrier") == 1
    clock.advance(61)                      # past the floor
    daemon.tick(); clock.advance(6); daemon.tick()
    assert published.count("carrier") == 2


def test_the_heartbeat_fires_with_no_events_at_all():
    """What catches another commander trading against your orders."""
    daemon, clock, published = build_with_carrier([[]])
    daemon.tick()
    published.clear()                      # ignore the first-run publish
    daemon._last_attempted["carrier"] = clock.t
    for _ in range(3):
        clock.advance(300)
        daemon.tick()
    assert published.count("carrier") == 1, "should fire once per 900s"


def test_the_floor_beats_the_heartbeat():
    """A target that just ran is not ready, whatever else is true."""
    daemon, clock, published = build_with_carrier(
        [[{"event": "CargoTransfer"}]], min_interval=600.0, max_interval=60.0)
    daemon.tick(); clock.advance(6); daemon.tick()
    before = published.count("carrier")
    clock.advance(100)                     # heartbeat due, floor is not
    daemon.tick()
    assert published.count("carrier") == before


def test_publishers_without_intervals_are_unaffected():
    daemon, clock, published = build_with_carrier([[{"event": "Docked"}]])
    daemon.tick(); clock.advance(6); daemon.tick()
    assert published.count("market") == 1
    clock.advance(1)
    daemon.note([{"event": "Docked"}])
    clock.advance(6); daemon.tick()
    assert published.count("market") == 2, "market has no floor"


def test_the_carrier_publishes_last():
    """It is the only one that leaves the machine; it must not delay others."""
    daemon, _, _ = build_with_carrier([[]])
    assert [p.name for p in daemon.publishers()][-1] == "carrier"


def test_no_credentials_means_no_carrier_and_a_stated_gap():
    daemon, _, _ = build([[]])
    assert daemon.carrier is None
    assert [p.name for p in daemon.publishers()] == ["market", "cargo"]
    gaps = " ".join(daemon.describe_gaps())
    assert "FreighterData" in gaps and "credentials" in gaps


def test_with_a_carrier_no_gap_is_claimed():
    daemon, _, _ = build_with_carrier([[]])
    assert daemon.describe_gaps() == []


# --- A source that lags the event announcing the change -------------------
#
# Every journal-fed target reads a file the game wrote BEFORE it wrote the
# event, so it cannot lag its own trigger. Frontier's fleet-carrier endpoint
# can and does: measured 2026-09-14, it still reported 840 t of Biowaste on
# the carrier fourteen minutes after the journal recorded that same 840 t
# being moved into the ship. These fence what the loop does about it.


class LaggingSource:
    """Reports 'nothing changed' for the first `lag` calls, then changes."""

    def __init__(self, lag):
        self.lag = lag
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.lag:
            return PublishResult(False, "unchanged -- not written")
        return PublishResult(True, "written")


def carrier_daemon(source, retries=3, batches=None):
    daemon, clock, _ = build(batches if batches is not None else [[]])
    daemon.carrier = Publisher(
        "carrier", CARRIER_EVENTS, source,
        min_interval=60.0, max_interval=900.0, confirm_retries=retries)
    return daemon, clock


def test_an_event_keeps_asking_until_the_source_catches_up():
    """
    The bug this exists for: a CargoTransfer fired, Frontier served its
    pre-transfer copy, the loop read 'unchanged' as 'nothing to do', and
    FreighterData kept the wrong number until the heartbeat.
    """
    source = LaggingSource(lag=2)
    daemon, clock = carrier_daemon(source)

    daemon.note([{"event": "CargoTransfer"}])
    clock.advance(6)                       # debounce clears
    assert "carrier" not in daemon.tick(), (
        "counted a publish that wrote nothing")
    assert source.calls == 1

    clock.advance(61)                      # the floor, not the heartbeat
    assert "carrier" not in daemon.tick()
    assert source.calls == 2, "gave up after the first stale read"

    clock.advance(61)
    assert "carrier" in daemon.tick(), (
        "never wrote once the source caught up")
    assert source.calls == 3


class RefreshingSource:
    """
    Writes every time, but only CHANGES after `lag` calls.

    The shape the carrier publisher takes once it refreshes `Last checked` on
    every successful check: the write happens, the data did not move. A loop
    that cannot tell those apart either gives up on a lagging source or spins
    on a settled one.
    """

    def __init__(self, lag):
        self.lag = lag
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.lag:
            return PublishResult(True, "stamp refreshed", changed=False)
        return PublishResult(True, "written", changed=True)


def test_a_write_that_changed_nothing_still_counts_as_not_confirmed():
    """
    The reason `wrote` had to stop being the loop's confirmation signal.

    `Last checked` means "when the tool last asked", so it has to be refreshed
    even when the answer was identical -- which makes the publisher write on
    every check. But the retry exists to keep asking until FRONTIER catches
    up, and under the old reading ("we wrote, therefore we are done") the very
    first stamp refresh would have retired the retry and left the tab wrong
    for up to half an hour: exactly the 840 t bug the retry was built for,
    reintroduced by the fix for #19.
    """
    source = RefreshingSource(lag=2)
    daemon, clock = carrier_daemon(source)

    daemon.note([{"event": "CargoTransfer"}])
    clock.advance(6)
    assert "carrier" not in daemon.tick(), (
        "a stamp refresh was counted as a real publish")
    assert source.calls == 1

    clock.advance(61)
    assert "carrier" not in daemon.tick()
    assert source.calls == 2, "stopped asking because the write succeeded"

    clock.advance(61)
    assert "carrier" in daemon.tick(), "never wrote once the source caught up"
    assert source.calls == 3


class AlwaysFails:
    """A publisher whose source is refusing -- a cooldown, a network blip."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise RuntimeError("Fleet carrier query cooldown. Wait 59 seconds.")


def test_a_failing_publish_still_arms_the_floor():
    """
    A target that RAISES must wait its own floor before being asked again.

    Observed in a real session, with the game closed: `serve` printed

        ! carrier publish failed: Fleet carrier query cooldown. Wait 59 seconds.
        ! carrier publish failed: Fleet carrier query cooldown. Wait 57 seconds.
        ... thirty times, counting down to 1 ...

    -- one line per poll for a solid minute. The cause is that
    the record (then named `_last_published`) was assigned AFTER the publish
    call, so an exception skipped it; `due` then saw no record, the heartbeat
    branch fired, and the target was due again two seconds later. The field is
    now `_last_attempted` and is written in a `finally`, which is the fix and
    also the honest name.

    Not harmful in that instance, because the cooldown is checked locally
    before any request leaves the machine. But the rule is general: ANY
    transient failure made a target retry at the POLL interval instead of its
    own, which is the difference between one attempt a minute and thirty.

    Thirty ticks of two seconds is exactly the window that produced the real
    output, so this measures the reported symptom rather than a model of it.
    """
    source = AlwaysFails()
    daemon, clock = carrier_daemon(source)

    for _ in range(30):
        daemon.tick()
        clock.advance(2)

    assert source.calls == 1, (
        f"asked a failing source {source.calls} times in 60s; the 60s floor "
        f"should have allowed exactly one"
    )


def test_the_startup_catch_up_arms_each_target_s_floor():
    """
    The catch-up publishes, so the loop must not then think nothing has run.

    This is the other half of the same real symptom. The CLI used to run the
    catch-up itself -- `for target in worker.publishers(): target.publish()` --
    which published successfully and recorded nothing. The daemon's first poll
    then found no record for any target, the heartbeat branch fired, and the
    carrier was asked again immediately, hitting the cooldown its OWN catch-up
    had just started.

    Consolidating it onto the Daemon is what fixes it, and this asserts the
    property that made consolidation worth doing rather than the fact that a
    method moved.
    """
    source = AlwaysFails()
    daemon, clock = carrier_daemon(source)

    daemon.catch_up()
    assert source.calls == 1

    # Immediately after: the floor has not elapsed, so nothing is due.
    daemon.tick()
    assert source.calls == 1, (
        "the catch-up published but left no record, so the first poll asked "
        "again straight away")

    # The floor elapsing does NOT make it due -- it only stops blocking. With
    # no events, the next ask is the heartbeat, and that distinction is the
    # whole bug: while there was no record, `due`'s heartbeat branch read
    # `last is None` as "overdue" and fired on every single poll.
    clock.advance(61)
    daemon.tick()
    assert source.calls == 1, "the floor elapsing should not itself make it due"

    clock.advance(900)
    daemon.tick()
    assert source.calls == 2, "the heartbeat never came round"


def test_a_catch_up_failure_is_counted_and_does_not_stop_the_others():
    """A target that cannot publish at startup must not take the rest down."""
    failing = AlwaysFails()
    daemon, clock = carrier_daemon(failing)

    daemon.catch_up()

    assert failing.calls == 1
    assert daemon.stats.errors == 1
    assert "cooldown" in (daemon.stats.last_error or "")


def test_a_publisher_that_says_nothing_about_change_is_read_by_its_write():
    """
    Backward compatibility, asserted rather than assumed.

    Every other target reads a local file written before the event that
    announces it, so its source cannot lag its own trigger and `changed` is
    meaningless there. Those publishers -- and every test double in this file
    -- return two-field results, which must keep meaning what they meant.
    """
    assert PublishResult(True, "x").source_changed is True
    assert PublishResult(False, "x").source_changed is False
    assert PublishResult.of("a bare string").source_changed is True


def test_it_retries_at_the_floor_not_the_heartbeat():
    """60s, not 900s. Waiting a quarter hour to re-ask is the failure itself."""
    source = LaggingSource(lag=5)
    daemon, clock = carrier_daemon(source)

    daemon.note([{"event": "CargoTransfer"}])
    clock.advance(6)
    daemon.tick()

    clock.advance(59)
    daemon.tick()
    assert source.calls == 1, "asked again inside the 60s floor"

    clock.advance(2)
    daemon.tick()
    assert source.calls == 2


def test_retries_are_capped_so_a_change_that_never_lands_cannot_spin():
    """A transfer the commander undid must not leave the loop asking forever."""
    source = LaggingSource(lag=99)
    daemon, clock = carrier_daemon(source, retries=3)

    daemon.note([{"event": "CargoTransfer"}])
    clock.advance(6)
    daemon.tick()
    for _ in range(10):
        clock.advance(61)
        daemon.tick()

    assert source.calls == 4, (
        f"expected 1 attempt + 3 retries, got {source.calls}")


def test_a_heartbeat_that_finds_nothing_new_does_not_re_arm():
    """
    Only an EVENT means something is known to have changed. Re-arming on a
    quiet heartbeat would turn an idle carrier into a call every minute.
    """
    source = LaggingSource(lag=99)
    daemon, clock = carrier_daemon(source)

    clock.advance(1000)                    # heartbeat overdue, no events
    daemon.tick()
    assert source.calls == 1

    clock.advance(61)
    daemon.tick()
    assert source.calls == 1, "re-asked at the floor after a quiet heartbeat"


def test_a_publish_that_wrote_nothing_is_not_counted_as_a_publish():
    """The summary line says what was written, not what was attempted."""
    source = LaggingSource(lag=1)
    daemon, clock = carrier_daemon(source)

    daemon.note([{"event": "CargoTransfer"}])
    clock.advance(6)
    daemon.tick()
    assert daemon.stats.by_target.get("carrier", 0) == 0

    clock.advance(61)
    daemon.tick()
    assert daemon.stats.by_target["carrier"] == 1


def test_a_publisher_that_does_not_confirm_is_never_asked_whether_it_wrote():
    """
    The journal-fed publishers return a bare message. They must keep working
    unchanged -- their source cannot lag, so there is nothing to confirm.
    """
    daemon, clock, published = build([[{"event": "Docked"}]])
    daemon.tick()
    clock.advance(6)
    daemon.tick()
    assert "market" in published
    assert daemon.stats.by_target["market"] == 1
