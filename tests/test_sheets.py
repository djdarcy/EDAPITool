"""
Tests for sheet reading and guarded writing
(build steps B-2/B-3, acceptance checks AC-2, AC-3, AC-3b).

The layout under test is the measured live one (2026-09-08):
headers on row 3, commodity rows from 5, "Left to buy" in column G,
column L empty across all 221 rows.
"""

import pytest

from APITool.catalog import load_catalog
from APITool.market import Market, MarketItem
from APITool.matcher import MatchState, build_requirements, compare
from APITool.sheets import (
    MARKER_COVERED,
    MARKER_EMPTY,
    MARKER_EMPTY_DOTTED,
    MARKER_ENOUGH,
    MARKER_HALF,
    MARKER_PARTIAL,
    MARKER_QUARTER,
    MARKER_THREE_QUARTER,
    coverage,
    SIGN_NEGATIVE,
    SIGN_POSITIVE,
    CellRange,
    SheetLayout,
    SheetLayoutError,
    RequirementSnapshot,
    TotalsTabReader,
    TotalsTabWriter,
    WriteGuard,
    WriteRefused,
    column_to_index,
    index_to_column,
    marker_for,
    marker_note,
    parse_quantity,
)


class FakeWorksheet:
    """Records writes instead of performing them."""

    def __init__(self, grid: list[list[str]], title: str = "Totals Tab"):
        self.grid = grid
        self.title = title
        self.batches: list[list[dict]] = []
        self.format_batches: list[list[dict]] = []

    def get_values(self, range_name: str, **kwargs) -> list[list[str]]:
        return [list(row) for row in self.grid]

    def batch_update(self, data: list[dict], **kwargs):
        self.batches.append(data)
        return {"replies": []}

    def batch_format(self, formats: list[dict]):
        self.format_batches.append(formats)
        return {"replies": []}


def make_grid(
    rows: list[tuple[str, str]],
    need_header: str = "Left to buy",
    need_col: int = 6,          # G
    header_row: int = 3,
    first_data_row: int = 5,
    width: int = 30,
) -> list[list[str]]:
    """Build a Totals-Tab-shaped grid: (commodity name, need) per data row."""
    grid = [[""] * width for _ in range(first_data_row + len(rows) + 3)]
    grid[0][1] = "Total Round Trips:"
    grid[1][1] = "Current Star System:"
    grid[1][2] = "Lhou Mans"
    grid[1][5] = "Cur Station:"

    header = grid[header_row - 1]
    header[1] = "ALL SETTLEMENTS"
    header[2] = "Required"
    header[3] = "In Carrier Now"
    header[5] = "Left to deliver"
    header[need_col] = need_header
    header[7] = "Extra next rnd"
    header[8] = "Cost"

    grid[header_row][1] = "TOTAL"          # the TOTAL row, right after headers
    grid[header_row][2] = "15,238"

    for offset, (name, need) in enumerate(rows):
        row = grid[first_data_row - 1 + offset]
        row[1] = name
        row[need_col] = need
    return grid


LIVE_ROWS = [
    ("Aluminium", "0"),
    ("Biowaste", "229"),
    ("Emergency power cells", "251"),
    ("Land enrichment systems", "210"),
    ("Power Generators", "9"),
    ("Steel", "0"),
]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


# ---------------------------------------------------------------------------
# A1 helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "letters,index", [("A", 0), ("B", 1), ("G", 6), ("L", 11), ("Z", 25), ("AA", 26), ("AZ", 51)]
)
def test_column_index_round_trip(letters, index):
    assert column_to_index(letters) == index
    assert index_to_column(index) == letters


def test_column_to_index_rejects_junk():
    with pytest.raises(ValueError):
        column_to_index("A1")
    with pytest.raises(ValueError):
        index_to_column(-1)


def test_cell_range_parses_single_cell():
    r = CellRange.parse("C2")
    assert (r.first_col, r.first_row, r.last_col, r.last_row) == (2, 2, 2, 2)


def test_cell_range_parses_open_ended_column():
    r = CellRange.parse("L3:L")
    assert r.first_col == 11 and r.first_row == 3
    assert r.last_col == 11 and r.last_row is None


