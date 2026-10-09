"""
Pipelines for every data kind (slice 2 of the pipeline redesign, unit 4b).

The claim this file measures, in the order the 2026-10-09 addendum asks:
WRITTEN FIRST, against the tree before the unit, it asserts that a plugin
step listed on a `cargo` pipeline is refused -- "this release runs only the
'market' pipeline". If that version does not pass today, the claim that
only the market pipeline accepts plugin steps was wrong and the unit is
unnecessary. Once the unit lands, the same scenario flips: the step runs
and receives the ShipCargo record.
"""

import json

import pytest

from APITool import loader, settings

RECORDER = "plug_recorder"
RECORDER_INIT = '''
"""A planted step that records what it was handed and passes it on."""
import json
from pathlib import Path

KIND = "jsonl"
needs = ()

def writes():
    return {}

def layout(**overrides):
    from types import SimpleNamespace
    return SimpleNamespace(path=overrides.get("path", ""), writes=lambda: {})

def process(data, ctx):
    import os
    Path(os.environ["RECORDER_OUT"]).write_text(json.dumps({
        "type": type(data).__name__,
        "total": getattr(data, "total", None),
    }), encoding="utf-8")
    return data
'''


@pytest.fixture
def planted(monkeypatch, tmp_path):
    plugins_dir = tmp_path / "plugins"
    (plugins_dir / RECORDER).mkdir(parents=True)
    (plugins_dir / RECORDER / "__init__.py").write_text(RECORDER_INIT, encoding="utf-8")
    monkeypatch.setenv("ED_PLUGIN_DIR", str(plugins_dir))
    monkeypatch.setenv("RECORDER_OUT", str(tmp_path / "seen.json"))
    directory = tmp_path / "cfg"
    directory.mkdir()
    (directory / "config.json").write_text(json.dumps({
        "targets": {"hold-log": {"kind": "jsonl", "plugin": RECORDER,
                                 "path": str(tmp_path / "seen.json"), "config": {}}},
        "pipelines": {"cargo": {"reads": "cargo", "steps": ["hold-log"]}},
    }), encoding="utf-8")
    monkeypatch.setenv("ED_CONFIG_DIR", str(directory))
    monkeypatch.setattr(settings, "CONFIG_FILE", directory / "config.json")
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    return tmp_path


def test_a_plugin_step_on_a_cargo_pipeline_resolves(planted):
    """
    Flipped by unit 4b. Its red-first form, run against `68eb07c`..`6a91b6a`
    before the unit and observed passing, was:

        assert result.steps("cargo") == []
        assert any("runs only the 'market' pipeline" in r for r in result.refusals)
    """
    result = loader.discover()
    assert [e.target.name for e in result.steps("cargo")] == ["hold-log"]
    assert result.refusals == []


def test_a_cargo_or_carrier_pipeline_derives_no_default_steps(planted, monkeypatch):
    """No plugin declares which kinds it reads, so an unlisted kind runs none, never the market's."""
    body = json.loads(settings.CONFIG_FILE.read_text(encoding="utf-8"))
    del body["pipelines"]
    settings.CONFIG_FILE.write_text(json.dumps(body), encoding="utf-8")
    result = loader.discover()
    assert result.steps("cargo") == [] and result.steps("carrier") == []
    assert result.steps("market") != [], "the market still derives its list"


def test_the_cargo_step_receives_the_ship_cargo_record_through_the_daemon(planted, monkeypatch):
    """
    End to end: the daemon's cargo pipeline, run once by token, hands the
    ShipCargo record to the configured step before writing the tab. The
    sheet writer is a fake; the journal is the Cargo.json fixture.
    """
    import argparse
    import shutil
    from pathlib import Path

    import APITool.google as google_mod
    from APITool import cli, daemon
    from APITool.loader import build_enforcer

    class FakeExporter:
        def __init__(self, *args, **kwargs):
            pass

        def export_grid(self, grid, sheet_id=None, tab_name=None):
            return len(grid)

    monkeypatch.setattr(google_mod, "GoogleSheetsExporter", FakeExporter)
    journal = planted / "journal"
    journal.mkdir()
    shutil.copy(Path(__file__).parent / "fixtures" / "cargo_ship.json", journal / "Cargo.json")
    (journal / "Journal.2026-09-08T060000.01.log").write_text("", encoding="utf-8")

    result = loader.discover()
    args = argparse.Namespace(_plugins=result)
    specs, problem = cli._specs_for(args, "serve", result.steps("cargo"))
    assert specs is not None, problem
    worker = daemon.build(sheet_id="FAKE_SHEET_ID_NEVER_CONTACTED", journal_dir=journal,
                          layout=cli._NoLayout(), guard=build_enforcer("gsheet", {}),
                          cargo_steps=specs, publish_carrier=False, log=lambda m: None)
    [outcome] = worker.run_stage("cargo")
    seen = json.loads((planted / "seen.json").read_text(encoding="utf-8"))
    assert seen["type"] == "ShipCargo" and seen["total"] > 0
    assert outcome.wrote and "via hold-log" in outcome.message
