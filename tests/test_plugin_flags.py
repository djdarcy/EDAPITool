"""
A plugin's flags are its own: declared by the plugin, registered by core only
when that plugin is loaded, and passed back to it unread.

The rule these tests hold (#28, restated): whose vocabulary is this? A word
that means something with no plugin loaded is core's; every other word is a
plugin's, and an install without that plugin never sees it.

Planted plugins live under ``ED_PLUGIN_DIR`` in ``tmp_path``; the config
file is the conftest's scratch one. Nothing under $HOME is touched, and no
command here reaches a sheet.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from APITool import loader, settings
from APITool.cli import main
from APITool.loader import PluginConflict
from APITool.registry import Flag

FLAGGED = "plug_flagged"
FLAGGED_INIT = '''
from APITool.registry import Flag

KIND = "jsonl"

class _Layout:
    totals_tab = None
    def writes(self):
        return {}

def layout(**overrides):
    return _Layout()

def flags():
    return [
        Flag("market", "--planted-word", "planted_word", "string",
             help="a word only this plugin knows", default="dune"),
        Flag("serve", "--planted-switch", "planted_switch", "store_true",
             help="a switch only this plugin knows"),
    ]
'''

RIVAL = "plug_rival"
RIVAL_INIT = '''
from APITool.registry import Flag

KIND = "jsonl"

def flags():
    return [Flag("market", "--planted-word", "planted_word", "string", help="mine too")]
'''

QUIET = "plug_quiet"
QUIET_INIT = 'KIND = "jsonl"\n'


def _plant(directory: Path, name: str, body: str) -> Path:
    package = directory / name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(body, encoding="utf-8")
    return package


@pytest.fixture
def user_dir(tmp_path: Path, monkeypatch) -> Path:
    directory = tmp_path / "plugins"
    directory.mkdir()
    monkeypatch.setenv("ED_PLUGIN_DIR", str(directory))
    return directory


@pytest.fixture
def config(monkeypatch):
    """Write a targets block to the conftest's scratch config file."""
    def write(targets: dict) -> None:
        settings.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        settings.CONFIG_FILE.write_text(json.dumps({"targets": targets}), encoding="utf-8")
    return write


def _target(plugin: str) -> dict:
    return {"kind": "jsonl", "plugin": plugin, "config": {"path": "out.jsonl"}}


def _help(capsys, *argv) -> str:
    with pytest.raises(SystemExit) as stop:
        main(list(argv))
    assert stop.value.code == 0
    return capsys.readouterr().out


# --------------------------------------------------------------------------
# declared, registered only when loaded
# --------------------------------------------------------------------------

def test_a_declared_flag_is_in_the_help_only_when_its_plugin_is_configured(user_dir, config, capsys):
    _plant(user_dir, FLAGGED, FLAGGED_INIT)

    before = _help(capsys, "market", "--help")
    assert "--planted-word" not in before
    assert f"the {FLAGGED} plugin" not in before

    config({"mine": _target(FLAGGED)})
    after = _help(capsys, "market", "--help")
    assert "--planted-word" in after
    assert f"the {FLAGGED} plugin:" in after         # its own group, under its own name


def test_a_flag_declared_for_serve_does_not_appear_on_market(user_dir, config, capsys):
    _plant(user_dir, FLAGGED, FLAGGED_INIT)
    config({"mine": _target(FLAGGED)})
    assert "--planted-switch" not in _help(capsys, "market", "--help")
    assert "--planted-switch" in _help(capsys, "serve", "--help")


def test_the_loader_reads_the_declaration_once_at_load(user_dir, config):
    _plant(user_dir, FLAGGED, FLAGGED_INIT)
    config({"mine": _target(FLAGGED)})
    result = loader.discover()
    entry = result.first()
    assert entry is not None and entry.name == FLAGGED
    assert [(f.verb, f.name) for f in entry.flags] == [
        ("market", "--planted-word"), ("serve", "--planted-switch")]


