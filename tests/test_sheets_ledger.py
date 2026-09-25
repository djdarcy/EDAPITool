"""
Whose cell is it? The pure rule of the writes ledger (slice 4, #25).

One test per row of the design's rule table
(2026-09-25__08-28-44__dev-workflow-process__the-writes-ledger, "The rule,
precisely"), plus the row that proves the rule with no ledger is exactly
v0.7.6's. No I/O anywhere in this file.
"""

from __future__ import annotations

import pytest

from APITool.sheets.ledger import MemoryLedger, as_text, classify, is_empty

PLANNED = ["L5", "L6", "L7"]


def lists(c):
    return c.refresh, c.fill, c.held, c.forced


@pytest.mark.parametrize("empty", [None, "", "   ", "\t"])
def test_an_empty_cell_is_filled_whatever_the_ledger_says(empty):
    got = classify({"L5": empty}, {"L5": "●"}, ["L5"])
    assert lists(got) == ([], ["L5"], [], [])


def test_a_cell_missing_from_the_read_counts_as_empty():
    got = classify({}, {}, ["L5"])
    assert got.fill == ["L5"]


def test_a_cell_still_holding_what_we_wrote_is_ours_and_refreshed():
    got = classify({"L5": "●"}, {"L5": "●"}, ["L5"])
    assert lists(got) == (["L5"], [], [], [])


def test_a_cell_we_wrote_that_a_person_changed_is_held():
    """#25's painted sheet, from the person's side: their edit wins."""
    got = classify({"L5": "hand-typed"}, {"L5": "●"}, ["L5"])
    assert lists(got) == ([], [], ["L5"], [])


def test_a_cell_we_never_wrote_that_holds_something_is_held():
    got = classify({"L5": "=IF($B5=\"\",\"\",LET(x,1,\"*\"))"}, {}, ["L5"])
    assert got.held == ["L5"]


def test_a_formula_we_did_not_write_is_held_even_if_the_ledger_knows_the_cell():
    """The comparison is exact: our glyph there once does not make a formula ours."""
    got = classify({"L5": "=A1"}, {"L5": "◑"}, ["L5"])
    assert got.held == ["L5"]


def test_an_unreadable_column_holds_every_cell():
    """Nothing known about any cell: the safe direction, never the write."""
    got = classify({"L5": "●"}, {"L5": "●"}, PLANNED, readable=False)
    assert lists(got) == ([], [], PLANNED, [])


@pytest.mark.parametrize("readable", [True, False])
def test_force_writes_everything_and_says_so(readable):
    got = classify({"L5": "=A1", "L6": "●"}, {"L6": "●"}, PLANNED, force=True, readable=readable)
    assert lists(got) == ([], [], [], PLANNED)


def test_with_no_ledger_the_rule_is_v076s_skip_if_occupied():
    """Decision 6 and the first run after upgrading: nothing is ever ours."""
    current = {"L5": "●", "L6": "", "L7": "=A1"}
    got = classify(current, {}, PLANNED)
    assert got.refresh == []
    assert got.fill == ["L6"]
    assert got.held == ["L5", "L7"], "our own old paint is held until one --force adopts it"


def test_a_number_read_back_compares_as_the_text_we_stored():
    """A FORMULA read can return a number; the ledger stores text."""
    got = classify({"C2": 1234}, {"C2": "1234"}, ["C2"])
    assert got.refresh == ["C2"]


def test_every_planned_cell_lands_in_exactly_one_list_in_plan_order():
    current = {"L5": "●", "L6": "", "L7": "mine", "C2": "Lhou Mans"}
    recorded = {"L5": "●", "C2": "Lhou Mans"}
    # (A `written()` helper once kept the plan's order here; the unit-2
    # mutation sweep showed nothing in production called it, so it went.)
    planned = ["L6", "C2", "L5", "L7"]
    got = classify(current, recorded, planned)
    everything = got.refresh + got.fill + got.held + got.forced
    assert sorted(everything) == sorted(planned) and len(everything) == len(planned)
    assert got.refresh == ["C2", "L5"], "each list keeps the plan's order"


def test_the_helpers_agree_with_v076():
    assert is_empty(None) and is_empty("  ") and not is_empty("0") and not is_empty(0)
    assert as_text(None) == "" and as_text(12) == "12" and as_text("=A1") == "=A1"


def test_the_memory_ledger_remembers_per_tab_and_as_text():
    ledger = MemoryLedger()
    assert ledger.record("Totals Tab", {"L5": "●", "C2": 1234})
    assert ledger.recorded("Totals Tab", ["L5", "C2", "L6"]) == {"L5": "●", "C2": "1234"}
    assert ledger.recorded("Other", ["L5"]) == {}
    assert ledger.record("Totals Tab", {}) is False
