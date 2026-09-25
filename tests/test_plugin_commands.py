"""
`edapitool plugins <name> <command>` -- a plugin's own commands (#33).

The verb is the container; there is no `plugin` verb. Naming a plugin
imports that one plugin and hands it the rest of the command line unread,
with the target that enables it or None. The rule these tests hold: a
command that needs a target never runs without one, and says so by name.

Every plugin here is planted under ``ED_PLUGIN_DIR`` in ``tmp_path`` and the
config file is the conftest's scratch one; no command reaches a sheet.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from APITool import settings
from APITool.cli import main

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

QUIET = "plug_quiet"
QUIET_INIT = '''
KIND = "jsonl"

def writes():
    return {}
'''

BROKEN = "plug_broken"
BROKEN_INIT = 'raise RuntimeError("planted: this plugin does not import")\n'

MALFORMED = "plug_malformed"
MALFORMED_INIT = '''
KIND = "jsonl"

def commands():
    return ["not", "a", "mapping"]
'''

RAISING = "plug_raising"
RAISING_INIT = '''
from APITool.registry import Command

KIND = "jsonl"

def _boom(tail, target):
    raise ValueError("planted: the handler fell over")

def commands():
    return {"boom": Command("boom", _boom, "fall over", safe_unconfigured=True)}
'''


def _plant(directory: Path, name: str, body: str) -> Path:
    package = directory / name
    package.mkdir()
    (package / "__init__.py").write_text(body, encoding="utf-8")
    return package


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    directory = tmp_path / "plugins"
    directory.mkdir()
    monkeypatch.setenv("ED_PLUGIN_DIR", str(directory))
    return directory


@pytest.fixture
def config(tmp_path, monkeypatch, user_dir):
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    monkeypatch.delenv("ED_CONFIG_DIR", raising=False)

    def write(data):
        path.write_text(json.dumps(data), encoding="utf-8")
    return write


def _enabled(config, name: str) -> None:
    config({"targets": {"mine": {"kind": "jsonl", "plugin": name, "path": "x.jsonl"}}})


def run(argv, capsys):
    code = main(argv)
    return code, capsys.readouterr().out


# --------------------------------------------------------------------------
# running a command
# --------------------------------------------------------------------------

def test_a_safe_command_runs_unconfigured_and_receives_its_tail(config, user_dir, capsys):
    """
    A setup command exists to write the very target the plugin needs, so it
    runs with no target at all; the tail after the command's name reaches
    the handler unread, options and all.
    """
    _plant(user_dir, COMMANDING, COMMANDING_INIT)
    config({"targets": {}})

    code, out = run(["plugins", COMMANDING, "setup", "--tab", "Base", "extra"], capsys)

    assert code == 0
    assert "setup ran with tail=['--tab', 'Base', 'extra'] target=None" in out


def test_an_enabled_plugin_receives_its_target_and_its_exit_code_is_returned(
        config, user_dir, capsys):
    _plant(user_dir, COMMANDING, COMMANDING_INIT)
    _enabled(config, COMMANDING)

    code, out = run(["plugins", COMMANDING, "sweep"], capsys)

    assert code == 7, "the handler's exit code, not a translation of it"
    assert "sweep ran for 'mine'" in out


def test_an_unsafe_command_on_an_unconfigured_plugin_is_refused_by_name(
        config, user_dir, capsys):
    """
    Refused, and the refusal names the plugin and the remedy. A handler that
    would read a destination must never be handed None and left to guess.
    """
    _plant(user_dir, COMMANDING, COMMANDING_INIT)
    config({"targets": {}})

    code, out = run(["plugins", COMMANDING, "sweep"], capsys)

    assert code == 1
    assert "sweep ran" not in out, "the handler must not have run"
    assert f"`plugins {COMMANDING} sweep` needs the {COMMANDING} plugin enabled" in out
    assert f'"plugin": "{COMMANDING}"' in out, "the remedy, in the config's own words"


def test_a_command_the_plugin_does_not_offer_is_named_with_what_it_does(
        config, user_dir, capsys):
    _plant(user_dir, COMMANDING, COMMANDING_INIT)
    _enabled(config, COMMANDING)

    code, out = run(["plugins", COMMANDING, "polish"], capsys)

    assert code == 1
    assert f"{COMMANDING} has no command 'polish'" in out
    assert "setup, sweep" in out


# --------------------------------------------------------------------------
# listing a plugin's commands
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tail", [[], ["--help"], ["-h"], ["help"]])
def test_no_command_or_help_lists_the_commands_and_which_run_without_a_target(
        config, user_dir, capsys, tail):
    _plant(user_dir, COMMANDING, COMMANDING_INIT)
    config({"targets": {}})

    code, out = run(["plugins", COMMANDING, *tail], capsys)

    assert code == 0
    assert "setup" in out and "write the target this plugin needs" in out
    assert "sweep" in out and "read the destination and report" in out
    assert out.count("(runs without a target)") == 1, "only setup is marked safe"
    assert "not enabled by any target" in out
    assert "setup ran" not in out and "sweep ran" not in out, "listing runs nothing"


def test_a_shipped_plugin_that_declares_no_commands_says_so(configured_totals, capsys):
    code, out = run(["plugins", "totals"], capsys)

    assert code == 0
    assert out.strip() == "totals declares no commands."


def test_a_plugin_without_commands_behaves_as_today_everywhere_else(config, user_dir, capsys):
    """A plugin that never heard of commands() still lists, describes, and refuses politely."""
    _plant(user_dir, QUIET, QUIET_INIT)
    _enabled(config, QUIET)

    assert run(["plugins", QUIET], capsys) == (0, f"{QUIET} declares no commands.\n")
    code, out = run(["plugins", QUIET, "anything"], capsys)
    assert code == 1 and "declares no commands" in out
    code, out = run(["plugins"], capsys)
    assert code == 0 and f"{QUIET}" in out and "serves 'mine'" in out
    code, out = run(["plugins", "describe", QUIET], capsys)
    assert code == 0 and "supplies   (none)" in out


# --------------------------------------------------------------------------
# a plugin that is not well
# --------------------------------------------------------------------------

def test_a_broken_plugin_reports_its_import_error_and_the_listing_still_works(
        config, user_dir, capsys):
    _plant(user_dir, BROKEN, BROKEN_INIT)
    _plant(user_dir, COMMANDING, COMMANDING_INIT)
    _enabled(config, COMMANDING)

    code, out = run(["plugins", BROKEN, "setup"], capsys)
    assert code == 1
    assert "does not import" in out and "the tool is unaffected" in out

    code, out = run(["plugins"], capsys)
    assert code == 0 and COMMANDING in out and "serves 'mine'" in out


def test_a_malformed_commands_table_is_the_plugins_defect_not_a_crash(config, user_dir, capsys):
    _plant(user_dir, MALFORMED, MALFORMED_INIT)
    config({"targets": {}})

    code, out = run(["plugins", MALFORMED], capsys)

    assert code == 1
    assert "its commands could not be read" in out and "not a mapping" in out


def test_a_handler_that_raises_is_reported_with_the_command_named(config, user_dir, capsys):
    _plant(user_dir, RAISING, RAISING_INIT)
    config({"targets": {}})

    code, out = run(["plugins", RAISING, "boom"], capsys)

    assert code == 1
    assert f"`plugins {RAISING} boom` failed: ValueError: planted: the handler fell over" in out


def test_naming_a_plugin_nobody_installed_lists_what_is(config, user_dir, capsys):
    _plant(user_dir, QUIET, QUIET_INIT)
    config({"targets": {}})

    code, out = run(["plugins", "nosuchplugin"], capsys)

    assert code == 1
    assert "no plugin named 'nosuchplugin'" in out and QUIET in out


# --------------------------------------------------------------------------
# the verb's own words
# --------------------------------------------------------------------------

def _tripwire_init(marker: Path) -> str:
    """A plugin whose import leaves a file behind: the only honest import detector."""
    return (f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n"
            f"KIND = 'jsonl'\n")


@pytest.mark.parametrize("tail", [["setup"], ["--help"], []])
def test_naming_a_plugin_imports_no_plugin_the_configuration_has_not_enabled(
        config, user_dir, tmp_path, capsys, tail):
    """
    #33 as corrected: consent is per name. Naming a plugin imports it, even
    unenabled; no OTHER plugin is imported that the configuration has not
    enabled. (Enabled ones are imported by every command, this one included,
    because that is where their flags come from.) Checked by a side effect of
    the import itself, not by what the output happens to say.
    """
    marker = tmp_path / "sibling-was-imported"
    _plant(user_dir, COMMANDING, COMMANDING_INIT)
    _plant(user_dir, "plug_sibling", _tripwire_init(marker))
    config({"targets": {}})

    code, _ = run(["plugins", COMMANDING, *tail], capsys)

    assert code == 0
    assert not marker.exists(), "an unenabled plugin nobody named was imported"


def test_the_named_plugin_is_imported_even_when_nothing_enables_it(config, user_dir, tmp_path, capsys):
    """The other side of the same rule: naming it is the consent."""
    marker = tmp_path / "named-was-imported"
    _plant(user_dir, "plug_named", _tripwire_init(marker))
    config({"targets": {}})

    run(["plugins", "plug_named"], capsys)

    assert marker.exists()


def test_a_broken_enabled_plugin_does_not_stop_another_plugins_command(config, user_dir, capsys):
    """#33: a broken plugin does not prevent other plugins' commands."""
    _plant(user_dir, COMMANDING, COMMANDING_INIT)
    _plant(user_dir, BROKEN, BROKEN_INIT)
    config({"targets": {
        "mine": {"kind": "jsonl", "plugin": COMMANDING, "path": "x.jsonl"},
        "theirs": {"kind": "jsonl", "plugin": BROKEN, "path": "y.jsonl"},
    }})

    code, out = run(["plugins", COMMANDING, "setup"], capsys)

    assert code == 0
    assert "setup ran" in out


