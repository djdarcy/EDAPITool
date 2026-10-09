"""
The first consumer of the store (the store design of 2026-10-09, unit 6):
`construction --delta`, and the two columns the construction block carries
beside the game's numbers -- what was delivered since the tool last
published it, and how much of that was others'.

The sheet is a fake that records what it was handed; the journal and the
store are real, in the test's own directories.
"""

import json

import pytest

from test_store_ingest import FIRST, header, loadgame, write
from test_store_projections import SITE, contribution, depot, docked, ingest

from APITool import settings
from APITool.cli import main
from APITool.export import CONSTRUCTION_REGION_HEADERS, construction_region_rows
from APITool.store import store_path, writes
from APITool.store import ingest as ingest_mod
from APITool.store.history import History

READINGS = (
    docked(1, "Site Alpha", market_id=SITE),
    depot(2, [("steel", 1000, 60, 500), ("titanium", 500, 40, 900)]),
    contribution(3, [("steel", 50)]),
    depot(4, [("steel", 1000, 300, 500), ("titanium", 500, 50, 900)], progress=0.35),
)


def with_history(fn):
    history = History.open()
    try:
        return fn(history)
    finally:
        history.close()


# -- the question the seam answers --------------------------------------------------

def test_the_change_since_the_first_reading_is_per_resource_with_the_commander_s_share(tmp_path):
    ingest(tmp_path, *READINGS)

    change = with_history(lambda h: h.construction_change(SITE))

    assert change["since"] == "2026-10-09T02:00:00Z" and change["until"] == "2026-10-09T04:00:00Z"
    assert change["from_first_reading"] is True
    assert change["resources"] == {
        "steel": {"delivered": 240, "own": 50, "by_others": 190},
        "titanium": {"delivered": 10, "own": 0, "by_others": 10},
    }
    assert (change["delivered"], change["own"], change["by_others"]) == (250, 50, 200)


def test_the_change_since_a_moment_takes_the_latest_reading_at_or_before_it(tmp_path):
    ingest(tmp_path, *READINGS, depot(5, [("steel", 1000, 320, 500), ("titanium", 500, 50, 900)]))

    at_four = with_history(lambda h: h.construction_change(SITE, since="2026-10-09T04:00:00Z"))
    assert at_four["since"] == "2026-10-09T04:00:00Z" and at_four["until"] == "2026-10-09T05:00:00Z"
    assert at_four["resources"]["steel"] == {"delivered": 20, "own": 0, "by_others": 20}
    assert at_four["from_first_reading"] is False

    between = with_history(lambda h: h.construction_change(SITE, since="2026-10-09T03:30:00Z"))
    assert between["since"] == "2026-10-09T02:00:00Z", "no reading at 03:30; the one before it"
    assert between["resources"]["steel"]["own"] == 50

    early = with_history(lambda h: h.construction_change(SITE, since="2026-10-01T00:00:00Z"))
    assert early["from_first_reading"] is True


def test_no_reading_of_the_site_answers_none_and_a_fresh_install_too(tmp_path):
    assert with_history(lambda h: h.construction_change(SITE)) is None
    ingest(tmp_path, docked(1, "Elsewhere", market_id=1))
    assert with_history(lambda h: h.construction_change(SITE)) is None
    assert with_history(lambda h: h.construction_delta(SITE)) is None


# -- the block ---------------------------------------------------------------------------

def test_the_block_carries_the_two_columns_from_the_change_and_blanks_without_one():
    from APITool.construction import ConstructionResource, ConstructionSite

    site = ConstructionSite(market_id=SITE, resources=(
        ConstructionResource(symbol="steel", name="Steel", required=1000, provided=300, payment=500),
        ConstructionResource(symbol="titanium", name="Titanium", required=500, provided=50, payment=900),
    ))
    change = {"resources": {"steel": {"delivered": 240, "own": 50, "by_others": 190}}}

    rows = construction_region_rows(site, None, change)

    assert rows[3][:8] == CONSTRUCTION_REGION_HEADERS
    assert CONSTRUCTION_REGION_HEADERS[6:] == ["Delivered since last publish", "By others"]
    assert rows[4][:8] == ["steel", "Steel", 1000, 300, 700, 500, 240, 190]
    assert rows[5][:8] == ["titanium", "Titanium", 500, 50, 450, 900, "", ""]
    assert all(len(row) == 9 for row in rows), "the block is as wide as its metadata row, as before"

    plain = construction_region_rows(site, None)
    assert plain[3][:8] == CONSTRUCTION_REGION_HEADERS, "the headers stay so a formula never finds the column moved"
    assert plain[4][6:8] == ["", ""]


def test_a_region_narrower_than_the_block_is_refused_by_name():
    from APITool.sheets import WriteGuard, WriteRefused

    guard = WriteGuard.build({"Tab": ["A1:F60"]})
    with pytest.raises(WriteRefused, match="Tab!A1:I5: outside the allowlist"):
        guard.check("Tab", "A1:I5")


# -- the command ----------------------------------------------------------------------------

