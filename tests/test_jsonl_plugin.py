"""
The second plugin, and the second KIND: a destination that is a file.

The settlement plugin publishes to a Google sheet. This one appends a JSON
record to a file on disk. It exists to answer one question that no amount of
care with a single plugin can answer: **is the plugin contract shaped like a
spreadsheet?** If anything here had needed ``registry.py`` widened, or a new
field on ``Subscription``, or a special case in the service, then the answer
would have been yes and the isolation would have been cosmetic.

So the tests that matter most here are the ones that assert an ABSENCE --
that the contract did not move -- and they are written against the same
surfaces the sheet plugin uses, in a vocabulary that has no cells in it.

SAFETY (rule 1b): every path in this file is under ``tmp_path``. The refusal
test asserts that an undeclared path is REFUSED, so per rule 1b it must be
structurally unable to perform that write if the refusal fails: it asserts on
the guard object and on the plugin's subscriber, which consults the guard
BEFORE it opens anything -- and the undeclared path it names is itself inside
``tmp_path``, so even a total failure of the guard could not reach a real file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from APITool import loader, settings
from APITool.guard import WriteRefused
from APITool.plugins import jsonl


# ---------------------------------------------------------------------------
# The shape of the plugin itself
# ---------------------------------------------------------------------------


def test_the_plugin_declares_a_kind_that_is_not_a_spreadsheet():
    assert jsonl.KIND == "jsonl"
    assert jsonl.KIND in loader.KINDS
    assert loader.KINDS[jsonl.KIND] is loader.JsonlKind


def test_a_layout_declares_the_one_path_it_owns(tmp_path):
    """
    A file has no sub-addresses -- it is owned whole or not at all -- so the
    declaration has one bucket where a sheet has one per tab.
    """
    target = tmp_path / "observations.jsonl"
    built = jsonl.layout(path=str(target))
    assert built.writes() == {loader.JsonlKind.FILE: [str(target)]}


def test_as_shipped_it_declares_nothing(tmp_path):
    """
    With no target there is no path, and a plugin that declares nothing
    cannot conflict with anything. Core then builds it an enforcer that
    permits nothing, which is the safe direction to be wrong in.
    """
    assert jsonl.writes() == {loader.JsonlKind.FILE: []}
    enforcer = loader.build_enforcer(jsonl.KIND, jsonl.writes())
    assert not enforcer.allows(str(tmp_path / "anything.jsonl"))


# ---------------------------------------------------------------------------
# The contract, unchanged
# ---------------------------------------------------------------------------


def test_it_satisfies_the_contract_with_no_change_to_the_contract():
    """
    #26 criterion 3, stated as an absence.

    The plugin supplies and subscribes through exactly the types the sheet
    plugin uses -- the same ``Subscription``, with the same three fields --
    and nothing about a file needed a fourth.
    """
    from APITool.registry import Subscription

    (subscription,) = jsonl.subscribes()
    assert isinstance(subscription, Subscription)
    assert subscription.name == "record"
    assert subscription.needs == ()
    assert callable(subscription.publish)

    supplied = jsonl.supplies()
    assert set(supplied) == {"previous"}
    assert all(callable(fn) for fn in supplied.values())


def test_the_shipped_plugins_share_no_vocabulary_with_the_file_plugin():
    """
    The real test of "not shaped like a spreadsheet": the file plugin has
    nothing in common with any sheet plugin but the contract. Overlapping
    names would mean the contract had quietly acquired a spreadsheet's
    nouns. Every shipped plugin is checked, so a third one cannot slip in
    a noun the two originals never shared.
    """
    import importlib

    from APITool.loader import SHIPPED_DIR

    shipped = sorted(p.name for p in SHIPPED_DIR.iterdir()
                     if p.is_dir() and not p.name.startswith(("_", ".")))
    assert "totals" in shipped and "construction" in shipped and len(shipped) >= 3

    def offered(module, asked):
        ask = getattr(module, asked, None)
        got = ask() if callable(ask) else ()
        return set(got) if isinstance(got, dict) else {s.name for s in got}

    for name in shipped:
        if name == "jsonl":
            continue
        other = importlib.import_module(f"APITool.plugins.{name}")
        assert offered(jsonl, "supplies") & offered(other, "supplies") == set(), name
        assert offered(jsonl, "subscribes") & offered(other, "subscribes") == set(), name
        assert jsonl.KIND != other.KIND, name


# ---------------------------------------------------------------------------
# The path comes from the target
# ---------------------------------------------------------------------------


def test_a_targets_path_reaches_the_plugins_layout(tmp_path, monkeypatch):
    """
    Nothing inside the plugin says where its file is; the person's target
    does. Core carries the target's own keys to the layout without knowing
    what any of them mean -- it asks the layout which names it accepts and
    hands over that intersection.
    """
    from APITool import cli

    wanted = tmp_path / "out.jsonl"
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    monkeypatch.setenv("ED_PLUGIN_DIR", str(tmp_path / "none"))
    path.write_text(json.dumps({"targets": {"observations": {
        "kind": "jsonl", "plugin": "jsonl", "path": str(wanted),
    }}}), encoding="utf-8")

    destination, problem = cli._resolve_destination()
    assert destination is not None, problem
    built, problem = cli._plugin_layout(destination)
    assert built is not None, problem
    assert built.path == str(wanted)
    assert built.writes() == {loader.JsonlKind.FILE: [str(wanted)]}


def test_a_sheet_targets_id_does_not_become_a_layout_override(tmp_path, monkeypatch):
    """
    The other half, and the reason the rule is "names the layout accepts"
    rather than "all of them": a sheet target carries ``id``, which belongs
    to the exporter and not to the layout. Handing it over would refuse the
    settlement plugin by name for a key the person configured correctly.
    """
    from APITool import cli

    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    monkeypatch.setenv("ED_PLUGIN_DIR", str(tmp_path / "none"))
    path.write_text(json.dumps({"targets": {"book": {
        "kind": "gsheet", "plugin": "totals", "id": "A-SHEET-ID",
    }}}), encoding="utf-8")

    destination, problem = cli._resolve_destination()
    assert destination is not None, problem
    built, problem = cli._plugin_layout(destination)
    assert built is not None, problem
    assert not hasattr(built, "id")


def test_market_publishes_to_a_file_destination_end_to_end(tmp_path, monkeypatch, capsys):
    """
    C10, through the real command: a plugin whose destination is a FILE gets
    its subscriptions run.

    This is the proof the whole slice was for, and it needs the real CLI
    rather than a service built by hand, because two of the three things it
    exercises live above the service: core no longer passes one plugin's
    flag vocabulary to every plugin, and it no longer returns early because
    there is no worksheet.

    SAFETY: the journal directory is empty ``tmp_path``, so no real journal
    is read, and the destination is a file inside ``tmp_path``.
    """
    from APITool import cli

    out_file = tmp_path / "observations.jsonl"
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    monkeypatch.setenv("ED_PLUGIN_DIR", str(tmp_path / "none"))
    path.write_text(json.dumps({"targets": {"observations": {
        "kind": "jsonl", "plugin": "jsonl", "path": str(out_file),
        "config": {"only": ["checked_at", "system", "station"]},
    }}}), encoding="utf-8")

    code = cli.main(["market", "--no-sheet", "--update-sheet",
                     "--journal-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code in (0, 2), out
    assert "does not understand" not in out, \
        "core handed a flag nobody typed to a plugin that never spoke that word"
    assert out_file.is_file(), out
    record = json.loads(out_file.read_text(encoding="utf-8").splitlines()[0])
    assert set(record) == {"checked_at", "system", "station"}


def test_a_flag_the_person_did_type_still_reaches_the_plugin(tmp_path, monkeypatch, capsys):
    """
    The other side of the same rule. Passing only what was typed must not
    become passing nothing: a flag the person actually supplied still has to
    arrive, and one the plugin cannot take is still refused by name rather
    than dropped in silence.
    """
    from APITool import cli

    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    monkeypatch.setenv("ED_PLUGIN_DIR", str(tmp_path / "none"))
    path.write_text(json.dumps({"targets": {"observations": {
        "kind": "jsonl", "plugin": "jsonl", "path": str(tmp_path / "o.jsonl"),
    }}}), encoding="utf-8")

    # v0.8.0: `--need-sign` is the settlement plugin's word, and with only
    # the file plugin loaded it is not a flag at all -- refused by the
    # parser, by name, before any command runs.
    with pytest.raises(SystemExit) as stop:
        cli.main(["market", "--no-sheet", "--need-sign", "negative",
                  "--journal-dir", str(tmp_path)])
    assert stop.value.code == 2
    assert "--need-sign" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# What it writes, and what it refuses to write
# ---------------------------------------------------------------------------


class _Refresh:
    """The slice of the refresh context this plugin's subscriber reads."""

    def __init__(self, layout, guard, write, result):
        self.layout = layout
        self.guard = guard
        self.options = {"write": write}
        self.result = result
        self.checked_at = "2026-09-19T22:00:00Z"


