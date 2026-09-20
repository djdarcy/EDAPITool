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


def test_no_targets_means_no_plugin_is_enabled(user_dir):
    """
    The core ships no destination (#18 criterion 6).

    Nothing is turned on by its mere presence -- not a user plugin, and not
    the one plugin this repository happens to ship. A destination is a thing
    a person configures, and an install that has configured none publishes
    open formats and nothing else. The shipped plugin is still FOUND, and
    still offered; it is simply off until a ``targets`` entry names it.
    """
    found = loader.scan(loader.SHIPPED_DIR, user_dir)
    assert loader.enabled_from({}, found) == []
    assert "settlement" in {f.name for f in found}


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


def test_a_targets_entry_carries_its_config_block_and_the_kinds_keys(config):
    """
    Core reads three keys -- ``kind``, ``plugin``, ``config`` -- and carries
    everything else for the kind. Nothing inside ``config`` is looked at, so
    a key core has never heard of travels through untouched.
    """
    config({"targets": {"mine": {
        "kind": "gsheet", "plugin": GOOD, "id": "SHEET-1", "spare": True,
        "config": {"anything": [1, 2]},
    }}})
    target = settings.get_targets()["mine"]
    assert target.config == {"anything": [1, 2]}
    assert target.params == {"id": "SHEET-1", "spare": True}
    assert loader.discover().first().target == target


def test_a_config_block_that_is_not_an_object_is_refused_by_name(config):
    config({"targets": {"mine": {"kind": "gsheet", "plugin": GOOD, "config": "nope"}}})
    with pytest.raises(ValueError, match=r"targets\['mine'\]\.config must be an object"):
        settings.get_targets()


def test_a_bare_sheet_id_names_a_spreadsheet_and_enables_nothing(config, monkeypatch):
    """
    ``sheet_id`` says WHERE, never WHO.

    It is still a first-class setting -- the plugin-free sheet commands read
    it, and a person who has never installed a plugin still needs a way to
    name a workbook. What it does not do is select a destination: that takes
    a ``targets`` entry naming a plugin, because choosing which code runs
    against a person's spreadsheet is a decision only they can make.
    """
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    config({"sheet_id": "A-SHEET", "client_id": "abc"})
    result = loader.discover()
    assert result.first() is None
    assert "settlement" in {f.name for f in result.available}
    assert settings.get_sheet_id(None) == "A-SHEET"


def test_the_first_target_naming_a_plugin_is_the_one_it_is_handed(config):
    """
    Two targets can name one plugin -- two workbooks, one plugin's shape.
    The FIRST is what that plugin is handed, the same precedence
    ``enabled_from`` and ``kinds_from`` use; a later entry must not silently
    replace the block the first one configured.
    """
    config({"targets": {
        "first": {"kind": "gsheet", "plugin": GOOD, "id": "ONE", "config": {"which": 1}},
        "second": {"kind": "gsheet", "plugin": GOOD, "id": "TWO", "config": {"which": 2}},
    }})
    entry = loader.discover().first()
    assert entry.target.name == "first"
    assert entry.target.config == {"which": 1}


def test_a_file_naming_no_target_enables_nothing(config, monkeypatch):
    """
    #18 criterion 6, at the loader: the core ships no destination.

    A file that configures the tool without configuring a destination gets a
    working tool and no destination -- not the one plugin this repository
    happens to ship, chosen on the person's behalf because it was the only
    one lying around.
    """
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    config({"client_id": "abc"})
    result = loader.discover()
    assert result.first() is None
    assert "settlement" in {f.name for f in result.available}


def test_discover_with_no_config_loads_nothing_and_offers_everything(config):
    """
    The same rule with no configuration at all, and the other half of it:
    nothing is loaded, and everything found is listed as available, so the
    person can see what they could turn on. Silence would be the failure --
    a tool that loads nothing and says nothing looks broken.
    """
    result = loader.discover()
    assert result.loaded == []
    # Both shipped plugins and both planted ones. Named rather than counted,
    # so that adding a plugin to the wheel turns this red and someone has to
    # decide it was meant -- which is exactly what happened when the jsonl
    # plugin arrived.
    assert {f.name for f in result.available} == {"settlement", "jsonl", GOOD, BAD}
    assert any("available" in line for line in result.describe())


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