def test_cell_range_containment():
    allowed = CellRange.parse("L3:L")
    assert allowed.contains(CellRange.parse("L5:L32"))
    assert allowed.contains(CellRange.parse("L3"))
    assert not allowed.contains(CellRange.parse("L2"))       # above the start
    assert not allowed.contains(CellRange.parse("K5:K32"))   # wrong column
    assert not allowed.contains(CellRange.parse("K5:L32"))   # spills left


def test_cell_range_rejects_junk():
    for bad in ("", "not a range", "!!", ":"):
        with pytest.raises(ValueError):
            CellRange.parse(bad)


# ---------------------------------------------------------------------------
# AC-2: the write allowlist
# ---------------------------------------------------------------------------

@pytest.fixture
def guard():
    return SheetLayout().guard()


def test_ac2_permitted_writes_are_allowed(guard):
    for a1 in ("C2", "G2", "L3", "L5", "L5:L32", "L3:L221"):
        assert guard.allows("Totals Tab", a1), a1


@pytest.mark.parametrize(
    "a1",
    [
        "B5",        # the commodity formula -- the one that must never be touched
        "B5:B32",
        "G5",        # Left to buy: a formula
        "A1",
        "C3",        # the header row
        "C1",
        "M5",        # In Ship Cargo: hand-entered
        "K5",
        "L2",        # above the marker header
        "A1:Z100",   # a whole-sheet write
    ],
)
def test_ac2_writes_outside_the_allowlist_are_refused(guard, a1):
    assert not guard.allows("Totals Tab", a1)
    with pytest.raises(WriteRefused, match="outside the allowlist"):
        guard.check("Totals Tab", a1)


@pytest.mark.parametrize(
    "tab", ["Agri Lrg. (ex)", "Sat. (ex)", "Extr. (ex)", "Base", "Sheet1", "Anything Else"]
)
def test_ac2_every_other_tab_is_refused_entirely(guard, tab):
    """
    Deny by default. The old PROTECTED_TABS deny-list left these writable.
    """
    assert not guard.allows(tab, "A1")
    assert not guard.allows(tab, "B5")
    with pytest.raises(WriteRefused):
        guard.check(tab, "A1")


def test_ac2_cargodata_remains_fully_writable(guard):
    """Existing behaviour: CargoData is generated by this tool."""
    assert guard.allows("CargoData", "A1:E100")
    assert guard.allows("CargoData", "A1")


def test_ac2_guard_refuses_unparseable_ranges(guard):
    assert not guard.allows("Totals Tab", "gibberish")
    with pytest.raises(WriteRefused):
        guard.check("Totals Tab", "gibberish")


def test_ac2_empty_guard_denies_everything():
    empty = WriteGuard.build({})
    assert not empty.allows("Totals Tab", "C2")
    with pytest.raises(WriteRefused, match="nothing"):
        empty.check("Totals Tab", "C2")


def test_ac2_guard_follows_a_reconfigured_marker_column():
    layout = SheetLayout(marker_column="O")
    guard = layout.guard()
    assert guard.allows("Totals Tab", "O5:O32")
    assert not guard.allows("Totals Tab", "L5:L32")


# ---------------------------------------------------------------------------
# parse_quantity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("229", 229),
        ("1,716", 1716),
        ("15,238", 15238),
        ("0", 0),
        ("  42  ", 42),
        ("229.0", 229),
        ("-229", -229),
        ("", None),
        ("   ", None),
        ("#N/A", None),        # formula mid-recalculation
        ("#REF!", None),
        ("#DIV/0!", None),
        ("-", None),
        ("abc", None),
    ],
)
def test_parse_quantity(raw, expected):
    assert parse_quantity(raw) == expected


# ---------------------------------------------------------------------------
# AC-3: header discovery
# ---------------------------------------------------------------------------

def test_ac3_finds_left_to_buy_at_g_with_headers_on_row_3(catalog):
    reader = TotalsTabReader(FakeWorksheet(make_grid(LIVE_ROWS)), catalog=catalog)
    snapshot = reader.read()
    assert snapshot.need_column_index == column_to_index("G")
    assert snapshot.header_row == 3
    assert len(snapshot.requirements) == len(LIVE_ROWS)
    assert [r.name for r in snapshot.outstanding] == [
        "Biowaste", "Emergency power cells", "Land enrichment systems", "Power Generators"
    ]