class _Location:
    system = "Col 285 Sector ZG-T c4-10"
    station_display = "Badeaux Nutrition Centre"


class _Result:
    location = _Location()
    market = None
    matches = ()


def _context(path, *, declared=None, write=True):
    built = jsonl.layout(path=str(path))
    guard = loader.build_enforcer(
        jsonl.KIND, {loader.JsonlKind.FILE: [str(declared or path)]})
    return _Refresh(built, guard, write, _Result())


def test_one_record_is_appended_per_refresh(tmp_path):
    target = tmp_path / "observations.jsonl"
    (subscription,) = jsonl.subscribes()

    subscription.publish(_context(target))
    subscription.publish(_context(target))

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, "exactly one record per refresh, appended"
    record = json.loads(lines[0])
    assert record["system"] == _Location.system
    assert record["station"] == _Location.station_display


def test_a_dry_run_says_what_it_would_do_and_writes_nothing(tmp_path):
    target = tmp_path / "observations.jsonl"
    (subscription,) = jsonl.subscribes()

    status = subscription.publish(_context(target, write=False))

    assert "would append" in status
    assert not target.exists(), "a dry run that creates the file is not dry"


def test_a_path_the_plugin_did_not_declare_is_refused(tmp_path):
    """
    The enforcement half of #26 criterion 3, and the one the whole kind
    registry exists for.

    Core builds the guard from the plugin's OWN declaration and the plugin
    writes through it -- it does not police itself. Here the declaration and
    the path disagree, which is what a transposed constant looks like, and
    the write must not happen.

    Rule 1b: both paths are inside tmp_path, and the subscriber consults the
    guard before it opens anything, so a failed refusal writes a stray file
    in a temporary directory rather than touching anything real.
    """
    declared = tmp_path / "declared.jsonl"
    elsewhere = tmp_path / "elsewhere.jsonl"
    (subscription,) = jsonl.subscribes()

    with pytest.raises(WriteRefused):
        subscription.publish(_context(elsewhere, declared=declared))

    assert not elsewhere.exists(), "refused, and refused BEFORE opening"


