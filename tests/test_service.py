"""
Tests for the refresh service: game state -> comparison -> sheet plan
(build steps B-6/B-8, acceptance checks AC-5 and AC-6).

These exercise the orchestration rules that no single module owns:
  * refuse to compare against a market that belongs to another station;
  * still update the location cells and CLEAR stale markers when undocked,
    because a sheet that keeps showing the last station's answer is worse
    than one showing nothing;
  * never touch anything outside the write allowlist.
"""

import json
from pathlib import Path

import pytest

from APITool.catalog import load_catalog
from APITool.matcher import MatchState
from APITool.service import (
    REASON_NOT_DOCKED,
    REASON_NO_COMMODITY_MARKET,
    REASON_NO_JOURNAL,
    REASON_NO_MARKET_DATA,
    REASON_OK,
    REASON_STALE_MARKET,
    MarketRefreshService,
    format_table,
)
from APITool.sheets import MARKER_EMPTY, MARKER_ENOUGH, SheetLayout, WriteRefused

FIXTURES = Path(__file__).parent / "fixtures"
RYMAN = 3226578176
CARRIER = 3705919488


class FakeWorksheet:
    def __init__(self, grid):
        self.grid = grid
        self.batches = []
        self.format_batches = []

    def get_values(self, range_name, **kwargs):
        return [list(r) for r in self.grid]

    def batch_update(self, data, **kwargs):
        self.batches.append(data)
        return {"replies": []}

    def batch_format(self, formats):
        self.format_batches.append(formats)
        return {"replies": []}


def totals_grid(rows, width=30, header_row=3, first_data_row=5, need_col=6):
    grid = [[""] * width for _ in range(first_data_row + len(rows) + 3)]
    grid[1][1] = "Current Star System:"
    grid[1][5] = "Cur Station:"
    header = grid[header_row - 1]
    header[1] = "ALL SETTLEMENTS"
    header[need_col] = "Left to buy"
    grid[header_row][1] = "TOTAL"
    for i, (name, need) in enumerate(rows):
        grid[first_data_row - 1 + i][1] = name
        grid[first_data_row - 1 + i][need_col] = need
    return grid


ROWS = [
    ("Aluminium", "0"),
    ("Biowaste", "229"),
    ("Emergency power cells", "251"),
    ("Land enrichment systems", "210"),
    ("Power Generators", "9"),
]


def ev(name, **kw):
    d = {"timestamp": "2026-09-08T02:14:10Z", "event": name}
    d.update(kw)
    return d


def make_journal(tmp_path, events, market_json=None):
    (tmp_path / "Journal.2026-09-08T021410.01.log").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )
    if market_json is not None:
        (tmp_path / "Market.json").write_text(json.dumps(market_json), encoding="utf-8")
    return tmp_path


def ryman_market_json(market_id=RYMAN):
    """The captured Ryman fixture, optionally relabelled to another station."""
    data = json.loads((FIXTURES / "market_ryman_journal.json").read_text(encoding="utf-8"))
    data["MarketID"] = market_id
    return data


def docked_event(station="Ryman Enterprise", system="Lhou Mans", market_id=RYMAN,
                 services=("dock", "commodities")):
    return ev("Docked", StationName=station, StarSystem=system, MarketID=market_id,
              StationType="Coriolis", StationServices=list(services))


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture
def service_factory(catalog):
    def build(journal_dir, capi_client=None, layout=None):
        return MarketRefreshService(
            journal_dir=journal_dir,
            catalog=catalog,
            layout=layout or SheetLayout(),
            capi_client=capi_client,
        )
    return build


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------

