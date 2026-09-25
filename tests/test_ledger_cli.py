"""
The writes ledger through the real command and the real store (slice 4, #25).

`market --update-sheet` run twice against one planted workbook, with the store
under the conftest's scratch ED_CONFIG_DIR: the tool's own glyphs refresh on
the second run and a person's edit is left alone. The same runs with the store
switched off freeze as v0.7.6 did. And the first run after upgrading holds
old paint until one --force adopts it.

SAFETY (rule 1b): the exporter is replaced by `_cli`'s FakeExporter and the
worksheet is a RangeAwareWorksheet that records every batch it is sent; every
"left alone" assertion is made against those recorded batches, so a cell
written in error would be seen, not assumed away. The store is a tmp_path file.
"""

from __future__ import annotations

from APITool import store
from APITool.store import writes

from test_marker_skip_occupied import RangeAwareWorksheet, _cli

TARGET = "test-workbook"          # conftest's configured_totals target name
TAB = "Totals Tab"


def _grid():
    from test_service import ROWS, totals_grid

    return totals_grid(ROWS)


def _marker_cells_written(sheet) -> set[str]:
    out = set()
    for batch in sheet.batches:
        for update in batch:
            rng = update["range"].split("!")[-1]
            if not rng.startswith("L"):
                continue
            first = int(rng.split(":")[0][1:])
            out.update(f"L{first + i}" for i in range(len(update["values"])))
    return out


def _painted_rows(sheet) -> list[int]:
    return [r + 1 for r, row in enumerate(sheet.grid) if len(row) > 11 and row[11] not in ("", None)]


def test_the_second_run_refreshes_the_tools_own_glyphs_and_keeps_a_persons_edit(
        tmp_path, monkeypatch, capsys, configured_totals):
    sheet = RangeAwareWorksheet(_grid())

    assert _cli(tmp_path, monkeypatch, sheet) == 0
    painted = _painted_rows(sheet)
    assert painted, "the first run should paint glyphs into the empty column"
    recorded = writes.recorded(TARGET, TAB, [f"L{r}" for r in painted])
    assert set(recorded) == {f"L{r}" for r in painted}, "what was painted is recorded, by target name"

    edited = f"L{painted[0]}"
    sheet.grid[painted[0] - 1][11] = "mine"        # a person edits one painted cell
    sheet.batches.clear()

    assert _cli(tmp_path, monkeypatch, sheet) == 0
    out = capsys.readouterr().out
    written = _marker_cells_written(sheet)

    assert edited not in written, f"the person's edit was overwritten: {written}"
    assert sheet.grid[painted[0] - 1][11] == "mine"
    assert {f"L{r}" for r in painted[1:]} <= written, "the tool's own glyphs are refreshed"
    assert edited in out, "the held cell is reported"


def test_with_the_store_off_the_second_run_freezes_as_v076_did(
        tmp_path, monkeypatch, capsys, configured_totals):
    """Decision 6: ED_NO_STORE falls back to skip-if-occupied, never to overwriting."""
    monkeypatch.setenv(store.GUARD_VAR, "1")
    sheet = RangeAwareWorksheet(_grid())

    _cli(tmp_path, monkeypatch, sheet)
    painted = _painted_rows(sheet)
    sheet.batches.clear()
    _cli(tmp_path, monkeypatch, sheet)

    assert painted and not (_marker_cells_written(sheet) & {f"L{r}" for r in painted}), \
        "with no memory every painted cell is someone else's"
    with store.open_store() as conn:
        assert conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0] == 0


