"""
#18 criterion 11: `WRITABLE_TABS` is derived from what the tool generates,
not enumerated.

The list guards `worksheet.clear()`. Its failure mode as a literal was silent
and one-directional: somebody adds a grid builder and forgets to add its tab,
and a legitimate export is refused -- or, in the version this project
actually shipped once, the list was a DENY list and every tab nobody thought
of was writable.

The proof these tests exist to give is a single sentence: **add a generated
tab and the set grows without `APITool/google/exporter.py` being edited.**

SAFETY (rule 1b): nothing here constructs a `GoogleSheetsExporter`, opens a
client, or holds a worksheet. The tests read a registry and a frozenset. The
one mutating fixture restores the registry it touched, and asserts it did.
"""

from __future__ import annotations

import pytest

from APITool.generated import builders, generated_tabs, generates_tab
from APITool.google.exporter import GoogleSheetsExporter


@pytest.fixture
def registry_restored():
    """Plant a builder, then put the registry back exactly as it was."""
    import APITool.generated as generated

    before = dict(generated._BUILDERS)
    yield generated
    generated._BUILDERS.clear()
    generated._BUILDERS.update(before)
    assert generated._BUILDERS == before


def test_the_three_tabs_this_tool_generates_are_all_writable():
    """The behaviour must not change: the same three names, differently sourced."""
    assert GoogleSheetsExporter.WRITABLE_TABS == frozenset(
        {"FreighterData", "MarketData", "ShipCargo"}
    )


def test_each_writable_tab_is_claimed_by_a_named_builder():
    """
    Every entry traces back to a function. A name in the set with no builder
    behind it would be an enumeration wearing a derivation's clothes.
    """
    claimed = builders()
    assert set(claimed.values()) == set(GoogleSheetsExporter.WRITABLE_TABS)
    assert sorted(claimed) == [
        "APITool.google.exporter.carrier_grid",
        "APITool.market.sheet_grid",
        "APITool.ship.sheet_grid",
    ]


def test_adding_a_generated_tab_grows_the_set_without_editing_the_exporter(
    registry_restored,
):
    """
    Criterion 11, stated as an experiment.

    Decorating a new builder is the whole change. Nothing in
    `google/exporter.py` is touched, and the allow list follows.
    """
    assert "PlanetData" not in GoogleSheetsExporter.WRITABLE_TABS

    @generates_tab("PlanetData")
    def planet_grid():
        return []

    assert "PlanetData" in GoogleSheetsExporter.WRITABLE_TABS
    assert "PlanetData" in generated_tabs()
    assert planet_grid.generated_tab == "PlanetData"


def test_the_class_and_an_instance_cannot_disagree(registry_restored):
    """
    Both spellings are read in this codebase -- `self.WRITABLE_TABS` in the
    constructor, `GoogleSheetsExporter.WRITABLE_TABS` elsewhere. A descriptor
    that answered only one of them would make the guard depend on how it was
    spelled.
    """
    @generates_tab("LateArrival")
    def late_grid():
        return []

    instance = object.__new__(GoogleSheetsExporter)   # no client, no network
    assert instance.WRITABLE_TABS == GoogleSheetsExporter.WRITABLE_TABS
    assert "LateArrival" in instance.WRITABLE_TABS


def test_a_tab_nobody_generates_is_not_writable():
    """
    The direction that matters. The tabs holding a person's own work are
    every tab no builder claims, and they are refused by default rather than
    by being listed.
    """
    for theirs in ("Totals Tab", "Settlements", "Notes", "Sheet1", ""):
        assert theirs not in GoogleSheetsExporter.WRITABLE_TABS


# ---------------------------------------------------------------------------
# The claim the docstring makes: no import-order dependency
# ---------------------------------------------------------------------------


def _in_a_fresh_interpreter(snippet: str) -> str:
    """
    Run one line in a brand-new Python, importing nothing extra.

    In-process this can never fail: by the time pytest reaches any test, the
    whole package has been imported by some other test module, so the
    registry is fully populated no matter how it got that way. That is
    exactly the condition under which an import-order bug hides. A fresh
    interpreter is the only place the question can be asked honestly.

    SAFETY (rule 1b): the child imports and prints. It constructs no client,
    opens no file and writes nothing.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def test_the_set_is_complete_in_an_interpreter_that_imported_nothing_else():
    """
    `generated_tabs()` imports the modules that carry builders before it
    answers. Without that, the set would say whatever happened to have been
    imported already -- the import-order dependency inside a safety check
    that the descriptor exists to avoid.
    """
    out = _in_a_fresh_interpreter(
        "from APITool.generated import generated_tabs;"
        " print(sorted(generated_tabs()))"
    )
    assert out == "['FreighterData', 'MarketData', 'ShipCargo']", out


def test_the_allow_list_is_complete_for_a_caller_that_imported_only_the_exporter():
    """
    The real shape of the hazard: a caller reaches for the exporter and
    nothing else. Every tab must still be authorized, including the ones
    whose builders live in modules that caller never named.
    """
    out = _in_a_fresh_interpreter(
        "from APITool.google.exporter import GoogleSheetsExporter;"
        " print(sorted(GoogleSheetsExporter.WRITABLE_TABS))"
    )
    assert out == "['FreighterData', 'MarketData', 'ShipCargo']", out


def test_the_builder_map_is_complete_in_a_fresh_interpreter_too():
    """`builders()` primes the registry for the same reason, and is read by
    diagnostics where a half-populated answer would be read as the truth."""
    out = _in_a_fresh_interpreter(
        "from APITool.generated import builders; print(sorted(builders()))"
    )
    assert out == (
        "['APITool.google.exporter.carrier_grid', 'APITool.market.sheet_grid',"
        " 'APITool.ship.sheet_grid']"
    ), out


def test_permitting_nothing_is_honoured_rather_than_falling_back():
    """
    `writable_tabs=[]` means "permit nothing", and it is the strictest thing
    a caller can say. Treating it as "not specified" would answer the most
    cautious possible request by re-opening every generated tab -- a safety
    override that fails open on its safest setting.
    """
    locked = GoogleSheetsExporter(writable_tabs=[])

    assert locked.writable_tabs == frozenset()
    assert GoogleSheetsExporter.WRITABLE_TABS   # and the default is unaffected
