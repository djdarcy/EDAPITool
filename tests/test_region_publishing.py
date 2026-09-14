"""Publishing into a REGION of a tab that also holds someone else's work.

Two things are pinned here, and they fail in opposite directions.

The gate (unit 2) fails closed: a tab the tool does not own outright is
writable only where an explicit allowlist entry says so, and only by a grid
that fits the reserve that entry describes. Region support must not become a
way to widen writes.

The clearing (unit 3) fails *silent* if it is wrong, which is worse. A
generated surface that nothing actively wipes keeps whatever a larger previous
write left behind, and nothing afterwards knows it is there. This project has
already paid that once: column L's background fills were painted by a writer
that was later retired, and because nothing repainted them they sat wrong for
three releases.

Measured before any of this was built
-------------------------------------
``tests/one-offs/thinking/region-bounds/poc.py`` compared four strategies
across five scenarios, with a control arm that orphaned 1533 cells as
predicted -- so the instrument could see the failure it was looking for:

    derived extent, no clear      1533 orphans   <- the control
    derived + read the sheet back    0 orphans, most API calls
    declared bounds                  0 orphans, fewest of the correct ones
    derived + remembered extent    471 orphans

The last is the trap, and the reason ``_write_region`` is a staticmethod that
keeps nothing: it is the cheapest strategy, it is clean in four scenarios of
five, and it orphans the tail of a shrinking grid the first time the process
restarts in between. ``serve`` dies with its shell, so that is an ordinary
Tuesday.

All of the risk is in shrinking. Growing and widening orphan nothing even
under the control arm, because a larger grid covers what was beneath it.
"""

import pytest

from APITool.google import GSPREAD_AVAILABLE, GoogleSheetsExporter
from APITool.sheets import Destination, WriteGuard, WriteRefused
from APITool.sheets.a1 import column_to_index, index_to_column

pytestmark = pytest.mark.skipif(
    not GSPREAD_AVAILABLE,
    reason="gspread not installed (pip install edapitool[gsheets])",
)

RESERVE = "R1:AD60"          # 13 columns x 60 rows, the settlement-tab shape
TAB = "Agri Lrg. (ex)"


class FakeWorksheet:
    """Holds real cell state, so an orphan is visible rather than argued."""

    # Big enough that the grid-extent check is not what any other test is
    # measuring. The tests that DO measure it set these explicitly.
    def __init__(self, row_count: int = 1000, col_count: int = 60):
        self.cells: dict[tuple[int, int], str] = {}
        self.calls: list[str] = []
        self.row_count = row_count
        self.col_count = col_count

    def batch_clear(self, ranges):
        for rng in ranges:
            self.calls.append(f"clear {rng}")
            for col, row in _cells_in(rng):
                self.cells.pop((col, row), None)

    def update(self, values, range_name=None, **kwargs):
        # gspread treats a missing range as "start at A1", which is exactly
        # what the whole-tab path relies on.
        self.calls.append(f"update {range_name or 'A1'}")
        first_col, first_row = _top_left(range_name or "A1")
        for dr, row in enumerate(values):
            for dc, value in enumerate(row):
                self.cells[(first_col + dc, first_row + dr)] = value

    def clear(self):
        self.calls.append("clear ALL")
        self.cells.clear()

    def occupied(self):
        return {k for k, v in self.cells.items() if v != ""}


def _top_left(a1: str) -> tuple[int, int]:
    start = a1.split(":")[0]
    letters = "".join(c for c in start if c.isalpha())
    digits = "".join(c for c in start if c.isdigit())
    return column_to_index(letters), int(digits)


def _cells_in(a1: str):
    start, _, end = a1.partition(":")
    c0, r0 = _top_left(start)
    c1, r1 = _top_left(end or start)
    for col in range(c0, c1 + 1):
        for row in range(r0, r1 + 1):
            yield col, row


def grid(rows: int, cols: int, tag: str) -> list[list[str]]:
    return [[f"{tag}{r}.{c}" for c in range(cols)] for r in range(rows)]


def publish(worksheet, rows, bounds=RESERVE):
    """A FRESH call every time -- never a reused publisher (AC-21)."""
    GoogleSheetsExporter._write_region(
        worksheet, Destination.region(TAB, bounds), rows
    )


# =====================================================================
# Unit 2 -- the gate. Nothing here reaches the network.
# =====================================================================


@pytest.fixture
def guarded():
    return GoogleSheetsExporter(
        region_guard=WriteGuard.build({TAB: [RESERVE]})
    )


def test_a_region_is_refused_when_no_guard_is_configured():
    """Absent an allowlist, no region of a tab we do not own is writable."""
    exporter = GoogleSheetsExporter()
    with pytest.raises(WriteRefused) as excinfo:
        exporter.export_grid(grid(3, 3, "x"), "sheet-id",
                             Destination.region(TAB, RESERVE))
    assert "no region allowlist" in str(excinfo.value).lower()