# ---------------------------------------------------------------------------
# the second kind: a file, enforced in its own vocabulary
# ---------------------------------------------------------------------------
#
# Nothing here opens a file. Every assertion is about what the GUARD says,
# because a test asserting "this write is refused" must not be able to
# perform the write when the refusal stops working (rule 1b).


def test_the_file_kinds_guard_refuses_a_path_it_did_not_declare(tmp_path):
    from APITool.guard import PathGuard, WriteRefused

    declared = tmp_path / "observations.jsonl"
    guard = PathGuard.build([str(declared)])

    assert guard.allows(str(declared))
    assert not guard.allows(str(tmp_path / "somewhere-else.jsonl"))
    with pytest.raises(WriteRefused, match="outside the allowlist"):
        guard.check(str(tmp_path / "somewhere-else.jsonl"))


def test_one_file_is_one_path_however_it_is_spelled(tmp_path):
    """
    The comparison is about WHICH file is written, not how it was typed. A
    relative spelling, an absolute one and a redundant `.` segment are one
    path -- otherwise a declaration could be sidestepped by rewriting it.
    """
    from APITool.guard import PathGuard

    declared = tmp_path / "out.jsonl"
    guard = PathGuard.build([str(declared)])

    assert guard.allows(str(tmp_path / "." / "out.jsonl"))
    assert guard.allows(str(tmp_path / "sub" / ".." / "out.jsonl"))


def test_a_guard_that_declared_nothing_permits_nothing(tmp_path):
    """Deny by default, the same way the sheet kind's guard does."""
    from APITool.guard import PathGuard

    assert not PathGuard.build([]).allows(str(tmp_path / "anything.jsonl"))


def test_core_builds_the_file_kinds_enforcer_from_the_declaration(tmp_path):
    """
    The plugin declares; the KIND supplies the vocabulary; CORE builds. The
    same three-way split the sheet kind has, in a vocabulary that has no
    cells in it.
    """
    from APITool.guard import PathGuard

    declared = str(tmp_path / "out.jsonl")
    enforcer = loader.build_enforcer(loader.JSONL, {loader.JsonlKind.FILE: [declared]})

    assert isinstance(enforcer, PathGuard)
    assert enforcer.allows(declared)
    assert not enforcer.allows(str(tmp_path / "other.jsonl"))


def test_two_file_plugins_declaring_one_file_overlap(tmp_path):
    """
    The same question the sheet kind asks of cell ranges. Two plugins
    appending to one file interleave their records and nobody can tell
    afterwards whose is whose, so it is a conflict exactly as an overlapping
    range is.
    """
    one = str(tmp_path / "shared.jsonl")
    two = str(tmp_path / "sub" / ".." / "shared.jsonl")   # the same file, spelled differently
    other = str(tmp_path / "mine.jsonl")

    assert loader.JsonlKind.overlapping({loader.JsonlKind.FILE: [one]},
                                        {loader.JsonlKind.FILE: [two]}) == [one]
    assert loader.JsonlKind.overlapping({loader.JsonlKind.FILE: [one]},
                                        {loader.JsonlKind.FILE: [other]}) == []


def test_the_two_kinds_cannot_be_confused_for_each_other(tmp_path):
    """
    Why enforcement is per-kind and not shared, measured rather than
    asserted: the sheet guard cannot read a path, and the file guard cannot
    read a range. One class could not have covered both.
    """
    from APITool.sheets import WriteGuard

    with pytest.raises(ValueError):
        WriteGuard.build({"Data": [str(tmp_path / "out.jsonl")]})

    assert loader.kind_for(loader.JSONL) is loader.JsonlKind
    assert loader.kind_for(loader.GSHEET) is loader.GSheetKind
    with pytest.raises(ValueError, match="known kinds: gsheet, jsonl"):
        loader.kind_for("parchment")


