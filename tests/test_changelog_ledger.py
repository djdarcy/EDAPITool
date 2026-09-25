"""
The v0.8.1 CHANGELOG entry says what an upgrading user will see (#25).

The one behaviour a person meets without asking for it: after upgrading,
their painted column is held until one --force. An entry that buried that,
or that stated the wrong call count, would send them to the tracker instead.
The count is checked against the counting test's own numbers, not typed here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


@pytest.fixture(scope="module")
def entry() -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    match = re.search(r"^## \[0\.8\.1\].*?(?=^## \[)", text, re.MULTILINE | re.DOTALL)
    assert match, "CHANGELOG.md has no [0.8.1] entry"
    return match.group(0)


def test_the_upgrade_behaviour_is_stated_with_its_remedy(entry):
    assert "After upgrading" in entry
    assert "--force" in entry and "adopts" in entry
    assert "ED_NO_STORE" in entry, "the switch that keeps v0.7.6's behaviour is named"


def test_the_three_answers_are_named_as_the_report_prints_them(entry):
    for phrase in ("ours and refreshed", "empty and filled", "held and left alone", "forced"):
        assert phrase in entry, phrase


def test_the_location_cell_change_is_stated(entry):
    assert "`--write-location` now leaves a formula" in entry


def test_the_call_count_matches_the_command(entry):
    """4 before, 5 after: the requirements read, the cells read, write, format, read-back."""
    assert re.search(r"makes 5 API calls where it made 4", entry)


def test_what_is_unaffected_is_said(entry):
    assert "Construction regions" in entry and "MarketData" in entry