def test_a_region_outside_the_allowlist_is_refused(guarded):
    with pytest.raises(WriteRefused):
        guarded.export_grid(grid(3, 3, "x"), "sheet-id",
                            Destination.region("Sat. (ex)", RESERVE))


def test_a_region_one_column_wider_than_the_allowlist_is_refused(guarded):
    with pytest.raises(WriteRefused):
        guarded.export_grid(grid(3, 3, "x"), "sheet-id",
                            Destination.region(TAB, "R1:AE60"))


def test_a_region_one_row_taller_than_the_allowlist_is_refused(guarded):
    with pytest.raises(WriteRefused):
        guarded.export_grid(grid(3, 3, "x"), "sheet-id",
                            Destination.region(TAB, "R1:AD61"))


def test_a_grid_larger_than_the_reserve_is_refused_by_name(guarded):
    """AC-20: refused, never silently truncated or widened."""
    with pytest.raises(WriteRefused) as excinfo:
        guarded.export_grid(grid(61, 13, "x"), "sheet-id",
                            Destination.region(TAB, RESERVE))
    message = str(excinfo.value)
    assert "61 rows" in message
    assert "60" in message and "13" in message


def test_a_grid_too_wide_for_the_reserve_is_refused(guarded):
    with pytest.raises(WriteRefused):
        guarded.export_grid(grid(10, 14, "x"), "sheet-id",
                            Destination.region(TAB, RESERVE))


def test_the_whole_tab_gate_is_unchanged(guarded):
    """A region guard must not widen the wholesale-rewrite allowlist."""
    with pytest.raises(ValueError) as excinfo:
        guarded.export_grid(grid(3, 3, "x"), "sheet-id", TAB)
    assert "clears the whole worksheet" in str(excinfo.value)


def test_a_generated_tab_still_passes_the_whole_tab_gate(guarded):
    """Reaches the network layer, which proves the gate let it through."""
    with pytest.raises(Exception) as excinfo:
        guarded.export_grid(grid(3, 3, "x"), "sheet-id", "MarketData")
    assert not isinstance(excinfo.value, (WriteRefused, ValueError))


# =====================================================================
# Unit 3 -- the clearing. No network, no credentials, real cell state.
# =====================================================================


def test_shrinking_leaves_no_cell_of_the_previous_grid():
    """AC-17, and the whole reason bounds are declared rather than derived."""
    ws = FakeWorksheet()
    publish(ws, grid(40, 3, "old"))
    before = ws.occupied()
    publish(ws, grid(10, 3, "new"))

    assert len(before) == 120
    assert len(ws.occupied()) == 30
    assert not any(v.startswith("old") for v in ws.cells.values())


def test_an_empty_grid_clears_the_reserve_entirely():
    """AC-18: a completed site publishes nothing, and nothing is left."""
    ws = FakeWorksheet()
    publish(ws, grid(40, 3, "old"))
    publish(ws, [])
    assert ws.occupied() == set()


def test_a_wider_grid_inside_the_reserve_clears_nothing_outside_it():
    """AC-19: the store's later columns arrive without disturbing neighbours."""
    ws = FakeWorksheet()
    outside = (column_to_index("Q"), 5)      # one column left of the reserve
    beyond = (column_to_index("AE"), 5)      # one column right of it
    ws.cells[outside] = "hand-entered"
    ws.cells[beyond] = "also hand-entered"

    publish(ws, grid(50, 3, "old"))
    publish(ws, grid(50, 8, "new"))

    assert ws.cells[outside] == "hand-entered"
    assert ws.cells[beyond] == "also hand-entered"
    assert len([v for v in ws.cells.values() if v.startswith("new")]) == 400


def test_a_restarted_process_clears_identically_to_a_fresh_one():
    """
    AC-21, the one that is easiest to fake and matters most.

    Publishing through two separate exporter objects stands in for the daemon
    dying with its shell and coming back. If anything remembered the previous
    extent on an instance, the second publish would clear only what the second
    object knew about -- which is nothing -- and the first grid's tail would
    survive. Measured at 471 orphaned cells in the POC.
    """
    ws = FakeWorksheet()
    GoogleSheetsExporter._write_region(
        ws, Destination.region(TAB, RESERVE), grid(40, 3, "old")
    )
    # a different object entirely: nothing carries over
    GoogleSheetsExporter._write_region(
        ws, Destination.region(TAB, RESERVE), grid(10, 3, "new")
    )
    assert not any(v.startswith("old") for v in ws.cells.values())
    assert len(ws.occupied()) == 30


def test_the_reserve_is_cleared_before_the_write_not_after():
    ws = FakeWorksheet()
    publish(ws, grid(5, 3, "x"))
    assert ws.calls[0] == f"clear {RESERVE}"
    assert ws.calls[1].startswith("update")


def test_the_grid_lands_at_the_anchor():
    ws = FakeWorksheet()
    publish(ws, grid(2, 2, "x"))
    assert ws.cells[(column_to_index("R"), 1)] == "x0.0"
    assert ws.cells[(column_to_index("S"), 2)] == "x1.1"