def test_a_plugin_that_declares_nothing_has_no_flags_and_no_group(user_dir, config, capsys):
    _plant(user_dir, QUIET, QUIET_INIT)
    config({"mine": _target(QUIET)})
    assert loader.discover().first().flags == ()
    assert f"the {QUIET} plugin" not in _help(capsys, "market", "--help")


# --------------------------------------------------------------------------
# collisions and reserved names
# --------------------------------------------------------------------------

def test_two_plugins_declaring_the_same_flag_are_refused_naming_both(user_dir, config):
    _plant(user_dir, FLAGGED, FLAGGED_INIT)
    _plant(user_dir, RIVAL, RIVAL_INIT)
    config({"one": _target(FLAGGED), "two": _target(RIVAL)})
    with pytest.raises(PluginConflict) as caught:
        loader.discover()
    message = str(caught.value)
    assert "--planted-word" in message and FLAGGED in message and RIVAL in message


def test_a_plugin_named_a_reserved_word_is_refused_by_name_and_the_listing_goes_on(
        user_dir, config, capsys):
    _plant(user_dir, "list", QUIET_INIT)
    _plant(user_dir, QUIET, QUIET_INIT)
    config({"one": _target("list"), "two": _target(QUIET)})
    result = loader.discover()
    assert [b.name for b in result.broken] == ["list"]
    assert "reserved" in result.broken[0].reason and "list" in result.broken[0].reason
    assert [e.name for e in result.loaded] == [QUIET]          # the other still loads

    assert main(["plugins"]) == 0
    out = capsys.readouterr().out
    assert "NOT loaded 1:" in out and "reserved" in out
    assert QUIET in out


def test_an_installed_reserved_name_is_reported_as_such_even_when_not_enabled(user_dir, capsys):
    _plant(user_dir, "describe", QUIET_INIT)
    assert main(["plugins"]) == 0
    out = capsys.readouterr().out
    assert "describe" in out and "RESERVED" in out


@pytest.mark.parametrize("directory, word", [
    ("List", "list"),          # a reserved word in another case
    ("enable", "enable"),      # reserved now, built later: held back from plugins
    ("INSTALL", "install"),
])
def test_every_reserved_word_is_refused_in_any_case_naming_plugin_and_word(
        user_dir, config, directory, word):
    """
    The verb keeps sixteen words, three of them built. The other thirteen are
    refused now so that building one later never breaks a plugin of that name,
    and case does not matter, because `plugins List` must not reach something
    `plugins list` does not.
    """
    _plant(user_dir, directory, QUIET_INIT)
    config({"one": _target(directory)})
    result = loader.discover()
    assert [b.name for b in result.broken] == [directory]
    reason = result.broken[0].reason
    assert repr(directory) in reason and repr(word) in reason and "reserved" in reason
    assert result.loaded == []


def test_a_plugin_whose_name_starts_with_a_dash_is_refused(user_dir, config):
    """`plugins -x` would be read as an option, so a plugin called -x is unreachable."""
    _plant(user_dir, "-dashed", QUIET_INIT)
    config({"one": _target("-dashed")})
    result = loader.discover()
    assert [b.name for b in result.broken] == ["-dashed"]
    assert "starts with '-'" in result.broken[0].reason


def test_an_ordinary_name_containing_a_reserved_word_is_not_refused(user_dir, config):
    """The rule is the whole name, not a substring: `listings` is a plugin."""
    _plant(user_dir, "listings", QUIET_INIT)
    config({"one": _target("listings")})
    result = loader.discover()
    assert [e.name for e in result.loaded] == ["listings"] and result.broken == []


# --------------------------------------------------------------------------
# what a declared flag does when registered (the sweep of 2026-09-25 found
# the first round of tests read the presence of flags, not their behaviour)
# --------------------------------------------------------------------------

