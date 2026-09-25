"""
The v0.8.0 CHANGELOG entry names the whole break.

A command-line break a person cannot reconstruct from the release notes is a
break they find by typing an old command. These tests read the entry itself
and hold it to the code: every word a shipped plugin now declares is named,
every renamed spelling appears with its replacement, and the migration for a
`settlement` target is there. The flag list is read from the plugins, not
typed here, so a word added to a plugin later without a line in the entry
fails this file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"

RENAMES = [
    ("--marker-column", "--glyph-marker-column"),
    ("--empty-marker", "--empty-glyph-marker"),
    ("--write-marker-header", "--write-glyph-marker-header"),
    ("--no-markers", "--no-glyph-markers"),
]


@pytest.fixture(scope="module")
def entry() -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    match = re.search(r"^## \[0\.8\.0\].*?(?=^## \[)", text, re.MULTILINE | re.DOTALL)
    assert match, "CHANGELOG.md has no [0.8.0] entry"
    return match.group(0)


def _shipped_flags():
    from APITool.plugins import construction, totals

    return [(module.__name__.rsplit(".", 1)[-1], flag)
            for module in (totals, construction) for flag in module.flags()]


def test_every_word_a_shipped_sheet_plugin_declares_is_named(entry):
    missing = sorted({f"{plugin}: {flag.name}" for plugin, flag in _shipped_flags()
                      if f"`{flag.name}`" not in entry})
    assert not missing, f"the [0.8.0] entry never names: {missing}"


@pytest.mark.parametrize("old, new", RENAMES)
def test_each_renamed_spelling_appears_beside_its_replacement(entry, old, new):
    rows = [line for line in entry.splitlines() if f"`{old}`" in line]
    assert rows, f"the entry never names the old spelling {old}"
    assert any(f"`{new}`" in row for row in rows), \
        f"{old} is named, but not on the same line as {new}"


def test_the_renames_are_real(entry):
    """The new spellings are the ones the plugin declares, and the old are gone."""
    declared = {flag.name for _, flag in _shipped_flags()}
    for old, new in RENAMES:
        assert new in declared, f"{new} is in the CHANGELOG but no plugin declares it"
        assert old not in declared, f"{old} is still declared"


def test_the_entry_uses_the_glyph_marker_term(entry):
    """#28 criterion 3: the term in --help, in docs/, and in this entry."""
    assert len(re.findall(r"glyph[ -]marker", entry, re.IGNORECASE)) >= 4


def test_the_settlement_migration_and_the_default_tab_are_spelled_out(entry):
    for needed in ('"plugin": "settlement"', '"plugin": "totals"', '"plugin": "construction"',
                   "`Totals Tab`", "`Totals`", '"totals_tab": "Totals Tab"'):
        assert needed in entry, f"the entry does not say {needed}"


def test_the_deprecation_carries_a_date(entry):
    section = entry.split("### Deprecated", 1)[1].split("###", 1)[0]
    assert "`--write-location`" in section
    assert re.search(r"\b20\d\d-\d\d-\d\d\b", section), "a deprecation without a date is a wish"
