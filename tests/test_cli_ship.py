"""
CLI tests for `edapitool ship` (issue #6, DWP build step 2).

The theme of this file is issue #10: `edapitool market` demands a spreadsheet
id before it will emit JSON, which makes an output format depend on a feature
the user never asked for. The `ship` verb must not inherit that, so most of
what follows asserts that things work with **no sheet id and no credentials
anywhere** -- the config file, the environment variable, and the flag are all
absent in these tests.
"""

import json
import shutil
from pathlib import Path

import pytest

from APITool.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def journal(tmp_path):
    """A journal directory holding the real Cargo.json fixture."""
    d = tmp_path / "journal"
    d.mkdir()
    shutil.copy(FIXTURES / "cargo_ship.json", d / "Cargo.json")
    # A journal file must exist for JournalReader.exists() to be satisfied.
    (d / "Journal.2026-09-08T060000.01.log").write_text("", encoding="utf-8")
    return d


@pytest.fixture(autouse=True)
def no_credentials_anywhere(tmp_path, monkeypatch):
    """
    Remove every route to a sheet id, so a test that passes here would pass on
    a machine that has never seen this tool.
    """
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "nohome"))


def run(argv, journal):
    return main(["ship", "--journal-dir", str(journal)] + argv)


# ---------------------------------------------------------------------------
# Issue #10's defect must not appear here
# ---------------------------------------------------------------------------

def test_plain_run_needs_no_spreadsheet(journal, capsys):
    assert run([], journal) == 0
    out = capsys.readouterr().out
    assert "227" in out
    assert "Biowaste" in out
    assert "spreadsheet" not in out.lower()


def test_json_needs_no_spreadsheet(journal, capsys):
    """
    The regression guard for issue #10. `market --json` errors out demanding a
    sheet id; `ship --json` must simply print JSON.
    """
    assert run(["--json"], journal) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["vessel"] == "Ship"
    assert payload["is_ship"] is True
    assert payload["itemised_total"] == 227
    assert len(payload["commodities"]) == 4


def test_csv_export_needs_no_spreadsheet(journal, tmp_path, capsys):
    out_dir = tmp_path / "out"
    assert run(["--export", "csv", "--output", str(out_dir)], journal) == 0
    written = list(out_dir.glob("shipcargo_*.csv"))
    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    assert "commodity,commodity_id,symbol,count,stolen" in text.replace("\r", "")
    assert "Biowaste" in text


def test_json_export_needs_no_spreadsheet(journal, tmp_path):
    out_dir = tmp_path / "out"
    assert run(["--export", "json", "--output", str(out_dir)], journal) == 0
    written = list(out_dir.glob("shipcargo_*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["itemised_total"] == 227


def test_stdout_json_and_file_json_have_the_same_shape(journal, tmp_path, capsys):
    """
    One payload builder, so a consumer written against stdout keeps working
    when pointed at a saved file.
    """
    out_dir = tmp_path / "out"
    run(["--json", "--export", "json", "--output", str(out_dir)], journal)
    from_stdout = json.loads(capsys.readouterr().out.split("\n\n")[0])
    from_file = json.loads(list(out_dir.glob("*.json"))[0].read_text(encoding="utf-8"))
    assert from_stdout == from_file


# ---------------------------------------------------------------------------
# Where a spreadsheet IS legitimately required
# ---------------------------------------------------------------------------

def test_ship_tab_export_requires_a_sheet_id(journal, capsys):
    """The one path that genuinely needs a spreadsheet says so and exits 1."""
    assert run(["--export", "ship-tab"], journal) == 1
    out = capsys.readouterr().out
    assert "needs a spreadsheet id" in out
    assert "--sheet-id" in out


def test_ship_tab_dry_run_writes_nothing_and_needs_no_network(journal, capsys):
    argv = ["--export", "ship-tab", "--sheet-id", "fake", "--dry-run"]
    assert run(argv, journal) == 0
    out = capsys.readouterr().out
    assert "Would write" in out
    assert "ShipCargo" in out


def test_ship_tab_write_passes_its_arguments_in_the_right_order(journal, monkeypatch):
    """
    Regression: the real write path was originally called as
    ``export_grid(sheet_id, tab_name, grid)`` against a signature of
    ``export_grid(rows, sheet_id, tab_name)``. The grid landed in ``tab_name``
    and the allow-list membership test raised "unhashable type: 'list'".

    Nothing caught it, because the only ship-tab test used --dry-run, which
    returns before this line. So this test drives the real branch against a
    fake exporter and asserts each argument arrived where it belongs.
    """
    seen = {}

    class FakeExporter:
        def export_grid(self, rows, sheet_id, tab_name):
            seen["rows"] = rows
            seen["sheet_id"] = sheet_id
            seen["tab_name"] = tab_name
            return len(rows) - 3

    import APITool.google as gsheet_mod
    monkeypatch.setattr(
        gsheet_mod, "GoogleSheetsExporter", lambda *a, **k: FakeExporter()
    )

    assert run(["--export", "ship-tab", "--sheet-id", "SHEET123"], journal) == 0
    assert seen["sheet_id"] == "SHEET123"
    assert seen["tab_name"] == "ShipCargo"
    assert isinstance(seen["rows"], list)
    assert seen["rows"][2] == [
        "", "Commodity", "Quantity", "Unit Price", "Symbol", "Stolen",
    ]


def test_ship_tab_honours_a_custom_tab_name(journal, monkeypatch):
    seen = {}

    class FakeExporter:
        def export_grid(self, rows, sheet_id, tab_name):
            seen["tab_name"] = tab_name
            return 0

    import APITool.google as gsheet_mod
    monkeypatch.setattr(
        gsheet_mod, "GoogleSheetsExporter", lambda *a, **k: FakeExporter()
    )

    run(["--export", "ship-tab", "--sheet-id", "X", "--ship-tab", "MyHold"], journal)
    assert seen["tab_name"] == "MyHold"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_srv_cargo_is_refused_rather_than_reported_as_the_ship(tmp_path, capsys):
    d = tmp_path / "srv"
    d.mkdir()
    (d / "Cargo.json").write_text(json.dumps({
        "timestamp": "2026-09-08T06:46:29Z", "Vessel": "SRV", "Count": 4,
        "Inventory": [{"Name": "biowaste", "Count": 4}],
    }), encoding="utf-8")
    (d / "Journal.2026-09-08T060000.01.log").write_text("", encoding="utf-8")

    assert run([], d) == 1
    out = capsys.readouterr().out
    assert "SRV" in out
    assert "not your ship" in out


def test_missing_cargo_file_explains_itself(tmp_path, capsys):
    d = tmp_path / "empty"
    d.mkdir()
    (d / "Journal.2026-09-08T060000.01.log").write_text("", encoding="utf-8")
    assert run([], d) == 1
    assert "No Cargo.json" in capsys.readouterr().out


def test_missing_journal_directory_explains_itself(tmp_path, capsys):
    assert run([], tmp_path / "does-not-exist") == 1
    assert "journal directory" in capsys.readouterr().out


def test_unknown_export_format_is_rejected(journal, capsys):
    assert run(["--export", "nonsense"], journal) == 1
    out = capsys.readouterr().out
    assert "unknown export format" in out
    assert "csv, json, ship-tab" in out
