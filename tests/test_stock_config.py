"""
The stock config the tool writes on first run (#30, as corrected 2026-09-21).

Every test here runs inside the suite's isolated config directory, which
exists and holds no file -- the exact state of a fresh install. The autouse
fixture sets ED_NO_STOCK_CONFIG so ordinary tests never trigger the write;
the tests that want it lift the guard explicitly.
"""

from __future__ import annotations

import json

import pytest

from APITool import settings, stockconfig
from APITool.cli import main


@pytest.fixture
def first_run(monkeypatch):
    """A fresh install: the directory exists, the file does not, the guard is off."""
    monkeypatch.delenv(stockconfig.GUARD_VAR, raising=False)
    assert not settings.CONFIG_FILE.exists()
    return settings.CONFIG_FILE


def _journal_free(argv):
    """A command that needs no journal, no sheet and no network."""
    return main(argv)


def test_the_first_command_writes_the_stock_file_and_says_so(first_run, capsys):
    code = _journal_free(["plugins"])
    out = capsys.readouterr().out

    assert code == 0
    assert first_run.exists(), "no config was written on a first run"
    assert "Wrote a starting configuration to" in out and str(first_run) in out, out


def test_the_stock_file_parses_and_names_a_working_default_target(first_run):
    _journal_free(["plugins"])

    data = settings.load()
    target = data["targets"][stockconfig.DEFAULT_TARGET]
    assert target["kind"] == "gsheet"
    assert target["plugin"] == "settlement"
    assert target["id"] == stockconfig.TEMPLATE_SHEET_ID


def test_the_plugin_block_is_the_plugins_own_default_config(first_run):
    """
    Composed by asking the plugin, never restated. If the settlement plugin
    changes what it accepts, the stock file follows without core knowing.
    """
    from APITool.plugins import settlement

    _journal_free(["plugins"])
    target = settings.load()["targets"][stockconfig.DEFAULT_TARGET]
    assert target["config"] == settlement.default_config()


def test_after_the_first_run_the_settlement_plugin_is_loaded(first_run, capsys):
    _journal_free(["plugins"])
    capsys.readouterr()

    _journal_free(["plugins"])
    out = capsys.readouterr().out
    assert "Loaded 1" in out and "settlement" in out, out


def test_the_header_explains_the_keys_and_the_template(first_run):
    _journal_free(["plugins"])
    text = first_run.read_text(encoding="utf-8")
    header, body = settings._split_header(text)

    assert header and all(
        line.startswith("#") or not line.strip() for line in header.splitlines())
    for word in ("client_id", "sheet_id", "targets", "kind", "plugin", "config",
                 "EXPECTED TO FAIL", "Make a copy", "docs/configuration.md",
                 "plugins describe", "config.json.bak"):
        assert word in header, f"the header does not explain {word!r}"
    # The second kind is shown as a commented example, not enabled. The
    # example's target name is the tell; the word "jsonl" also appears in
    # the kind explanation, so it proves nothing on its own.
    assert stockconfig.EXAMPLE_FILE_TARGET in header
    assert "jsonl" not in json.dumps(json.loads(body))


def test_a_second_run_does_not_touch_the_file(first_run, capsys):
    _journal_free(["plugins"])
    first_run.write_text(first_run.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    before = first_run.read_text(encoding="utf-8")
    capsys.readouterr()

    _journal_free(["plugins"])
    assert first_run.read_text(encoding="utf-8") == before
    assert "Wrote a starting configuration" not in capsys.readouterr().out


def test_the_guard_stops_the_write(monkeypatch):
    """What the suite relies on: with the variable set, nothing is written."""
    assert not settings.CONFIG_FILE.exists()
    _journal_free(["plugins"])
    assert not settings.CONFIG_FILE.exists()


def test_version_writes_nothing_even_on_a_first_run(first_run, capsys):
    """Printing a version must have no side effect on disk (#30)."""
    _journal_free(["--version"])
    assert not first_run.exists()


def test_help_writes_nothing_even_on_a_first_run(first_run):
    with pytest.raises(SystemExit):
        _journal_free(["market", "--help"])
    assert not first_run.exists()


def test_the_stock_file_round_trips_through_save(first_run):
    """The header the first run wrote must survive the first `auth`."""
    _journal_free(["plugins"])
    header_before, _ = settings._split_header(first_run.read_text(encoding="utf-8"))

    assert settings.save("client_id", "CID") is True
    text = first_run.read_text(encoding="utf-8")
    assert text.startswith(header_before)
    assert settings.load()["client_id"] == "CID"
    assert settings.load()["targets"][stockconfig.DEFAULT_TARGET]["id"] == stockconfig.TEMPLATE_SHEET_ID


def test_only_shipped_plugins_are_asked(monkeypatch, tmp_path):
    """
    A plugin in the person's own directory is never imported to write
    defaults: nothing has been enabled yet, and running it would break the
    consent rule `plugins` keeps.
    """
    user_dir = tmp_path / "plugins" / "spy"
    user_dir.mkdir(parents=True)
    (user_dir / "__init__.py").write_text(
        'KIND = "jsonl"\nraise RuntimeError("a user plugin was imported on first run")\n'
        "def default_config():\n    return {}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ED_PLUGIN_DIR", str(tmp_path / "plugins"))

    defaults = stockconfig.shipped_defaults()
    assert "spy" not in defaults
    assert {"settlement", "jsonl"} <= set(defaults)


def test_the_docs_describe_the_header_the_backup_and_the_guard():
    """docs/configuration.md is read as data: the three new behaviours are named."""
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "docs" / "configuration.md").read_text(encoding="utf-8")
    for word in ("config.json.bak", stockconfig.GUARD_VAR, "above the first `{`", "not yours"):
        assert word in page, f"docs/configuration.md does not mention {word!r}"


def test_the_composing_modules_hold_no_plugin_schema_literal():
    """
    The modules that write the stock file name no key that belongs inside a
    plugin's block. (`cli.py` still mentions `construction_regions` in one
    flag's help text; that is the flag-vocabulary leak D-19 removes, not
    this unit's.)
    """
    from pathlib import Path

    for module in (stockconfig, settings):
        text = Path(module.__file__).read_text(encoding="utf-8")
        assert "construction_regions" not in text, module.__name__