def test_ac3_still_finds_the_column_after_it_moves(catalog):
    """The whole point of header discovery: no code change when a column moves."""
    grid = make_grid(LIVE_ROWS, need_col=column_to_index("T"))
    snapshot = TotalsTabReader(FakeWorksheet(grid), catalog=catalog).read()
    assert snapshot.need_column_index == column_to_index("T")
    assert [r.need for r in snapshot.outstanding] == [229, 251, 210, 9]


def test_ac3_missing_header_raises_with_a_useful_message(catalog):
    grid = make_grid(LIVE_ROWS, need_header="Something Else")
    with pytest.raises(SheetLayoutError, match="Left to buy.*not found"):
        TotalsTabReader(FakeWorksheet(grid), catalog=catalog).read()


def test_ac3_missing_header_message_lists_what_is_present(catalog):
    grid = make_grid(LIVE_ROWS, need_header="Something Else")
    with pytest.raises(SheetLayoutError) as excinfo:
        TotalsTabReader(FakeWorksheet(grid), catalog=catalog).read()
    assert "ALL SETTLEMENTS" in str(excinfo.value)


def test_ac3_duplicate_header_raises_rather_than_guessing(catalog):
    grid = make_grid(LIVE_ROWS)
    grid[2][20] = "Left to buy"        # a second one in column U
    with pytest.raises(SheetLayoutError, match="multiple columns"):
        TotalsTabReader(FakeWorksheet(grid), catalog=catalog).read()


def test_ac3_header_match_is_case_and_space_insensitive(catalog):
    grid = make_grid(LIVE_ROWS, need_header="  LEFT TO BUY  ")
    snapshot = TotalsTabReader(FakeWorksheet(grid), catalog=catalog).read()
    assert snapshot.need_column_index == column_to_index("G")


def test_ac3_too_few_rows_raises(catalog):
    with pytest.raises(SheetLayoutError, match="fewer than 3 rows"):
        TotalsTabReader(FakeWorksheet([[""], [""]]), catalog=catalog).read()


def test_blank_rows_and_the_total_row_are_excluded(catalog):
    """Row 4 is TOTAL and must never become a requirement."""
    snapshot = TotalsTabReader(FakeWorksheet(make_grid(LIVE_ROWS)), catalog=catalog).read()
    assert "TOTAL" not in [r.name for r in snapshot.requirements]
    assert all(r.row >= 5 for r in snapshot.requirements)


def test_error_values_are_reported_not_silently_zeroed(catalog):
    grid = make_grid([("Biowaste", "#N/A"), ("Steel", "0")])
    snapshot = TotalsTabReader(FakeWorksheet(grid), catalog=catalog).read()
    assert snapshot.unparsed_rows == [(5, "Biowaste", "#N/A")]
    assert snapshot.outstanding == []       # not treated as a requirement


def test_last_data_row_tracks_the_real_block(catalog):
    snapshot = TotalsTabReader(FakeWorksheet(make_grid(LIVE_ROWS)), catalog=catalog).read()
    assert snapshot.last_data_row == 5 + len(LIVE_ROWS) - 1


# ---------------------------------------------------------------------------
# AC-3b: the signed "What's left" column
# ---------------------------------------------------------------------------

def test_ac3b_signed_column_inverts_the_convention(catalog):
    """
    The user's planned merge of "Left to buy" and "Extra next rnd":
    -229 means buy 229; +40 means 40 spare.
    """
    rows = [("Biowaste", "-229"), ("Steel", "40"), ("Aluminium", "0")]
    grid = make_grid(rows, need_header="What's left")
    layout = SheetLayout(need_header="What's left", need_sign=SIGN_NEGATIVE)
    snapshot = TotalsTabReader(FakeWorksheet(grid), layout=layout, catalog=catalog).read()

    needs = {r.name: r.need for r in snapshot.requirements}
    assert needs["Biowaste"] == 229      # negative -> outstanding
    assert needs["Steel"] == -40         # positive -> surplus, not a requirement
    assert needs["Aluminium"] == 0
    assert [r.name for r in snapshot.outstanding] == ["Biowaste"]


