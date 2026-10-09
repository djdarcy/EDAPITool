"""
The store's query seam (the store design of 2026-10-09, unit 1).

Core offers one supplier, ``history``, on every pipeline. A step that
declares ``needs = ("history",)`` receives a ``History``; the refresh
memoises it, so two steps share one open store; a step that does not pull
it leaves the store unopened; and a fresh install -- no store file at all
-- answers empty rather than creating one. A plugin that offers a supplier
named ``history`` is refused by the merge, as any name offered twice is.
"""

import json
import types

import pytest

from test_service import ROWS, FakeWorksheet, docked_event, make_journal, ryman_market_json, totals_grid

from APITool import pipeline
from APITool.catalog import load_catalog
from APITool.loader import build_enforcer
from APITool.plugins import jsonl
from APITool.service import MarketRefreshService, StepSpec
from APITool.store import archive, open_store, store_path
from APITool.store import history as history_mod
from APITool.store.history import History, Observation


def _planted(name, needs=(), seen=None, supplies=None):
    """A step module that records the context it ran with."""
    seen = {} if seen is None else seen

    def process(data, ctx):
        for need in needs:
            seen[need] = ctx.get(need)
        seen["ctx"] = ctx
        return data

    module = types.SimpleNamespace(process=process, needs=tuple(needs), seen=seen)
    if supplies is not None:
        module.supplies = supplies
    return module


def _spec(name, module, tmp_path) -> StepSpec:
    layout = jsonl.layout(path=str(tmp_path / f"{name}.jsonl"))
    return StepSpec(name, module, layout, build_enforcer("jsonl", layout.writes()))


def _count_opens(monkeypatch):
    opens = []
    real = History.open.__func__

    def counting(cls):
        opens.append(1)
        return real(cls)

    monkeypatch.setattr(History, "open", classmethod(counting))
    return opens


# -- the supplier on the kind runner -----------------------------------------

def test_a_step_that_needs_history_receives_one_through_run_specs(tmp_path):
    step = _planted("a", needs=("history",))
    data, reported = pipeline.run_specs([_spec("a", step, tmp_path)], {"kind": "cargo"})

    assert data == {"kind": "cargo"}
    assert isinstance(step.seen["history"], History)
    assert step.seen["ctx"].calls["history"] == 1


def test_two_steps_needing_history_share_one_open_store(tmp_path, monkeypatch):
    opens = _count_opens(monkeypatch)
    first = _planted("a", needs=("history",))
    second = _planted("b", needs=("history",))

    pipeline.run_specs([_spec("a", first, tmp_path), _spec("b", second, tmp_path)], {})

    assert first.seen["history"] is second.seen["history"]
    assert len(opens) == 1, "the refresh memoises the supplier: one open for the run"


def test_a_step_that_does_not_pull_history_leaves_the_store_unopened(tmp_path, monkeypatch):
    opens = _count_opens(monkeypatch)
    step = _planted("a")

    pipeline.run_specs([_spec("a", step, tmp_path)], {})

    assert opens == [], "lazy: nothing pulled, nothing opened"
    assert not store_path().exists(), "and nothing created"


# -- the supplier on the market service ---------------------------------------

def _service(tmp_path, specs) -> MarketRefreshService:
    journal = make_journal(tmp_path, [docked_event()], ryman_market_json())
    return MarketRefreshService(journal_dir=journal, catalog=load_catalog(),
                                layout=specs[0].layout, guard=specs[0].guard,
                                target=specs[0].target, steps=specs)


def test_the_market_service_offers_history_beside_its_own_suppliers(tmp_path):
    step = _planted("market-log", needs=("history", "location"))
    service = _service(tmp_path, [_spec("market-log", step, tmp_path)])

    assert "history" in service.suppliers
    assert service.suppliers.offered_by["history"] == "core"

    result = service.refresh(worksheet=FakeWorksheet(totals_grid(ROWS)), write=False)

    assert result.ok
    assert isinstance(step.seen["history"], History)


def test_a_plugin_offering_history_is_refused_by_name(tmp_path):
    step = _planted("market-log", supplies=lambda: {"history": lambda ctx: "mine"})

    with pytest.raises(ValueError, match="history"):
        _service(tmp_path, [_spec("market-log", step, tmp_path)])


# -- what History answers ---------------------------------------------------------

def test_a_fresh_install_answers_empty_and_creates_nothing():
    assert not store_path().exists()
    h = History.open()

    assert h.available is False
    assert h.latest("market_json") is None
    assert h.observations("market_json") == []
    assert h.markets(128666762) == []
    assert h.construction(3957057282) == []
    assert not store_path().exists()


def _kept(kind, payload: bytes, subject=None, observed_at=None, locator="x"):
    obs_id = archive(kind, payload, locator=locator, subject=subject, observed_at=observed_at)
    assert obs_id is not None
    return obs_id


def test_history_answers_the_kept_reads_newest_first():
    conn = open_store(store_path())
    conn.close()
    older = _kept("colonisationconstructiondepot", b'{"MarketID": 1}', subject="1",
                  observed_at="2026-10-01T00:00:00Z", locator="j1")
    newer = _kept("colonisationconstructiondepot", b'{"MarketID": 1, "n": 2}', subject="1",
                  observed_at="2026-10-02T00:00:00Z", locator="j2")
    other = _kept("colonisationconstructiondepot", b'{"MarketID": 2}', subject="2",
                  observed_at="2026-10-03T00:00:00Z", locator="j3")

    h = History.open()
    try:
        assert h.available
        found = h.construction(1)
        assert [o.obs_id for o in found] == [newer, older]
        assert isinstance(found[0], Observation)
        assert found[0].payload == b'{"MarketID": 1, "n": 2}'
        assert h.latest("colonisationconstructiondepot", "1").obs_id == newer
        assert h.latest("colonisationconstructiondepot").obs_id == other
        assert [o.obs_id for o in h.observations("colonisationconstructiondepot",
                                                 since="2026-10-01T12:00:00Z")] == [other, newer]
        assert len(h.observations("colonisationconstructiondepot")) == 3
        assert h.observations("colonisationconstructiondepot", limit=1)[0].subject == "2"
    finally:
        h.close()


def test_history_answers_a_station_s_market_snapshots():
    payload = json.dumps(ryman_market_json()).encode("utf-8")
    obs_id = _kept("market_json", payload, observed_at="2026-10-02T00:00:00Z", locator="Market.json")
    # archive() projects a market read as it keeps it; read the snapshot's key back.
    conn = open_store(store_path())
    try:
        market_id = conn.execute("SELECT market_id FROM market_snapshot WHERE obs_id = ?",
                                 (obs_id,)).fetchone()[0]
    finally:
        conn.close()

    h = History.open()
    try:
        snaps = h.markets(market_id)
        assert len(snaps) == 1
        assert snaps[0]["obs_id"] == obs_id
        assert snaps[0]["items_count"] > 0
        assert h.markets(market_id + 1) == []
    finally:
        h.close()


def test_the_supplier_is_a_history_and_offered_under_its_name():
    assert history_mod.offered() == {"history": history_mod.supply}
    assert isinstance(history_mod.supply(None), History)