def test_the_refusal_is_one_class_whichever_kind_raises_it():
    """
    ``WriteRefused`` moved out of the spreadsheet toolkit when a second kind
    needed it. Every old import still resolves to the same class, so an
    ``except`` clause written against any of them catches both kinds.
    """
    from APITool.guard import WriteRefused as moved
    from APITool.sheets import WriteRefused as via_package
    from APITool.sheets.guard import WriteRefused as via_module

    assert moved is via_package is via_module


# ---------------------------------------------------------------------------
# the plugin owns its config schema: core asks and repeats the answer
# ---------------------------------------------------------------------------

COMPLAINING_INIT = GOOD_INIT + '''
KIND = "gsheet"
def writes():
    return {}
def default_config():
    return {"shape": "whatever this plugin likes"}
def check_config(config):
    if config.get("shape") == "wrong":
        return ["\\"shape\\" is wrong, and only this plugin knows why"]
    return []
'''

RAISING_CHECK_INIT = GOOD_INIT + '''
KIND = "gsheet"
def writes():
    return {}
def check_config(config):
    raise RuntimeError("check_config itself blew up")
'''


def test_a_plugin_reports_what_is_wrong_with_its_own_block(config, user_dir):
    """
    Core hands the block over unread and asks one question. Whatever the
    plugin answers is repeated, naming the target -- core could not have
    produced that sentence itself, because it does not know what "shape"
    means.
    """
    _plant(user_dir, "plug_fussy", COMPLAINING_INIT)
    config({"targets": {"mine": {"kind": "gsheet", "plugin": "plug_fussy",
                                 "config": {"shape": "wrong"}}}})
    entry = loader.discover().first()
    assert entry.complaints == ('"shape" is wrong, and only this plugin knows why',)
    assert any("CONFIG    mine:" in line for line in loader.discover().describe())


def test_a_block_a_plugin_is_happy_with_produces_no_complaint(config, user_dir):
    _plant(user_dir, "plug_fussy", COMPLAINING_INIT)
    config({"targets": {"mine": {"kind": "gsheet", "plugin": "plug_fussy",
                                 "config": {"shape": "fine"}}}})
    assert loader.discover().first().complaints == ()


def test_a_plugin_without_check_config_is_not_failing_a_duty(config, user_dir):
    """Validation is optional. A plugin that does not offer it reports nothing."""
    _plant(user_dir, "plug_quiet", GOOD_INIT + 'KIND = "gsheet"\ndef writes():\n    return {}\n')
    config({"targets": {"mine": {"kind": "gsheet", "plugin": "plug_quiet",
                                 "config": {"anything": 1}}}})
    assert loader.discover().first().complaints == ()


def test_a_check_config_that_raises_is_the_plugins_defect_and_is_isolated(config, user_dir):
    _plant(user_dir, "plug_boom", RAISING_CHECK_INIT)
    config({"targets": {"mine": {"kind": "gsheet", "plugin": "plug_boom", "config": {"a": 1}}}})
    entry = loader.discover().first()
    assert entry is not None, "a plugin whose check_config raises still loaded"
    assert len(entry.complaints) == 1
    assert "RuntimeError while checking its configuration" in entry.complaints[0]