def test_ac3b_positive_convention_is_the_default(catalog):
    assert SheetLayout().need_sign == SIGN_POSITIVE
    grid = make_grid([("Biowaste", "229")])
    snapshot = TotalsTabReader(FakeWorksheet(grid), catalog=catalog).read()
    assert snapshot.outstanding[0].need == 229


def test_ac3b_a_surplus_row_is_never_marked(catalog):
    """A signed surplus must not produce a marker even if the station sells it."""
    grid = make_grid([("Biowaste", "40")], need_header="What's left")
    layout = SheetLayout(need_header="What's left", need_sign=SIGN_NEGATIVE)
    snapshot = TotalsTabReader(FakeWorksheet(grid), layout=layout, catalog=catalog).read()
    market = Market(1, "S", "Sys", None, "journal",
                    (MarketItem(128049153, "Palladium", "Biowaste", stock=999, buy_price=54),))
    assert compare(snapshot.requirements, market) == []


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def _match(name, need, stock, buy, row):
    from APITool.matcher import compare_one, Requirement
    market = Market(1, "S", "Sys", None, "journal",
                    (MarketItem(1, "X", name, stock=stock, buy_price=buy),))
    return compare_one(Requirement(row=row, name=name, need=need), market)


def test_marker_glyph_per_state():
    assert marker_for(_match("A", 10, 999, 5, 5)) == MARKER_ENOUGH
    assert marker_for(_match("A", 10, 0, 5, 5)) == MARKER_EMPTY
    assert marker_for(_match("A", 10, 0, 0, 5)) == ""


# ---------------------------------------------------------------------------
# The graded fill scale: how full the circle is, is how much of the need
# this station covers. ○ ◔ ◑ ◕ ● -- one scale, five levels.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "need,stock,expected,why",
    [
        (100, 0, MARKER_EMPTY, "sells it, none in stock"),
        (100, 1, MARKER_QUARTER, "barely any"),
        (100, 20, MARKER_QUARTER, "20% rounds down to a quarter"),
        (100, 37, MARKER_QUARTER, "just under the quarter/half boundary"),
        (100, 38, MARKER_HALF, "just over it"),
        (100, 50, MARKER_HALF, "exactly half"),
        (100, 62, MARKER_HALF, "just under the half/three-quarter boundary"),
        (100, 63, MARKER_THREE_QUARTER, "just over it"),
        (100, 90, MARKER_THREE_QUARTER, "most of it"),
        (100, 99, MARKER_THREE_QUARTER, "almost all"),
        (100, 100, MARKER_ENOUGH, "exactly enough is full"),
        (100, 999, MARKER_ENOUGH, "more than enough is still full"),
    ],
)
def test_partial_scale_reflects_coverage(need, stock, expected, why):
    assert marker_for(_match("A", need, stock, 5, 5)) == expected, why


def test_the_scale_is_monotonic():
    """More stock must never produce a less-full glyph."""
    order = [MARKER_EMPTY, MARKER_QUARTER, MARKER_HALF, MARKER_THREE_QUARTER, MARKER_ENOUGH]
    seen = [marker_for(_match("A", 100, s, 5, 5)) for s in range(0, 101, 1)]
    indices = [order.index(g) for g in seen]
    assert indices == sorted(indices)
    assert indices[0] == 0 and indices[-1] == len(order) - 1


def test_coverage_is_clamped():
    assert coverage(_match("A", 100, 0, 5, 5)) == 0.0
    assert coverage(_match("A", 100, 50, 5, 5)) == 0.5
    assert coverage(_match("A", 100, 999, 5, 5)) == 1.0


def test_all_five_glyphs_are_distinct_single_characters():
    glyphs = [MARKER_EMPTY, MARKER_QUARTER, MARKER_HALF, MARKER_THREE_QUARTER, MARKER_ENOUGH]
    assert len(set(glyphs)) == 5
    assert all(len(g) == 1 for g in glyphs)


def test_empty_and_full_are_the_same_circle_family():
    """The hollow/solid pair is what makes 'sold here but out' read as zero."""
    assert ord(MARKER_EMPTY) == 0x25CB
    assert ord(MARKER_QUARTER) == 0x25D4
    assert ord(MARKER_HALF) == 0x25D1
    assert ord(MARKER_THREE_QUARTER) == 0x25D5
    assert ord(MARKER_ENOUGH) == 0x25CF


