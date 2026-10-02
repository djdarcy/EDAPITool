"""
Smokes for the pipeline runner and the bound view (slice 1, unit 1).

Scenarios S1-S5 of the unit's test-scenarios pass; the goldens cover the
market refresh end to end, so these are the few things the goldens cannot
see: order, a refused None, a refused need, and whose view a supplier runs in.
"""

import pytest

from APITool import pipeline
from APITool.pipeline import Step
from APITool.registry import Refresh, merge_suppliers


def test_data_flows_from_step_to_step_and_statuses_are_reported():
    ctx = Refresh({})
    steps = [
        Step("a", lambda data, c: (c.report("a ran"), data + ["a"])[1], ctx),
        Step("b", lambda data, c: (c.report("b ran"), data + ["b"])[1], ctx),
    ]
    assert pipeline.run(steps, []) == ["a", "b"]
    assert ctx.reported == ["a ran", "b ran"]


def test_a_step_returning_none_is_refused_by_name():
    ctx = Refresh({})
    steps = [Step("market-log", lambda data, c: None, ctx)]
    with pytest.raises(ValueError, match="'market-log' returned None"):
        pipeline.run(steps, {})


def test_an_unknown_need_is_refused_before_any_step_acts():
    ctx = Refresh({"location": lambda c: "here"})
    acted = []
    steps = [
        Step("a", lambda data, c: acted.append("a") or data, ctx, needs=("location",)),
        Step("b", lambda data, c: acted.append("b") or data, ctx, needs=("nothere",)),
    ]
    with pytest.raises(KeyError, match="nothere"):
        pipeline.run(steps, {})
    assert acted == []


def test_a_supplier_runs_in_its_offerers_view_and_is_pulled_once():
    """S1/S5: `totals` requirements read `totals`' worksheet whoever asks."""
    seen = []
    table = merge_suppliers([
        ("totals-workbook", {"requirements": lambda c: seen.append(c.worksheet) or "reqs"}),
    ])
    ctx = Refresh(table, worksheet="parent-ws")
    totals = ctx.bind("totals-workbook", worksheet="totals-ws")
    other = ctx.bind("market-log", worksheet=None)

    steps = [
        Step("market-log", lambda data, c: c.get("requirements") and data, other, needs=("requirements",)),
        Step("totals-workbook", lambda data, c: c.get("requirements") and data, totals, needs=("requirements",)),
    ]
    assert pipeline.run(steps, {"x": 1}) == {"x": 1}
    assert seen == ["totals-ws"]
    assert ctx.calls["requirements"] == 1


def test_a_bound_view_reads_the_parents_env_as_it_is_now():
    """S2: the service sets `result` after the views exist; every view sees it."""
    ctx = Refresh({}, result=None, worksheet="parent-ws")
    view = ctx.bind("t", worksheet="own-ws")
    ctx.env["result"] = "the result"
    assert view.result == "the result"
    assert view.worksheet == "own-ws"
    assert ctx.worksheet == "parent-ws"
    with pytest.raises(AttributeError):
        view.nothere
