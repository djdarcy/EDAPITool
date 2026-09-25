"""
#25: `--update-sheet` must not overwrite what is already in the marker column.

The defect, measured live on 2026-09-16 against the maintainer's own sheet:
the marker plan rewrote `Totals Tab!L5:L24` wholesale, and that column had
stopped being painted -- it held twenty `LET` formulas reading the generated
MarketData tab. All twenty were destroyed. The clearing step was correct when
the tool PAINTED the column, because a leftover glyph from a previous station
is confidently wrong; it became destructive the moment the column started
computing itself.

The fix, as the maintainer scoped it on 2026-09-21: **a cell that already
holds anything is skipped.** Empty cells are filled. `--force` overwrites.
`--dry-run` reports what it skipped as well as what it would write.

THE SUBTLETY THAT DECIDES CORRECTNESS, and the reason these tests read
formulas rather than values: the settlement formulas render as the EMPTY
STRING whenever the commodity is not sold at the current station --
`IF(buy=0,"",...)`. So a cell holding a live formula very often *displays*
nothing. Reading rendered values would call that cell empty and overwrite the
formula, which is the exact defect this fix exists to stop. The occupancy
read must therefore ask for `value_render_option="FORMULA"`, and the test
below fails if it does not.

SAFETY (rule 1b): no test here touches a real worksheet. The fake records
what it was asked for and returns what the test planted; it has no network
and no file access, so a regression cannot reach a spreadsheet.
"""

from __future__ import annotations

import pytest

from APITool.sheets import WriteGuard
from APITool.sheets.writer import MarkerWriter


class RecordingWorksheet:
    """A worksheet that records reads and writes, and returns planted cells."""

    def __init__(self, cells: dict[str, str] | None = None):
        self.cells = cells or {}
        self.reads: list[tuple[str, dict]] = []
        self.writes: list[dict] = []

    def get_values(self, range_name: str, **kwargs) -> list[list[str]]:
        self.reads.append((range_name, kwargs))
        first, last = _bounds(range_name)
        column = range_name.split("!")[-1].split(":")[0].rstrip("0123456789")
        return [[self.cells.get(f"{column}{row}", "")] for row in range(first, last + 1)]

    def batch_get(self, ranges: list[str], **kwargs) -> list[list[list[str]]]:
        # One answer per range, through get_values, so a subclass that makes
        # the read raise or overshoot still does.
        return [self.get_values(r, **kwargs) for r in ranges]

    def batch_update(self, data: list[dict], **kwargs):
        self.writes.extend(data)
        # What was written is what the cells now hold, for the read-back.
        for update in data:
            first, last = _bounds(update["range"])
            column = update["range"].split("!")[-1].split(":")[0].rstrip("0123456789")
            for offset, row in enumerate(update["values"]):
                self.cells[f"{column}{first + offset}"] = row[0] if row else ""

    def batch_format(self, data: list[dict], **kwargs):
        pass


def _bounds(range_name: str) -> tuple[int, int]:
    body = range_name.split("!")[-1]
    start, _, end = body.partition(":")
    first = int("".join(c for c in start if c.isdigit()) or 1)
    last = int("".join(c for c in end if c.isdigit()) or first)
    return first, last


class Layout:
    """The slice of a layout the marker writer reads."""

    totals_tab = "Totals Tab"
    marker_column = "L"
    marker_header = "At Current Station"
    header_row = 3
    first_data_row = 5
    system_cell = "C2"
    station_cell = "G2"

    def marker_range(self, last: int) -> str:
        return f"{self.marker_column}{self.first_data_row}:{self.marker_column}{last}"

    def marker_header_cell(self) -> str:
        return f"{self.marker_column}{self.header_row}"

    def writes(self) -> dict[str, list[str]]:
        return {self.totals_tab: ["C2", "G2", "L3:L"]}


class Renderer:
    """Marks every row, so any skipping observed is the fix and not emptiness."""

    def cell(self, match, show_covered: bool = True):
        return "X"

    def cell_note(self, match, checked_at):
        return ""

    def cell_format(self, match, value):
        return None


def _writer(worksheet) -> MarkerWriter:
    layout = Layout()
    return MarkerWriter(
        worksheet, Renderer(), layout,
        guard=WriteGuard.build(layout.writes()),
    )


class Snapshot:
    def __init__(self, rows):
        self.rows = rows
        self.last_data_row = max(rows) if rows else 0