def test_explicit_marker_override_collapses_the_partial_scale():
    """A caller supplying their own glyphs opts out of the graded scale."""
    custom = {
        MatchState.ENOUGH: "E",
        MatchState.PARTIAL: "P",
        MatchState.EMPTY: "M",
    }
    assert marker_for(_match("A", 100, 999, 5, 5), custom) == "E"
    assert marker_for(_match("A", 100, 20, 5, 5), custom) == "P"
    assert marker_for(_match("A", 100, 90, 5, 5), custom) == "P"
    assert marker_for(_match("A", 100, 0, 5, 5), custom) == "M"
    assert marker_for(_match("A", 100, 0, 0, 5), custom) == ""


def test_layout_markers_flow_through_to_the_plan(catalog):
    """The --empty-marker CLI flag works by setting SheetLayout.markers."""
    custom = {
        MatchState.ENOUGH: MARKER_ENOUGH,
        MatchState.PARTIAL: MARKER_PARTIAL,
        MatchState.EMPTY: MARKER_EMPTY_DOTTED,
    }
    grid = make_grid([("Land enrichment systems", "210")])
    snapshot = TotalsTabReader(FakeWorksheet(grid), catalog=catalog).read()
    market = Market(1, "S", "Sys", None, "journal",
                    (MarketItem(128049232, "TerrainEnrichmentSystems",
                                "Land Enrichment Systems", stock=0, buy_price=3404),))
    matches = compare(snapshot.requirements, market)
    layout = SheetLayout(markers=custom)
    plan = TotalsTabWriter(FakeWorksheet(grid), layout=layout).build_plan(
        matches, snapshot, "Sys", "St"
    )
    column = next(u for u in plan.updates if ":" in u["range"])["values"]
    assert column == [[MARKER_EMPTY_DOTTED]]


def test_marker_note_carries_the_numbers():
    note = marker_note(_match("Biowaste", 229, 70192, 54, 6), checked_at="2026-09-08 05:48 UTC")
    assert "Need: 229" in note
    assert "Stock: 70,192" in note
    assert "Buy now: 229" in note
    assert "Unit price: 54 cr" in note
    assert f"Estimated cost: {229*54:,} cr" in note
    assert "2026-09-08 05:48 UTC" in note


def test_marker_note_for_empty_says_currently_out():
    note = marker_note(_match("Land Enrichment Systems", 210, 0, 3404, 18))
    assert "currently out" in note
    assert "3,404 cr" in note


def test_marker_note_blank_for_unmarked():
    assert marker_note(_match("A", 10, 0, 0, 5)) == ""


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _snapshot_and_matches(catalog, market):
    grid = make_grid(LIVE_ROWS)
    snapshot = TotalsTabReader(FakeWorksheet(grid), catalog=catalog).read()
    return snapshot, compare(snapshot.requirements, market)


@pytest.fixture
def ryman_like():
    return Market(
        3226578176, "Ryman Enterprise", "Lhou Mans", None, "journal",
        (
            MarketItem(128049671, "Biowaste", "Biowaste", stock=70192, buy_price=54),
            MarketItem(128673861, "EmergencyPowerCells", "Emergency Power Cells",
                       stock=0, buy_price=0),
            MarketItem(128049232, "TerrainEnrichmentSystems", "Land Enrichment Systems",
                       stock=0, buy_price=3404),
            MarketItem(128049217, "PowerGenerators", "Power Generators",
                       stock=794414, buy_price=2015),
        ),
    )


def test_plan_writes_location_cells_and_markers(catalog, ryman_like):
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    sheet = FakeWorksheet(make_grid(LIVE_ROWS))
    writer = TotalsTabWriter(sheet)
    plan = writer.build_plan(matches, snapshot, "Lhou Mans", "Ryman Enterprise",
                             write_header=True)

    ranges = plan.ranges()
    assert "C2" in ranges
    assert "G2" in ranges
    assert "L3" in ranges
    assert f"L5:L{snapshot.last_data_row}" in ranges

    values = {u["range"]: u["values"] for u in plan.updates}
    assert values["C2"] == [["Lhou Mans"]]
    assert values["G2"] == [["Ryman Enterprise"]]
    assert values["L3"] == [["At Current Station"]]


