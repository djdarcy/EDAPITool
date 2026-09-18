"""
Two-phase plugin discovery: scan without importing, load only what is enabled.

Before v0.7.2 a plugin was selected by a hardcoded import in ``cli.py``. That
line was the whole mechanism, so adding ``APITool/plugins/mysheet/`` produced
a directory nothing read. These tests pin the loader that replaced it, and
each one is the promoted form of a row in
``tests/one-offs/thinking/plugin-isolation/probe_second_plugin_loads.py``.

The property under test is failure ISOLATION, not "everything works": a
plugin that does not import is listed with its reason and takes nothing else
down with it. That is what lets a scanned user directory exist at all.

SAFETY (rule 1b): every plugin here is planted in ``tmp_path``; the
configuration file is redirected through ``settings.CONFIG_FILE``; the user
plugin directory through ``ED_PLUGIN_DIR``. Nothing under $HOME is touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from APITool import loader, settings

GOOD = "plug_good"
BAD = "plug_bad"

GOOD_INIT = '''
class _Layout:
    totals_tab = "Planted Tab"

def layout(**overrides):
    return _Layout()
'''

BAD_INIT = 'raise RuntimeError("planted: this plugin does not import")\n'


def _plant(directory: Path, name: str, body: str) -> Path:
    package = directory / name
    package.mkdir()
    (package / "__init__.py").write_text(body, encoding="utf-8")
    return package


@pytest.fixture
def user_dir(tmp_path: Path) -> Path:
    """A user plugin directory holding one good plugin and one that raises."""
    directory = tmp_path / "plugins"
    directory.mkdir()
    _plant(directory, GOOD, GOOD_INIT)
    _plant(directory, BAD, BAD_INIT)
    return directory


@pytest.fixture
def config(tmp_path: Path, monkeypatch, user_dir: Path):
    """Redirect the config file and the plugin directory; return a writer."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    monkeypatch.setenv("ED_PLUGIN_DIR", str(user_dir))

    def write(data: dict) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    return write


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


def test_scan_finds_shipped_and_user_plugins(user_dir):
    names = {f.name for f in loader.scan(loader.SHIPPED_DIR, user_dir)}
    assert {"settlement", GOOD, BAD} <= names


def test_scan_imports_nothing(user_dir):
    """
    The point of two phases. Importing to discover would run a broken
    plugin's side effects before anyone could decide not to load it.
    """
    # A user plugin registered by an earlier test would hide an import here
    # -- "new" is measured against what was present, so start from nothing.
    for name in [m for m in sys.modules if m.startswith(loader.USER_PACKAGE)]:
        sys.modules.pop(name)
    before = set(sys.modules)
    loader.scan(loader.SHIPPED_DIR, user_dir)
    new = {m for m in set(sys.modules) - before
           if m.startswith(loader.USER_PACKAGE) or m.startswith("APITool.plugins.")}
    assert not new, f"scan imported {sorted(new)}"


def test_scan_ignores_things_that_are_not_packages(user_dir):
    (user_dir / "notes.txt").write_text("not a plugin", encoding="utf-8")
    (user_dir / "_private").mkdir()
    (user_dir / "_private" / "__init__.py").write_text("", encoding="utf-8")
    (user_dir / "loose_dir").mkdir()  # no __init__.py
    names = {f.name for f in loader.scan(None, user_dir)}
    assert names == {GOOD, BAD}


def test_a_user_plugin_shadows_a_shipped_one_and_says_so(user_dir):
    _plant(user_dir, "settlement", GOOD_INIT)
    found = {f.name: f for f in loader.scan(loader.SHIPPED_DIR, user_dir)}
    shadowing = found["settlement"]
    assert shadowing.origin == loader.ORIGIN_USER
    assert shadowing.location == user_dir / "settlement"
    assert shadowing.shadows == loader.SHIPPED_DIR / "settlement"

    result = loader.load(list(found.values()), ["settlement"])
    assert result.first().module.layout().totals_tab == "Planted Tab"
    assert any("shadows the shipped plugin" in line for line in result.describe())


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def test_load_imports_only_what_is_enabled(user_dir):
    found = loader.scan(None, user_dir)
    result = loader.load(found, [GOOD])
    assert [e.name for e in result.loaded] == [GOOD]
    assert [f.name for f in result.available] == [BAD]
    assert result.broken == []


