"""Where a construction region binding comes from, and who wins.

A binding is the most stable thing in a `serve` setup -- it changes when you
start a new settlement, which is roughly monthly -- and it is also the longest
thing to type. That combination is what makes it belong in a config file: a
flag you must retype every session is a flag that stops getting used.

The command line still wins outright when it is given. Merging an explicit
flag with saved settings would mean no single place tells you what will
happen, which is worse than either source alone.

Since v0.7.4 the binding lives in the target's ``config`` block and the
settlement plugin reads it (``APITool.plugins.settlement.bindings``); core
carries the block without parsing it. A file written before ``targets``
existed -- a bare ``sheet_id`` with a top-level ``construction_regions`` --
resolves to a ``default`` target whose block carries that list, so every
assertion below holds through both shapes.
"""

import json
from pathlib import Path

import pytest

from APITool import settings
from APITool.plugins.settlement import bindings

LEGACY = "legacy"
TARGETS = "targets"


class Captured(BaseException):
    """
    Raised by a stubbed ``daemon.build`` to stop ``cmd_serve`` where it stands.

    A BaseException on purpose: ``cmd_serve`` reports every ``Exception`` a
    real build raises as a spreadsheet error and returns 1, which is right
    for gspread and wrong for a stub whose whole job is to escape.
    """


def regions(config=None, flag=None):
    return bindings.construction_regions(config, flag)


@pytest.fixture
def user_dir(tmp_path: Path, monkeypatch) -> Path:
    """An empty user plugin directory, so only shipped plugins are found."""
    directory = tmp_path / "plugins"
    directory.mkdir()
    monkeypatch.setenv("ED_PLUGIN_DIR", str(directory))
    return directory