def test_plan_marker_column_matches_the_states(catalog, ryman_like):
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    plan = TotalsTabWriter(FakeWorksheet(make_grid(LIVE_ROWS))).build_plan(
        matches, snapshot, "Lhou Mans", "Ryman Enterprise", show_covered=False
    )
    column = next(u for u in plan.updates if ":" in u["range"])["values"]
    # rows 5..10 == Aluminium, Biowaste, Emergency power cells,
    #               Land enrichment systems, Power Generators, Steel
    assert column == [
        [""],               # Aluminium, need 0
        [MARKER_ENOUGH],    # Biowaste
        [""],               # Emergency power cells: no buy price
        [MARKER_EMPTY],     # Land enrichment systems: sold here, out
        [MARKER_ENOUGH],    # Power Generators
        [""],               # Steel, need 0
    ]
    assert plan.marked_rows == [6, 8, 9]


def test_plan_clears_the_whole_marker_block_not_just_hits(catalog, ryman_like):
    """
    Row identity is unstable, so a stale marker must never survive. The plan
    writes a value for EVERY row in the block, blanks included.
    """
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    plan = TotalsTabWriter(FakeWorksheet(make_grid(LIVE_ROWS))).build_plan(
        matches, snapshot, "Lhou Mans", "Ryman Enterprise", show_covered=False
    )
    column = next(u for u in plan.updates if ":" in u["range"])["values"]
    assert len(column) == snapshot.last_data_row - 5 + 1


def test_not_docked_clears_markers(catalog):
    snapshot, _ = _snapshot_and_matches(catalog, Market(None, "", "", None, "journal", ()))
    plan = TotalsTabWriter(FakeWorksheet(make_grid(LIVE_ROWS))).build_plan(
        [], snapshot, "Juipedun", "Not docked", show_covered=False
    )
    values = {u["range"]: u["values"] for u in plan.updates}
    assert values["G2"] == [["Not docked"]]
    column = next(u for u in plan.updates if ":" in u["range"])["values"]
    assert all(cell == [""] for cell in column)
    assert plan.marked_rows == []


def test_apply_sends_one_batch(catalog, ryman_like):
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    sheet = FakeWorksheet(make_grid(LIVE_ROWS))
    writer = TotalsTabWriter(sheet)
    plan = writer.build_plan(matches, snapshot, "Lhou Mans", "Ryman Enterprise",
                             show_covered=False)
    assert writer.apply(plan) == len(plan.updates)
    assert len(sheet.batches) == 1


def test_writer_refuses_a_layout_that_would_hit_formulas(catalog, ryman_like):
    """
    A layout pointing the marker column at B would destroy the commodity
    formulas. The guard must stop it before anything is sent.
    """
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    bad_layout = SheetLayout(marker_column="B")
    sheet = FakeWorksheet(make_grid(LIVE_ROWS))
    # Guard built from the DEFAULT layout, as the service would hold it.
    writer = TotalsTabWriter(sheet, layout=bad_layout, guard=SheetLayout().guard())
    with pytest.raises(WriteRefused):
        writer.build_plan(matches, snapshot, "Lhou Mans", "Ryman Enterprise")
    assert sheet.batches == []      # nothing was sent


def test_dry_run_plan_sends_nothing(catalog, ryman_like):
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    sheet = FakeWorksheet(make_grid(LIVE_ROWS))
    TotalsTabWriter(sheet).build_plan(matches, snapshot, "Lhou Mans", "Ryman Enterprise")
    assert sheet.batches == []      # building a plan is not applying it


def test_header_cell_is_left_alone_by_default(catalog, ryman_like):
    """
    The cell above the markers belongs to whoever owns the sheet. Observed in
    practice: the user had typed their own header there and the tool replaced
    it. Labelling it is now opt-in.
    """
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    plan = TotalsTabWriter(FakeWorksheet(make_grid(LIVE_ROWS))).build_plan(
        matches, snapshot, "Lhou Mans", "Ryman Enterprise", show_covered=False
    )
    assert "L3" not in plan.ranges()
    assert set(plan.ranges()) == {"C2", "G2", f"L5:L{snapshot.last_data_row}"}