def test_a_broken_plugin_is_listed_with_its_reason_and_stops_nothing(user_dir):
    """
    The property the whole loader exists for. Enable the bad one FIRST so
    that a fatal failure would also have prevented the good one loading.
    """
    found = loader.scan(None, user_dir)
    result = loader.load(found, [BAD, GOOD])
    assert [e.name for e in result.loaded] == [GOOD]
    assert len(result.broken) == 1
    assert result.broken[0].name == BAD
    assert "RuntimeError" in result.broken[0].reason
    assert "planted" in result.broken[0].reason
    assert any(line.startswith(f"BROKEN    {BAD}") for line in result.describe())


def test_a_broken_plugin_is_not_left_half_imported(user_dir):
    found = loader.scan(None, user_dir)
    loader.load(found, [BAD])
    assert f"{loader.USER_PACKAGE}.{BAD}" not in sys.modules


def test_enabling_a_plugin_that_does_not_exist_is_reported_not_silent(user_dir):
    found = loader.scan(None, user_dir)
    result = loader.load(found, ["nothere"])
    assert result.loaded == []
    assert result.broken[0].name == "nothere"
    assert "not found" in result.broken[0].reason


def test_load_keeps_the_enabled_order_as_precedence(user_dir):
    _plant(user_dir, "plug_second", GOOD_INIT)
    found = loader.scan(None, user_dir)
    assert [e.name for e in loader.load(found, ["plug_second", GOOD]).loaded] == ["plug_second", GOOD]
    assert [e.name for e in loader.load(found, [GOOD, "plug_second"]).loaded] == [GOOD, "plug_second"]


def test_first_is_the_first_enabled_not_the_last(user_dir):
    """
    Mutation survivor, pinned: ``first()`` returning ``loaded[-1]`` passed
    every test above, because none of them loaded two plugins and asked.
    """
    _plant(user_dir, "plug_second", GOOD_INIT)
    found = loader.scan(None, user_dir)
    assert loader.load(found, ["plug_second", GOOD]).first().name == "plug_second"
    assert loader.load(found, [GOOD, "plug_second"]).first().name == GOOD


# ---------------------------------------------------------------------------
# what configuration enables
# ---------------------------------------------------------------------------


def test_no_targets_means_the_shipped_plugins(user_dir):
    """
    Every install from before v0.7.2 has no ``targets`` map, and must behave
    exactly as it did. The user directory's plugins are found but not turned
    on by their mere presence.
    """
    found = loader.scan(loader.SHIPPED_DIR, user_dir)
    assert loader.enabled_from({}, found) == ["settlement"]


def test_targets_enable_exactly_what_they_name_in_order(user_dir):
    found = loader.scan(loader.SHIPPED_DIR, user_dir)
    targets = {
        "b": settings.Target("b", "gsheet", BAD),
        "g": settings.Target("g", "gsheet", GOOD),
        "again": settings.Target("again", "gsheet", GOOD),
    }
    assert loader.enabled_from(targets, found) == [BAD, GOOD]


def test_discover_reads_targets_from_the_config_file(config):
    config({"targets": {
        "mine": {"kind": "gsheet", "plugin": GOOD},
        "theirs": {"kind": "gsheet", "plugin": BAD},
    }})
    result = loader.discover()
    assert result.first().name == GOOD
    assert [e.name for e in result.broken] == [BAD]
    assert "settlement" in {f.name for f in result.available}


def test_discover_with_no_config_loads_the_shipped_plugin(config):
    result = loader.discover()
    assert result.first().name == "settlement"
    assert {f.name for f in result.available} == {GOOD, BAD}


