"""
The settlement plugin: a tab from a template, seeded from the matrix (U43).

Smokes against fakes (scenarios S1-S6 of the unit's test-scenarios pass).
Nothing here opens a spreadsheet: the plugin's `_open` and `_exporter`
seams are replaced, and the fake workbook holds its state in memory.
"""

import json

import pytest

from APITool import loader
from APITool.export import construction_region_rows
from APITool.plugins import settlement
from APITool.plugins.settlement import base, tabs

# ---------------------------------------------------------------------------
# A slice of the matrix as the workbook has it: leading spaces on the types,
# a zero-width space after every count, blanks where a type needs nothing.
# Public data (the forum's construction requirements matrix).
# ---------------------------------------------------------------------------

Z = "​"
BASE = [
    [],
    ["", "https://forums.frontier.co.uk/threads/construction-requirements-matrix.634358/"],
    ["PLANETARY ", " agricultural small", " agricultural medium", " agricultural large",
     " extraction small", " extraction medium", " extraction large",
     " industrial small", " industrial medium", " industrial large",
     " military small", " military medium", " military large",
     " research bio small", " research bio medium", " research bio large",
     " tourism small", " tourism medium", " tourism large"],
    ["Advanced catalysers", "", "", "", "", "", "", f"41{Z}", f"82{Z}", f"123{Z}", "", "", "",
     f"95{Z}", f"190{Z}", f"285{Z}"],
    ["Agri-medicines"],
    ["Aluminium", f"559{Z}", f"1,118{Z}", f"1677{Z}", f"632{Z}", f"1264{Z}", f"1896{Z}",
     f"585{Z}", f"1170{Z}", f"1755{Z}", f"593{Z}", f"1186{Z}", f"1779{Z}",
     f"607{Z}", f"1214{Z}", f"1821{Z}", f"509{Z}", f"1018{Z}", f"1527{Z}"],
    ["Beer", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", f"311{Z}", f"622{Z}", f"933{Z}"],
    ["Biowaste", f"280{Z}", f"560{Z}", f"840{Z}"],
    ["Crop harvesters", f"210{Z}", f"420{Z}", f"630{Z}"],
    ["Insulating membrane"],
    ["Liquid oxygen", f"224{Z}", f"448{Z}", f"672{Z}", f"177{Z}", f"354{Z}", f"531{Z}",
     f"272{Z}", f"544{Z}", f"816{Z}"],
]


def test_the_matrix_parses_the_header_row_and_every_type():
    matrix = base.parse_matrix(BASE)
    assert len(matrix.types) == 18
    assert matrix.types[2] == "agricultural large" and matrix.types[-1] == "tourism large"


@pytest.mark.parametrize("spelling", ["agricultural large", " agricultural large",
                                      "Settlement agricultural large", "AGRICULTURAL  LARGE"])
def test_a_type_resolves_from_any_of_the_workbooks_spellings(spelling):
    needs = dict(base.parse_matrix(BASE).requirements(spelling))
    assert needs["Aluminium"] == 1677 and needs["Biowaste"] == 840
    assert "Beer" not in needs and "Agri-medicines" not in needs, "blank cells are not requirements"


def test_a_comma_in_a_count_is_read_as_a_count():
    needs = dict(base.parse_matrix(BASE).requirements("agricultural medium"))
    assert needs["Aluminium"] == 1118


def test_an_unknown_type_is_refused_naming_the_types_the_matrix_offers():
    with pytest.raises(ValueError, match="unknown settlement type 'nope'") as caught:
        base.parse_matrix(BASE).requirements("nope")
    assert "tourism large" in str(caught.value) and "agricultural small" in str(caught.value)


def test_a_grid_with_no_header_row_is_refused():
    with pytest.raises(ValueError, match="PLANETARY"):
        base.parse_matrix([["Aluminium", "1"]])


# ---------------------------------------------------------------------------
# The seed (S1)
# ---------------------------------------------------------------------------


def test_the_seed_is_the_live_blocks_shape_with_the_state_planned():
    needs = base.parse_matrix(BASE).requirements("agricultural large")
    grid = tabs.seed_grid("agricultural large", needs, site="Agri 2", system="Lhou Mans")

    from types import SimpleNamespace

    from APITool.construction import ConstructionResource, ConstructionSite, normalize
    site = ConstructionSite(market_id=None, resources=tuple(
        ConstructionResource(symbol=normalize(n), name=n, required=q) for n, q in needs))
    expected = construction_region_rows(site, SimpleNamespace(short_station="Agri 2", system="Lhou Mans"))
    expected[1][4] = "planned"
    expected[1][2] = ""
    assert grid == expected
    assert grid[1][0] == "Agri 2" and grid[1][1] == "Lhou Mans"
    assert grid[4][:6] == ["aluminium", "Aluminium", 1677, 0, 1677, 0]


# ---------------------------------------------------------------------------
# The fakes: a workbook in memory, a writer that records
# ---------------------------------------------------------------------------


class FakeWorksheet:
    _ids = iter(range(1000, 9999))

    def __init__(self, title, grid=None, hidden=False):
        self.id = next(self._ids)
        self.title = title
        self.grid = [list(r) for r in (grid or [])]
        self.isSheetHidden = hidden
        self.cleared = []

    def get_values(self, *a, **k):
        return [list(r) for r in self.grid]

    def batch_clear(self, ranges):
        self.cleared.append(list(ranges))

    def hide(self):
        self.isSheetHidden = True


class FakeSpreadsheet:
    def __init__(self, *sheets):
        self._sheets = list(sheets)
        self.updates = []

    def worksheets(self):
        return list(self._sheets)

    def worksheet(self, title):
        for ws in self._sheets:
            if ws.title == title:
                return ws
        raise KeyError(title)

    def duplicate_sheet(self, source_sheet_id, insert_sheet_index=None, new_sheet_id=None, new_sheet_name=None):
        source = next(ws for ws in self._sheets if ws.id == source_sheet_id)
        copy = FakeWorksheet(new_sheet_name, source.grid, hidden=source.isSheetHidden)
        self._sheets.append(copy)
        return copy

    def batch_update(self, body):
        self.updates.append(body)
        for request in body.get("requests", []):
            props = request.get("updateSheetProperties", {}).get("properties", {})
            for ws in self._sheets:
                if ws.id == props.get("sheetId") and "hidden" in props:
                    ws.isSheetHidden = props["hidden"]
        return {"replies": []}

    def del_worksheet(self, worksheet):
        self._sheets.remove(worksheet)


class FakeExporter:
    def __init__(self, region_guard=None):
        self.region_guard = region_guard
        self.writes = []

    def export_grid(self, rows, sheet_id=None, tab_name=None):
        self.writes.append((tab_name, rows))
        return len(rows)


def _workbook():
    return FakeSpreadsheet(
        FakeWorksheet("Base", BASE),
        FakeWorksheet("Totals Tab", [["x"]]),
        FakeWorksheet("Agri Lrg. (ex)", [["", "Total Round Trips:"], [], ["", "PLANETARY SETTLEMENT", "Settlement agricultural large"]]),
    )


@pytest.fixture
def planted(monkeypatch, tmp_path):
    """A target naming the plugin, a fake workbook behind the seams, the exporters recorded."""
    from APITool import settings

    directory = tmp_path / "cfg"
    directory.mkdir()
    (directory / "config.json").write_text(json.dumps({"targets": {"settlements": {
        "kind": "gsheet", "plugin": "settlement", "id": "FAKE_SHEET_ID_NEVER_CONTACTED", "config": {},
    }}}), encoding="utf-8")
    monkeypatch.setenv("ED_CONFIG_DIR", str(directory))
    monkeypatch.setattr(settings, "CONFIG_FILE", directory / "config.json")

    workbook = _workbook()
    exporters = []

    def fake_exporter(guard):
        exporter = FakeExporter(guard)
        exporters.append(exporter)
        return exporter

    monkeypatch.setattr(settlement, "_open", lambda sheet_id: workbook)
    monkeypatch.setattr(settlement, "_exporter", fake_exporter)
    return workbook, exporters


def _new(*argv):
    from APITool import cli

    return cli.main(["plugins", "settlement", "new", *argv])


# ---------------------------------------------------------------------------
# The plugin as the loader sees it
# ---------------------------------------------------------------------------


def test_the_plugin_loads_offers_new_and_stays_out_of_the_pipeline(planted, capsys):
    result = loader.discover()
    entry = next(e for e in result.loaded if e.name == "settlement")
    assert entry.kind == "gsheet" and entry.complaints == ()
    assert entry not in result.steps("market"), "a command-only plugin is not a step"

    from APITool import cli

    assert cli.main(["plugins", "describe", "settlement"]) == 0
    out = capsys.readouterr().out
    assert "process    (none)" in out and '"template_tab"' in out
    assert cli.main(["plugins", "settlement"]) == 0
    assert "new" in capsys.readouterr().out


def test_check_config_names_a_bad_range():
    assert settlement.check_config({"region": "not a range"}) and settlement.check_config({}) == []
    assert settlement.check_config({"base_tab": ""}) == ['"base_tab" must be a non-empty string']


# ---------------------------------------------------------------------------
# The command (S2, S3, S5, S6)
# ---------------------------------------------------------------------------


def test_a_dry_run_describes_the_tab_and_creates_nothing(planted, capsys):
    workbook, exporters = planted
    before = [ws.title for ws in workbook.worksheets()]
    assert _new("--type", "agricultural large", "--name", "Agri 2", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "4 commodities" in out and "'Agri 2'" in out and "Dry run: nothing created." in out
    assert [ws.title for ws in workbook.worksheets()] == before
    assert exporters == []


def test_a_real_run_makes_the_template_once_and_a_shown_tab_written_through_its_own_guard(planted, capsys):
    workbook, exporters = planted
    assert _new("--type", "agricultural large", "--name", "Agri 2", "--site", "New Site") == 0
    out = capsys.readouterr().out

    template = workbook.worksheet("_settlement template")
    assert template.isSheetHidden and template.cleared == [["R1:AC60", "C3"]]
    created = workbook.worksheet("Agri 2")
    assert not created.isSheetHidden, "the copy of a hidden template is shown"
    assert workbook.updates[-1]["requests"][0]["updateSheetProperties"]["properties"]["sheetId"] == created.id

    (exporter,) = exporters
    guard = exporter.region_guard
    assert guard.allows("Agri 2", "R1:AC60") and guard.allows("Agri 2", "C3")
    assert not guard.allows("Agri 2", "A5"), "the bound is the block and the title, not the tab"
    assert not guard.allows("Agri Lrg. (ex)", "R1:AC60"), "the source tab is outside the bound (S3)"
    (block_dest, block), (title_dest, title) = exporter.writes
    assert block_dest.tab == "Agri 2" and block[1][0] == "New Site" and block[1][4] == "planned"
    assert title_dest.tab == "Agri 2" and title == [["Settlement agricultural large"]]
    assert '"region": "Agri 2!R1:AC60"' in out and "Totals Tab" in out

    assert _new("--type", "industrial large", "--name", "Ind 2") == 0
    assert sum(1 for ws in workbook.worksheets() if ws.title == "_settlement template") == 1


def test_an_existing_name_is_refused_before_anything_is_made(planted, capsys):
    workbook, exporters = planted
    assert _new("--type", "agricultural large", "--name", "Totals Tab") == 1
    assert "already exists" in capsys.readouterr().out
    assert tabs.find_tab(workbook, "_settlement template") is None and exporters == []


def test_an_unknown_type_is_refused_naming_the_types(planted, capsys):
    assert _new("--type", "nope", "--name", "X") == 1
    out = capsys.readouterr().out
    assert "unknown settlement type 'nope'" in out and "tourism large" in out
