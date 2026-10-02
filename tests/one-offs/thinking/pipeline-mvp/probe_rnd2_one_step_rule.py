"""
Round-2 collab probes: the one-step rule, the bound golden, and the config census.

    python -m pytest tests/one-offs/thinking/pipeline-mvp/probe_rnd2_one_step_rule.py -p no:cacheprovider -q -s

Fakes only. Config files go to the suite's isolated ED_CONFIG_DIR (conftest
autouse); ED_PLUGIN_DIR points at a directory that does not exist; the journal
directory is an empty tmp_path or the suite's fixture; every sheet is an
in-memory fake. `_finish` is monkeypatched on the class inside one test.
No production file is edited.

P1  Check 4 as a refusal: a `pipelines` list naming `totals-workbook` and a
    jsonl target is refused at startup, naming both. Also the refusal the
    round-2 brief did not list: a target that is not the one its plugin was
    handed (test_plugin_loader.py:262-275 pins "the first wins") is refused
    by name rather than silently bound to the first target's config.
P2  The golden with the step bound to an explicitly built per-target view
    (the fields service._context builds, copied from the parent, sharing the
    supplier cache and `calls`): predicted byte-identical.
P3  Census: every `"targets": {...}` literal under tests/, plus stockconfig.py
    and settings.py, counted programmatically for two targets naming one
    plugin.
P4  (mine) What the stock header's own suggestion does TODAY: `totals-workbook`
    plus the commented `nightly-dump` jsonl target, uncommented. Predicted: the
    file is never written and nothing says so.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
GOLDEN = ROOT / "tests" / "goldens" / "v0.8.1__market--update-sheet--dry-run__fixture.txt"
_AGE = re.compile(r"\b\d[\d,]* min old\b")


def _settled(text: str) -> str:
    return _AGE.sub("<age> min old", text)


def _write_config(monkeypatch, tmp_path, targets: dict, pipelines=None) -> None:
    from APITool import settings

    settings.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = {"targets": targets}
    if pipelines is not None:
        body["pipelines"] = pipelines
    settings.CONFIG_FILE.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setenv("ED_PLUGIN_DIR", str(tmp_path / "no-user-plugins"))


# ---------------------------------------------------------------------------
# P1: the one-step rule, as a startup check over what the loader produced
# ---------------------------------------------------------------------------


def _offers_step(module) -> bool:
    # In the MVP this is `process`; today the equivalent is `subscribes`.
    return callable(getattr(module, "process", None)) or callable(getattr(module, "subscribes", None))


def check_pipelines(pipelines: dict, loaded, targets: dict, deferred_issue: str = "#N") -> list[str]:
    """
    The startup check the round-2 brief proposes, written out so its
    messages can be read. Returns the refusals; empty means the list is fine.
    """
    problems: list[str] = []
    handed = {entry.target.name: entry for entry in loaded if entry.target is not None}
    for data_kind, names in pipelines.items():
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            problems.append(f'pipelines[{data_kind!r}] must be a list of target names')
            continue
        for name in names:
            if name not in targets:
                problems.append(
                    f"pipelines[{data_kind!r}] names {name!r}, which is not a configured target; "
                    f"known targets: {', '.join(targets) or '(none)'}")
            elif name not in handed:
                first = next((e.target.name for e in loaded if e.name == targets[name].plugin), None)
                problems.append(
                    f"pipelines[{data_kind!r}] names {name!r}, but its plugin {targets[name].plugin!r} "
                    f"was loaded for {first!r} (the first target naming it); only that target can be "
                    f"a step until per-target loading ({deferred_issue})")
            elif not _offers_step(handed[name].module):
                problems.append(
                    f"pipelines[{data_kind!r}] names {name!r}, whose plugin {handed[name].name!r} "
                    f"offers no step")
        if len(names) > 1:
            problems.append(
                f"pipelines[{data_kind!r}] lists {len(names)} targets ({', '.join(repr(n) for n in names)}); "
                f"one step per data kind until {deferred_issue}")
    return problems


def _discover():
    from APITool import loader

    return loader.discover()


def test_p1_two_targets_in_one_list_are_refused_naming_both(tmp_path, monkeypatch):
    from APITool import settings

    _write_config(monkeypatch, tmp_path, {
        "totals-workbook": {"kind": "gsheet", "plugin": "totals", "id": "FAKE_NEVER_CONTACTED",
                            "config": {"totals_tab": "Totals Tab"}},
        "market-log": {"kind": "jsonl", "plugin": "jsonl", "path": str(tmp_path / "market.jsonl")},
    }, pipelines={"market": ["totals-workbook", "market-log"]})
    loaded = _discover().loaded
    problems = check_pipelines(settings.load()["pipelines"], loaded, settings.get_targets(), "#U53-2")
    print("\n[P1-a] loaded:", [(e.name, e.target.name) for e in loaded])
    for p in problems:
        print("[P1-a] REFUSED:", p)
    assert len(problems) == 1
    assert "'totals-workbook'" in problems[0] and "'market-log'" in problems[0]


def test_p1_an_unknown_target_and_a_second_target_of_one_plugin_are_refused(tmp_path, monkeypatch):
    from APITool import settings

    _write_config(monkeypatch, tmp_path, {
        "first": {"kind": "gsheet", "plugin": "totals", "id": "ONE", "config": {"totals_tab": "A"}},
        "second": {"kind": "gsheet", "plugin": "totals", "id": "TWO", "config": {"totals_tab": "B"}},
    }, pipelines={"market": ["second"], "cargo": ["nope"]})
    loaded = _discover().loaded
    problems = check_pipelines(settings.load()["pipelines"], loaded, settings.get_targets(), "#U53-2")
    print("\n[P1-b] loaded:", [(e.name, e.target.name) for e in loaded])
    for p in problems:
        print("[P1-b] REFUSED:", p)
    assert any("'second'" in p and "'first'" in p for p in problems), "the misbinding must be named"
    assert any("'nope'" in p for p in problems)


def test_p1_a_single_step_list_and_a_jsonl_only_list_pass(tmp_path, monkeypatch):
    from APITool import settings

    _write_config(monkeypatch, tmp_path, {
        "totals-workbook": {"kind": "gsheet", "plugin": "totals", "id": "FAKE", "config": {}},
        "regions-workbook": {"kind": "gsheet", "plugin": "regions", "id": "FAKE", "config": {}},
    }, pipelines={"market": ["totals-workbook"]})
    problems = check_pipelines(settings.load()["pipelines"], _discover().loaded, settings.get_targets())
    print("\n[P1-c] stock shape + explicit one-step list ->", problems or "OK")
    assert problems == []

    _write_config(monkeypatch, tmp_path, {
        "market-log": {"kind": "jsonl", "plugin": "jsonl", "path": str(tmp_path / "m.jsonl")},
    }, pipelines={"market": ["market-log"]})
    problems = check_pipelines(settings.load()["pipelines"], _discover().loaded, settings.get_targets())
    print("[P1-d] jsonl as the kind's one step ->", problems or "OK")
    assert problems == []


# ---------------------------------------------------------------------------
# P2: the golden with the step bound to an explicit per-target view
# ---------------------------------------------------------------------------


class Bound:
    """
    A per-step view of one Refresh: the parent's suppliers, cache and `calls`,
    with an env of its own. The fields are the ones service._context builds
    (service.py:202-216); here they are copied from the parent so the ledger
    and its run_id are the refresh's, not a second one.
    """

    _ENV = ("worksheet", "layout", "guard", "ledger", "catalog", "renderer",
            "options", "target", "result", "checked_at")

    def __init__(self, parent, **overrides):
        self._parent = parent
        self.env = {k: parent.env.get(k) for k in self._ENV}
        self.env.update(overrides)

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


def _bound_finish(step_name, step):
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

        # The binding, made explicit: this step's own target's fields.
        view = Bound(ctx, worksheet=ctx.worksheet, layout=self.layout, guard=self.guard,
                     ledger=ctx.env.get("ledger"), target=self.target)
        reported = []
        view.report = reported.append          # ctx.report(status)
        data = step(result, view)
        if data is None:
            raise ValueError(f"step {step_name!r} returned None")
        for status in reported:
            if isinstance(status, MarkerPlan):
                data.plan = status
                break
        if data.plan is not None and ctx.options["write"]:
            data.written = True
        return data

    return _finish


def test_p2_golden_with_the_step_bound_to_its_own_targets_view(tmp_path, monkeypatch, capsys, configured_totals):
    from test_marker_skip_occupied import RangeAwareWorksheet, _cli, _planted_grid

    from APITool import service as service_mod
    from APITool.plugins import totals

    seen = {}

    def totals_step(data, ctx):
        seen["bound_target"] = ctx.target
        seen["bound_layout"] = type(ctx.layout).__name__
        ctx.report(totals._publish_markers(ctx))
        seen["calls"] = dict(ctx.calls)
        return data

    monkeypatch.setattr(service_mod.MarketRefreshService, "_finish", _bound_finish("totals-workbook", totals_step))
    sheet = RangeAwareWorksheet(_planted_grid())
    code = _cli(tmp_path, monkeypatch, sheet, "--dry-run", "--write-location")
    out = _settled(capsys.readouterr().out)
    assert code == 0 and sheet.batches == []
    identical = out == GOLDEN.read_text(encoding="utf-8")
    print("\n[P2] identical to golden:", identical, "| step saw:", seen)
    assert identical
    assert seen["calls"] == {"location": 1, "market": 1, "requirements": 1}


# ---------------------------------------------------------------------------
# P3: the census
# ---------------------------------------------------------------------------


def _targets_blocks(text: str):
    """Every balanced `{...}` that follows a `"targets":` key, as source text."""
    for m in re.finditer(r'["\']targets["\']\s*:\s*\{', text):
        start = m.end() - 1
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:i + 1], text[:m.start()].count("\n") + 1
                    break
            i += 1


def _plugins_in(block: str) -> list[str]:
    return re.findall(r'["\']plugin["\']\s*:\s*([A-Za-z_][A-Za-z_0-9]*|["\'][^"\']+["\'])', block)


def test_p3_census_of_two_targets_naming_one_plugin():
    files = sorted((ROOT / "tests").rglob("*.py"))
    files = [f for f in files if "one-offs" not in f.parts]     # the probes are not configs
    files += [ROOT / "APITool" / "stockconfig.py", ROOT / "APITool" / "settings.py"]
    blocks = 0
    duplicates = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for block, line in _targets_blocks(text):
            blocks += 1
            names = _plugins_in(block)
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                duplicates.append((path.relative_to(ROOT).as_posix(), line, dupes))
    print(f"\n[P3] targets blocks scanned: {blocks} across {len(files)} files")
    for where, line, dupes in duplicates:
        print(f"[P3] duplicate plugin in one targets block: {where}:{line} -> {dupes}")
    # stockconfig: the body's two targets, and the header's commented example
    from APITool import stockconfig

    body = stockconfig.body()
    print("[P3] stockconfig.body() targets:", {k: v["plugin"] for k, v in body["targets"].items()})
    print("[P3] stockconfig header example (commented):", stockconfig.EXAMPLE_FILE_TARGET, "->",
          stockconfig.EXAMPLE_FILE_PLUGIN)
    assert duplicates == [("tests/test_plugin_loader.py", 269, ["GOOD"])]


# ---------------------------------------------------------------------------
# P4: the stock header's suggestion, as it behaves today
# ---------------------------------------------------------------------------


def test_p4_the_stock_headers_suggested_jsonl_target_never_runs_beside_totals(tmp_path, monkeypatch, capsys):
    from test_service import docked_event, make_journal, ryman_market_json

    from APITool import cli, stockconfig

    out_file = tmp_path / "market.jsonl"
    targets = stockconfig.body()["targets"]
    for entry in targets.values():
        entry["id"] = "FAKE_SHEET_ID_NEVER_CONTACTED"
    targets[stockconfig.EXAMPLE_FILE_TARGET] = {
        "kind": "jsonl", "plugin": "jsonl", "path": str(out_file), "config": {},
    }
    _write_config(monkeypatch, tmp_path, targets)

    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    code = cli.main(["market", "--no-sheet", "--update-sheet", "--journal-dir", str(directory)])
    out = capsys.readouterr().out
    beside = (code, out_file.exists(), "nightly-dump" in out, "jsonl" in out.lower())
    assert code in (0, 2)
    assert not out_file.exists(), "prediction was: the jsonl target beside totals never runs"
    assert "nightly-dump" not in out

    # The same target alone DOES run (test_jsonl_plugin.py:176-209 pins it); shown here for contrast.
    _write_config(monkeypatch, tmp_path, {stockconfig.EXAMPLE_FILE_TARGET: targets[stockconfig.EXAMPLE_FILE_TARGET]})
    code = cli.main(["market", "--no-sheet", "--update-sheet", "--journal-dir", str(directory)])
    capsys.readouterr()
    alone = (code, out_file.exists())
    # Printed after the last readouterr, or capsys swallows the first line.
    print("\n[P4] beside totals: exit:", beside[0], "| file written:", beside[1],
          "| 'nightly-dump' mentioned:", beside[2], "| 'jsonl' mentioned:", beside[3])
    print("[P4] alone: exit:", alone[0], "| file written:", alone[1])
    assert out_file.exists()