def test_discover_honours_an_explicit_user_dir(config, tmp_path, monkeypatch):
    """
    Mutation survivor, pinned: every other test reaches ``discover()``
    through ``ED_PLUGIN_DIR``, so a loader that ignored its argument and
    re-read the environment was indistinguishable from one that did not.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _plant(elsewhere, "plug_elsewhere", GOOD_INIT)
    monkeypatch.setenv("ED_PLUGIN_DIR", str(tmp_path / "does-not-exist"))
    config({"targets": {"e": {"kind": "gsheet", "plugin": "plug_elsewhere"}}})
    assert loader.discover(user_dir=elsewhere).first().name == "plug_elsewhere"


# ---------------------------------------------------------------------------
# the user plugin directory
# ---------------------------------------------------------------------------


def test_plugin_dir_from_the_environment_expands_home(monkeypatch):
    monkeypatch.setenv("ED_PLUGIN_DIR", "~/my-plugins")
    assert settings.get_plugin_dir() == Path.home() / "my-plugins"


def test_plugin_dir_from_the_file_expands_home(config, monkeypatch):
    monkeypatch.delenv("ED_PLUGIN_DIR")
    config({"plugin_dir": "~/my-plugins"})
    assert settings.get_plugin_dir() == Path.home() / "my-plugins"


@pytest.mark.parametrize("bad", [42, "", ["a"]])
def test_a_malformed_plugin_dir_is_refused_by_name(config, monkeypatch, bad):
    """
    The settings module's rule, applied here too: a malformed entry refuses
    the run and names itself. A mutation sweep found the first version of
    this coercing a number to a string instead.
    """
    monkeypatch.delenv("ED_PLUGIN_DIR")
    config({"plugin_dir": bad})
    with pytest.raises(ValueError, match='"plugin_dir" must be a non-empty string'):
        settings.get_plugin_dir()


def test_the_default_plugin_dir_is_used_when_nothing_names_one(config, monkeypatch):
    monkeypatch.delenv("ED_PLUGIN_DIR")
    config({})
    assert settings.get_plugin_dir() == settings.PLUGIN_DIR


@pytest.mark.parametrize("entry,missing", [
    ({"plugin": GOOD}, "kind"),
    ({"kind": "gsheet"}, "plugin"),
    ({"kind": "", "plugin": GOOD}, "kind"),
])
def test_a_malformed_target_names_itself(config, entry, missing):
    config({"targets": {"broken-entry": entry}})
    with pytest.raises(ValueError, match=rf"targets\['broken-entry'\] has no \"{missing}\""):
        settings.get_targets()


def test_targets_that_are_not_an_object_are_refused(config):
    config({"targets": ["settlement"]})
    with pytest.raises(ValueError, match='"targets" must be an object'):
        settings.get_targets()


# ---------------------------------------------------------------------------
# the shipped plugin's loader-facing surface
# ---------------------------------------------------------------------------


def test_the_shipped_plugin_keeps_an_explicit_empty_override():
    """
    Mutation survivor, pinned. ``layout()`` drops overrides that are None --
    a flag nobody gave -- and must keep everything else, including a value
    that happens to be falsy. A person who typed ``--totals-tab ""`` meant
    it, and silently substituting the default is the failure the settings
    module refuses everywhere else.
    """
    from APITool.plugins import settlement

    assert settlement.layout(totals_tab="").totals_tab == ""
    default = settlement.SheetLayout().totals_tab
    assert settlement.layout(totals_tab=None).totals_tab == default


# ---------------------------------------------------------------------------
# core builds the enforcer from the plugin's declaration (V2, check C6)
# ---------------------------------------------------------------------------
#
# Promoted from tests/one-offs/thinking/plugin-isolation/poc_subscriber_model.py
# (H6), where it ran 8/8 with its control arm firing. The plugin says WHERE;
# core decides WHETHER.


class _CountingSheet:
    def __init__(self):
        self.writes = 0

    def batch_update(self, data):
        self.writes += 1


class _BuggyPlugin:
    """
    Declares one range, then writes over another.

    Not malice -- a transposed constant. The column it hits is the one that
    holds formulas a person maintains, and the project has a test named for
    exactly that cell range.
    """

    def writes(self):
        return {"Data": ["L5:L24"]}

    def write(self, guard, sheet):
        if guard is not None:
            guard.check("Data", "B5:B24")
        sheet.batch_update([{"range": "B5:B24", "values": [[""]]}])
        return "wrote OUTSIDE its declaration"


def test_a_plugin_policing_itself_does_not_catch_its_own_bad_write():
    """
    THE CONTROL ARM. A plugin trusted to build its own guard can build a
    permissive one -- or, as here, none. Nothing outside it notices, and
    the write lands. This test is what makes the next one mean something.
    """
    from APITool.sheets import WriteRefused

    sheet = _CountingSheet()
    try:
        _BuggyPlugin().write(None, sheet)
        blocked = False
    except WriteRefused:
        blocked = True
    assert not blocked
    assert sheet.writes == 1


def test_a_guard_core_builds_from_the_declaration_refuses_the_bad_write():
    """
    Core builds the enforcer from the plugin's OWN declaration and hands it
    in. The same transposed constant is now refused before the sheet is
    reached, and the refusal names what was permitted.
    """
    from APITool.sheets import WriteRefused

    plugin = _BuggyPlugin()
    sheet = _CountingSheet()
    guard = loader.build_enforcer(loader.GSHEET, plugin.writes())
    with pytest.raises(WriteRefused, match=r"refusing to write Data!B5:B24.*Permitted: Data!L5:L24"):
        plugin.write(guard, sheet)
    assert sheet.writes == 0


def test_an_honest_plugin_is_unaffected_by_the_guard_being_cores():
    class Honest:
        def writes(self):
            return {"Data": ["L5:L24"]}

        def write(self, guard, sheet):
            guard.check("Data", "L5:L24")
            sheet.batch_update([{"range": "L5:L24", "values": [["*"]]}])

    sheet = _CountingSheet()
    Honest().write(loader.build_enforcer(loader.GSHEET, Honest().writes()), sheet)
    assert sheet.writes == 1


def test_an_unknown_kind_is_refused_and_names_the_known_ones():
    with pytest.raises(ValueError, match=r"unknown target kind 'parchment'; known kinds: gsheet"):
        loader.build_enforcer("parchment", {"Data": ["A1"]})
    with pytest.raises(ValueError, match="unknown target kind None"):
        loader.build_enforcer(None, {"Data": ["A1"]})


def test_the_writer_cannot_be_built_without_a_guard():
    """
    A fence: the writer used to fall back to ``layout.guard()``, which made
    the plugin its own safety boundary. Now nothing inside the plugin can
    produce a guard; only the caller can, and the caller is core.
    """
    from APITool.plugins.settlement.markers import MarketRenderer
    from APITool.plugins.settlement.totals import TotalsTabWriter

    with pytest.raises(TypeError, match="guard"):
        TotalsTabWriter(object(), MarketRenderer())


def test_the_shipped_plugin_declares_rather_than_guards():
    from APITool.plugins.settlement.layout import SheetLayout

    layout = SheetLayout()
    assert not hasattr(layout, "guard")
    declared = layout.writes()
    guard = loader.build_enforcer(loader.GSHEET, declared)
    assert guard.allows(layout.totals_tab, layout.marker_range(20))
    assert guard.allows(layout.totals_tab, layout.system_cell)
    assert not guard.allows(layout.totals_tab, f"{layout.name_column}5:{layout.name_column}24")


def test_a_targets_kind_overrides_the_plugins_own_and_absence_falls_back(user_dir):
    _plant(user_dir, "plug_kinded", GOOD_INIT + 'KIND = "gsheet"\n')
    found = loader.scan(loader.SHIPPED_DIR, user_dir)
    by_name = {e.name: e for e in loader.load(found, ["plug_kinded", GOOD, "settlement"]).loaded}
    assert by_name["plug_kinded"].kind == "gsheet"      # its own KIND
    assert by_name[GOOD].kind is None                    # no KIND, no target
    assert by_name["settlement"].kind == "gsheet"        # the shipped plugin's own

    configured = loader.load(found, [GOOD, "settlement"], kinds={GOOD: "jsonl", "settlement": "parchment"})
    kinds = {e.name: e.kind for e in configured.loaded}
    assert kinds == {GOOD: "jsonl", "settlement": "parchment"}


def test_kinds_come_from_the_first_target_naming_a_plugin():
    targets = {
        "a": settings.Target("a", "gsheet", "p"),
        "b": settings.Target("b", "jsonl", "p"),
        "c": settings.Target("c", "jsonl", "q"),
    }
    assert loader.kinds_from(targets) == {"p": "gsheet", "q": "jsonl"}


def test_the_daemon_hands_the_composition_roots_guard_to_the_service(monkeypatch, tmp_path):
    """
    Mutation survivor, pinned: ``daemon.build`` dropping its ``guard`` on
    the way into the service was exercised by nothing, because no test
    calls ``build`` -- it constructs a real exporter. Capture-and-abort:
    the service stand-in records what it was handed and raises, so the
    real exporter is never reached (rule 1b) and the assertion is exactly
    the pass-through.
    """
    from APITool import daemon
    from APITool.plugins.settlement.layout import SheetLayout

    class Stop(Exception):
        pass

    seen = {}

    class Recording:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            raise Stop

    monkeypatch.setattr(daemon, "MarketRefreshService", Recording)
    sentinel = loader.build_enforcer(loader.GSHEET, {"Only": ["A1"]})
    with pytest.raises(Stop):
        daemon.build(sheet_id="unused", journal_dir=tmp_path, layout=SheetLayout(), guard=sentinel)
    assert seen["guard"] is sentinel


def test_the_service_builds_the_guard_from_the_declaration_when_handed_none():
    """
    A caller that passes no guard gets core's construction, not the
    plugin's: the same declaration, the same enforcer, built in core.
    """
    from APITool.plugins.settlement.layout import SheetLayout
    from APITool.service import MarketRefreshService

    layout = SheetLayout(marker_column="O")
    service = MarketRefreshService(layout=layout)
    assert service.guard.allows(layout.totals_tab, "O5:O30")
    assert not service.guard.allows(layout.totals_tab, "L5:L30")


# ---------------------------------------------------------------------------
# two plugins declaring the same cells (V5, check C7)
# ---------------------------------------------------------------------------
#
# `severity` answers "did you mean this?"; `precedence` answers "who wins
# when you did?". Two knobs, because `ignore` must not be the only way to
# get a deterministic winner.


def _declaring(tab: str, rng: str, kind: str = "gsheet") -> str:
    return (GOOD_INIT
            + f'KIND = "{kind}"\n'
            + f'def writes():\n    return {{"{tab}": ["{rng}"]}}\n')


@pytest.fixture
def overlapping(user_dir: Path) -> list[loader.Found]:
    """Three plugins: A and B overlap on one tab; C touches neither."""
    _plant(user_dir, "plug_a", _declaring("Data", "L5:L24"))
    _plant(user_dir, "plug_b", _declaring("Data", "L20:L30"))
    _plant(user_dir, "plug_c", _declaring("Data", "B1:B2"))
    return loader.scan(None, user_dir)


def test_overlapping_declarations_are_refused_under_error(overlapping):
    with pytest.raises(loader.PluginConflict) as caught:
        loader.load(overlapping, ["plug_a", "plug_b", "plug_c"])
    message = str(caught.value)
    assert "plug_a / plug_b: Data!L5:L24 overlaps L20:L30" in message
    assert "plug_c" not in message
    assert "severity to 'warn'" in message


def test_error_is_the_default_severity(overlapping):
    with pytest.raises(loader.PluginConflict):
        loader.load(overlapping, ["plug_a", "plug_b"])


def test_overlapping_declarations_load_in_order_under_warn(overlapping):
    result = loader.load(overlapping, ["plug_a", "plug_b", "plug_c"], severity=loader.SEVERITY_WARN)
    assert [e.name for e in result.loaded] == ["plug_a", "plug_b", "plug_c"]
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert (conflict.first, conflict.second, conflict.kind) == ("plug_a", "plug_b", "gsheet")
    assert conflict.where == "Data!L5:L24 overlaps L20:L30"
    assert any(line.startswith("CONFLICT  plug_a / plug_b") and "plug_a takes precedence" in line
               for line in result.describe())


def test_overlap_is_silent_under_ignore(overlapping):
    result = loader.load(overlapping, ["plug_a", "plug_b"], severity=loader.SEVERITY_IGNORE)
    assert [e.name for e in result.loaded] == ["plug_a", "plug_b"]
    assert result.conflicts == []
    assert not any("CONFLICT" in line for line in result.describe())


def test_precedence_decides_who_wins_without_changing_what_is_enabled(overlapping):
    result = loader.load(overlapping, ["plug_a", "plug_b"],
                         severity=loader.SEVERITY_WARN, precedence=["plug_b", "plug_a"])
    assert [e.name for e in result.loaded] == ["plug_b", "plug_a"]
    assert result.first().name == "plug_b"
    assert (result.conflicts[0].first, result.conflicts[0].second) == ("plug_b", "plug_a")


def test_precedence_names_it_does_not_know_go_last_and_are_ignored(overlapping):
    result = loader.load(overlapping, ["plug_a", "plug_c"],
                         severity=loader.SEVERITY_WARN, precedence=["nothere", "plug_c"])
    assert [e.name for e in result.loaded] == ["plug_c", "plug_a"]


def test_different_kinds_never_conflict(overlapping):
    """A sheet range and a file path have no cell in common."""
    result = loader.load(overlapping, ["plug_a", "plug_b"], kinds={"plug_b": "jsonl"})
    assert [e.name for e in result.loaded] == ["plug_a", "plug_b"]
    assert result.conflicts == []


def test_a_plugin_that_declares_nothing_cannot_conflict(overlapping):
    result = loader.load(overlapping, [GOOD, "plug_a"])
    assert {e.name: e.declaration for e in result.loaded} == {GOOD: None, "plug_a": {"Data": ["L5:L24"]}}
    assert result.conflicts == []


def test_the_severity_words_are_the_ones_a_person_will_type(overlapping):
    """
    Mutation survivor, pinned. Every other test passes the constants, so a
    misspelled constant was invisible -- but "error", "warn" and "ignore"
    are the vocabulary a configuration file will carry, and the literals
    must be what the loader accepts.
    """
    assert loader.SEVERITIES == ("error", "warn", "ignore")
    with pytest.raises(loader.PluginConflict):
        loader.load(overlapping, ["plug_a", "plug_b"], severity="error")
    warned = loader.load(overlapping, ["plug_a", "plug_b"], severity="warn")
    assert len(warned.conflicts) == 1
    ignored = loader.load(overlapping, ["plug_a", "plug_b"], severity="ignore")
    assert ignored.conflicts == [] and len(ignored.loaded) == 2


def test_an_unknown_severity_is_refused(overlapping):
    with pytest.raises(ValueError, match="severity must be one of error, warn, ignore"):
        loader.load(overlapping, ["plug_a"], severity="shrug")


def test_the_shipped_plugins_module_declaration_is_its_layouts():
    """One definition: the module-level writes() the loader reads at load is the layout's."""
    from APITool.plugins import settlement

    assert settlement.writes() == settlement.SheetLayout().writes()
    loaded = loader.load(loader.scan(loader.SHIPPED_DIR, None), ["settlement"]).first()
    assert loaded.declaration == settlement.writes()


