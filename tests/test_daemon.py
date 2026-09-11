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

from APITool.daemon import Daemon, ServeStats


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
