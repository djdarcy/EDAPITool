"""
Round-1 collab probes for the step contract and the pipeline MVP (U53).

Run explicitly (the name keeps it out of the suite):

    python -m pytest tests/one-offs/thinking/pipeline-mvp/probe_rnd1_step_contract.py -p no:cacheprovider -q -s

Every sheet is an in-memory fake, every file is under tmp_path, nothing
reaches Google or Frontier. `_finish` is monkeypatched on the service class
for the duration of one test only; production code is not edited.

H1  The DWP's literal contract, `process(data, ctx) -> data`, loses the
    MarkerPlan: the CLI prints the dry-run block from `result.plan`, and the
    golden IS that block. Arm A (data only) predicted to differ from the
    golden; arm B (data + status) predicted byte-identical.
H2  `Refresh.env` is ONE target's context (layout, guard, worksheet). A
    second step from another target, handed "the same ctx", gets the wrong
    layout and the wrong guard: jsonl silently no-ops on totals' layout and
    TypeErrors on totals' guard; totals AttributeErrors on jsonl's layout.
H3  The loader collapses two targets naming one plugin into one Loaded
    (`targets_by_plugin` keeps the first), so target names in `pipelines`
    cannot resolve to distinct steps without a loader change.
H4  Today's order is not "enabled targets in enablement order": exactly one
    plugin, `publisher()` (the first with a layout), reaches the service.
H5  Memoisation survives lazy `ctx.get` inside steps (calls stays 1) -- but
    the pre-run `needs` check is lost: an unknown supplier now fails AFTER
    a step's earlier side effect rather than before the step runs.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parents[3] / "goldens" / "v0.8.1__market--update-sheet--dry-run__fixture.txt"
_AGE = re.compile(r"\b\d[\d,]* min old\b")


def _settled(text: str) -> str:
    return _AGE.sub("<age> min old", text)


# ---------------------------------------------------------------------------
# H1: the plan has to travel somewhere the contract names
# ---------------------------------------------------------------------------


def _pipeline_finish(steps, collect_status):
    """A `_finish` that runs a list of steps instead of `ctx.run(self.subscriptions)`."""
    from APITool.sheets.writer import MarkerPlan

    def _finish(self, result, ctx):
        # service.py:358-367, verbatim in effect
        if result.snapshot is None and ctx.has("requirements"):
            result.snapshot = ctx.get("requirements")
        checked_at = ""
        if result.market is not None and result.market.timestamp is not None:
            checked_at = result.market.timestamp.strftime("%Y-%m-%d %H:%M UTC")
        elif result.ok:
            checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        ctx.env["result"] = result
        ctx.env["checked_at"] = checked_at

        data = result
        statuses = {}
        for name, step in steps:
            out = step(data, ctx)
            if collect_status:
                data, statuses[name] = out
            else:
                data = out
            if data is None:
                raise ValueError(f"step {name!r} returned None")
        for status in statuses.values():
            if isinstance(status, MarkerPlan):
                data.plan = status
                break
        if data.plan is not None and ctx.options["write"]:
            data.written = True
        return data

    return _finish


def _run_golden_cli(tmp_path, monkeypatch, capsys):
    from test_marker_skip_occupied import RangeAwareWorksheet, _cli, _planted_grid

    sheet = RangeAwareWorksheet(_planted_grid())
    code = _cli(tmp_path, monkeypatch, sheet, "--dry-run", "--write-location")
    out = capsys.readouterr().out
    assert code == 0
    assert sheet.batches == []
    return _settled(out)


def test_h1_arm_a_data_only_contract_loses_the_plan(tmp_path, monkeypatch, capsys, configured_totals):
    from APITool import service as service_mod
    from APITool.plugins import totals

    def totals_step(data, ctx):
        totals._publish_markers(ctx)      # builds the plan, returns it -- and the runner drops it
        return data

    monkeypatch.setattr(service_mod.MarketRefreshService, "_finish",
                        _pipeline_finish([("totals-workbook", totals_step)], collect_status=False))
    out = _run_golden_cli(tmp_path, monkeypatch, capsys)
    expected = GOLDEN.read_text(encoding="utf-8")
    print("\n[H1-A] identical to golden:", out == expected)
    print("[H1-A] 'DRY RUN' in output:", "DRY RUN" in out)
    assert out != expected, "prediction was: the dry-run block is missing"
    assert "DRY RUN" not in out


def test_h1_arm_b_data_plus_status_reproduces_the_golden(tmp_path, monkeypatch, capsys, configured_totals):
    from APITool import service as service_mod
    from APITool.plugins import totals

    def totals_step(data, ctx):
        return data, totals._publish_markers(ctx)

    monkeypatch.setattr(service_mod.MarketRefreshService, "_finish",
                        _pipeline_finish([("totals-workbook", totals_step)], collect_status=True))
    out = _run_golden_cli(tmp_path, monkeypatch, capsys)
    expected = GOLDEN.read_text(encoding="utf-8")
    print("\n[H1-B] identical to golden:", out == expected)
    assert out == expected


def test_h1_arm_c_two_steps_second_sees_first_output_and_golden_holds(tmp_path, monkeypatch, capsys, configured_totals):
    """A second, data-changing step after totals: the golden must not move, and data must flow."""
    from APITool import service as service_mod
    from APITool.plugins import totals

    seen = {}

    def totals_step(data, ctx):
        return data, totals._publish_markers(ctx)

    def tag_step(data, ctx):
        seen["matches"] = len(data.matches)
        seen["plan_visible_to_second_step"] = data.plan is not None   # NOT yet: plan is set after the list
        return data, "tagged"

    monkeypatch.setattr(service_mod.MarketRefreshService, "_finish",
                        _pipeline_finish([("totals-workbook", totals_step), ("tag", tag_step)], collect_status=True))
    out = _run_golden_cli(tmp_path, monkeypatch, capsys)
    print("\n[H1-C] identical to golden:", out == GOLDEN.read_text(encoding="utf-8"), "| second step saw:", seen)
    assert seen["matches"] == 5
    assert seen["plan_visible_to_second_step"] is False


# ---------------------------------------------------------------------------
# H2: the context is one target's
# ---------------------------------------------------------------------------


def _market_result():
    from test_service import RYMAN
    from APITool.journal import LocationState
    from APITool.service import RefreshResult

    loc = LocationState()
    loc.system, loc.station, loc.market_id, loc.docked = "Lhou Mans", "Ryman Enterprise", RYMAN, True
    return RefreshResult(location=loc)


def test_h2_jsonl_step_on_totals_context_silently_writes_nothing(tmp_path):
    from test_service import FakeWorksheet, ROWS, totals_grid
    from APITool.loader import GSHEET, build_enforcer
    from APITool.plugins import jsonl
    from APITool.plugins.totals.layout import SheetLayout
    from APITool.registry import Refresh

    layout = SheetLayout()
    ctx = Refresh({}, worksheet=FakeWorksheet(totals_grid(ROWS)), layout=layout,
                  guard=build_enforcer(GSHEET, layout.writes()), ledger=None,
                  options={"write": True}, target="totals-workbook",
                  result=_market_result(), checked_at="2026-09-27 00:00 UTC")
    status = jsonl._append_record(ctx)
    print("\n[H2-a] jsonl on totals' ctx ->", repr(status))
    assert status == "no path configured: nothing written"


def test_h2_jsonl_step_with_a_path_but_totals_guard_typeerrors(tmp_path):
    from APITool.loader import GSHEET, build_enforcer
    from APITool.plugins import jsonl
    from APITool.plugins.totals.layout import SheetLayout
    from APITool.registry import Refresh

    path = str(tmp_path / "market.jsonl")
    ctx = Refresh({}, worksheet=None, layout=jsonl.layout(path=path),
                  guard=build_enforcer(GSHEET, SheetLayout().writes()),   # the WRONG kind's guard
                  ledger=None, options={"write": True}, target="jsonl-file",
                  result=_market_result(), checked_at="")
    with pytest.raises(TypeError) as exc:
        jsonl._append_record(ctx)
    print("\n[H2-b] jsonl with totals' guard ->", exc.value)
    assert not (tmp_path / "market.jsonl").exists()


def test_h2_totals_step_on_jsonl_context_attributeerrors(tmp_path):
    from test_service import FakeWorksheet, ROWS, totals_grid
    from APITool.loader import JSONL, build_enforcer
    from APITool.plugins import jsonl, totals
    from APITool.registry import Refresh

    path = str(tmp_path / "market.jsonl")
    layout = jsonl.layout(path=path)
    ctx = Refresh({"requirements": lambda c: None}, worksheet=FakeWorksheet(totals_grid(ROWS)),
                  layout=layout, guard=build_enforcer(JSONL, layout.writes()), ledger=None,
                  options={"write": False}, target="jsonl-file", renderer=None,
                  result=_market_result(), checked_at="")
    with pytest.raises(AttributeError) as exc:
        totals._publish_markers(ctx)
    print("\n[H2-c] totals on jsonl's ctx ->", exc.value)


# ---------------------------------------------------------------------------
# H3 / H4: what the loader hands the service today
# ---------------------------------------------------------------------------


def _load(targets_json):
    from APITool.loader import (SHIPPED_DIR, enabled_from, kinds_from, load, scan,
                                targets_by_plugin)
    from APITool.settings import Target

    targets = {name: Target(name, e["kind"], e["plugin"], dict(e.get("config", {})),
                            {k: v for k, v in e.items() if k not in ("kind", "plugin", "config")})
               for name, e in targets_json.items()}
    found = scan(SHIPPED_DIR, None)
    return load(found, enabled_from(targets, found), kinds_from(targets), targets=targets_by_plugin(targets))


def test_h3_two_targets_of_one_plugin_collapse_to_one_loaded(tmp_path):
    result = _load({
        "totals-a": {"kind": "gsheet", "plugin": "totals", "id": "FAKE", "config": {"totals_tab": "A"}},
        "totals-b": {"kind": "gsheet", "plugin": "totals", "id": "FAKE", "config": {"totals_tab": "B"}},
    })
    names = [(e.name, e.target.name if e.target else None) for e in result.loaded]
    print("\n[H3] loaded (plugin, target):", names)
    assert names == [("totals", "totals-a")]


def test_h4_only_the_first_plugin_with_a_layout_reaches_the_service(tmp_path):
    path = str(tmp_path / "m.jsonl")
    first_jsonl = _load({
        "jsonl-file": {"kind": "jsonl", "plugin": "jsonl", "path": path},
        "totals-workbook": {"kind": "gsheet", "plugin": "totals", "id": "FAKE"},
    })
    first_totals = _load({
        "totals-workbook": {"kind": "gsheet", "plugin": "totals", "id": "FAKE"},
        "jsonl-file": {"kind": "jsonl", "plugin": "jsonl", "path": path},
    })
    print("\n[H4] enablement [jsonl, totals] -> publisher:", first_jsonl.publisher().name,
          "| loaded:", [e.name for e in first_jsonl.loaded])
    print("[H4] enablement [totals, jsonl] -> publisher:", first_totals.publisher().name,
          "| loaded:", [e.name for e in first_totals.loaded])
    assert first_jsonl.publisher().name == "jsonl"
    assert first_totals.publisher().name == "totals"

    # And the service takes exactly one of them: its subscriptions are that one's.
    from APITool.plugins.totals.layout import SheetLayout
    from APITool.service import MarketRefreshService
    from APITool.loader import GSHEET, build_enforcer

    svc = MarketRefreshService(layout=SheetLayout(), journal_dir=tmp_path,
                               guard=build_enforcer(GSHEET, {}), plugin=first_jsonl.publisher().module)
    print("[H4] service subscriptions with jsonl as publisher:", [s.name for s in svc.subscriptions],
          "| suppliers:", sorted(svc.suppliers))
    assert [s.name for s in svc.subscriptions] == ["record"]


# ---------------------------------------------------------------------------
# H5: memoisation under lazy pulls, and what the pre-run check bought
# ---------------------------------------------------------------------------


def test_h5_two_steps_pull_once_but_an_unknown_need_now_fails_after_a_side_effect():
    from APITool.registry import Refresh, Subscription

    pulls = []
    ctx = Refresh({"requirements": lambda c: pulls.append(1) or [("Biowaste", 229)]})
    wrote = []

    def step_one(data, ctx):
        wrote.append("one wrote")            # a side effect BEFORE its ask
        return data + [len(ctx.get("requirements"))]

    def step_two(data, ctx):
        return data + [len(ctx.get("requirements"))]

    data = []
    for step in (step_one, step_two):
        data = step(data, ctx)
    print("\n[H5] calls:", ctx.calls, "| data:", data)
    assert ctx.calls == {"requirements": 1} and data == [1, 1]

    # Subscription form: the unknown need is refused BEFORE publish runs.
    wrote.clear()
    with pytest.raises(KeyError):
        Refresh({}).run([Subscription("x", ("nothere",), lambda c: wrote.append("published"))])
    print("[H5] subscription with unknown need, side effects:", wrote)
    assert wrote == []

    # process form: the same mistake is found only AFTER the step's earlier effect.
    wrote.clear()

    def bad_step(data, ctx):
        wrote.append("wrote first")
        return ctx.get("nothere")

    with pytest.raises(KeyError):
        bad_step([], Refresh({}))
    print("[H5] process step with unknown need, side effects:", wrote)
    assert wrote == ["wrote first"]