def _matches(rows):
    class M:
        def __init__(self, row):
            self.row = row
            self.is_covered = False
            self.requirement = type("R", (), {"name": "x", "need": 1})()
            self.state = type("S", (), {"name": "ENOUGH"})()
    return [M(r) for r in rows]


# ---------------------------------------------------------------------------
# The occupancy read
# ---------------------------------------------------------------------------


def test_the_occupancy_read_asks_for_formulas_not_values():
    """
    The whole fix turns on this. A settlement formula renders as "" when the
    commodity is not sold here, so a rendered-value read reports an occupied
    cell as empty and the write destroys it -- #25, exactly.
    """
    worksheet = RecordingWorksheet()
    _writer(worksheet).build_plan(
        _matches([5, 6]), Snapshot([5, 6]), "Sys", "Stn",
    )

    assert worksheet.reads, "the plan must read the marker range before writing it"
    _, kwargs = worksheet.reads[0]
    assert kwargs.get("value_render_option") == "FORMULA", (
        "reading rendered values would see a formula that evaluates to empty "
        "as an empty cell, and overwrite it"
    )


def test_a_cell_holding_a_formula_is_not_written():
    worksheet = RecordingWorksheet({"L5": '=IF($B5="","",LET(...))', "L6": ""})
    plan = _writer(worksheet).build_plan(
        _matches([5, 6]), Snapshot([5, 6]), "Sys", "Stn",
    )

    written = " ".join(u["range"] for u in plan.updates)
    assert "L5" not in written, "L5 holds a formula and must be left alone"
    assert "L6" in written, "L6 is empty and should be filled"
    assert "L5" in plan.skipped


def test_a_cell_holding_a_literal_is_not_written_either():
    """
    The maintainer's scope is 'anything', not 'a formula'. Someone who typed
    a note into the column meant it as much as a formula.

    With no ledger (this writer is built without one) nothing is ever the
    tool's own, so even a glyph it painted earlier is held -- v0.7.6's rule,
    and still the rule whenever the store is off. The writes ledger (v0.8.1)
    is what lets the tool refresh its own paint; see test_writer_ledger.py.
    """
    worksheet = RecordingWorksheet({"L5": "mine", "L6": ""})
    plan = _writer(worksheet).build_plan(
        _matches([5, 6]), Snapshot([5, 6]), "Sys", "Stn",
    )

    assert "L5" in plan.skipped
    assert not any("L5" in u["range"] for u in plan.updates)


def test_force_overwrites_everything_and_skips_the_read():
    worksheet = RecordingWorksheet({"L5": '=FORMULA()', "L6": "mine"})
    plan = _writer(worksheet).build_plan(
        _matches([5, 6]), Snapshot([5, 6]), "Sys", "Stn", force=True,
    )

    assert plan.skipped == []
    written = " ".join(u["range"] for u in plan.updates)
    assert "L5" in written and "L6" in written
    assert not worksheet.reads, "--force needs no occupancy read at all"


def test_an_all_empty_column_is_written_as_one_range():
    """
    The common case must not degrade into twenty single-cell writes. With
    nothing in the way the plan keeps its contiguous range.
    """
    worksheet = RecordingWorksheet()
    plan = _writer(worksheet).build_plan(
        _matches([5, 6, 7]), Snapshot([5, 6, 7]), "Sys", "Stn",
    )

    marker_updates = [u for u in plan.updates if u["range"].startswith("L5")]
    assert len(marker_updates) == 1
    assert marker_updates[0]["range"] == "L5:L7"


def test_the_location_cells_follow_the_same_rule_as_the_markers():
    """
    Until v0.8.0 C2/G2 sat outside the occupancy check and were written
    whenever asked. From v0.8.1 (slice 4, decision 1) they obey the same
    rule: an empty location cell is filled, one holding something the tool
    did not write is held -- independently of the marker column.
    """
    worksheet = RecordingWorksheet({"L5": "occupied", "G2": "=MarketData!$C$1"})
    plan = _writer(worksheet).build_plan(
        _matches([5]), Snapshot([5]), "Sys", "Stn", write_location=True,
    )

    ranges = [u["range"] for u in plan.updates]
    assert "C2" in ranges, "an empty location cell is filled"
    assert "G2" not in ranges and "G2" in plan.held, "a formula there is someone else's"
    assert "L5" in plan.held


