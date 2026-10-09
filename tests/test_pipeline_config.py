"""
Smokes for the `pipelines` configuration, the derived default and the
refusals (slice 1, unit 3; scenarios S4 and S5).

The goldens cover the one-target path. These cover what they cannot: the
shape of the key, which targets a pipeline selects, and that a bad one is
refused by name with nothing run.
"""

import json
import types

import pytest

from APITool import loader, settings
from APITool.loader import Found, Loaded, LoadResult
from APITool.settings import Target


# ---------------------------------------------------------------------------
# The key's shape
# ---------------------------------------------------------------------------


def _config(monkeypatch, tmp_path, body: dict):
    directory = tmp_path / "cfg"
    directory.mkdir()
    (directory / "config.json").write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setenv("ED_CONFIG_DIR", str(directory))
    monkeypatch.setattr(settings, "CONFIG_FILE", directory / "config.json")


def test_pipelines_parses_the_named_shape(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, {
        "pipelines": {"market": {"reads": "market", "steps": ["a", "b"]}},
    })
    found = settings.get_pipelines()
    assert list(found) == ["market"]
    assert found["market"].reads == "market"
    assert found["market"].steps == ("a", "b")


def test_pipelines_refuses_steps_that_are_not_a_list_of_names(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, {"pipelines": {"market": {"reads": "market", "steps": "a"}}})
    with pytest.raises(ValueError, match=r"pipelines\['market'\]\.steps"):
        settings.get_pipelines()


# ---------------------------------------------------------------------------
# Which targets a pipeline selects
# ---------------------------------------------------------------------------


def _loaded(name: str, target: str, *, step: bool = True) -> Loaded:
    module = types.SimpleNamespace(__name__=name)
    if step:
        module.process = lambda data, ctx: data
        module.needs = ()
    found = Found(name=name, location=None, origin="test")
    return Loaded(name=name, module=module, found=found, kind="gsheet",
                  target=Target(target, "gsheet", name))


def _result(pipelines=None, *loaded: Loaded) -> LoadResult:
    configured = {e.target.name: e.target for e in loaded}
    return LoadResult(loaded=list(loaded), pipelines=dict(pipelines or {}),
                      configured=configured)


def test_with_no_pipelines_every_step_offering_plugin_runs_in_enablement_order():
    """D-all: the P4 configuration runs both; a plugin with no step (regions) is left out."""
    result = _result(None,
                     _loaded("totals", "totals-workbook"),
                     _loaded("regions", "regions-workbook", step=False),
                     _loaded("jsonl", "market-log"))
    assert [e.target.name for e in result.steps("market")] == ["totals-workbook", "market-log"]
    assert result.derived and result.refusals == []


def test_a_configured_pipeline_runs_its_targets_in_the_listed_order():
    pipelines = {"market": settings.Pipeline("market", "market", ("market-log", "totals-workbook"))}
    result = _result(pipelines, _loaded("totals", "totals-workbook"), _loaded("jsonl", "market-log"))
    assert [e.target.name for e in result.steps("market")] == ["market-log", "totals-workbook"]
    assert not result.derived


@pytest.mark.parametrize("pipelines, loaded, extra_target, expect", [
    ({"market": settings.Pipeline("market", "market", ("nothere",))},
     [("totals", "totals-workbook")], None, "names target 'nothere', which is not configured"),
    ({"market": settings.Pipeline("market", "market", ("totals-workbook", "totals-workbook"))},
     [("totals", "totals-workbook")], None, "lists plugin 'totals' twice"),
    ({"market": settings.Pipeline("market", "market", ("second-totals",))},
     [("totals", "totals-workbook")], Target("second-totals", "gsheet", "totals"),
     "served by plugin 'totals', which is loaded for target 'totals-workbook'"),
    ({"nightly": settings.Pipeline("nightly", "market", ("totals-workbook",))},
     [("totals", "totals-workbook")], None, "runs the pipelines market, cargo, carrier"),
    ({"market": settings.Pipeline("market", "cargo", ("totals-workbook",))},
     [("totals", "totals-workbook")], None, "reads 'cargo'"),
    ({"market": settings.Pipeline("market", "market", ("regions-workbook",))},
     [("regions", "regions-workbook")], None, "offers no step (no process) and no suppliers"),
], ids=["unknown-target", "plugin-twice", "other-target-of-plugin", "other-name", "other-kind", "no-step"])
def test_a_pipeline_that_cannot_run_is_refused_by_name_with_no_steps(pipelines, loaded, extra_target, expect):
    entries = [_loaded(name, target, step=(name != "regions")) for name, target in loaded]
    result = _result(pipelines, *entries)
    if extra_target is not None:
        result.configured[extra_target.name] = extra_target
    name = next(iter(pipelines))
    assert result.steps(name) == []
    assert any(expect in refusal for refusal in result.refusals), result.refusals


