"""
The writer obeys the writes ledger (slice 4, #25 criterion 3).

The painted-sheet freeze, and its fix: a workbook that lets the tool paint its
glyph-marker column used to freeze on the first station's glyphs, because every
glyph the tool painted counted as "occupied" at the next station. With the
ledger, the tool's own cells refresh and a person's edit is still left alone.

SAFETY (rule 1b): every worksheet here is a fake that records its writes; no
test can reach a spreadsheet, and every "held" assertion is made against the
fake's recorded writes, so a held cell that got written would be seen.
"""

from __future__ import annotations

from APITool.sheets import WriteGuard
from APITool.sheets.ledger import MemoryLedger
from APITool.sheets.writer import MarkerWriter

from test_marker_skip_occupied import Layout, RecordingWorksheet, Snapshot, _matches


class StationRenderer:
    """Paints the glyph a station says for each row, so two stations differ."""

    def __init__(self, glyphs: dict[int, str]):
        self.glyphs = glyphs

    def cell(self, match, show_covered: bool = True):
        return self.glyphs.get(match.row, "")

    def cell_note(self, match, checked_at):
        return ""

    def cell_format(self, match, value):
        return None


def _writer(worksheet, glyphs, ledger):
    layout = Layout()
    return MarkerWriter(worksheet, StationRenderer(glyphs), layout,
                        guard=WriteGuard.build(layout.writes()), ledger=ledger)


def _publish(worksheet, glyphs, ledger, **kwargs):
    rows = sorted(glyphs)
    writer = _writer(worksheet, glyphs, ledger)
    plan = writer.build_plan(_matches(rows), Snapshot(rows), "Sys", "Stn", **kwargs)
    writer.apply(plan)
    return plan


def _written_cells(worksheet) -> set[str]:
    out = set()
    for update in worksheet.writes:
        rng = update["range"]
        column = rng.split(":")[0].rstrip("0123456789")
        first = int(rng.split(":")[0][len(column):])
        for offset in range(len(update["values"])):
            out.add(f"{column}{first + offset}")
    return out


# ---------------------------------------------------------------------------
# The painted sheet across two stations -- the slice's proof
# ---------------------------------------------------------------------------


def test_a_painted_sheet_refreshes_its_own_glyphs_and_keeps_a_persons_edit():
    sheet = RecordingWorksheet()
    ledger = MemoryLedger()

    first = _publish(sheet, {5: "●", 6: "◑", 7: "○"}, ledger)
    assert first.filled == ["L5", "L6", "L7"]

    sheet.cells["L6"] = "hand-typed"          # a person edits one of our cells
    sheet.writes.clear()

    second = _publish(sheet, {5: "◔", 6: "●", 7: "●"}, ledger)

    assert second.refreshed == ["L5", "L7"], "the tool's own glyphs from the last station"
    assert second.held == ["L6"], "the person's edit"
    assert _written_cells(sheet) == {"L5", "L7"}, "L6 must not be written at all"
    assert sheet.cells["L5"] == "◔" and sheet.cells["L7"] == "●"
    assert sheet.cells["L6"] == "hand-typed"


def test_without_a_ledger_the_same_sheet_freezes_as_v076_did():
    """The control arm: what the ledger fixes, shown failing without it."""
    sheet = RecordingWorksheet()
    _publish(sheet, {5: "●", 6: "◑"}, None)
    sheet.writes.clear()

    second = _publish(sheet, {5: "◔", 6: "●"}, None)

    assert second.held == ["L5", "L6"] and _written_cells(sheet) == set()


# ---------------------------------------------------------------------------
# What is recorded
# ---------------------------------------------------------------------------


class Normalising(RecordingWorksheet):
    """Sheets reinterprets USER_ENTERED text; this fake drops a leading zero."""

    def batch_update(self, data, **kwargs):
        cleaned = [{"range": u["range"],
                    "values": [[str(int(v[0])) if v and v[0].isdigit() else (v[0] if v else "")]
                               for v in u["values"]]} for u in data]
        super().batch_update(cleaned, **kwargs)


def test_what_reads_back_is_recorded_not_what_was_sent():
    """Record what was sent and the tool's own "007" cell reads "7" and is foreign."""
    sheet = Normalising()
    ledger = MemoryLedger()

    _publish(sheet, {5: "007"}, ledger)
    assert ledger.recorded("Totals Tab", ["L5"]) == {"L5": "7"}

    second = _publish(sheet, {5: "008"}, ledger)
    assert second.refreshed == ["L5"]


def test_a_failed_read_back_records_nothing_and_the_cell_is_held_next_time():
    class ReadBackFails(RecordingWorksheet):
        calls = 0

        def batch_get(self, ranges, **kwargs):
            self.calls += 1
            if self.calls == 2:                  # the read-back, after the write
                raise RuntimeError("the API said no")
            return super().batch_get(ranges, **kwargs)

    sheet = ReadBackFails()
    ledger = MemoryLedger()
    _publish(sheet, {5: "●"}, ledger)

    assert ledger.records == []
    assert _publish(sheet, {5: "◑"}, ledger).held == ["L5"]