def test_nothing_is_read_when_markers_are_excluded():
    """`include_markers=False` writes no marker cells, so it needs no read."""
    worksheet = RecordingWorksheet()
    _writer(worksheet).build_plan(
        _matches([5]), Snapshot([5]), "Sys", "Stn", include_markers=False,
    )
    assert not worksheet.reads


def test_the_free_runs_are_written_as_ranges_not_one_call_per_cell():
    """
    Cost check. Skipping must not turn one API range into twenty: a column
    with a single occupied cell in the middle costs two ranges, not two
    writes per surviving row.
    """
    worksheet = RecordingWorksheet({"L8": "x"})
    plan = _writer(worksheet).build_plan(
        _matches(range(5, 13)), Snapshot(list(range(5, 13))), "Sys", "Stn",
    )

    marker = [u["range"] for u in plan.updates if u["range"].startswith("L")]
    assert marker == ["L5:L7", "L9:L12"]


@pytest.mark.parametrize("occupied, expect_written", [
    ({}, ["L5:L7"]),
    ({"L6": "x"}, ["L5", "L7"]),
    ({"L5": "x", "L7": "x"}, ["L6"]),
    ({"L5": "x", "L6": "x", "L7": "x"}, []),
])
def test_only_the_free_cells_are_written(occupied, expect_written):
    worksheet = RecordingWorksheet(occupied)
    plan = _writer(worksheet).build_plan(
        _matches([5, 6, 7]), Snapshot([5, 6, 7]), "Sys", "Stn",
    )
    marker_ranges = [u["range"] for u in plan.updates if u["range"].startswith("L")]
    assert marker_ranges == expect_written


# ---------------------------------------------------------------------------
# Through the CLI, where --force and the skip report actually live
# ---------------------------------------------------------------------------


class RangeAwareWorksheet:
    """
    A worksheet that answers the range it was ASKED for.

    The suite's usual fake returns its whole grid whatever you ask for, which
    is fine for a reader that wants the whole grid and useless here: the
    occupancy probe asks for one column, and a fake that ignores the range
    cannot plant a formula in it. This one honours the range, so a formula in
    L5 is a formula in L5.
    """

    def __init__(self, grid):
        self.grid = grid
        self.batches: list[list[dict]] = []
        self.format_batches: list[list[dict]] = []
        self.reads: list[tuple[str, dict]] = []

    def get_values(self, range_name: str, **kwargs) -> list[list[str]]:
        self.reads.append((range_name, kwargs))
        body = range_name.split("!")[-1]
        start, _, end = body.partition(":")
        column = start.rstrip("0123456789")
        if column in ("A", ""):            # the requirements block
            return [list(row) for row in self.grid]
        index = ord(column) - ord("A")
        first, last = _bounds(range_name)
        return [
            [self.grid[r - 1][index] if r - 1 < len(self.grid) else ""]
            for r in range(first, last + 1)
        ]

    def batch_get(self, ranges: list[str], **kwargs) -> list[list[list[str]]]:
        return [self.get_values(r, **kwargs) for r in ranges]

    def batch_update(self, data: list[dict], **kwargs):
        self.batches.append(data)
        # Written values land in the grid, so a read-back sees them.
        for update in data:
            body = update["range"].split("!")[-1]
            column = body.split(":")[0].rstrip("0123456789")
            index = ord(column) - ord("A")
            first, _ = _bounds(update["range"])
            for offset, row in enumerate(update["values"]):
                r = first + offset - 1
                if r < len(self.grid) and index < len(self.grid[r]):
                    self.grid[r][index] = row[0] if row else ""
        return {"replies": []}

    def batch_format(self, formats: list[dict]):
        self.format_batches.append(formats)
        return {"replies": []}


def _cli(tmp_path, monkeypatch, sheet, *extra):
    """Drive the real `market` command against a planted worksheet."""
    import APITool.google as gsheet_mod
    from test_service import docked_event, make_journal, ryman_market_json

    from APITool.cli import main

    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())

    class FakeExporter:
        def worksheet(self, sheet_id, tab):
            return sheet

    monkeypatch.setattr(gsheet_mod, "GoogleSheetsExporter", FakeExporter)
    return main([
        "market", "--journal-dir", str(directory),
        "--sheet-id", "fake", "--update-sheet", *extra,
    ])


