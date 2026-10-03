"""
`--publish-to TAB --region A1:B2` on every data command (#34, native regions
sub-unit 3): `profile`, `carrier`, `market` and `ship` place the grid their
tab holds into one rectangle of a tab you keep, once, through a guard for
exactly that rectangle -- the way `construction` always has.

Smokes. Only the edges that leave the machine are replaced -- Frontier auth,
the Frontier client, the Sheets writer -- and the fake writer records the
destination and the guard it was built with. Nothing here reaches Google or
Frontier: the writer is a fake, and in the refusal tests the client raises if
it is ever constructed, so a refusal that failed to fire fails the test
instead of fetching (Critical Safety Rule 1b).
"""

import shutil
from pathlib import Path

import pytest

from APITool import settings
from APITool.cli import main

FIXTURES = Path(__file__).parent / "fixtures"

PROFILE = {"commander": {"name": "CMDR Test", "credits": 1234567},
           "ship": {"name": "Type-9 Heavy"}}
CARRIER = {
    "name": {"callsign": "Q9G-6HX", "vanityName": "", "filteredVanityName": ""},
    "currentStarSystem": "Col 285 Sector ZG-T c4-10",
    "state": "normalOperation", "dockingAccess": "all", "notoriousAccess": False,
    "finance": {},
    "cargo": [{"commodity": "Aluminium", "locName": "Aluminium", "qty": 1751,
               "value": 3715622, "stolen": False, "mission": False}],
}


class FakeExporter:
    built: list = []

    def __init__(self, region_guard=None):
        self.region_guard = region_guard
        self.writes = []
        FakeExporter.built.append(self)

    def export_grid(self, rows, sheet_id=None, tab_name=None):
        self.writes.append((sheet_id, tab_name, rows))
        return len(rows)


class Fetched(BaseException):
    """Raised by a client that must never be built in a refusal test."""


