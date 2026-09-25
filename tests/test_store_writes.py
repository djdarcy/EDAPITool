"""
The writes ledger's storage (slice 4, #25): what the tool last wrote to each
cell, per target -- and that it never takes a command down with it.

Every store here is the conftest's scratch one (``ED_CONFIG_DIR`` under
``tmp_path``); nothing touches a spreadsheet.
"""

from __future__ import annotations

import pytest

from APITool import store
from APITool.store import writes


def test_what_was_recorded_is_what_is_read_back():
    assert writes.record("totals-workbook", "Totals Tab", {"L5": "●", "L6": "=A1"}, "run1")

    got = writes.recorded("totals-workbook", "Totals Tab", ["L5", "L6", "L7"])

    assert got == {"L5": "●", "L6": "=A1"}, "a cell never written is absent, not empty"


def test_a_second_write_replaces_the_first():
    writes.record("t", "Tab", {"L5": "old"}, "run1")
    writes.record("t", "Tab", {"L5": "new"}, "run2")

    assert writes.recorded("t", "Tab", ["L5"]) == {"L5": "new"}
    with store.open_store() as conn:
        rows = conn.execute("SELECT run_id FROM writes WHERE a1='L5'").fetchall()
    assert rows == [("run2",)], "one row per cell, carrying the latest run"


def test_two_targets_on_one_sheet_keep_separate_memories():
    """The key is the target's NAME, so two targets naming one id never mix."""
    writes.record("totals-workbook", "Tab", {"C2": "Lhou Mans"})
    writes.record("construction-workbook", "Tab", {"C2": "somewhere else"})

    assert writes.recorded("totals-workbook", "Tab", ["C2"]) == {"C2": "Lhou Mans"}
    assert writes.recorded("totals-workbook", "Other", ["C2"]) == {}


def test_rebuild_never_touches_the_ledger():
    """Primary data: a regenerated ledger would be a forged one."""
    writes.record("t", "Tab", {"L5": "●"})
    with store.open_store() as conn:
        store.rebuild(conn)
    assert writes.recorded("t", "Tab", ["L5"]) == {"L5": "●"}


def test_the_off_switch_records_nothing_and_remembers_nothing(monkeypatch):
    writes.record("t", "Tab", {"L5": "kept before the switch"})
    monkeypatch.setenv(store.GUARD_VAR, "1")

    assert writes.record("t", "Tab", {"L6": "●"}) is False
    assert writes.recorded("t", "Tab", ["L5", "L6"]) == {}, \
        "with the store off every cell is someone else's -- v0.7.6's rule"

    monkeypatch.delenv(store.GUARD_VAR)
    assert writes.recorded("t", "Tab", ["L5", "L6"]) == {"L5": "kept before the switch"}


def test_a_store_that_will_not_open_reports_once_and_answers_nothing(monkeypatch, capsys):
    def broken(*a, **k):
        raise store.StoreError("planted: the file is locked")

    monkeypatch.setattr(writes, "open_store", broken)
    monkeypatch.setattr(writes.settings, "_reported", set())

    assert writes.record("t", "Tab", {"L5": "●"}) is False
    assert writes.recorded("t", "Tab", ["L5"]) == {}
    err = capsys.readouterr().err
    assert err.count("planted: the file is locked") == 1, "reported once, never raised"


def test_a_ledger_failure_is_not_silenced_by_an_archive_failure(monkeypatch, capsys):
    """The two report under different keys, because they say different things."""
    monkeypatch.setattr(writes.settings, "_reported", set())
    writes.settings.report_once(store.store_path(), "store: could not archive market: x")
    monkeypatch.setattr(writes, "open_store", lambda *a, **k: (_ for _ in ()).throw(OSError("y")))

    writes.recorded("t", "Tab", ["L5"])

    assert "could not read the writes ledger" in capsys.readouterr().err


def test_many_cells_are_read_in_chunks():
    """
    SQLite caps bound parameters per statement: 999 before 3.32, 32766 after.
    The test uses more cells than the higher cap, so a single IN over every
    cell fails on any SQLite this runs on. (First written with 1,500 cells,
    which the red-green audit showed could never fail on 3.42.)
    """
    values = {f"L{row}": "x" for row in range(5, 33_005)}
    writes.record("t", "Tab", values)

    got = writes.recorded("t", "Tab", list(values))

    assert len(got) == len(values) and got["L33004"] == "x"


def test_the_bound_ledger_speaks_for_one_target():
    ledger = writes.StoreLedger("totals-workbook", run_id="abc123")
    assert ledger.record("Tab", {"L5": "●"})

    assert ledger.recorded("Tab", ["L5"]) == {"L5": "●"}
    assert writes.recorded("another", "Tab", ["L5"]) == {}
    with store.open_store() as conn:
        assert conn.execute("SELECT run_id FROM writes").fetchone() == ("abc123",)


@pytest.mark.parametrize("empty", [{}, []])
def test_nothing_asked_opens_nothing(monkeypatch, empty):
    monkeypatch.setattr(writes, "open_store", lambda *a, **k: pytest.fail("opened the store"))
    if isinstance(empty, dict):
        assert writes.record("t", "Tab", empty) is False
    else:
        assert writes.recorded("t", "Tab", empty) == {}