def test_the_first_run_after_upgrading_holds_old_paint_and_one_force_adopts_it(
        tmp_path, monkeypatch, capsys, configured_totals):
    """Decision 4: paint from before the ledger existed is held until one --force."""
    sheet = RangeAwareWorksheet(_grid())
    monkeypatch.setenv(store.GUARD_VAR, "1")
    _cli(tmp_path, monkeypatch, sheet)                 # "an older version" paints
    monkeypatch.delenv(store.GUARD_VAR)
    painted = {f"L{r}" for r in _painted_rows(sheet)}
    sheet.batches.clear()

    _cli(tmp_path, monkeypatch, sheet)                 # first run on the ledger
    assert not (_marker_cells_written(sheet) & painted), "old paint is held"

    sheet.batches.clear()
    _cli(tmp_path, monkeypatch, sheet, "--force")      # adopt it
    assert painted <= _marker_cells_written(sheet)

    sheet.batches.clear()
    _cli(tmp_path, monkeypatch, sheet)                 # and from now on it is ours
    assert painted <= _marker_cells_written(sheet)


def test_a_real_write_through_the_command_makes_five_calls(
        tmp_path, monkeypatch, capsys, configured_totals):
    """
    The CHANGELOG's number, measured through main(): the requirements read,
    the cells read, the write, the formatting, and the read-back that records
    what landed. v0.8.0 made the same minus the read-back.
    """
    class Counting(RangeAwareWorksheet):
        def __init__(self, grid):
            super().__init__(grid)
            self.calls: list[str] = []

        def get_values(self, range_name, **kwargs):
            self.calls.append("get_values")
            return super().get_values(range_name, **kwargs)

        def batch_get(self, ranges, **kwargs):
            self.calls.append("batch_get")
            return [RangeAwareWorksheet.get_values(self, r, **kwargs) for r in ranges]

        def batch_update(self, data, **kwargs):
            self.calls.append("batch_update")
            return super().batch_update(data, **kwargs)

        def batch_format(self, formats):
            self.calls.append("batch_format")
            return super().batch_format(formats)

    sheet = Counting(_grid())
    assert _cli(tmp_path, monkeypatch, sheet) == 0
    assert sheet.calls == ["get_values", "batch_get", "batch_update", "batch_format", "batch_get"], \
        sheet.calls

    dry = Counting(_grid())
    _cli(tmp_path, monkeypatch, dry, "--dry-run")
    assert dry.calls == ["get_values", "batch_get"], dry.calls


def test_a_marked_row_whose_cell_is_held_says_so_on_both_paths(
        tmp_path, monkeypatch, capsys, configured_totals):
    """
    The v0.8.0 checklist run found "Wrote 0 ranges" beside "Marked rows: [17]"
    read as a contradiction. The marked-rows line now says which marked rows
    were held, in the same words on the dry run and the real write.
    """
    sheet = RangeAwareWorksheet(_grid())
    _cli(tmp_path, monkeypatch, sheet)            # paint once to learn a marked row
    row = _painted_rows(sheet)[0]
    capsys.readouterr()

    for extra in (("--dry-run",), ()):
        planted = RangeAwareWorksheet(_grid())
        planted.grid[row - 1][11] = "=A FORMULA()"
        _cli(tmp_path, monkeypatch, planted, *extra)
        out = capsys.readouterr().out
        line = next(l for l in out.splitlines() if l.strip().startswith("marked rows:"))
        assert f" -- 1 held, not written: [{row}]" in line, (extra, line)
        assert line.startswith("  marked rows:"), "one spelling on both paths"


def test_a_plan_with_nothing_marked_says_none(capsys):
    """The report's words for an empty plan, checked directly (mutation survivor M04)."""
    from APITool.cli import _report_plan
    from APITool.sheets.writer import MarkerPlan

    class Layout:
        totals_tab = "Totals Tab"
        marker_column = "L"

    _report_plan(MarkerPlan(), Layout())
    out = capsys.readouterr().out

    assert out == "  marked rows: (none)\n", out


def test_a_dry_run_records_nothing(tmp_path, monkeypatch, capsys, configured_totals):
    sheet = RangeAwareWorksheet(_grid())
    _cli(tmp_path, monkeypatch, sheet, "--dry-run")

    assert sheet.batches == []
    with store.open_store() as conn:
        assert conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0] == 0