def test_docked_with_matching_market_produces_the_comparison(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    sheet = FakeWorksheet(totals_grid(ROWS))
    result = service_factory(directory).refresh(worksheet=sheet, show_covered=False)

    assert result.ok
    assert result.system == "Lhou Mans"
    assert result.station == "Ryman Enterprise"
    states = {m.name: m.state for m in result.matches}
    assert states["Biowaste"] is MatchState.ENOUGH
    assert states["Power Generators"] is MatchState.ENOUGH
    assert states["Land enrichment systems"] is MatchState.EMPTY
    assert states["Emergency power cells"] is MatchState.NONE
    assert "Aluminium" not in states           # need 0, excluded when not shown


def test_ac6_plan_writes_the_expected_ranges(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    sheet = FakeWorksheet(totals_grid(ROWS))
    result = service_factory(directory).refresh(worksheet=sheet, write_header=True)

    values = {u["range"]: u["values"] for u in result.plan.updates}
    assert values["C2"] == [["Lhou Mans"]]
    assert values["G2"] == [["Ryman Enterprise"]]
    assert values["L3"] == [["At Current Station"]]
    assert values["L5:L9"] == [
        [""],                # Aluminium (need 0)
        [MARKER_ENOUGH],     # Biowaste
        [""],                # Emergency power cells
        [MARKER_EMPTY],      # Land enrichment systems
        [MARKER_ENOUGH],     # Power Generators
    ]
    assert result.plan.marked_rows == [6, 8, 9]


def test_ac6_nothing_is_written_without_the_write_flag(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    sheet = FakeWorksheet(totals_grid(ROWS))
    result = service_factory(directory).refresh(worksheet=sheet, write=False)
    assert result.plan is not None
    assert result.written is False
    assert sheet.batches == []


def test_ac6_write_sends_exactly_one_batch(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    sheet = FakeWorksheet(totals_grid(ROWS))
    result = service_factory(directory).refresh(worksheet=sheet, write=True)
    assert result.written is True
    assert len(sheet.batches) == 1                 # one values batch
    assert {u["range"] for u in sheet.batches[0]} == {"C2", "G2", "L5:L9"}
    assert len(sheet.format_batches) == 1          # one formatting batch
    # every cell in the block is formatted, so last run's colour is cleared
    assert {f["range"] for f in sheet.format_batches[0]} == {
        "L5", "L6", "L7", "L8", "L9"
    }


def test_ac6_only_allowlisted_ranges_are_ever_sent(tmp_path, service_factory):
    """Nothing outside C2, G2 and the marker column may reach the API."""
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    sheet = FakeWorksheet(totals_grid(ROWS))
    service_factory(directory).refresh(worksheet=sheet, write=True)
    guard = SheetLayout().guard()
    for update in sheet.batches[0]:
        assert guard.allows("Totals Tab", update["range"]), update["range"]
    for entry in sheet.format_batches[0]:
        assert guard.allows("Totals Tab", entry["range"]), entry["range"]


def test_notes_are_attached_for_marked_rows(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    sheet = FakeWorksheet(totals_grid(ROWS))
    result = service_factory(directory).refresh(worksheet=sheet, show_covered=False)
    assert set(result.plan.notes) == {"L6", "L8", "L9"}
    assert "Stock: 70,192" in result.plan.notes["L6"]
    assert "Market checked:" in result.plan.notes["L6"]


# ---------------------------------------------------------------------------
# AC-5: refusing a market that belongs somewhere else
# ---------------------------------------------------------------------------

def test_ac5_stale_market_is_refused(tmp_path, service_factory):
    """
    The real observed case: docked at fleet carrier Q9G-6HX in Inara while
    Market.json still held Ryman Enterprise.
    """
    directory = make_journal(
        tmp_path,
        [docked_event(), ev("Undocked", StationName="Ryman Enterprise", MarketID=RYMAN),
         ev("FSDJump", StarSystem="Inara"),
         docked_event(station="Q9G-6HX", system="Inara", market_id=CARRIER)],
        ryman_market_json(),      # still Ryman
    )
    sheet = FakeWorksheet(totals_grid(ROWS))
    result = service_factory(directory).refresh(worksheet=sheet)

    assert not result.ok
    assert result.reason == REASON_STALE_MARKET
    assert result.matches == []
    assert result.station == "Q9G-6HX"
    assert result.system == "Inara"
    assert "Commodity Market screen" in result.advice()


def test_ac5_stale_market_still_clears_markers_and_sets_location(tmp_path, service_factory):
    """
    Refusing to compare must NOT mean leaving the previous station's markers
    on screen -- that is the failure being prevented.
    """
    directory = make_journal(
        tmp_path,
        [docked_event(station="Q9G-6HX", system="Inara", market_id=CARRIER)],
        ryman_market_json(),
    )
    sheet = FakeWorksheet(totals_grid(ROWS))
    result = service_factory(directory).refresh(worksheet=sheet, write=True)

    values = {u["range"]: u["values"] for u in sheet.batches[0]}
    assert values["C2"] == [["Inara"]]
    assert values["G2"] == [["Q9G-6HX"]]
    assert all(cell == [""] for cell in values["L5:L9"])
    assert result.plan.marked_rows == []


def test_not_docked_reports_and_clears(tmp_path, service_factory):
    directory = make_journal(
        tmp_path,
        [docked_event(), ev("Undocked", StationName="Ryman Enterprise", MarketID=RYMAN)],
        ryman_market_json(),
    )
    sheet = FakeWorksheet(totals_grid(ROWS))
    result = service_factory(directory).refresh(worksheet=sheet, write=True)

    assert result.reason == REASON_NOT_DOCKED
    assert result.station == "Not docked"
    values = {u["range"]: u["values"] for u in sheet.batches[0]}
    assert values["G2"] == [["Not docked"]]
    assert all(cell == [""] for cell in values["L5:L9"])


def test_missing_market_json_is_reported(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], market_json=None)
    result = service_factory(directory).refresh()
    assert result.reason == REASON_NO_MARKET_DATA
    assert "Commodity Market" in result.advice()


def test_station_without_a_commodity_market(tmp_path, service_factory):
    directory = make_journal(
        tmp_path,
        [docked_event(services=("dock", "refuel", "repair"))],
        ryman_market_json(),
    )
    result = service_factory(directory).refresh()
    assert result.reason == REASON_NO_COMMODITY_MARKET


def test_missing_journal_directory(tmp_path, service_factory):
    result = service_factory(tmp_path / "does-not-exist").refresh()
    assert result.reason == REASON_NO_JOURNAL
    assert "ED_JOURNAL_DIR" in result.advice()


# ---------------------------------------------------------------------------
# CAPI supplementation
# ---------------------------------------------------------------------------

class FakeCAPI:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def get_market(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


def capi_payload(market_id=RYMAN):
    data = json.loads((FIXTURES / "market_ryman_capi.json").read_text(encoding="utf-8"))
    data["id"] = market_id
    return data


def test_capi_supplements_the_journal(tmp_path, service_factory):
    """The union recovers Limpet, which Market.json omits entirely."""
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    service = service_factory(directory, capi_client=FakeCAPI(capi_payload()))
    result = service.refresh()

    assert result.ok
    assert result.market.source == "merged"
    assert result.market.find(name="Limpet") is not None
    assert len(result.market) == 373


def test_capi_failure_does_not_block_the_journal_answer(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    service = service_factory(directory, capi_client=FakeCAPI(error=RuntimeError("boom")))
    result = service.refresh()
    assert result.ok
    assert result.market.source == "journal"


def test_capi_for_a_different_station_is_ignored(tmp_path, service_factory):
    """A CAPI response for the wrong market must not slip past the gate."""
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    service = service_factory(directory, capi_client=FakeCAPI(capi_payload(market_id=999)))
    result = service.refresh()
    assert result.ok
    assert result.market.source == "journal"


def test_capi_alone_works_when_market_json_is_stale(tmp_path, service_factory):
    """CAPI is live, so it can answer where the on-disk snapshot cannot."""
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json(market_id=999))
    service = service_factory(directory, capi_client=FakeCAPI(capi_payload()))
    result = service.refresh()
    assert result.ok
    assert result.market.source == "capi"


def test_capi_is_not_called_when_absent(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    result = service_factory(directory, capi_client=None).refresh()
    assert result.ok
    assert result.market.source == "journal"


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_a_layout_pointing_at_formulas_is_refused(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    sheet = FakeWorksheet(totals_grid(ROWS))
    service = service_factory(directory, layout=SheetLayout(marker_column="B"))
    # The guard comes from the same (bad) layout, so this one is permitted --
    # what must NOT happen is a write to B under the DEFAULT guard.
    from APITool.sheets import TotalsTabWriter
    snapshot_service = service_factory(directory)
    result = snapshot_service.refresh(worksheet=sheet)
    writer = TotalsTabWriter(sheet, layout=SheetLayout(marker_column="B"),
                             guard=SheetLayout().guard())
    with pytest.raises(WriteRefused):
        writer.build_plan(result.matches, result.snapshot, "S", "St")


def test_refresh_without_a_worksheet_reports_state_only(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    result = service_factory(directory).refresh(worksheet=None)
    assert result.ok
    assert result.market is not None
    assert result.plan is None
    assert result.snapshot is None


def test_market_names_are_learned_into_the_catalog(tmp_path, service_factory, catalog):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    service_factory(directory).refresh()
    # Whatever the game called things is now a valid lookup key.
    assert catalog.by_name("Low Temp. Diamonds") is not None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_format_table_lists_rows_in_sheet_order(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    sheet = FakeWorksheet(totals_grid(ROWS))
    result = service_factory(directory).refresh(worksheet=sheet)
    text = format_table(result.matches)
    assert "Biowaste" in text
    assert "ENOUGH" in text
    assert "70,192" in text
    rows = [ln for ln in text.splitlines()[2:] if ln.strip()]
    numbers = [int(ln.split()[0]) for ln in rows]
    assert numbers == sorted(numbers)


def test_format_table_handles_nothing_outstanding():
    assert "nothing outstanding" in format_table([])


def test_describe_is_one_line(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    result = service_factory(directory).refresh()
    line = result.describe()
    assert "\n" not in line
    assert "Ryman Enterprise" in line


def test_describe_when_refused_carries_the_advice(tmp_path, service_factory):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json(market_id=999))
    result = service_factory(directory).refresh()
    assert "Commodity Market screen" in result.describe()