def test_one_targets_bad_block_does_not_take_down_another_target(config, user_dir):
    """
    #27's seventh criterion, in one test: two targets, one misconfigured.
    The bad one is reported by name with its own plugin's words; the other
    is loaded and publishable, which is what "not fatal to others" means.
    """
    _plant(user_dir, "plug_fussy", COMPLAINING_INIT)
    _plant(user_dir, "plug_ok", GOOD_INIT + 'KIND = "gsheet"\ndef writes():\n    return {}\n')
    config({"targets": {
        "broken-one": {"kind": "gsheet", "plugin": "plug_fussy", "config": {"shape": "wrong"}},
        "fine-one": {"kind": "gsheet", "plugin": "plug_ok", "config": {"shape": "wrong"}},
    }})
    result = loader.discover()
    by_name = {e.name: e for e in result.loaded}

    assert set(by_name) == {"plug_fussy", "plug_ok"}, "both targets load"
    assert by_name["plug_fussy"].complaints, "the misconfigured one is reported"
    assert by_name["plug_ok"].complaints == (), "the other is untouched by its neighbour"
    listing = result.describe()
    assert any("CONFIG    broken-one:" in line for line in listing)
    assert not any("CONFIG    fine-one:" in line for line in listing)


def test_the_settlement_plugins_schema_lives_with_the_plugin(config):
    """
    The validation that left core in v0.7.4 has a declared home now. Core
    names no key of it; this plugin does.
    """
    from APITool.plugins import settlement

    assert settlement.check_config({"construction_regions": [{"site": "no region key"}]}) == [
        'construction_regions[0] has no "region"'
    ]
    assert settlement.check_config({"construction_regions": "not a list"})[0].startswith(
        '"construction_regions" must be a list')
    assert settlement.check_config({"construction_regions": [{"region": "Tab!R1:AC60"}]}) == []
    assert settlement.check_config({}) == []
    assert settlement.check_config(None) == []
    assert "construction_regions" in settlement.default_config()


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
# the courier removed: the composition root names no plugin (slice B, unit 3)
# ---------------------------------------------------------------------------


def test_the_composition_root_names_no_plugin_and_carries_no_glyph():
    """
    cli.py used to import four glyph constants only to build a dict it handed
    straight back to the plugin's renderer, and the plugin's help text by
    name. Core must not be a courier: the decision moved to where the glyphs
    live, and the help text is asked of whichever plugin loaded.
    """
    from APITool import cli

    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "plugins.settlement" not in source
    assert "MARKER_" not in source


@pytest.mark.parametrize("choice,empty", [
    ("small", "MARKER_EMPTY_SMALL"),
    ("dotted", "MARKER_EMPTY_DOTTED"),
])
def test_the_shipped_plugin_builds_the_glyph_map_the_cli_used_to(choice, empty):
    from APITool.matcher import MatchState
    from APITool.plugins import settlement
    from APITool.plugins.settlement import markers

    built = settlement.layout(empty_marker=choice).markers
    assert built == {
        MatchState.ENOUGH: markers.MARKER_ENOUGH,
        MatchState.PARTIAL: markers.MARKER_PARTIAL,
        MatchState.EMPTY: getattr(markers, empty),
    }


def test_an_explicit_markers_map_wins_over_a_family_name():
    """
    Mutation survivor, pinned: a caller who hands in a markers map has
    already decided; a family name given beside it must not overwrite it.
    """
    from APITool.plugins import settlement

    custom = {"x": "y"}
    assert settlement.layout(markers=custom, empty_marker="small").markers is custom
    assert settlement.layout(markers=custom).markers is custom


def test_the_cli_passes_its_flags_to_the_plugins_layout_as_words(config, monkeypatch):
    """
    Mutation survivor, pinned. cmd_market maps --need-sign and --empty-marker
    to what the plugin's layout takes; no test drove those flags through the
    command. Capture-and-abort: the layout builder records what it was
    handed and stops the command there, before any journal or sheet.
    """
    from APITool import cli
    from APITool.sheets import SIGN_NEGATIVE, SIGN_POSITIVE

    config({"targets": {"s": {"kind": "gsheet", "plugin": "settlement"}}})
    seen: list[dict] = []

    def recording(destination, **overrides):
        seen.append(overrides)
        return None, "stopped by the test"

    monkeypatch.setattr(cli, "_plugin_layout", recording)
    assert cli.main(["market", "--no-sheet", "--need-sign", "negative", "--empty-marker", "small"]) == 1
    assert seen[0]["need_sign"] == SIGN_NEGATIVE
    assert seen[0]["empty_marker"] == "small"

    seen.clear()
    assert cli.main(["market", "--no-sheet", "--need-sign", "positive"]) == 1
    assert seen[0]["need_sign"] == SIGN_POSITIVE
    # And nothing for the flags nobody typed. This used to read
    # `== "hollow"`, pinning a core-side default for one plugin's glyph
    # family -- which meant every plugin was handed the first plugin's
    # vocabulary whether it spoke it or not. The plugin supplies its own
    # default now; core supplies only what it was told.
    assert seen[0]["empty_marker"] is None
    assert seen[0]["marker_column"] is None
    assert seen[0]["totals_tab"] is None