@pytest.fixture
def config(tmp_path, monkeypatch, user_dir):
    """Point the config loader at a throwaway file."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)

    def write(data):
        path.write_text(json.dumps(data), encoding="utf-8")
        return path
    return write


# --- the command line -----------------------------------------------


def test_the_flag_is_read():
    (dest, site), = regions(None, ["Agri Lrg. (ex)!R1:AC60=Badeaux Nutrition Centre"])
    assert dest.tab == "Agri Lrg. (ex)"
    assert dest.range_a1() == "R1:AC60"
    assert site == "Badeaux Nutrition Centre"


def test_the_site_may_be_omitted():
    (dest, site), = regions(None, ["Tab!R1:AC60"])
    assert site is None


def test_the_flag_repeats():
    got = regions(None, ["A!R1:AC60=One", "B!R1:AC60=Two"])
    assert [d.tab for d, _ in got] == ["A", "B"]
    assert [s for _, s in got] == ["One", "Two"]


# --- the plugin's config block ----------------------------------------


def test_config_entries_are_objects():
    (dest, site), = regions({"construction_regions": [
        {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"},
    ]})
    assert dest.tab == "Agri Lrg. (ex)"
    assert site == "Badeaux Nutrition Centre"


def test_config_site_may_be_omitted():
    (_, site), = regions({"construction_regions": [{"region": "Tab!R1:AC60"}]})
    assert site is None


def test_a_pasted_flag_string_is_tolerated_in_config():
    """So a value can be moved from the command line without rewriting it."""
    (dest, site), = regions({"construction_regions": ["Tab!R1:AC60=Site Name"]})
    assert dest.tab == "Tab"
    assert site == "Site Name"


def test_an_empty_site_means_the_same_as_an_absent_one():
    """
    "Whichever site I am docked at" is expressed by omitting ``site``, and
    typing it empty means the same thing -- so the binding says None either
    way rather than leaving every consumer to treat "" as falsy for itself.
    The flag spelling normalises the same way, and both are the plugin's
    contract now that core asks for this list by name.
    """
    assert regions({"construction_regions": [{"region": "Tab!R1:AC60", "site": ""}]})[0][1] is None
    assert regions(None, ["Tab!R1:AC60="])[0][1] is None
    assert regions(None, ["Tab!R1:AC60=   "])[0][1] is None
    # Asymmetry, pre-existing and carried by the move: the flag spelling
    # strips before testing, the block's does not, so a site of spaces
    # survives in the block. Pinned as it is rather than changed inside a
    # verbatim move; recorded as a rough edge in this version's checklist.
    assert regions({"construction_regions": [{"region": "Tab!R1:AC60", "site": "   "}]})[0][1] == "   "


def test_no_config_and_no_flag_means_no_regions():
    assert regions({"client_id": "abc"}) == []
    assert regions({}) == []
    assert regions(None) == []


# --- precedence -----------------------------------------------------


def test_the_flag_wins_outright_over_config():
    """Not merged: one place must explain what will happen."""
    got = regions({"construction_regions": [{"region": "FromConfig!R1:AC60"}]},
                  ["FromFlag!R1:AC60"])
    assert [d.tab for d, _ in got] == ["FromFlag"]


# --- malformed bindings are refused, never skipped -------------------


def test_a_config_entry_with_no_region_is_refused():
    with pytest.raises(ValueError) as excinfo:
        regions({"construction_regions": [{"site": "Somewhere"}]})
    assert "construction_regions[0]" in str(excinfo.value)


def test_a_non_object_entry_is_refused_and_named():
    with pytest.raises(ValueError) as excinfo:
        regions({"construction_regions": [{"region": "A!R1:B2"}, 42]})
    assert "construction_regions[1]" in str(excinfo.value)


def test_a_bare_tab_name_in_config_is_refused():
    """Owning a whole tab is never arrived at by omitting the range."""
    with pytest.raises(ValueError):
        regions({"construction_regions": [{"region": "Agri Lrg. (ex)"}]})


def test_a_malformed_binding_is_not_silently_dropped():
    """
    The failure this guards against: one bad entry among several, skipped
    quietly, leaving a region that simply stops being published with nothing
    said. Better to refuse the whole run and name the entry.
    """
    with pytest.raises(ValueError):
        regions({"construction_regions": [
            {"region": "Good!R1:AC60"},
            {"region": "Bad!R1:AC"},          # open-ended, cannot be cleared
            {"region": "AlsoGood!R1:AC60"},
        ]})


# --- the file, through the alias -------------------------------------------
#
# A file written before ``targets`` existed carries its bindings at the top
# level. The alias moves every key core does not own into the default
# target's config block, so the plugin reads them exactly as it reads a
# ``targets`` entry's block -- and core never names the key.


def test_a_legacy_file_carries_its_bindings_into_the_default_target(config):
    config({"sheet_id": "FAKE-SHEET",
            "construction_regions": [{"region": "Tab!R1:AC60", "site": "Fine"}]})
    target = settings.default_target("settlement")
    assert target is not None
    assert (target.name, target.kind, target.plugin) == ("default", "gsheet", "settlement")
    assert target.params == {"id": "FAKE-SHEET"}
    (dest, site), = regions(target.config)
    assert (dest.tab, site) == ("Tab", "Fine")


def test_a_sheet_id_alone_is_enough_to_alias(config):
    """
    The commonest legacy file has nothing but a client id and a sheet id --
    no bindings, no plugin keys. It must still resolve to the default
    target, or every such install loses its destination the day the alias
    ships.
    """
    config({"client_id": "abc", "sheet_id": "ONLY-A-SHEET"})
    target = settings.default_target("settlement")
    assert target is not None
    assert target.params == {"id": "ONLY-A-SHEET"}
    assert target.config == {}


def test_a_legacy_file_with_only_a_plugins_keys_still_aliases(config, monkeypatch):
    """The other half of the same guard: bindings but no sheet id is still a target."""
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    config({"construction_regions": [{"region": "Tab!R1:AC60"}]})
    target = settings.default_target("settlement")
    assert target is not None
    assert target.params == {}
    assert "construction_regions" in target.config


def test_the_default_targets_block_carries_no_key_core_owns(config):
    """
    Everything core parses for itself stays core's. ``plugin_dir`` in
    particular is a core setting that sits at the top level beside a
    plugin's keys, and handing it to the plugin would make core's own
    configuration part of a plugin's block.
    """
    config({"client_id": "abc", "sheet_id": "S", "plugin_dir": "~/plugs",
            "construction_regions": [{"region": "Tab!R1:AC60"}]})
    target = settings.default_target("settlement")
    assert set(target.config) == {"construction_regions"}
    assert not settings.CORE_KEYS & set(target.config)


def test_a_file_with_a_targets_map_is_never_aliased(config):
    config({"sheet_id": "OLD", "targets": {}})
    assert settings.default_target("settlement") is None


def test_a_missing_config_file_is_not_a_target(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_FILE", tmp_path / "absent.json")
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    assert settings.default_target("settlement") is None


def test_an_unreadable_config_file_is_not_a_target(tmp_path, monkeypatch):
    bad = tmp_path / "config.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(settings, "CONFIG_FILE", bad)
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    assert settings.default_target("settlement") is None


# --- through main(), which nothing did before ------------------------------
#
# Every CLI-level test in this suite reached its branch by monkeypatching a
# resolver to a stub -- routing AROUND config resolution rather than through
# it. So the refusal messages themselves had no coverage at all, and a defect
# lived in exactly that gap: a ternary inside a print() that emitted a stray
# blank line on one branch. The ternary chose which string to print; print ran
# either way. These drive the real parser against a throwaway config file, in
# BOTH shapes the file can take.


def payload(shape, entries):
    if shape == LEGACY:
        data = {"sheet_id": "FAKE-SHEET"}
        if entries is not None:
            data["construction_regions"] = entries
        return data
    block = {} if entries is None else {"construction_regions": entries}
    return {"targets": {"mine": {"kind": "gsheet", "plugin": "settlement",
                                 "id": "FAKE-SHEET", "config": block}}}


def run_serve(argv, config_file, monkeypatch, capsys, entries=None, shape=LEGACY):
    """
    Drive main(["serve", ...]) against a throwaway config.

    The daemon builder is replaced with something that fails loudly, and that
    is not belt-and-braces. Every test here asserts that a bad setting is
    REFUSED, and the refusal is the only thing that returns before
    `daemon_mod.build(...)` and `worker.run()` -- an endless watch loop that
    publishes to a real spreadsheet. So a test whose refusal stops firing
    would not go red; it would start a live daemon and hang, against whatever
    sheet id the fixture happened to supply, alongside any serve the developer
    already has running.

    Observed 2026-09-15: a mutation run disabled the flag path, this helper
    sailed past the refusal, and pytest never returned. A test that asserts
    something is refused must not be ABLE to do that thing when the refusal
    fails.
    """
    from APITool import daemon as daemon_mod
    from APITool.cli import main

    def must_not_reach(*a, **k):
        raise Captured(
            "cmd_serve reached daemon build: the refusal under test did not "
            "fire, and without this guard a real publish loop would start")

    monkeypatch.setattr(daemon_mod, "build", must_not_reach)

    config_file.write_text(json.dumps(payload(shape, entries)), encoding="utf-8")
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    code = main(["serve"] + argv)
    return code, capsys.readouterr().out


@pytest.mark.parametrize("shape", [LEGACY, TARGETS])
def test_a_malformed_config_entry_refuses_the_run_through_the_cli(
        shape, tmp_path, monkeypatch, capsys, user_dir):
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    code, out = run_serve([], path, monkeypatch, capsys,
                          entries=[{"site": "No Region Key"}], shape=shape)

    assert code == 1, "a refusal that exits 0 is one no script will notice"
    lines = out.splitlines()
    assert lines[0] == 'Error: construction_regions[0] has no "region"'
    assert lines[1].strip().startswith("(from "), "must name the file it read"
    assert str(path) in lines[1]
    assert len(lines) == 2, f"expected exactly two lines, got {lines!r}"


@pytest.mark.parametrize("shape", [LEGACY, TARGETS])
def test_the_index_named_is_the_real_index(shape, tmp_path, monkeypatch, capsys, user_dir):
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    code, out = run_serve([], path, monkeypatch, capsys, entries=[
        {"region": "Tab!A1:B2", "site": "Fine"},
        {"site": "Broken"},
    ], shape=shape)

    assert code == 1
    assert "construction_regions[1]" in out
    assert "construction_regions[0]" not in out


def test_a_bad_flag_value_refuses_without_a_trailing_blank_line(
        tmp_path, monkeypatch, capsys, user_dir):
    """
    The regression guard for the stray blank line. When the bad value came
    from the flag rather than the file, the code correctly omitted the
    "(from <path>)" TEXT but still executed print(""), leaving an empty line
    after the error.
    """
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    code, out = run_serve(["--construction-region", "BareTabNoRange"],
                          path, monkeypatch, capsys)

    assert code == 1
    lines = out.splitlines()
    assert len(lines) == 1, f"expected one line and no blank, got {lines!r}"
    assert "names no region" in lines[0]
    assert "(from " not in out, "the value came from the flag, not the file"


# --- the bindings reach the daemon, in both shapes --------------------------


def capture_build(monkeypatch):
    """
    Replace the daemon builder with one that records its arguments and
    aborts. Capture-and-abort, not capture-and-continue: the real build
    opens a spreadsheet and the worker it returns runs a watch loop, and a
    test must not be able to start either.
    """
    from APITool import daemon as daemon_mod

    seen = {}

    def record(*a, **k):
        seen.update(k)
        raise Captured()

    monkeypatch.setattr(daemon_mod, "build", record)
    return seen


@pytest.mark.parametrize("shape", [LEGACY, TARGETS])
def test_the_bindings_reach_the_daemon_unchanged_in_both_shapes(
        shape, tmp_path, monkeypatch, user_dir):
    """
    The criterion's own words: ``serve`` behaves identically before and
    after the move. The list the daemon is handed is the same for a file
    written before ``targets`` existed and for one written after.
    """
    from APITool.cli import main

    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    path.write_text(json.dumps(payload(shape, [
        {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"},
        "Other!R1:AC60",
    ])), encoding="utf-8")
    seen = capture_build(monkeypatch)

    with pytest.raises(Captured):
        main(["serve"])

    got = [(d.tab, d.range_a1(), s) for d, s in seen["construction_regions"]]
    assert got == [("Agri Lrg. (ex)", "R1:AC60", "Badeaux Nutrition Centre"),
                   ("Other", "R1:AC60", None)]
    assert seen["sheet_id"] == "FAKE-SHEET"
    assert seen["target"] == ("default" if shape == LEGACY else "mine")


def test_a_plugin_with_no_bindings_publishes_no_regions(tmp_path, monkeypatch, user_dir):
    """
    The question is the plugin's to answer. One that has no
    ``construction_regions`` is not asked twice, and the daemon is handed
    nothing -- even when the file still carries a top-level list meant for
    a plugin that did read it.
    """
    from APITool.cli import main

    (user_dir / "plug_plain").mkdir()
    (user_dir / "plug_plain" / "__init__.py").write_text(
        'KIND = "gsheet"\n'
        'class _Layout:\n'
        '    totals_tab = "Plain Tab"\n'
        '    def writes(self):\n'
        '        return {}\n'
        'def layout(**overrides):\n'
        '    return _Layout()\n'
        'def writes():\n'
        '    return {}\n', encoding="utf-8")
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    path.write_text(json.dumps({"targets": {"plain": {
        "kind": "gsheet", "plugin": "plug_plain", "id": "FAKE-SHEET",
        "config": {"construction_regions": [{"region": "Tab!R1:AC60"}]},
    }}}), encoding="utf-8")
    seen = capture_build(monkeypatch)

    with pytest.raises(Captured):
        main(["serve"])

    assert seen["construction_regions"] == []


def test_a_flag_the_plugin_cannot_honour_is_refused_rather_than_dropped(
        tmp_path, monkeypatch, capsys, user_dir):
    """
    The tester sweep's finding for v0.7.4, pinned. A plugin with no
    ``construction_regions`` publishes none, which is right -- but the flag
    was then never even inspected, so a person who typed one got silence
    indistinguishable from typing nothing. That breaks both of this
    surface's stated rules at once: a flag wins outright, and a setting
    that cannot take effect says so rather than being dropped.
    """
    from APITool.cli import main

    (user_dir / "plug_plain").mkdir()
    (user_dir / "plug_plain" / "__init__.py").write_text(
        'KIND = "gsheet"\n'
        'class _Layout:\n'
        '    totals_tab = "Plain Tab"\n'
        '    def writes(self):\n'
        '        return {}\n'
        'def layout(**overrides):\n'
        '    return _Layout()\n'
        'def writes():\n'
        '    return {}\n', encoding="utf-8")
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    path.write_text(json.dumps({"targets": {"plain": {
        "kind": "gsheet", "plugin": "plug_plain", "id": "FAKE-SHEET",
    }}}), encoding="utf-8")
    capture_build(monkeypatch)

    code = main(["serve", "--construction-region", "Tab!R1:AC60=Somewhere"])
    out = capsys.readouterr().out

    assert code == 1, "a flag that cannot take effect must not exit 0"
    assert "plug_plain" in out, "the message must name the plugin that cannot take it"
    assert "--construction-region" in out
    assert "Traceback" not in out