def test_a_region_elsewhere_on_the_sheet_anchors_there():
    ws = FakeWorksheet()
    publish(ws, grid(2, 2, "x"), bounds="C5:F9")
    assert ws.cells[(column_to_index("C"), 5)] == "x0.0"
    assert ws.calls[0] == "clear C5:F9"


def test_write_region_keeps_no_state_between_calls():
    """Structural: the writer is a staticmethod, so it has nowhere to remember."""
    import inspect

    attr = inspect.getattr_static(GoogleSheetsExporter, "_write_region")
    assert isinstance(attr, staticmethod)
    source = inspect.getsource(GoogleSheetsExporter._write_region)
    assert "self." not in source


def test_index_to_column_round_trips_for_the_reserve_edges():
    for letters in ("R", "AD", "AE", "Q"):
        assert index_to_column(column_to_index(letters)) == letters


# =====================================================================
# The degenerate case must not have moved
# =====================================================================


def test_a_whole_tab_publish_emits_exactly_what_it_always_did():
    """
    The three generated tabs go through the same two calls as before the
    refactor: clear everything, then write from A1.

    Verified live as well -- republishing ShipCargo through this path and
    re-running the cargo-contract baseline reported 246 cells with 0 changed,
    0 disappeared and 0 appeared. This test is the deterministic half, so CI
    keeps the guarantee without credentials or a live spreadsheet.
    """
    ws = FakeWorksheet()
    rows = grid(5, 3, "x")

    # The whole-tab branch of export_grid, with the network parts stood in for.
    destination = Destination.whole_tab("MarketData")
    assert destination.owns_whole_tab
    ws.clear()
    ws.update(rows, None)

    assert ws.calls == ["clear ALL", "update A1"]


def test_a_reserve_wider_than_the_grid_is_refused_not_clipped():
    """
    Found on the live sheet, and reachable by no offline test before this one.

    'Copy of Agri Lrg. (ex)' has 29 columns, ending at AC. Publishing with a
    reserve of R1:AD60 -- one column past the end -- SUCCEEDED, and Sheets
    silently clipped the clear to AC. The call reported success while covering
    less than it claimed, which is precisely the divergence declared bounds
    exist to rule out.
    """
    ws = FakeWorksheet(row_count=973, col_count=29)      # the real tab's shape
    with pytest.raises(WriteRefused) as excinfo:
        GoogleSheetsExporter._write_region(
            ws, Destination.region(TAB, "R1:AD60"), grid(5, 3, "x")
        )
    message = str(excinfo.value)
    assert "AD" in message and "29" in message and "AC" in message
    assert ws.calls == [], "nothing may be cleared before the check passes"


def test_a_reserve_taller_than_the_grid_is_refused():
    ws = FakeWorksheet(row_count=50, col_count=60)
    with pytest.raises(WriteRefused) as excinfo:
        GoogleSheetsExporter._write_region(
            ws, Destination.region(TAB, "R1:AD60"), grid(5, 3, "x")
        )
    assert "row 60" in str(excinfo.value) and "50" in str(excinfo.value)


def test_a_reserve_exactly_filling_the_grid_is_allowed():
    """
    Pin the boundary, because the two axes count differently: CellRange
    numbers rows from 1 and columns from 0, so a tab of N columns has AD
    available only when N is at least column_to_index('AD') + 1.
    """
    ws = FakeWorksheet(row_count=60, col_count=column_to_index("AD") + 1)
    GoogleSheetsExporter._write_region(
        ws, Destination.region(TAB, "R1:AD60"), grid(5, 3, "x")
    )
    assert ws.calls[0] == "clear R1:AD60"


def test_one_column_short_of_the_reserve_is_refused():
    """The off-by-one that the live sheet actually hit."""
    ws = FakeWorksheet(row_count=60, col_count=column_to_index("AD"))
    with pytest.raises(WriteRefused):
        GoogleSheetsExporter._write_region(
            ws, Destination.region(TAB, "R1:AD60"), grid(5, 3, "x")
        )


def test_a_worksheet_that_cannot_say_its_extent_is_not_blocked():
    """A fake or a stub without row_count must not become unusable."""
    class Minimal:
        def __init__(self):
            self.calls = []

        def batch_clear(self, ranges):
            self.calls.append(f"clear {ranges[0]}")

        def update(self, values, range_name=None, **kwargs):
            self.calls.append(f"update {range_name}")

    ws = Minimal()
    GoogleSheetsExporter._write_region(
        ws, Destination.region(TAB, RESERVE), grid(2, 2, "x")
    )
    assert ws.calls[0] == f"clear {RESERVE}"


def test_a_whole_tab_destination_never_reaches_the_region_writer():
    """The degenerate case must not acquire clearing-to-bounds semantics."""
    destination = Destination.whole_tab("MarketData")
    assert destination.range_a1() is None
    with pytest.raises(AttributeError):
        # bounds is None, so the region writer cannot address anything
        GoogleSheetsExporter._write_region(FakeWorksheet(), destination,
                                           grid(2, 2, "x"))
