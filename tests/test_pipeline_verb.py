"""
The `pipeline` verb (slice 2 of the pipeline redesign, unit 3): a typed
sequence of built-in pipelines and plugin steps, run in order, stopping at
the first failure, printed before anything runs. Smokes.

Rule 1b throughout: `daemon.build` is replaced by a builder that RAISES, so a
refusal or a dry run that failed to stop would fail the test rather than
open a spreadsheet or start a loop; the run-path tests replace the verb's
own worker seam with a fake that records which stage ran.
"""

import json

import pytest

from APITool import cli, daemon, settings
from APITool.cli import main


class Built(BaseException):
    """daemon.build was reached; nothing past it may run in these tests."""


@pytest.fixture
def planted(monkeypatch, tmp_path):
    """A totals target and a jsonl target, no `pipelines` key (the derived default)."""
    directory = tmp_path / "cfg"
    directory.mkdir()
    (directory / "config.json").write_text(json.dumps({"targets": {
        "totals-workbook": {"kind": "gsheet", "plugin": "totals",
                            "id": "FAKE_SHEET_ID_NEVER_CONTACTED",
                            "config": {"totals_tab": "Totals Tab"}},
        "market-log": {"kind": "jsonl", "plugin": "jsonl",
                       "path": str(tmp_path / "market.jsonl"), "config": {}},
    }}), encoding="utf-8")
    monkeypatch.setenv("ED_CONFIG_DIR", str(directory))
    monkeypatch.setattr(settings, "CONFIG_FILE", directory / "config.json")
    monkeypatch.delenv("ED_SHEET_ID", raising=False)

    def never(*args, **kwargs):
        raise Built("daemon.build must not be reached")

    monkeypatch.setattr(daemon, "build", never)
    return tmp_path


def test_help_names_the_three_token_forms(capsys):
    with pytest.raises(SystemExit) as left:
        main(["pipeline", "--help"])
    assert left.value.code == 0
    out = capsys.readouterr().out
    for form in ("BUILT-IN", "TARGET", "COMMAND", "market", "cargo", "carrier", "regions"):
        assert form in out


