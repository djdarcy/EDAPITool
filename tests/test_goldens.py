"""
The plan `market --update-sheet --dry-run` prints must not move by accident.

Before v0.8.0 the only golden was the LIVE plan captured at the maintainer's
carrier (`tests/goldens/v0.7.6__market--update-sheet--dry-run.txt`), which
no test can reproduce: its system and station came from a real journal. So
"nothing else moved" was a diff a person ran by hand. This file holds the
fixture-driven equivalent: the same command, driven through `main()` against
the suite's planted worksheet, compared byte-for-byte with a file captured
once and committed.

The golden changes only when someone means it to:

    EDAPITOOL_UPDATE_GOLDENS=1 python -m pytest tests/test_goldens.py

That is the whole update mechanism, and it is deliberately not the default:
a test that rewrote its own golden on a mismatch would pass by definition.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

GOLDENS = Path(__file__).parent / "goldens"
UPDATE = "EDAPITOOL_UPDATE_GOLDENS"


#: The one field that moves on its own: the market's age against the wall
#: clock, printed as "<n> min old". The fixture's timestamp is fixed and
#: the clock is not, so the number is normalised before comparing.
_AGE = re.compile(r"\b\d[\d,]* min old\b")


def _settled(text: str) -> str:
    return _AGE.sub("<age> min old", text)


def _compare(name: str, actual: str) -> None:
    path = GOLDENS / name
    actual = _settled(actual)
    if os.environ.get(UPDATE):
        path.write_text(actual, encoding="utf-8", newline="\n")
        pytest.skip(f"golden written: {path.name}")
    assert path.is_file(), f"no golden at {path}; capture it with {UPDATE}=1"
    expected = path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"{path.name} differs from the plan the tool prints now.\n"
        f"If the change is intended, recapture with {UPDATE}=1 and say so in the CHANGELOG."
    )


def test_the_dry_run_plan_matches_the_fixture_golden(tmp_path, monkeypatch, capsys, configured_totals):
    """
    The planted grid holds a formula in every marker cell, so the plan is
    two location cells and twenty cells left alone -- the same shape the
    live v0.7.6 golden has, minus the real system and carrier.
    """
    from test_marker_skip_occupied import RangeAwareWorksheet, _cli, _planted_grid

    sheet = RangeAwareWorksheet(_planted_grid())
    code = _cli(tmp_path, monkeypatch, sheet, "--dry-run", "--write-location")
    out = capsys.readouterr().out
    assert code == 0
    assert sheet.batches == [], "a dry run must not write"
    _compare("v0.7.9__market--update-sheet--dry-run__fixture.txt", out)


def test_the_plan_names_the_new_default_tab_when_the_target_does_not_pin_one(
        tmp_path, monkeypatch, capsys, configured_totals):
    """
    v0.8.0's one visible rename: the roll-up plugin's default tab is `Totals`.
    The fixture above pins `Totals Tab` in its target block, which is what
    keeps its golden identical to the v0.7.x plan; this one drops the pin
    and captures the plan a fresh copy of the workbook would get.
    """
    import json

    from APITool import settings
    from test_marker_skip_occupied import RangeAwareWorksheet, _cli, _planted_grid

    data = settings.load()
    data["targets"]["test-workbook"]["config"] = {}
    settings.CONFIG_FILE.write_text(json.dumps(data), encoding="utf-8")

    sheet = RangeAwareWorksheet(_planted_grid())
    code = _cli(tmp_path, monkeypatch, sheet, "--dry-run", "--write-location")
    out = capsys.readouterr().out
    assert code == 0
    assert "Totals!C2" in out and "Totals Tab!" not in out
    _compare("v0.8.0__market--update-sheet--dry-run__fixture-default-tab.txt", out)