def _planted_grid(formula: str = '=IF($B5="","",LET(x,1,"*"))'):
    """The suite's totals grid, with a formula sitting in the marker column."""
    from test_service import ROWS, totals_grid

    grid = totals_grid(ROWS)
    grid[4][11] = formula          # L5 -- first data row, marker column
    return grid


def test_the_cli_leaves_a_planted_formula_alone(tmp_path, monkeypatch, capsys, configured_totals):
    sheet = RangeAwareWorksheet(_planted_grid())
    code = _cli(tmp_path, monkeypatch, sheet)
    out = capsys.readouterr().out

    assert code == 0
    written = {u["range"] for batch in sheet.batches for u in batch}
    assert not any(r.startswith("L5") for r in written), (
        f"L5 held a formula and was written anyway: {written}\n{out}"
    )


def test_the_cli_says_which_cells_it_left_alone(tmp_path, monkeypatch, capsys, configured_totals):
    """
    A silent skip looks exactly like a write that worked. #25's acceptance
    criteria ask for the write to be visible before it happens; a skip is
    part of what happens.
    """
    sheet = RangeAwareWorksheet(_planted_grid())
    _cli(tmp_path, monkeypatch, sheet, "--dry-run")
    out = capsys.readouterr().out

    assert "left alone" in out, out
    assert "L5" in out, out
    assert "--force" in out, out


def test_force_through_the_cli_writes_the_whole_block(tmp_path, monkeypatch, capsys, configured_totals):
    sheet = RangeAwareWorksheet(_planted_grid())
    code = _cli(tmp_path, monkeypatch, sheet, "--force")
    out = capsys.readouterr().out

    assert code == 0
    written = {u["range"] for batch in sheet.batches for u in batch}
    assert any(r.startswith("L5:") for r in written), (
        f"--force did not overwrite the formula-bearing block: {written}\n{out}"
    )
    assert "left alone" not in out, out


def test_a_clean_sheet_is_unchanged_by_the_new_check(tmp_path, monkeypatch, capsys, configured_totals):
    """
    The guard on the fix: a workbook with an empty marker column must behave
    exactly as it did before -- one contiguous range, no skip report.
    """
    from test_service import ROWS, totals_grid

    sheet = RangeAwareWorksheet(totals_grid(ROWS))
    code = _cli(tmp_path, monkeypatch, sheet)
    out = capsys.readouterr().out

    assert code == 0
    written = [u["range"] for batch in sheet.batches for u in batch]
    marker = [r for r in written if r.startswith("L")]
    assert len(marker) == 1, f"a clean column should travel as one range: {written}"
    assert "left alone" not in out, out


def test_an_unreadable_column_is_treated_as_occupied():
    """
    Fail closed. If we cannot find out what is in the column, writing nothing
    is the safe answer -- and the plan says so out loud rather than reporting
    a successful write of nothing.
    """
    class Unreadable(RecordingWorksheet):
        def get_values(self, range_name, **kwargs):
            raise RuntimeError("the API said no")

    worksheet = Unreadable()
    plan = _writer(worksheet).build_plan(
        _matches([5, 6, 7]), Snapshot([5, 6, 7]), "Sys", "Stn",
    )

    assert not [u for u in plan.updates if u["range"].startswith("L")]
    assert plan.skipped == ["L5", "L6", "L7"]


def test_a_real_write_also_says_what_it_left_alone(tmp_path, monkeypatch, capsys, configured_totals):
    """
    Not only the dry run. On the real path "Wrote 3 ranges" is exactly what
    the tool printed while it was destroying twenty formulas, so the write
    path is the one that most needs to say what it did not touch.
    """
    sheet = RangeAwareWorksheet(_planted_grid())
    code = _cli(tmp_path, monkeypatch, sheet)
    out = capsys.readouterr().out

    assert code == 0
    assert "Wrote" in out, out
    assert "left alone" in out and "L5" in out, out


def test_the_occupancy_read_is_bounded_by_the_block_being_written():
    """
    A worksheet may answer with more than it was asked for -- the suite's own
    fakes return their whole grid whatever range you name. The occupancy
    decision must cover exactly the rows about to be written and no others,
    or a value living BELOW the block gets reported as a skipped cell inside
    it, and the row numbering of everything in `skipped` is off.
    """
    class Overshooting(RecordingWorksheet):
        def get_values(self, range_name, **kwargs):
            self.reads.append((range_name, kwargs))
            first, last = _bounds(range_name)
            rows = [[""] for _ in range(first, last + 1)]
            return rows + [["something further down the column"]]

    worksheet = Overshooting()
    plan = _writer(worksheet).build_plan(
        _matches([5, 6]), Snapshot([5, 6]), "Sys", "Stn",
    )

    assert plan.skipped == []
    assert [u["range"] for u in plan.updates if u["range"].startswith("L")] == ["L5:L6"]