def test_hollow_keeps_the_graded_scale():
    from APITool.plugins import settlement

    assert settlement.layout(empty_marker="hollow").markers is None
    assert settlement.layout().markers is None
    assert settlement.markers_for("hollow") is None


def test_show_formula_comes_from_the_configured_plugin(config, capsys):
    from APITool import cli

    config({"targets": {"s": {"kind": "gsheet", "plugin": "settlement"}}})
    assert cli.main(["market", "--show-formula"]) == 0
    assert "Reproducing the marker column" in capsys.readouterr().out


def test_a_plugin_without_formula_help_says_so(config, capsys):
    from APITool import cli

    config({"targets": {"mine": {"kind": "gsheet", "plugin": GOOD}}})
    assert cli.main(["market", "--show-formula"]) == 1
    assert f"The {GOOD!r} plugin has no formula help." in capsys.readouterr().out


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


PLAIN_LAYOUT_INIT = '''
KIND = "gsheet"
from dataclasses import dataclass

@dataclass(frozen=True)
class _Layout:
    totals_tab: str = "Plain Tab"
    def writes(self):
        return {}

def layout(**overrides):
    return _Layout(**{k: v for k, v in overrides.items() if v is not None})

def writes():
    return {}
'''


def test_a_flag_one_plugin_does_not_speak_names_the_flag_not_the_traceback(
        config, user_dir, capsys):
    """
    The flag names are one destination's vocabulary -- `--need-sign` means
    something to a settlement tab and nothing to a file. A plugin that
    cannot take one is not broken and the person is not wrong; they are
    talking to a plugin that does not speak that word. Before this they got
    `TypeError: _Layout.__init__() got an unexpected keyword argument`.
    """
    from APITool import cli

    _plant(user_dir, "plug_plain", PLAIN_LAYOUT_INIT)
    config({"targets": {"mine": {"kind": "gsheet", "plugin": "plug_plain"}}})

    code = cli.main(["market", "--no-sheet", "--need-sign", "negative"])
    out = capsys.readouterr().out

    assert code == 1
    assert "does not understand --need-sign" in out
    assert "--totals-tab" in out, "and says which overrides it does take"
    assert "TypeError" not in out and "Traceback" not in out


def test_a_plugin_that_takes_the_flag_is_unaffected(config):
    """The shipped plugin speaks all of them; nothing about it changed."""
    from APITool import cli

    config({"targets": {"s": {"kind": "gsheet", "plugin": "settlement"}}})
    layout, problem = cli._plugin_layout(
        cli._resolve_destination()[0], totals_tab="Other Tab", need_sign="-")
    assert problem is None
    assert layout.totals_tab == "Other Tab"


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


# A plugin that supplies what core already supplies. Its layout declares no
# writes, so nothing before the service's constructor has a reason to refuse it.
COLLIDING_SUPPLIER_INIT = '''
KIND = "gsheet"

class _Layout:
    totals_tab = "Collider Tab"
    def writes(self):
        return {}

def layout(**overrides):
    return _Layout()

def writes():
    return _Layout().writes()

def supplies():
    return {"location": lambda ctx: None}
'''