# ---------------------------------------------------------------------------
# The commands, with a refusal present (S4)
# ---------------------------------------------------------------------------


def _planted_refusal(monkeypatch, tmp_path):
    """A real totals target plus a pipeline naming a target that does not exist."""
    _config(monkeypatch, tmp_path, {
        "targets": {"test-workbook": {"kind": "gsheet", "plugin": "totals",
                                      "id": "FAKE_SHEET_ID_NEVER_CONTACTED",
                                      "config": {"totals_tab": "Totals Tab"}}},
        "pipelines": {"market": {"reads": "market", "steps": ["nothere"]}},
    })


def test_market_no_sheet_json_still_answers_with_a_refusal_present(monkeypatch, tmp_path, capsys):
    from test_service import docked_event, make_journal, ryman_market_json

    from APITool import cli

    _planted_refusal(monkeypatch, tmp_path)
    journal = make_journal(tmp_path, [docked_event()], ryman_market_json())
    code = cli.main(["market", "--no-sheet", "--json", "--journal-dir", str(journal)])
    out = capsys.readouterr().out
    assert code == 0
    assert "cannot run" in out and "nothere" in out
    assert '"station"' in out, "the market itself is still answered"


def test_serve_refuses_before_building_a_daemon_when_the_pipeline_cannot_run(monkeypatch, tmp_path, capsys):
    """Rule 1b: the daemon builder is patched to raise, so a failed refusal cannot start a daemon."""
    from APITool import cli, daemon

    _planted_refusal(monkeypatch, tmp_path)

    def never(*args, **kwargs):
        raise AssertionError("daemon.build must not be reached while the pipeline is refused")

    monkeypatch.setattr(daemon, "build", never)
    code = cli.main(["serve", "--once", "--sheet-id", "FAKE_SHEET_ID_NEVER_CONTACTED",
                     "--journal-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "cannot run" in out and "nothere" in out


# ---------------------------------------------------------------------------
# A value the file cannot parse ends the command, by name, on every verb
# (found by the v0.9.0 checklist's tester sweep: `plugins` tracebacked and
# `market` ran as if nothing were configured)
# ---------------------------------------------------------------------------


def _malformed_pipelines(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, {
        "targets": {"test-workbook": {"kind": "gsheet", "plugin": "totals",
                                      "id": "FAKE_SHEET_ID_NEVER_CONTACTED", "config": {}}},
        "pipelines": {"market": {"reads": "market", "steps": "test-workbook"}},
    })


def test_plugins_names_a_malformed_pipelines_value_instead_of_tracebacking(monkeypatch, tmp_path, capsys):
    from APITool import cli

    _malformed_pipelines(monkeypatch, tmp_path)
    code = cli.main(["plugins"])
    out = capsys.readouterr().out
    assert code == 1
    assert "pipelines['market'].steps must be a list" in out
    # The file is named, as every other discovery refusal names it (the
    # v0.10.1 checklist's HV.4 found `plugins` alone left it out).
    assert "(from " in out and str(settings.CONFIG_FILE) in out
    assert "Traceback" not in out


def test_market_refuses_a_malformed_pipelines_value_rather_than_running_unconfigured(monkeypatch, tmp_path, capsys):
    from test_service import docked_event, make_journal, ryman_market_json

    from APITool import cli

    _malformed_pipelines(monkeypatch, tmp_path)
    journal = make_journal(tmp_path, [docked_event()], ryman_market_json())
    code = cli.main(["market", "--no-sheet", "--json", "--journal-dir", str(journal)])
    out = capsys.readouterr().out
    assert code == 1
    assert "pipelines['market'].steps must be a list" in out
    assert '"station"' not in out, "a broken configuration is not answered as if it were absent"