@pytest.fixture
def edges(monkeypatch, tmp_path):
    import APITool.cli as cli_mod
    import APITool.google as google_mod

    directory = tmp_path / "cfg"
    directory.mkdir()
    monkeypatch.setenv("ED_CONFIG_DIR", str(directory))
    monkeypatch.setattr(settings, "CONFIG_FILE", directory / "config.json")
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    monkeypatch.setenv("ED_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(cli_mod, "setup_auth", lambda *a, **k: object())

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def get_profile(self):
            return PROFILE

        def get_fleet_carrier(self):
            return CARRIER

    monkeypatch.setattr(cli_mod, "CAPIClient", FakeClient)
    monkeypatch.setattr(google_mod, "GoogleSheetsExporter", FakeExporter)
    FakeExporter.built = []
    return cli_mod


@pytest.fixture
def journal(tmp_path):
    d = tmp_path / "journal"
    d.mkdir()
    shutil.copy(FIXTURES / "cargo_ship.json", d / "Cargo.json")
    (d / "Journal.2026-09-08T060000.01.log").write_text("", encoding="utf-8")
    return d


def _one_region_write(tab, a1):
    """The one exporter built, its one write, and a guard bound to exactly tab!a1."""
    assert len(FakeExporter.built) == 1
    exporter = FakeExporter.built[0]
    assert len(exporter.writes) == 1
    sheet_id, destination, rows = exporter.writes[0]
    assert sheet_id == "FAKE_SHEET_ID_NEVER_CONTACTED"
    assert destination.tab == tab
    guard = exporter.region_guard
    assert guard.allows(tab, a1)
    assert not guard.allows(tab, "A1000"), "the bound is the region, not the tab"
    return rows


SHEET = ["--sheet-id", "FAKE_SHEET_ID_NEVER_CONTACTED"]


def test_profile_publishes_a_label_value_block(edges, capsys):
    assert main(["profile", "--publish-to", "Hauling", "--region", "A1:B4", *SHEET]) == 0
    rows = _one_region_write("Hauling", "A1:B4")
    assert rows[:3] == [["Commander", "CMDR Test"], ["Credits", 1234567],
                        ["Current ship", "Type-9 Heavy"]]
    assert rows[3][0] == "Checked at" and rows[3][1]
    assert "Published 4 rows (profile) to" in capsys.readouterr().out


def test_carrier_publishes_the_freighterdata_grid(edges, capsys):
    from APITool.google.exporter import carrier_grid, carrier_rows
    from APITool.models import FleetCarrier

    assert main(["carrier", "--publish-to", "Hauling", "--region", "W1:AB300", *SHEET]) == 0
    rows = _one_region_write("Hauling", "W1:AB300")
    expected = carrier_grid(carrier_rows(FleetCarrier.from_capi(CARRIER)),
                            checked_at=rows[0][1] if rows and len(rows[0]) > 1 else "")
    assert len(rows) == len(expected)
    assert any("Aluminium" in str(cell) for row in rows for cell in row)
    assert "rows (FreighterData)" in capsys.readouterr().out


def test_ship_publishes_the_shipcargo_grid(edges, journal, capsys):
    assert main(["ship", "--journal-dir", str(journal),
                 "--publish-to", "Hauling", "--region", "P1:U40", *SHEET]) == 0
    rows = _one_region_write("Hauling", "P1:U40")
    assert rows[2] == ["", "Commodity", "Quantity", "Unit Price", "Symbol", "Stolen"]
    assert "region: Published" in capsys.readouterr().out


def test_ship_dry_run_opens_nothing(edges, journal, capsys):
    assert main(["ship", "--journal-dir", str(journal), "--dry-run",
                 "--publish-to", "Hauling", "--region", "P1:U40", *SHEET]) == 0
    assert FakeExporter.built == []
    assert "Would publish" in capsys.readouterr().out


def test_market_publishes_the_marketdata_grid_even_with_no_market(edges, tmp_path, capsys):
    """No market read: the region gets the "no current market" grid, as MarketData would."""
    empty = tmp_path / "empty-journal"
    empty.mkdir()
    code = main(["market", "--journal-dir", str(empty),
                 "--publish-to", "Hauling", "--region", "H1:N200", *SHEET])
    assert code in (0, 2)  # 2 = no market reading, which is not a write failure
    rows = _one_region_write("Hauling", "H1:N200")
    assert rows, "the empty grid is written, never nothing"
    assert "rows (MarketData) to" in capsys.readouterr().out


@pytest.mark.parametrize("argv, said", [
    (["carrier", "--publish-to", "Hauling"], "needs --region"),
    (["carrier", "--region", "A1:B2"], "pass both"),
    (["profile", "--publish-to", "Hauling", "--region", "not a range"], "Error"),
    (["carrier", "--publish-to", "Hauling", "--region", "A1:B2"], "needs a spreadsheet"),
])
def test_a_bad_region_is_refused_before_frontier_is_asked(edges, monkeypatch, capsys, argv, said):
    def never(*a, **k):
        raise Fetched("the client was built after a refusal should have fired")

    monkeypatch.setattr(edges, "CAPIClient", never)
    sheet = SHEET if "needs a spreadsheet" not in said else []
    assert main([*argv, *sheet]) == 1
    assert said in capsys.readouterr().out
    assert FakeExporter.built == []


def test_market_refuses_publish_to_with_no_sheet(edges, tmp_path, capsys):
    assert main(["market", "--no-sheet", "--journal-dir", str(tmp_path),
                 "--publish-to", "Hauling", "--region", "H1:N200", *SHEET]) == 1
    assert "--no-sheet" in capsys.readouterr().out
    assert FakeExporter.built == []


def test_construction_keeps_its_refusal_wording(edges, tmp_path, capsys):
    """The one-off write moved into a shared helper; construction's refusal reads as before."""
    from APITool import cli as cli_mod

    args = type("A", (), {"publish_to": "Hauling", "region": None, "sheet_id": None})()
    assert cli_mod._region_target(args) is False
    assert "--publish-to needs --region, e.g. --region R1:AD60." in capsys.readouterr().out