CHOOSY = "plug_choosy"
CHOOSY_INIT = '''
from APITool.registry import Flag

KIND = "jsonl"

class _Layout:
    totals_tab = None
    def writes(self):
        return {}

def layout(**overrides):
    return _Layout()

def flags():
    return [
        Flag("market", "--planted-pick", "planted_pick", "choices",
             help="one of two", choices=("left", "right"), default="left"),
        Flag("market", "--planted-switch", "planted_switch", "store_true",
             help="off unless typed"),
    ]
'''


def _parsed_options(tmp_path, monkeypatch, *argv) -> dict:
    """Run market --no-sheet with a planted plugin that records its options."""
    body = CHOOSY_INIT + '''
from APITool.registry import Subscription

def writes():
    return {"__file__": ["out.jsonl"]}

def _publish(ctx):
    import json, pathlib
    pathlib.Path(__PROBE__).write_text(json.dumps(dict(ctx.options)))
    return "ok"

def subscribes():
    return [Subscription("probe", ("location",), _publish)]
'''.replace("__PROBE__", repr(str(tmp_path / "seen.json")))
    directory = tmp_path / "plugins"
    directory.mkdir(exist_ok=True)
    monkeypatch.setenv("ED_PLUGIN_DIR", str(directory))
    _plant(directory, CHOOSY, body)
    settings.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.CONFIG_FILE.write_text(
        json.dumps({"targets": {"mine": _target(CHOOSY)}}), encoding="utf-8")
    from test_service import docked_event, make_journal, ryman_market_json
    (tmp_path / "journal").mkdir(exist_ok=True)
    journal = make_journal(tmp_path / "journal", [docked_event()], ryman_market_json())
    code = main(["market", "--journal-dir", str(journal), "--no-sheet", *argv])
    assert code == 0
    return json.loads((tmp_path / "seen.json").read_text())


def test_a_choices_flag_refuses_a_value_outside_its_choices(user_dir, config, tmp_path, monkeypatch, capsys):
    _plant(user_dir, CHOOSY, CHOOSY_INIT)
    config({"mine": _target(CHOOSY)})
    with pytest.raises(SystemExit) as stop:
        main(["market", "--no-sheet", "--planted-pick", "sideways"])
    assert stop.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_an_untyped_switch_reads_false_not_none(tmp_path, monkeypatch):
    """A store_true flag nobody typed is False -- a value, not an absence."""
    seen = _parsed_options(tmp_path, monkeypatch)
    assert seen["planted_switch"] is False
    assert seen["planted_pick"] == "left"


def test_a_typed_switch_reads_true(tmp_path, monkeypatch):
    seen = _parsed_options(tmp_path, monkeypatch, "--planted-switch", "--planted-pick", "right")
    assert seen["planted_switch"] is True
    assert seen["planted_pick"] == "right"


# --------------------------------------------------------------------------
# two plugins on one workbook (v0.8.0's split)
# --------------------------------------------------------------------------

def test_the_two_shipped_sheet_plugins_load_together_without_a_conflict(
        configured_totals, configured_construction):
    """
    The roll-up tab and the construction bindings share one sheet id. That
    is not an overlap: the loader compares declared RANGES per tab, and the
    bindings declare none as shipped. The destination for `market` is the
    plugin with a layout; the region binder is the one that binds.
    """
    result = loader.discover()
    assert [e.name for e in result.loaded] == ["totals", "construction"]
    assert result.conflicts == []
    assert result.publisher().name == "totals"
    assert result.offering("construction_regions").name == "construction"


def test_a_construction_only_config_gives_market_no_destination(configured_construction, capsys):
    """
    Bindings are not a place to compare against. `--update-sheet` is core's
    word and needs a destination; with only the construction plugin loaded
    there is none, and the command says so rather than treating the
    bindings as a tab. (`--show-formula` would not do here: it is the
    roll-up plugin's word and does not exist in this install at all.)
    """
    assert main(["market", "--update-sheet"]) == 1
    assert "needs a destination plugin" in capsys.readouterr().out