def test_a_plugin_supplying_what_core_supplies_is_refused_in_one_line(
    config, user_dir, tmp_path, capsys
):
    """
    The tester sweep's finding for v0.7.3, pinned. ``merge_suppliers``
    refuses a supplier name offered twice, and ``cmd_market`` guarded the
    refresh but not the constructor where that refusal is raised -- so a
    plugin claiming ``location``, which core supplies, arrived as a
    traceback where its twin, two plugins declaring the same cells, arrives
    as one line. Written before the guard, so it was red by construction.
    """
    from APITool import cli

    _plant(user_dir, "plug_collider", COLLIDING_SUPPLIER_INIT)
    config({"targets": {"mine": {"kind": "gsheet", "plugin": "plug_collider"}}})
    code = cli.main(["market", "--no-sheet", "--journal-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "Error: supplier 'location' is offered by both 'core' and" in out
    assert "Traceback" not in out


# ---------------------------------------------------------------------------
# market, with no destination configured at all
# ---------------------------------------------------------------------------
#
# The other half of "the core ships no destination" (#18 criterion 6). Once
# nothing is enabled by default, an install that has configured no plugin is
# an ordinary state rather than a broken one, and the command that reads a
# station market has to behave like it. Where you are, what the station
# sells, and the csv or json of it all come from the journal; none of them
# has ever needed a plugin, and the old code refused the whole command
# before it got as far as finding that out.


def test_market_reads_the_station_with_no_destination_configured(
    config, tmp_path, capsys
):
    """
    No target, no plugin, and the command still runs. The comparison is the
    one thing missing, and it is reported as missing -- rather than rendered
    as an empty table, which a reader takes to mean "you need nothing here".

    Asserted through ``--json``, where ``comparison_skipped`` carries the
    reason as a field. The rendered form would show the same thing, but only
    when a commander is docked: an empty journal stops at "Dock at a station
    to compare its market", which is a different and more specific absence
    and rightly takes precedence in the display.
    """
    import json as json_mod

    from APITool import cli

    config({"client_id": "abc"})
    code = cli.main(["market", "--no-sheet", "--json",
                     "--journal-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code in (0, 2), f"a missing plugin is not a failed command: {out!r}"
    assert json_mod.loads(out)["comparison_skipped"] == \
        "no destination plugin is configured"
    assert "Traceback" not in out


def test_market_exports_csv_with_no_destination_configured(
    config, tmp_path, capsys, monkeypatch
):
    """
    #18 criterion 6's actual promise: with none configured it publishes open
    formats only. "Only" is the easy half; that it publishes them AT ALL is
    the half that was broken, because the command returned 1 before reaching
    the exporter.
    """
    from APITool import cli, service

    config({"client_id": "abc"})
    exported: list[str] = []
    monkeypatch.setattr(cli, "_export_market",
                        lambda args, result, formats, sheet_id: exported.extend(formats))
    monkeypatch.setattr(service.MarketRefreshService, "current_market",
                        lambda self, location=None: None)
    code = cli.main(["market", "--no-sheet", "--journal-dir", str(tmp_path),
                     "--export", "csv,json"])
    assert code in (0, 2), capsys.readouterr().out
    assert exported == ["csv", "json"], "the exporter was never reached"


def test_market_refuses_update_sheet_by_name_with_no_destination(
    config, tmp_path, capsys
):
    """
    The refusal that must survive. Publishing markers is exactly what a
    destination plugin is for, so --update-sheet with none configured is a
    real error -- and it names the flag, because "no destination plugin is
    loaded" alone does not tell a person which thing they asked for needed
    one.
    """
    from APITool import cli

    config({"client_id": "abc"})
    code = cli.main(["market", "--update-sheet", "--dry-run",
                     "--journal-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "--update-sheet" in out, "which flag needed one"
    assert "destination plugin" in out, "what it needed"
    assert "settlement" in out and "not enabled" in out, \
        "and where to go next -- the loader's listing, not just a refusal"


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
