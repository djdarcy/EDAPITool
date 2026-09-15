"""Where a construction region binding comes from, and who wins.

A binding is the most stable thing in a `serve` setup -- it changes when you
start a new settlement, which is roughly monthly -- and it is also the longest
thing to type. That combination is what makes it belong in a config file: a
flag you must retype every session is a flag that stops getting used.

The command line still wins outright when it is given. Merging an explicit
flag with saved settings would mean no single place tells you what will
happen, which is worse than either source alone.
"""

import argparse
import json

import pytest

from APITool import cli, settings


@pytest.fixture
def args():
    return argparse.Namespace(construction_region=None)


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Point the config loader at a throwaway file."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)

    def write(data):
        path.write_text(json.dumps(data), encoding="utf-8")
        return path
    return write


# --- the command line -----------------------------------------------


def test_the_flag_is_read(args):
    args.construction_region = ["Agri Lrg. (ex)!R1:AC60=Badeaux Nutrition Centre"]
    (dest, site), = cli.get_construction_regions(args)
    assert dest.tab == "Agri Lrg. (ex)"
    assert dest.range_a1() == "R1:AC60"
    assert site == "Badeaux Nutrition Centre"


def test_the_site_may_be_omitted(args):
    args.construction_region = ["Tab!R1:AC60"]
    (dest, site), = cli.get_construction_regions(args)
    assert site is None


def test_the_flag_repeats(args):
    args.construction_region = ["A!R1:AC60=One", "B!R1:AC60=Two"]
    got = cli.get_construction_regions(args)
    assert [d.tab for d, _ in got] == ["A", "B"]
    assert [s for _, s in got] == ["One", "Two"]


# --- the config file ------------------------------------------------


def test_config_entries_are_objects(args, config):
    config({"construction_regions": [
        {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"},
    ]})
    (dest, site), = cli.get_construction_regions(args)
    assert dest.tab == "Agri Lrg. (ex)"
    assert site == "Badeaux Nutrition Centre"


def test_config_site_may_be_omitted(args, config):
    config({"construction_regions": [{"region": "Tab!R1:AC60"}]})
    (_, site), = cli.get_construction_regions(args)
    assert site is None


def test_a_pasted_flag_string_is_tolerated_in_config(args, config):
    """So a value can be moved from the command line without rewriting it."""
    config({"construction_regions": ["Tab!R1:AC60=Site Name"]})
    (dest, site), = cli.get_construction_regions(args)
    assert dest.tab == "Tab"
    assert site == "Site Name"


def test_no_config_and_no_flag_means_no_regions(args, config):
    config({"client_id": "abc"})
    assert cli.get_construction_regions(args) == []


def test_a_missing_config_file_is_not_an_error(args, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_FILE", tmp_path / "absent.json")
    assert cli.get_construction_regions(args) == []


def test_unreadable_config_does_not_take_serve_down(args, tmp_path, monkeypatch):
    bad = tmp_path / "config.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(settings, "CONFIG_FILE", bad)
    assert cli.get_construction_regions(args) == []


# --- precedence -----------------------------------------------------


def test_the_flag_wins_outright_over_config(args, config):
    """Not merged: one place must explain what will happen."""
    config({"construction_regions": [{"region": "FromConfig!R1:AC60"}]})
    args.construction_region = ["FromFlag!R1:AC60"]
    got = cli.get_construction_regions(args)
    assert [d.tab for d, _ in got] == ["FromFlag"]


# --- malformed bindings are refused, never skipped -------------------


def test_a_config_entry_with_no_region_is_refused(args, config):
    config({"construction_regions": [{"site": "Somewhere"}]})
    with pytest.raises(ValueError) as excinfo:
        cli.get_construction_regions(args)
    assert "construction_regions[0]" in str(excinfo.value)


def test_a_non_object_entry_is_refused_and_named(args, config):
    config({"construction_regions": [{"region": "A!R1:B2"}, 42]})
    with pytest.raises(ValueError) as excinfo:
        cli.get_construction_regions(args)
    assert "construction_regions[1]" in str(excinfo.value)


def test_a_bare_tab_name_in_config_is_refused(args, config):
    """Owning a whole tab is never arrived at by omitting the range."""
    config({"construction_regions": [{"region": "Agri Lrg. (ex)"}]})
    with pytest.raises(ValueError):
        cli.get_construction_regions(args)


def test_a_malformed_binding_is_not_silently_dropped(args, config):
    """
    The failure this guards against: one bad entry among several, skipped
    quietly, leaving a region that simply stops being published with nothing
    said. Better to refuse the whole run and name the entry.
    """
    config({"construction_regions": [
        {"region": "Good!R1:AC60"},
        {"region": "Bad!R1:AC"},          # open-ended, cannot be cleared
        {"region": "AlsoGood!R1:AC60"},
    ]})
    with pytest.raises(ValueError):
        cli.get_construction_regions(args)


# --- through main(), which nothing did before ------------------------------
#
# Every CLI-level test in this suite reached its branch by monkeypatching a
# resolver to a stub -- routing AROUND config resolution rather than through
# it. So the refusal messages themselves had no coverage at all, and a defect
# lived in exactly that gap: a ternary inside a print() that emitted a stray
# blank line on one branch. The ternary chose which string to print; print ran
# either way. These drive the real parser against a throwaway config file.


def run_serve(argv, config_file, monkeypatch, capsys, entries=None):
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
        raise AssertionError(
            "cmd_serve reached daemon build: the refusal under test did not "
            "fire, and without this guard a real publish loop would start")

    monkeypatch.setattr(daemon_mod, "build", must_not_reach)

    payload = {"sheet_id": "FAKE-SHEET"}
    if entries is not None:
        payload["construction_regions"] = entries
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    code = main(["serve"] + argv)
    return code, capsys.readouterr().out


def test_a_malformed_config_entry_refuses_the_run_through_the_cli(
        tmp_path, monkeypatch, capsys):
    from APITool import settings

    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    code, out = run_serve([], path, monkeypatch, capsys,
                          entries=[{"site": "No Region Key"}])

    assert code == 1, "a refusal that exits 0 is one no script will notice"
    lines = out.splitlines()
    assert lines[0] == 'Error: construction_regions[0] has no "region"'
    assert lines[1].strip().startswith("(from "), "must name the file it read"
    assert str(path) in lines[1]
    assert len(lines) == 2, f"expected exactly two lines, got {lines!r}"


def test_the_index_named_is_the_real_index(tmp_path, monkeypatch, capsys):
    from APITool import settings

    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    code, out = run_serve([], path, monkeypatch, capsys, entries=[
        {"region": "Tab!A1:B2", "site": "Fine"},
        {"site": "Broken"},
    ])

    assert code == 1
    assert "construction_regions[1]" in out
    assert "construction_regions[0]" not in out


def test_a_bad_flag_value_refuses_without_a_trailing_blank_line(
        tmp_path, monkeypatch, capsys):
    """
    The regression guard for the stray blank line. When the bad value came
    from the flag rather than the file, the code correctly omitted the
    "(from <path>)" TEXT but still executed print(""), leaving an empty line
    after the error.
    """
    from APITool import settings

    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    code, out = run_serve(["--construction-region", "BareTabNoRange"],
                          path, monkeypatch, capsys)

    assert code == 1
    lines = out.splitlines()
    assert len(lines) == 1, f"expected one line and no blank, got {lines!r}"
    assert "names no region" in lines[0]
    assert "(from " not in out, "the value came from the flag, not the file"