def test_header_cell_written_when_explicitly_requested(catalog, ryman_like):
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    plan = TotalsTabWriter(FakeWorksheet(make_grid(LIVE_ROWS))).build_plan(
        matches, snapshot, "Lhou Mans", "Ryman Enterprise", write_header=True,
        show_covered=False
    )
    assert "L3" in plan.ranges()


def test_apply_does_not_mutate_the_plan(catalog, ryman_like):
    """
    gspread rewrites each dict's "range" in place, prefixing the sheet title
    ("L3" -> "'Totals Tab'!L3"). If it were handed our own dicts, the plan
    would be corrupted after one apply and a second apply would be rejected by
    the guard as an unparseable range.
    """
    class MutatingWorksheet(FakeWorksheet):
        def batch_update(self, data, **kwargs):
            for entry in data:                      # what gspread actually does
                entry["range"] = f"'Totals Tab'!{entry['range']}"
            return super().batch_update(data, **kwargs)

    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    sheet = MutatingWorksheet(make_grid(LIVE_ROWS))
    writer = TotalsTabWriter(sheet)
    plan = writer.build_plan(matches, snapshot, "Lhou Mans", "Ryman Enterprise",
                             show_covered=False)
    before = list(plan.ranges())

    writer.apply(plan)
    assert plan.ranges() == before, "apply() must not corrupt the plan it was given"

    # And the plan must remain usable: a second apply still passes the guard.
    writer.apply(plan)
    assert plan.ranges() == before
    assert len(sheet.batches) == 2


def test_notes_are_produced_only_for_marked_rows(catalog, ryman_like):
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    plan = TotalsTabWriter(FakeWorksheet(make_grid(LIVE_ROWS))).build_plan(
        matches, snapshot, "Lhou Mans", "Ryman Enterprise",
        checked_at="2026-09-08 05:48 UTC", show_covered=False
    )
    assert set(plan.notes) == {"L6", "L8", "L9"}
    assert "Stock: 70,192" in plan.notes["L6"]


# ---------------------------------------------------------------------------
# Covered rows: disambiguating the two reasons a cell is blank
#
# Found in use. At Willis Dock the sheet showed no glyph beside "Surface
# stabilisers" even though the station stocked 731,096 of them -- because
# "Left to buy" was 0 (167 already in the carrier). Correct, but a blank meant
# both "not sold here" and "sold here, you need none", which is 13 of 28 rows.
# ---------------------------------------------------------------------------

def _covered_match(name, stock, buy, row=28, need=0):
    from APITool.matcher import Requirement, compare_one
    market = Market(1, "S", "Sys", None, "journal",
                    (MarketItem(1, "X", name, stock=stock, buy_price=buy),))
    return compare_one(Requirement(row=row, name=name, need=need), market)


def test_covered_row_is_never_an_action():
    """A commodity you need none of is never something to buy."""
    match = _covered_match("Surface stabilisers", 731096, 430)
    assert match.is_covered
    assert match.should_mark is False          # not on the buy scale
    assert marker_for(match, show_covered=False) == ""


def test_covered_row_shows_its_fill_glyph_greyed_rather_than_a_tick():
    """
    The glyph says WHAT IS HERE; the colour says whether you need it.
    Surface stabilisers with 731,096 in stock gets a full circle -- greyed
    out by _cell_format, not replaced by a different symbol.
    """
    match = _covered_match("Surface stabilisers", 731096, 430)
    assert marker_for(match, show_covered=True) == MARKER_ENOUGH


def test_covered_row_stays_blank_when_not_sold_here():
    """The tick means 'sold here, you're covered' -- not merely 'covered'."""
    match = _covered_match("Grain", 0, 0)
    assert match.is_covered
    assert match.is_sold_here is False
    assert marker_for(match, show_covered=True) == ""


def test_covered_row_out_of_stock_shows_the_hollow_glyph():
    match = _covered_match("Structural regulators", 0, 1207)
    assert match.is_sold_here is True
    assert marker_for(match, show_covered=True) == MARKER_EMPTY