def test_a_configured_overlap_is_reported_by_the_command_not_a_traceback(config, overlapping):
    from APITool import cli

    config({"targets": {
        "one": {"kind": "gsheet", "plugin": "plug_a"},
        "two": {"kind": "gsheet", "plugin": "plug_b"},
    }})
    with pytest.raises(loader.PluginConflict):
        loader.discover()
    destination, problem = cli._resolve_destination()
    assert destination is None
    assert "Data!L5:L24 overlaps L20:L30" in problem
    assert cli._destination_defaults().totals_tab is None


# ---------------------------------------------------------------------------
# the composition root asks the loader
# ---------------------------------------------------------------------------


def test_the_cli_takes_its_defaults_from_the_configured_plugin(config):
    from APITool import cli

    config({"targets": {"mine": {"kind": "gsheet", "plugin": GOOD}}})
    assert cli._destination_defaults().totals_tab == "Planted Tab"


def test_a_plugin_without_this_workbooks_flags_still_lets_the_parser_build(config):
    """
    The probe's finding, pinned. The planted plugin's layout has no
    ``need_header``, and ``main()`` read it as a bare attribute to default a
    flag -- so a second plugin of a different shape crashed ``--version``.
    A flag the plugin cannot default is simply undefaulted.
    """
    from APITool import cli

    config({"targets": {"mine": {"kind": "gsheet", "plugin": GOOD}}})
    defaults = cli._destination_defaults()
    assert defaults.totals_tab == "Planted Tab"
    assert defaults.need_header is None
    try:
        code = cli.main(["--version"])
    except SystemExit as exc:
        code = exc.code
    assert code in (0, None)