def test_a_capability_is_a_function_the_plugin_offers_not_a_value_it_holds():
    """
    `offering()` asks whether a plugin can DO something, so a module that
    merely holds a truthy attribute by that name -- a tab name in `layout`,
    a list in `construction_regions` -- is not offering the capability and
    is passed over for the first plugin that defines the function. (Mutation
    survivor v0.8.0 unit 3 M01: dropping `callable()` picked the holder.)
    """
    import types

    holder = types.ModuleType("plug_holder")
    holder.layout = "Totals"
    holder.construction_regions = ["Base!A1:B2"]
    doer = types.ModuleType("plug_doer")
    doer.layout = lambda **overrides: None
    doer.construction_regions = lambda config: []
    found = loader.Found("x", Path("."), loader.ORIGIN_USER)
    result = loader.LoadResult(loaded=[
        loader.Loaded("holder", holder, found),
        loader.Loaded("doer", doer, found),
    ])

    assert result.publisher().name == "doer"
    assert result.offering("construction_regions").name == "doer"
    assert result.offering("nothing_offers_this") is None


# --------------------------------------------------------------------------
# the envelope
# --------------------------------------------------------------------------

def test_refresh_has_no_plugin_word_in_its_signature():
    """Structural: the options travel as one mapping, never as named parameters."""
    from APITool.service import MarketRefreshService

    params = list(inspect.signature(MarketRefreshService.refresh).parameters)
    assert params == ["self", "worksheet", "write", "options"]


def test_the_options_reach_the_plugin_exactly_as_typed(user_dir, config, tmp_path, monkeypatch):
    """A declared flag's value arrives in the subscriber's ctx.options under its dest."""
    seen = {}
    body = FLAGGED_INIT + '''
from APITool.registry import Subscription

def writes():
    return {"__file__": ["out.jsonl"]}

def _publish(ctx):
    import json, pathlib
    pathlib.Path(__PROBE__).write_text(json.dumps(dict(ctx.options)))
    return "ok"

def subscribes():
    return [Subscription("probe", ("location",), _publish)]
'''.replace("__PROBE__", repr(str(tmp_path / "seen.json")))
    _plant(user_dir, FLAGGED, body)
    config({"mine": _target(FLAGGED)})
    from test_service import docked_event, make_journal, ryman_market_json
    (tmp_path / "journal").mkdir()
    directory = make_journal(tmp_path / "journal", [docked_event()], ryman_market_json())

    code = main(["market", "--journal-dir", str(directory), "--no-sheet",
                 "--planted-word", "arrakis"])
    assert code == 0
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert seen["planted_word"] == "arrakis"
    assert seen["write"] is False                       # core's word rides beside it


# --------------------------------------------------------------------------
# the first run and the help
# --------------------------------------------------------------------------

def test_help_in_an_empty_config_writes_nothing(monkeypatch, capsys):
    monkeypatch.delenv("ED_NO_STOCK_CONFIG", raising=False)
    assert not settings.CONFIG_FILE.exists()
    _help(capsys, "market", "--help")
    assert not settings.CONFIG_FILE.exists()


def test_a_first_run_writes_the_stock_config_before_the_parser_is_built(monkeypatch, capsys, tmp_path):
    """
    The stock config enables the settlement plugin, whose flags are (from
    this slice on) registered only when it is loaded -- so the write must
    come first, or a first `market --force` would have no `--force`.
    """
    monkeypatch.delenv("ED_NO_STOCK_CONFIG", raising=False)
    assert not settings.CONFIG_FILE.exists()

    # `--show-formula` needs a destination, and the destination the command
    # sees is the one discovery loaded BEFORE the parser was built. On a
    # first run that is the stock config's plugin only if the file was
    # written first -- the ordering this test holds. (The `plugins` listing
    # would not do: it discovers again for itself, after the write.)
    code = main(["market", "--show-formula"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert settings.CONFIG_FILE.exists()
    assert out.startswith("Wrote a starting configuration")
    assert "needs a destination plugin" not in out