def test_covered_tick_is_outside_the_circle_family():
    """It answers a different question, so it must not read as a fill level."""
    scale = {MARKER_EMPTY, MARKER_QUARTER, MARKER_HALF, MARKER_THREE_QUARTER, MARKER_ENOUGH}
    assert MARKER_COVERED not in scale
    assert ord(MARKER_COVERED) == 0x2713


def test_outstanding_rows_are_unaffected_by_show_covered():
    match = _match("Biowaste", 42, 49267, 51, 6)
    assert marker_for(match, show_covered=True) == MARKER_ENOUGH
    assert marker_for(match, show_covered=False) == MARKER_ENOUGH


def test_show_covered_flows_through_the_plan(catalog):
    from APITool.matcher import compare as _compare
    grid = make_grid([("Surface stabilisers", "0"), ("Biowaste", "42"), ("Grain", "231")])
    snapshot = TotalsTabReader(FakeWorksheet(grid), catalog=catalog).read()
    market = Market(1, "Willis Dock", "Inara", None, "journal", (
        MarketItem(128049169, "SurfaceStabilisers", "Surface Stabilisers",
                   stock=731096, buy_price=430),
        MarketItem(128049671, "Biowaste", "Biowaste", stock=49267, buy_price=51),
    ))
    matches = _compare(snapshot.requirements, market, include_satisfied=True)
    plan = TotalsTabWriter(FakeWorksheet(grid)).build_plan(
        matches, snapshot, "Inara", "Willis Dock", show_covered=True
    )
    column = next(u for u in plan.updates if ":" in u["range"])["values"]
    assert column == [[MARKER_ENOUGH], [MARKER_ENOUGH], [""]]
    # ...distinguished by colour, not by symbol: grey text, no fill.
    fmt = {f["range"]: f["format"] for f in plan.formats}
    from APITool.sheets import COLOUR_TEXT_COVERED, COLOUR_ENOUGH, _rgb
    assert fmt["L5"]["textFormat"]["foregroundColor"] == _rgb(COLOUR_TEXT_COVERED)
    assert fmt["L5"]["backgroundColor"] == _rgb("#ffffff")
    assert fmt["L6"]["backgroundColor"] == _rgb(COLOUR_ENOUGH)
    assert plan.covered_rows == [5]
    assert plan.marked_rows == [6]


def test_build_plan_guards_the_location_cells_too():
    """
    Isolates the guard check on VALUE ranges. A bad marker column would be
    caught by either guard loop, so this uses a location cell instead --
    formats never cover C2/G2, so only the values check can reject it.
    """
    from APITool.matcher import Requirement
    snapshot = RequirementSnapshot(
        requirements=[Requirement(row=5, name="Steel", need=0)],
        last_data_row=5, need_column_index=6, header_row=3,
    )
    bad = SheetLayout(system_cell="B2")      # B is the commodity formula column
    writer = TotalsTabWriter(FakeWorksheet(make_grid(LIVE_ROWS)),
                             layout=bad, guard=SheetLayout().guard())
    with pytest.raises(WriteRefused, match="B2"):
        writer.build_plan([], snapshot, "Sys", "Station")


def test_format_ranges_never_reach_outside_the_value_ranges(catalog, ryman_like):
    """
    The invariant that makes the second guard loop defence-in-depth rather
    than load-bearing: formatting only ever touches cells the value write
    already covers. If that ever stops being true, the guard is there -- but
    this test is what would notice the change.
    """
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    plan = TotalsTabWriter(FakeWorksheet(make_grid(LIVE_ROWS))).build_plan(
        matches, snapshot, "Lhou Mans", "Ryman Enterprise"
    )
    covered = [CellRange.parse(r) for r in plan.ranges()]
    for a1 in plan.format_ranges():
        target = CellRange.parse(a1)
        assert any(c.contains(target) for c in covered), a1


def test_every_format_range_is_allowlisted(catalog, ryman_like):
    snapshot, matches = _snapshot_and_matches(catalog, ryman_like)
    plan = TotalsTabWriter(FakeWorksheet(make_grid(LIVE_ROWS))).build_plan(
        matches, snapshot, "Lhou Mans", "Ryman Enterprise"
    )
    guard = SheetLayout().guard()
    assert plan.format_ranges()
    for a1 in plan.format_ranges():
        assert guard.allows("Totals Tab", a1), a1