def test_dry_run_prints_the_plan_and_builds_nothing(planted, capsys):
    code = main(["pipeline", "market", "totals-workbook", "market-log", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Sequence (2 runs):" in out
    assert "1. market -- the market pipeline: totals-workbook -> market-log" in out
    assert "2. totals-workbook -> market-log -- the market pipeline with those steps only" in out
    assert "dry run; nothing read or written" in out
    assert not (planted / "market.jsonl").exists()


def test_the_maintainers_example_prints_two_runs_in_that_order(planted, capsys):
    assert main(["pipeline", "regions", "totals-workbook", "--dry-run"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  ")]
    assert lines[0].startswith("  1. regions --")
    assert lines[1].startswith("  2. totals-workbook --")


def test_a_bad_token_refuses_naming_it_and_the_three_meanings(planted, capsys):
    code = main(["pipeline", "regions", "nothere", "--sheet-id", "X"])
    out = capsys.readouterr().out
    assert code == 1
    assert "the sequence cannot run" in out
    assert "names target 'nothere', which is not configured" in out
    assert "built-in stage (market, cargo, carrier, regions)" in out and "plugin command" in out
    assert "Run 1" not in out, "nothing ran"


def test_a_command_the_plugin_does_not_offer_is_refused_by_name(planted, capsys):
    code = main(["pipeline", "totals:nope=--x", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 1 and "offers no command 'nope'" in out


# --- commands as entries (unit 4) -------------------------------------------

COMMANDING = "plug_commanding"
COMMANDING_INIT = '''
from APITool.registry import Command

KIND = "jsonl"

def writes():
    return {}

def _setup(tail, target):
    print("setup ran with tail=%r target=%r" % (tail, None if target is None else target.name))
    return 0

def _sweep(tail, target):
    print("sweep ran for %r" % target.name)
    return 7

def commands():
    return {
        "setup": Command("setup", _setup, "write the target this plugin needs", safe_unconfigured=True),
        "sweep": Command("sweep", _sweep, "read the destination and report"),
    }
'''


@pytest.fixture
def commanding(planted, monkeypatch, tmp_path):
    """The planted totals and jsonl targets plus a user-dir plugin offering two commands."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / COMMANDING).mkdir()
    (plugins_dir / COMMANDING / "__init__.py").write_text(COMMANDING_INIT, encoding="utf-8")
    monkeypatch.setenv("ED_PLUGIN_DIR", str(plugins_dir))
    body = json.loads(settings.CONFIG_FILE.read_text(encoding="utf-8"))
    body["targets"]["mine"] = {"kind": "jsonl", "plugin": COMMANDING, "path": "x.jsonl"}
    settings.CONFIG_FILE.write_text(json.dumps(body), encoding="utf-8")
    return plugins_dir


def test_a_command_token_runs_the_command_with_its_parameters_as_its_tail(commanding, worker_seam, capsys):
    """U43's shape: a command first, then the pipelines that use what it made."""
    _, workers, _ = worker_seam
    code = main(["pipeline", f'{COMMANDING}:setup=--type "industrial large" --name a=b',
                 "regions", "--sheet-id", "X"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "1. plug_commanding:setup=" in out and "`setup` command with: --type industrial large --name a=b" in out
    assert "setup ran with tail=['--type', 'industrial large', '--name', 'a=b'] target='mine'" in out
    assert [w.ran for w in workers] == [["regions"]], "the command ran, then the regions run"


def test_a_failing_command_stops_the_sequence_with_its_exit_code(commanding, worker_seam, capsys):
    _, workers, _ = worker_seam
    code = main(["pipeline", f"{COMMANDING}:sweep", "cargo", "--sheet-id", "X"])
    out = capsys.readouterr().out
    assert code == 7, "the handler's exit code, not a translation of it"
    assert "sweep ran for 'mine'" in out
    assert "Stopped at run 1 of 2 (exit 7)" in out
    assert workers == [], "the cargo run's worker was never built"


def test_dry_run_prints_a_command_and_runs_it_not_at_all(commanding, capsys):
    code = main(["pipeline", f"{COMMANDING}:sweep", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "`sweep` command; a non-zero exit stops the sequence" in out
    assert "sweep ran" not in out


class FakeWorker:
    def __init__(self, fail_on=None):
        self.ran = []
        self.fail_on = fail_on

    def run_stage(self, name):
        self.ran.append(name)
        if name == self.fail_on:
            raise RuntimeError(f"{name} blew up")
        return [daemon.PublishResult(True, f"  {name} ok")]


@pytest.fixture
def worker_seam(planted, monkeypatch):
    """The verb's worker seam replaced; every build's worker is recorded."""
    workers = []
    discoveries = []

    def fake_build(sheet_id, journal_dir, specs, destination, regions, **kwargs):
        worker = FakeWorker(fail_on=getattr(fake_build, "fail_on", None))
        worker.specs = specs
        workers.append(worker)
        return worker

    real_discover = cli._discover_once

    def counted():
        discoveries.append(1)
        return real_discover()

    monkeypatch.setattr(cli, "_build_worker", fake_build)
    monkeypatch.setattr(cli, "_discover_once", counted)
    return fake_build, workers, discoveries


def test_each_run_builds_its_own_worker_from_a_fresh_read_of_the_configuration(worker_seam, capsys):
    fake_build, workers, discoveries = worker_seam
    code = main(["pipeline", "cargo", "market-log", "regions", "--sheet-id", "X"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert [w.ran for w in workers] == [["cargo"], ["market"], ["regions"]]
    # The second run's worker holds only the named step; a cargo run carries
    # no market steps at all (its own kind's steps ride as cargo_steps).
    assert [s.offerer for s in workers[1].specs] == ["market-log"]
    assert workers[0].specs == []
    # main() discovers once; runs 2 and 3 re-read the configuration.
    assert len(discoveries) == 3


def test_the_sequence_stops_at_the_first_failure(worker_seam, capsys):
    fake_build, workers, _ = worker_seam
    fake_build.fail_on = "market"
    code = main(["pipeline", "cargo", "market", "regions", "--sheet-id", "X"])
    out = capsys.readouterr().out
    assert code == 1
    assert "Stopped at run 2 of 3" in out
    assert len(workers) == 2, "the third run's worker was never built"


def test_no_sheet_id_refuses_before_any_run(worker_seam, monkeypatch, capsys):
    """A gsheet target supplies its id; with every route to one removed, the verb refuses."""
    _, workers, _ = worker_seam
    monkeypatch.setattr(cli, "get_sheet_id", lambda args: None)
    assert main(["pipeline", "cargo"]) == 1
    assert "needs a spreadsheet id" in capsys.readouterr().out
    assert workers == []