def test_a_cell_holding_only_whitespace_is_not_treated_as_occupied():
    """
    A deliberate line, not an accident of `.strip()`.

    "Holds something" means data a person would miss. A cell containing only
    spaces is not that -- and treating it as occupied would freeze a row
    nobody can explain, permanently, because nothing in the sheet LOOKS
    different from an empty cell. The tool's own blanking writes "", so this
    costs nothing real and removes a failure mode with no visible cause.
    """
    worksheet = RecordingWorksheet({"L5": "   ", "L6": "\t"})
    plan = _writer(worksheet).build_plan(
        _matches([5, 6]), Snapshot([5, 6]), "Sys", "Stn",
    )

    assert plan.skipped == []
    assert [u["range"] for u in plan.updates if u["range"].startswith("L")] == ["L5:L6"]


def test_a_context_that_forgot_to_carry_force_does_not_overwrite():
    """
    The plugin reads `force` with `.get(..., False)` rather than `[...]`, and
    this is what makes that a decision instead of a habit: a refresh context
    assembled without the option must come out as "do not overwrite", never
    as "overwrite" and never as a KeyError a caller could paper over.
    """
    from APITool.plugins import totals
    from APITool.registry import Refresh

    worksheet = RecordingWorksheet({"L5": "=A FORMULA()"})
    layout = Layout()
    ctx = Refresh(
        {"requirements": lambda ctx: Snapshot([5])},
        worksheet=worksheet,
        layout=layout,
        guard=WriteGuard.build(layout.writes()),
        catalog=None,
        renderer=Renderer(),
        options={"write": False, "write_header": False, "show_covered": True,
                 "apply_colour": False, "include_markers": True},   # no "force"
        target="",
        result=_result_at(rows=[5]),
        checked_at="",
    )
    plan = totals._publish_markers(ctx)

    assert plan.skipped == ["L5"]
    assert not [u for u in plan.updates if u["range"].startswith("L5")]


def _result_at(rows):
    """The slice of a RefreshResult that the marker subscriber reads."""
    import types

    return types.SimpleNamespace(
        matches=_matches(rows),
        location=types.SimpleNamespace(system="Sys", station_display="Stn"),
    )


# ---------------------------------------------------------------------------
# What the report actually says
# ---------------------------------------------------------------------------


def test_the_skip_report_condenses_runs_and_leaves_single_cells_single():
    """
    The shape of the line, not just its presence. Twenty skipped cells must
    read as one span; a lone cell must not read as "L5:L5", which looks like
    a range and invites the reader to wonder what happened to L6.
    """
    from APITool.cli import _condense_cells

    assert _condense_cells([f"L{r}" for r in range(5, 25)]) == "L5:L24"
    assert _condense_cells(["L5"]) == "L5"
    assert _condense_cells(["L5", "L6", "L7", "L9", "L14", "L15", "L24"]) == (
        "L5:L7, L9, L14:L15, L24"
    )
    # Different columns never merge, however adjacent their row numbers look.
    assert _condense_cells(["L9", "M10"]) == "L9, M10"


def test_a_skipped_cell_is_not_coloured_either():
    """
    Colour is a write. Painting a cell we just decided not to touch would not
    destroy the formula in it, but it is still an unasked-for edit to a cell
    that is not ours -- and the plan would be reporting a skip while editing
    the cell anyway. The same reasoning `--no-glyph-markers` already applies to the
    whole column applies here to one cell of it.
    """
    class Colouring(Renderer):
        def cell_format(self, match, value):
            return {"backgroundColor": {"red": 1.0}}

    layout = Layout()
    worksheet = RecordingWorksheet({"L5": "=A FORMULA()"})
    writer = MarkerWriter(
        worksheet, Colouring(), layout, guard=WriteGuard.build(layout.writes()),
    )
    plan = writer.build_plan(_matches([5, 6]), Snapshot([5, 6]), "Sys", "Stn")

    assert plan.skipped == ["L5"]
    assert [f["range"] for f in plan.formats] == ["L6"]