def test_with_no_path_configured_it_writes_nothing_and_says_so(tmp_path):
    (subscription,) = jsonl.subscribes()
    status = subscription.publish(_context("", declared=tmp_path / "x.jsonl"))
    assert "no path configured" in status


# ---------------------------------------------------------------------------
# What it supplies: a file has prior state too
# ---------------------------------------------------------------------------


def test_previous_reads_the_last_record_already_in_the_file(tmp_path):
    target = tmp_path / "observations.jsonl"
    target.write_text('{"n": 1}\n{"n": 2}\n', encoding="utf-8")
    read = jsonl.supplies()["previous"]
    assert read(_context(target))["n"] == 2


@pytest.mark.parametrize("contents, why", [
    ("", "an empty file"),
    ("\n\n", "blank lines only"),
    ('{"n": 1}\n{truncated', "a last line somebody else truncated"),
])
def test_prior_state_we_cannot_read_is_prior_state_we_do_not_have(
        tmp_path, contents, why):
    target = tmp_path / "observations.jsonl"
    target.write_text(contents, encoding="utf-8")
    assert jsonl.supplies()["previous"](_context(target)) is None, why


def test_a_file_that_does_not_exist_yet_supplies_nothing(tmp_path):
    read = jsonl.supplies()["previous"]
    assert read(_context(tmp_path / "not-created-yet.jsonl")) is None


# ---------------------------------------------------------------------------
# Its configuration schema is its own
# ---------------------------------------------------------------------------


def test_a_happy_block_produces_no_complaint():
    assert jsonl.check_config({"only": ["system", "station"]}) == []
    assert jsonl.check_config({}) == []
    assert jsonl.check_config(None) == []


def test_it_names_a_field_it_does_not_publish():
    (complaint,) = jsonl.check_config({"only": ["system", "cargo_capacity"]})
    assert "cargo_capacity" in complaint
    assert "does not publish" in complaint


def test_a_block_of_the_wrong_shape_is_refused_in_the_plugins_own_words():
    (complaint,) = jsonl.check_config({"only": "system"})
    assert '"only" must be a list' in complaint


def test_only_narrows_what_a_record_carries(tmp_path):
    target = tmp_path / "observations.jsonl"
    built = jsonl.layout(path=str(target), only=["system", "station"])
    guard = loader.build_enforcer(jsonl.KIND, built.writes())
    (subscription,) = jsonl.subscribes()

    subscription.publish(_Refresh(built, guard, True, _Result()))

    record = json.loads(target.read_text(encoding="utf-8").splitlines()[0])
    assert set(record) == {"system", "station"}


def test_the_starter_block_is_one_this_plugin_accepts():
    """A starter block that its own check_config complains about is a defect."""
    assert jsonl.check_config(jsonl.default_config()) == []