def test_one_force_adopts_old_paint_for_good():
    """Decision 4: the first run after upgrading holds; one --force adopts."""
    sheet = RecordingWorksheet({"L5": "●"})     # paint from before the ledger existed
    ledger = MemoryLedger()

    assert _publish(sheet, {5: "◑"}, ledger).held == ["L5"]
    forced = _publish(sheet, {5: "◑"}, ledger, force=True)
    assert forced.forced == ["L5"] and ledger.recorded("Totals Tab", ["L5"]) == {"L5": "◑"}

    assert _publish(sheet, {5: "○"}, ledger).refreshed == ["L5"]


def test_the_header_cell_is_outside_the_rule_and_not_recorded():
    sheet = RecordingWorksheet()
    ledger = MemoryLedger()

    _publish(sheet, {5: "●"}, ledger, write_header=True)

    assert "L3" in _written_cells(sheet)
    assert not any(a1 == "L3" for (_, a1) in ledger.cells), ledger.cells
    assert ledger.recorded("Totals Tab", ["L5"]) == {"L5": "●"}


def test_the_location_cells_are_recorded_and_refreshed_like_markers():
    sheet = RecordingWorksheet()
    ledger = MemoryLedger()

    _publish(sheet, {5: "●"}, ledger, write_location=True)
    assert ledger.recorded("Totals Tab", ["C2", "G2"]) == {"C2": "Sys", "G2": "Stn"}

    second = _publish(sheet, {5: "●"}, ledger, write_location=True)
    assert second.refreshed[:2] == ["C2", "G2"]


def test_a_dry_run_reads_the_ledger_and_records_nothing():
    sheet = RecordingWorksheet({"L5": "●"})
    ledger = MemoryLedger({("Totals Tab", "L5"): "●"})
    writer = _writer(sheet, {5: "◑"}, ledger)

    plan = writer.build_plan(_matches([5]), Snapshot([5]), "Sys", "Stn")

    assert plan.refreshed == ["L5"]
    assert ledger.records == [] and sheet.writes == []


# ---------------------------------------------------------------------------
# What it costs -- #29 criterion 8: the extra calls, measured
# ---------------------------------------------------------------------------


class Counting(RecordingWorksheet):
    def __init__(self, cells=None):
        super().__init__(cells)
        self.calls: list[str] = []

    def get_values(self, range_name, **kwargs):
        self.calls.append("get_values")
        return super().get_values(range_name, **kwargs)

    def batch_get(self, ranges, **kwargs):
        self.calls.append("batch_get")
        # Answer without going through get_values, so one call counts once.
        return [RecordingWorksheet.get_values(self, r, **kwargs) for r in ranges]

    def batch_update(self, data, **kwargs):
        self.calls.append("batch_update")
        return super().batch_update(data, **kwargs)

    def batch_format(self, data, **kwargs):
        self.calls.append("batch_format")


def test_the_writer_costs_one_extra_read_per_real_write():
    """v0.8.0: read, update, format = 3. v0.8.1 with a ledger: + one read-back = 4."""
    class Colour(StationRenderer):
        def cell_format(self, match, value):
            return {"backgroundColor": {"red": 1.0}}

    layout = Layout()
    for ledger, expected in ((None, ["batch_get", "batch_update", "batch_format"]),
                             (MemoryLedger(), ["batch_get", "batch_update", "batch_format",
                                               "batch_get"])):
        sheet = Counting()
        writer = MarkerWriter(sheet, Colour({5: "●", 6: "◑"}), layout,
                              guard=WriteGuard.build(layout.writes()), ledger=ledger)
        plan = writer.build_plan(_matches([5, 6]), Snapshot([5, 6]), "Sys", "Stn",
                                 write_location=True)
        writer.apply(plan)
        assert sheet.calls == expected, (ledger, sheet.calls)


def test_an_empty_single_cell_answer_is_read_as_empty_not_a_crash():
    """
    gspread answers a single empty cell with an EMPTY list, not [[""]] -- the
    suite's other fakes always return the padded shape, so this is the one
    that sends what the API sends. (Mutation survivor v0.8.1 unit 3 M07.)
    """
    class SparseAnswers(RecordingWorksheet):
        def batch_get(self, ranges, **kwargs):
            out = []
            for r in ranges:
                rows = RecordingWorksheet.get_values(self, r, **kwargs)
                out.append([] if all(not row or row[0] == "" for row in rows) else rows)
            return out

    sheet = SparseAnswers()
    plan = _writer(sheet, {5: "●"}, MemoryLedger()).build_plan(
        _matches([5]), Snapshot([5]), "Sys", "Stn", write_location=True)

    assert plan.filled == ["C2", "G2", "L5"]


def test_nothing_governed_written_means_no_read_back():
    """
    When every governed cell is held and only the (ungoverned) header is
    written, a read-back could record nothing -- so it is not made. The call
    count is the contract #29 asks to be stated. (Mutation survivor M11.)
    """
    sheet = Counting({"L5": "=A FORMULA()"})
    writer = _writer(sheet, {5: "●"}, MemoryLedger())
    plan = writer.build_plan(_matches([5]), Snapshot([5]), "Sys", "Stn", write_header=True)
    writer.apply(plan)

    assert plan.held == ["L5"]
    assert sheet.calls == ["batch_get", "batch_update"], sheet.calls


def test_a_dry_run_costs_one_read_whatever_is_planned():
    sheet = Counting()
    _writer(sheet, {5: "●"}, MemoryLedger()).build_plan(
        _matches([5]), Snapshot([5]), "Sys", "Stn", write_location=True)
    assert sheet.calls == ["batch_get"], "the location cells and the column in one call"
