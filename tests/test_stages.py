"""
Built-in stages (slice 2 of the pipeline redesign, unit 2): what `serve` keeps
current is a list of stage tokens, not a hand-written list of publishers, and
one stage can be run once by name -- the call the `pipeline` verb makes.
Smokes, with doubles for every publish; nothing is read or written.
"""

import pytest

from APITool import steps
from APITool.daemon import SERVE_ORDER, Daemon, Publisher, PublishResult


class FakeWatcher:
    def poll(self):
        return []


def _daemon(**kwargs):
    calls = []
    daemon = Daemon(
        watcher=FakeWatcher(),
        publish_market=lambda: calls.append("market") or "market ok",
        publish_cargo=lambda: calls.append("cargo") or "cargo ok",
        log=lambda msg: None,
        sleep=lambda s: None,
        **kwargs,
    )
    return daemon, calls


def test_serve_order_names_exactly_the_built_in_step_tokens():
    assert set(SERVE_ORDER) == set(steps.BUILTINS)


def test_the_default_order_is_todays():
    region = Publisher("Hauling!H1:N200", frozenset(), lambda: "region ok")
    carrier = Publisher("carrier", frozenset(), lambda: "carrier ok")
    daemon, _ = _daemon(regions=[region], carrier=carrier)
    assert [p.name for p in daemon.publishers()] == ["market", "cargo", "Hauling!H1:N200", "carrier"]


def test_an_order_reorders_the_stages():
    daemon, _ = _daemon(order=("cargo", "market"))
    assert [p.name for p in daemon.publishers()] == ["cargo", "market"]


def test_an_unknown_stage_is_refused_at_construction():
    with pytest.raises(ValueError, match="unknown stage.*'weather'.*market, cargo, regions, carrier"):
        _daemon(order=("market", "weather"))


def test_one_stage_runs_once_by_name():
    daemon, calls = _daemon()
    results = daemon.run_stage("cargo")
    assert calls == ["cargo"]
    assert [type(r) for r in results] == [PublishResult]


def test_a_stage_with_nothing_to_run_runs_nothing():
    daemon, calls = _daemon()
    assert daemon.run_stage("carrier") == [] and daemon.run_stage("regions") == []
    assert calls == []