def test_help_prints_the_verbs_own_page_and_describe_needs_a_name(config, user_dir, capsys):
    _plant(user_dir, QUIET, QUIET_INIT)
    config({"targets": {}})

    code, out = run(["plugins", "help"], capsys)
    assert code == 0 and "plugins <name> <command>" in out

    code, out = run(["plugins", "describe"], capsys)
    assert code == 2 and "needs a plugin name" in out and QUIET in out


@pytest.mark.parametrize("word", ["enable", "Install", "status"])
def test_a_reserved_word_not_yet_built_says_so_instead_of_listing(config, user_dir, capsys, word):
    _plant(user_dir, QUIET, QUIET_INIT)
    config({"targets": {}})

    code, out = run(["plugins", word], capsys)

    assert code == 2
    assert f"`plugins {word.lower()}` is reserved for a later version" in out
    assert "Loaded" not in out and "Available but not loaded" not in out


def test_the_verbs_own_words_answer_in_any_case(config, user_dir, capsys):
    _plant(user_dir, QUIET, QUIET_INIT)
    _enabled(config, QUIET)

    assert run(["plugins", "LIST"], capsys) == run(["plugins"], capsys)
    code, out = run(["plugins", "Describe", QUIET], capsys)
    assert code == 0 and "supplies   (none)" in out


def test_list_is_still_the_listing(config, user_dir, capsys):
    _plant(user_dir, QUIET, QUIET_INIT)
    _enabled(config, QUIET)

    bare = run(["plugins"], capsys)
    listed = run(["plugins", "list"], capsys)

    assert bare == listed and bare[0] == 0 and "Loaded 1" in bare[1]
