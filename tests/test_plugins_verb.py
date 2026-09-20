"""
`edapitool plugins` -- what is installed, what is on, and what broke.

The verb is split along consent, and these tests hold that line: `list`
imports only what configuration already enables, because you asked for those
by configuring them; `describe` imports the one plugin you name, because
naming it is the asking. A plugin sitting in the directory that nobody has
configured is reported from the scan and never run.

Nothing here touches a real home directory or a real config file: every test
redirects `settings.CONFIG_FILE` and `ED_PLUGIN_DIR` at a tmp_path.
"""

import json
import sys
from pathlib import Path

import pytest

from APITool import settings

GOOD_INIT = '''
KIND = "gsheet"

class _Layout:
    totals_tab = "Planted Tab"
    def writes(self):
        return {"Planted Tab": ["A1:B2"]}

def layout(**overrides):
    return _Layout()

def writes():
    return {"Planted Tab": ["A1:B2"]}

def supplies():
    return {"planted": lambda ctx: None}

def subscribes():
    from APITool.registry import Subscription
    return [Subscription("planted-out", (), lambda ctx: "ok")]

def default_config():
    return {"a_key": "a value"}
'''

BAD_INIT = 'raise RuntimeError("planted: this plugin does not import")\n'


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


def run(argv, capsys):
    from APITool import cli

    code = cli.main(argv)
    return code, capsys.readouterr().out


def test_list_reports_loaded_broken_and_available_each_with_a_reason(
        config, user_dir, capsys):
    """
    The section that matters is the third: a plugin that did not load is
    named, with why, and with the fact that nothing else was affected.
    """
    _plant(user_dir, "plug_on", GOOD_INIT)
    _plant(user_dir, "plug_broken", BAD_INIT)
    _plant(user_dir, "plug_idle", GOOD_INIT)
    config({"targets": {
        "mine": {"kind": "gsheet", "plugin": "plug_on"},
        "theirs": {"kind": "gsheet", "plugin": "plug_broken"},
    }})

    code, out = run(["plugins"], capsys)

    assert code == 0
    assert "plug_on" in out and "serves 'mine'" in out
    assert "NOT loaded" in out and "plug_broken" in out
    assert "does not import" in out, "the reason, not just the fact"
    assert "the tool is unaffected" in out, "and a remedy for the alarm"
    assert "Available but not loaded" in out and "plug_idle" in out
    assert "never configured" in out


def test_describe_shows_what_the_configured_target_makes_it_write(
        config, user_dir, tmp_path, capsys):
    """
    `describe` answers about the plugin AS CONFIGURED, not as shipped.

    A file plugin declares nothing until a target gives it a path -- that is
    correct and deliberate. But `describe` was re-loading the named plugin
    without the targets map, so a configured jsonl destination reported
    "writes nothing as shipped" while it was in fact about to append to a
    file. Found by writing the v0.7.5 checklist, which asserted the honest
    behaviour before the code had it.
    """
    out_file = tmp_path / "obs.jsonl"
    config({"targets": {"observations": {
        "kind": "jsonl", "plugin": "jsonl", "path": str(out_file),
    }}})

    code, out = run(["plugins", "describe", "jsonl"], capsys)

    assert code == 0
    assert str(out_file) in out, "the path its target gives it"
    assert "nothing as shipped" not in out


def test_describe_says_shipped_when_nothing_is_configured(config, user_dir, capsys):
    """The other half: with no target, declaring nothing is the honest answer."""
    config({"client_id": "abc"})

    code, out = run(["plugins", "describe", "jsonl"], capsys)

    assert code == 0
    # The column padding between "writes" and its value is why this matches
    # on the value alone -- an assertion carrying the exact run of spaces
    # breaks the first time a column widens, and says nothing about the
    # behaviour under test.
    assert "nothing as shipped" in out


def test_the_listing_never_opens_on_a_blank_line(config, user_dir, capsys):
    """
    A blank line separates sections; it does not precede the first one.

    Now that an unconfigured install loads nothing -- the ordinary state of a
    fresh one, since the core ships no destination -- the first section a
    person sees is usually "Available but not loaded", and it was opening on
    a stray empty line. Checked in both arrangements, because the defect was
    invisible in the one where something loaded first.
    """
    _plant(user_dir, "plug_idle", GOOD_INIT)
    config({"client_id": "abc"})
    code, out = run(["plugins"], capsys)
    assert code == 0
    assert out.startswith("Available but not loaded"), repr(out[:40])

    config({"targets": {"mine": {"kind": "gsheet", "plugin": "plug_idle"}}})
    _, out = run(["plugins"], capsys)
    assert out.startswith("Loaded"), repr(out[:40])


def test_list_does_not_import_a_plugin_nobody_configured(config, user_dir, capsys):
    """
    The consent line, asserted rather than described: a plugin present in
    the directory but named by no target is reported and never executed.
    """
    _plant(user_dir, "plug_untouched", GOOD_INIT)
    config({"targets": {}})
    for mod in [m for m in sys.modules if "plug_untouched" in m]:
        del sys.modules[mod]

    code, out = run(["plugins"], capsys)

    assert code == 0
    assert "plug_untouched" in out
    assert not any("plug_untouched" in m for m in sys.modules), \
        "listing a plugin must not run it"


def test_describe_imports_the_one_plugin_named_and_shows_its_contract(
        config, user_dir, capsys):
    _plant(user_dir, "plug_detail", GOOD_INIT)
    config({"targets": {}})

    code, out = run(["plugins", "describe", "plug_detail"], capsys)

    assert code == 0
    assert "kind       gsheet" in out
    assert "Planted Tab: A1:B2" in out, "what it declares it writes"
    assert "planted" in out, "what it supplies"
    assert "planted-out" in out, "what it subscribes"
    assert '"a_key"' in out, "the starter block it offers"


def test_describe_names_what_it_does_not_have(config, user_dir, capsys):
    _plant(user_dir, "plug_detail", GOOD_INIT)
    config({"targets": {}})

    code, out = run(["plugins", "describe", "nosuchplugin"], capsys)

    assert code == 1
    assert "no plugin named 'nosuchplugin'" in out
    assert "plug_detail" in out, "and says what there is instead"


def test_describe_reports_a_plugin_that_will_not_import(config, user_dir, capsys):
    _plant(user_dir, "plug_broken", BAD_INIT)
    config({"targets": {}})

    code, out = run(["plugins", "describe", "plug_broken"], capsys)

    assert code == 1
    assert "did not load" in out and "does not import" in out


def test_list_reports_a_malformed_targets_map_rather_than_crashing(
        config, user_dir, capsys):
    _plant(user_dir, "plug_on", GOOD_INIT)
    config({"targets": {"mine": {"kind": "gsheet"}}})

    code, out = run(["plugins"], capsys)

    assert code == 1
    assert "targets['mine'] has no \"plugin\"" in out
    assert "Traceback" not in out


def test_list_repeats_what_a_plugin_said_about_its_own_configuration(
        config, user_dir, capsys):
    """The verb is where a config complaint is meant to be seen."""
    _plant(user_dir, "plug_fussy", GOOD_INIT + '''
def check_config(config):
    return ["this plugin is unhappy with its block"] if config else []
''')
    config({"targets": {"mine": {"kind": "gsheet", "plugin": "plug_fussy",
                                 "config": {"anything": 1}}}})

    code, out = run(["plugins"], capsys)

    assert code == 0
    assert "CONFIG mine: this plugin is unhappy with its block" in out