def test_construction_delta_prints_the_table_and_the_json_carries_it(tmp_path, capsys):
    journal = ingest(tmp_path, *READINGS)

    assert main(["construction", "--delta", "--journal-dir", str(journal), "--site", str(SITE)]) == 0
    out = capsys.readouterr().out
    assert f"Delivered at Site Alpha ({SITE}) since the store's first reading of it:" in out
    assert "Steel" in out and "240" in out and "190" in out
    assert "250 t delivered, 50 t yours, 200 t by others" in out

    assert main(["construction", "--delta", "2026-10-09T04:00:00Z", "--json",
                 "--journal-dir", str(journal), "--site", str(SITE)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["delta"]["why"] == "2026-10-09T04:00:00Z"
    assert payload["delta"]["resources"]["steel"]["delivered"] == 0


def test_construction_delta_without_a_store_or_a_reading_says_what_to_run(tmp_path, capsys):
    journal = tmp_path / "journal"
    journal.mkdir()
    write(journal, FIRST, header(), loadgame(), *READINGS)

    assert main(["construction", "--delta", "--journal-dir", str(journal), "--site", str(SITE)]) == 1
    assert "store ingest" in capsys.readouterr().out
    assert not store_path().exists()

    empty = tmp_path / "nothing-here"
    empty.mkdir()
    ingest_mod.ingest_dir(empty)                 # a store now exists, with no reading of the site
    assert main(["construction", "--delta", "--journal-dir", str(journal), "--site", str(SITE)]) == 1
    assert f"no reading of site {SITE}" in capsys.readouterr().out


# -- the publish, remembered ----------------------------------------------------------------

class FakeExporter:
    built: list = []

    def __init__(self, region_guard=None):
        self.region_guard = region_guard
        self.writes = []
        FakeExporter.built.append(self)

    def export_grid(self, rows, sheet_id=None, tab_name=None):
        self.writes.append((sheet_id, tab_name, rows))
        return len(rows)


@pytest.fixture
def sheet(monkeypatch):
    import APITool.google as google_mod
    monkeypatch.setattr(google_mod, "GoogleSheetsExporter", FakeExporter)
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    FakeExporter.built = []
    return FakeExporter


def _publish(journal):
    return main(["construction", "--publish-to", "Hauling", "--region", "A1:I60", "--sheet-id", "sid",
                 "--journal-dir", str(journal), "--site", str(SITE)])


def test_the_published_block_shows_the_change_since_its_last_publish(tmp_path, sheet, capsys):
    journal = ingest(tmp_path, *READINGS)

    assert _publish(journal) == 0
    first = sheet.built[-1].writes[-1][2]
    assert first[4][:8] == ["steel", "Steel", 1000, 300, 700, 500, 240, 190], "since the first reading"
    assert writes.recorded("gsheet:sid", "Hauling", ["A1:I60"]) == {"A1:I60": f"{SITE}@2026-10-09T04:00:00Z"}

    write(journal, "Journal.2026-10-09T060000.01.log", header(part=2),
          contribution(5, [("titanium", 5)]),
          depot(6, [("steel", 1000, 320, 500), ("titanium", 500, 70, 900)], progress=0.39))
    ingest_mod.ingest_dir(journal)
    assert _publish(journal) == 0
    second = sheet.built[-1].writes[-1][2]
    assert second[4][:8] == ["steel", "Steel", 1000, 320, 680, 500, 20, 20]
    assert second[5][:8] == ["titanium", "Titanium", 500, 70, 430, 900, 20, 15]
    assert writes.recorded("gsheet:sid", "Hauling", ["A1:I60"]) == {"A1:I60": f"{SITE}@2026-10-09T06:00:00Z"}
    assert "Published" in capsys.readouterr().out


def test_a_dry_run_publish_writes_nothing_and_remembers_nothing(tmp_path, sheet, capsys):
    journal = ingest(tmp_path, *READINGS)

    rc = main(["construction", "--publish-to", "Hauling", "--region", "A1:I60", "--sheet-id", "sid",
               "--journal-dir", str(journal), "--site", str(SITE), "--dry-run"])

    assert rc == 0
    assert "Would publish 2 commodities" in capsys.readouterr().out
    assert sheet.built == [], "no writer was built"
    assert writes.recorded("gsheet:sid", "Hauling", ["A1:I60"]) == {}


def test_a_publish_without_a_store_leaves_the_columns_blank_and_still_remembers(tmp_path, sheet):
    journal = tmp_path / "journal"
    journal.mkdir()
    write(journal, FIRST, header(), loadgame(), *READINGS)
    assert not store_path().exists()

    assert _publish(journal) == 0

    grid = sheet.built[-1].writes[-1][2]
    assert grid[4][6:8] == ["", ""]
    assert writes.recorded("gsheet:sid", "Hauling", ["A1:I60"]) == {"A1:I60": f"{SITE}@2026-10-09T04:00:00Z"}
    assert settings.resolve("store.db").is_file(), "the ledger row is the store's first write"
