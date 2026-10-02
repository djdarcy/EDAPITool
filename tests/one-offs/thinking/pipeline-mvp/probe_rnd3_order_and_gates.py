"""
Round-3 collab probes: can unit 3 land before unit 2, and what gates a run today.

    python -m pytest tests/one-offs/thinking/pipeline-mvp/probe_rnd3_order_and_gates.py -p no:cacheprovider -q -s

Fakes only: the suite's isolated ED_CONFIG_DIR, ED_PLUGIN_DIR at a directory
that does not exist, the fixture journal in tmp_path, files under tmp_path,
in-memory sheets. `_finish` is monkeypatched on the class inside one test.
No production file is edited.

P5  Unit 3 without unit 2, on the jsonl path: a jsonl-only config, no
    `pipelines` key anywhere, `_finish` replaced by the bound runner with
    `ctx.report`, driven through the real `market` command. Predicted: the
    file is written, exactly as test_jsonl_plugin.py:176-209 pins today.
    (P2 in round 2 is the same claim for the totals golden.)
P6  The composition root's selection: with `[jsonl, totals]` enabled, the
    layout, guard and worksheet the service is built with are the
    PUBLISHER's (jsonl's), so an explicit `pipelines: {"market":
    ["totals-workbook"]}` would bind the totals step to jsonl's layout unless
    `_resolve_destination` is changed to select by the pipeline. Measured on
    what `_plugin_layout(publisher)` returns for that config.
P7  A `check_config` complaint does NOT gate `market` today: a jsonl target
    whose block names a field the plugin does not publish is loaded with a
    complaint, and `market --update-sheet` still runs and writes. So a gate
    on "any problem" would be a behaviour change; a gate on pipeline
    problems only would not.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _write_config(monkeypatch, tmp_path, targets: dict) -> None:
    from APITool import settings

    settings.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.CONFIG_FILE.write_text(json.dumps({"targets": targets}), encoding="utf-8")
    monkeypatch.setenv("ED_PLUGIN_DIR", str(tmp_path / "no-user-plugins"))


class Bound:
    _ENV = ("worksheet", "layout", "guard", "ledger", "catalog", "renderer",
            "options", "target", "result", "checked_at")

    def __init__(self, parent, **overrides):
        self._parent = parent
        self.env = {k: parent.env.get(k) for k in self._ENV}
        self.env.update(overrides)
        self.reported: list = []

    def report(self, status):
        self.reported.append(status)

    def get(self, name):
        return self._parent.get(name)

    def has(self, name):
        return self._parent.has(name)

    @property
    def calls(self):
        return self._parent.calls

    def __getattr__(self, name):
        env = self.__dict__.get("env", {})
        if name in env:
            return env[name]
        raise AttributeError(name)


def _bound_finish_from_own_plugin():
    """
    Unit 3's `_finish` as it would be BEFORE unit 2 exists: the one step is
    the service's own plugin, bound to the service's own target -- no config
    key is read anywhere.
    """
    from APITool.sheets.writer import MarkerPlan

    def _finish(self, result, ctx):
        if result.snapshot is None and ctx.has("requirements"):
            result.snapshot = ctx.get("requirements")
        checked_at = ""
        if result.market is not None and result.market.timestamp is not None:
            checked_at = result.market.timestamp.strftime("%Y-%m-%d %H:%M UTC")
        elif result.ok:
            checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        ctx.env["result"] = result
        ctx.env["checked_at"] = checked_at

        plugin = self.plugin
        steps = []
        for sub in (list(plugin.subscribes()) if plugin is not None and callable(getattr(plugin, "subscribes", None)) else []):
            # Today's subscriber, wrapped as a step: it reads ctx.result, which
            # the bound view still carries here; unit 3 moves it to `data`.
            steps.append((self.target or plugin.__name__, sub.needs,
                          lambda data, view, publish=sub.publish: (view.report(publish(view)), data)[1]))

        data = result
        for name, needs, step in steps:
            view = Bound(ctx, worksheet=ctx.worksheet, layout=self.layout, guard=self.guard,
                         ledger=ctx.env.get("ledger"), target=self.target)
            for need in needs:
                view.get(need)
            data = step(data, view)
            if data is None:
                raise ValueError(f"step {name!r} returned None")
            for status in view.reported:
                if isinstance(status, MarkerPlan):
                    data.plan = status
        if data.plan is not None and ctx.options["write"]:
            data.written = True
        return data

    return _finish


def test_p5_unit3_without_unit2_jsonl_end_to_end(tmp_path, monkeypatch, capsys):
    from test_service import docked_event, make_journal, ryman_market_json

    from APITool import cli
    from APITool import service as service_mod

    out_file = tmp_path / "observations.jsonl"
    _write_config(monkeypatch, tmp_path, {"observations": {
        "kind": "jsonl", "plugin": "jsonl", "path": str(out_file),
        "config": {"only": ["checked_at", "system", "station"]},
    }})
    monkeypatch.setattr(service_mod.MarketRefreshService, "_finish", _bound_finish_from_own_plugin())

    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    code = cli.main(["market", "--no-sheet", "--update-sheet", "--journal-dir", str(directory)])
    out = capsys.readouterr().out
    written = out_file.is_file()
    record = json.loads(out_file.read_text(encoding="utf-8").splitlines()[0]) if written else None
    print("\n[P5] exit:", code, "| file written:", written, "| record keys:", sorted(record) if record else None)
    assert code in (0, 2), out
    assert written and set(record) == {"checked_at", "system", "station"}


def test_p6_the_publisher_decides_the_layout_the_service_is_built_with(tmp_path, monkeypatch):
    from APITool import cli, loader

    _write_config(monkeypatch, tmp_path, {
        "market-log": {"kind": "jsonl", "plugin": "jsonl", "path": str(tmp_path / "m.jsonl")},
        "totals-workbook": {"kind": "gsheet", "plugin": "totals", "id": "FAKE", "config": {"totals_tab": "Totals Tab"}},
    })
    plugins = loader.discover()
    destination, problem = cli._resolve_destination(plugins)
    layout, why = cli._plugin_layout(destination)
    guard = loader.build_enforcer(destination.kind, layout.writes())
    print("\n[P6] enabled [market-log, totals-workbook] -> destination:", destination.name,
          "(target", repr(destination.target.name) + ")", "| layout:", type(layout).__name__,
          "| guard:", type(guard).__name__)
    assert destination.name == "jsonl" and type(layout).__name__ == "FileLayout"
    # An explicit pipelines: {"market": ["totals-workbook"]} would bind the totals
    # step to THIS layout and guard -- round 1's H2-c -- unless selection changes.


def test_p7_a_check_config_complaint_does_not_gate_market_today(tmp_path, monkeypatch, capsys):
    from test_service import docked_event, make_journal, ryman_market_json

    from APITool import cli, loader

    out_file = tmp_path / "observations.jsonl"
    _write_config(monkeypatch, tmp_path, {"observations": {
        "kind": "jsonl", "plugin": "jsonl", "path": str(out_file),
        "config": {"only": ["checked_at", "bogus_field"]},
    }})
    entry = loader.discover().first()
    print("\n[P7] complaints at load:", list(entry.complaints))
    assert entry.complaints, "the probe needs a real complaint to exist"

    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    code = cli.main(["market", "--no-sheet", "--update-sheet", "--journal-dir", str(directory)])
    out = capsys.readouterr().out
    print("[P7] market with the complaint present -> exit:", code, "| file written:", out_file.is_file(),
          "| complaint printed by market:", "bogus_field" in out)
    assert code in (0, 2)
    assert out_file.is_file(), "prediction was: the complaint is advisory; the run proceeds"