RAISING_LAYOUT_INIT = 'KIND = "gsheet"\ndef layout(**overrides):\n    raise RuntimeError("layout blew up")\n'


def test_a_plugin_whose_layout_raises_does_not_take_down_version(config, user_dir):
    """
    The tester sweep's finding for v0.7.2, pinned. ``_destination_defaults``
    guarded ``discover()`` and then called ``layout()`` outside the guard, so
    a plugin that imported cleanly and raised on its layout crashed every
    command -- ``--version`` included -- with a traceback.
    """
    from APITool import cli

    _plant(user_dir, "plug_raises", RAISING_LAYOUT_INIT)
    config({"targets": {"mine": {"kind": "gsheet", "plugin": "plug_raises"}}})
    assert cli._destination_defaults().totals_tab is None
    try:
        code = cli.main(["--version"])
    except SystemExit as exc:
        code = exc.code
    assert code in (0, None)


def test_a_plugin_whose_layout_raises_is_reported_by_name(config, user_dir):
    from APITool import cli

    _plant(user_dir, "plug_raises", RAISING_LAYOUT_INIT)
    config({"targets": {"mine": {"kind": "gsheet", "plugin": "plug_raises"}}})
    destination, problem = cli._resolve_destination()
    assert destination is not None and problem is None
    layout, problem = cli._plugin_layout(destination, totals_tab="x")
    assert layout is None
    assert problem == "Error: plugin 'plug_raises' could not build its layout: RuntimeError: layout blew up"


def test_the_cli_has_no_defaults_when_the_configured_plugin_is_broken(config):
    from APITool import cli

    config({"targets": {"mine": {"kind": "gsheet", "plugin": BAD}}})
    assert cli._destination_defaults().totals_tab is None


def test_a_command_that_needs_a_destination_reports_the_listing(config, capsys):
    from APITool import cli

    config({"targets": {"mine": {"kind": "gsheet", "plugin": BAD}}})
    destination, problem = cli._resolve_destination()
    assert destination is None
    assert "no destination plugin is loaded" in problem
    assert f"BROKEN    {BAD}" in problem
    assert "available settlement" in problem
