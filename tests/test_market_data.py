"""
Tests for emitting a market as data (AC-1..AC-4, AC-8).

The point of these is the project's framing: EDAPITool extracts data from Elite
Dangerous and presents it in numerous ways, and the Google Sheet is one of them.
Several future spreadsheets -- weapon upgrades, ship builds -- will ask the same
structural question against different data, so the artifact the tool produces
must know nothing about settlement commodities in particular.

The load-bearing property is therefore NEGATIVE: these paths must work with no
spreadsheet, no credentials, and no import of the sheets layer.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from APITool import market as market_mod
from APITool.catalog import load_catalog
from APITool.export import MarketExporter
from APITool.market import Market, MarketItem

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def ryman(catalog):
    raw = json.loads((FIXTURES / "market_ryman_journal.json").read_text(encoding="utf-8"))
    return market_mod.from_journal(raw, catalog)


# ---------------------------------------------------------------------------
# AC-1: the pure row builders
# ---------------------------------------------------------------------------

def test_flat_rows_one_per_commodity(ryman):
    rows = market_mod.flat_rows(ryman)
    assert len(rows) == len(ryman.items) == 366


def test_flat_rows_are_self_contained(ryman):
    """
    Station and timestamp repeat on every row, so snapshots from different
    stations concatenate into a usable dataset and a lone row still says where
    and when it came from.
    """
    for row in market_mod.flat_rows(ryman)[:5]:
        assert row["station"] == "Ryman Enterprise"
        assert row["system"] == "Lhou Mans"
        assert row["market_id"] == 3226578176
        assert row["timestamp"].startswith("2026-09-08")


def test_flat_rows_sorted_by_display_name(ryman):
    names = [r["commodity"] for r in market_mod.flat_rows(ryman)]
    assert names == sorted(names, key=lambda n: market_mod.normalize(n))


def test_flat_rows_carry_all_three_identifiers(ryman):
    row = next(r for r in market_mod.flat_rows(ryman) if r["commodity"] == "Biowaste")
    assert row["commodity_id"] == 128049244
    assert row["symbol"] == "Biowaste"
    assert row["stock"] == 70192
    assert row["buy_price"] == 54
    assert row["source"] == "journal"


def test_flat_fields_cover_every_key(ryman):
    for row in market_mod.flat_rows(ryman)[:3]:
        assert set(row) == set(market_mod.FLAT_FIELDS)


def test_row_builders_perform_no_io(ryman, monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("row builder attempted I/O")

    monkeypatch.setattr("builtins.open", explode)
    assert market_mod.flat_rows(ryman)
    assert market_mod.sheet_grid(ryman)


# ---------------------------------------------------------------------------
# AC-4: the sheet grid is a VLOOKUP table, shaped like CargoData
# ---------------------------------------------------------------------------

def test_sheet_grid_shape(ryman):
    grid = market_mod.sheet_grid(ryman)
    assert len(grid) == 3 + len(ryman.items)
    assert grid[0][1] == "Station" and grid[0][2] == "Ryman Enterprise"
    assert grid[1][1] == "Updated (UTC)"
    assert grid[2] == [""] + market_mod.SHEET_HEADERS


def test_sheet_grid_leaves_column_a_empty(ryman):
    """Mirrors CargoData, which keeps column A as margin."""
    assert all(row[0] == "" for row in market_mod.sheet_grid(ryman))


def test_ac4_vlookup_positions_match_the_documented_formula(ryman):
    """
    The published contract is:
        =VLOOKUP($B5, MarketData!$B:$G, 2, FALSE)  -> stock
        =VLOOKUP($B5, MarketData!$B:$G, 3, FALSE)  -> buy price
    VLOOKUP index N over B:G is offset N-1 from column B, i.e. grid index N.
    """
    grid = market_mod.sheet_grid(ryman)
    row = next(r for r in grid if r[1] == "Biowaste")
    assert row[1] == "Biowaste"   # key column
    assert row[2] == 70192        # VLOOKUP index 2 -> stock
    assert row[3] == 54           # VLOOKUP index 3 -> buy price


def test_ac4_metadata_can_never_collide_with_a_commodity_lookup(ryman, catalog):
    """
    Metadata LABELS sit in the key column; a lookup only breaks if a label is
    also a real commodity name. Check that against the whole catalog, not just
    this station -- the risk is a future commodity, not a current one.
    """
    grid = market_mod.sheet_grid(ryman)
    labels = {grid[0][1], grid[1][1], grid[2][1]}
    assert labels == {"Station", "Updated (UTC)", "Commodity"}
    for label in labels:
        assert catalog.by_name(label) is None, f"{label!r} is a real commodity name"


def test_ac4_metadata_values_are_not_in_the_key_column(ryman):
    """Station names are not commodity names, but keeping them out of column B
    removes the question entirely."""
    grid = market_mod.sheet_grid(ryman)
    assert grid[0][1] != "Ryman Enterprise"
    assert grid[0][2] == "Ryman Enterprise"


def test_ac4_every_commodity_is_findable_by_its_display_name(ryman):
    grid = market_mod.sheet_grid(ryman)
    keys = [row[1] for row in grid[3:]]
    assert len(keys) == len(set(keys)), "duplicate keys would make VLOOKUP ambiguous"
    for item in ryman.items:
        assert item.name in keys


# ---------------------------------------------------------------------------
# AC-8: no current market clears the tab rather than leaving it stale
# ---------------------------------------------------------------------------

def test_ac8_empty_grid_has_headers_but_no_commodities():
    grid = market_mod.empty_sheet_grid("Not docked")
    assert len(grid) == 3
    assert grid[0][2] == "Not docked"
    assert grid[2] == [""] + market_mod.SHEET_HEADERS


def test_ac8_empty_grid_carries_the_reason():
    grid = market_mod.empty_sheet_grid("Market.json describes a different station")
    assert "different station" in grid[0][2]


def test_ac8_a_lookup_against_the_empty_grid_finds_nothing():
    grid = market_mod.empty_sheet_grid()
    assert [r[1] for r in grid[3:]] == []


# ---------------------------------------------------------------------------
# AC-2: files, with no spreadsheet and no credentials
# ---------------------------------------------------------------------------

def test_ac2_csv_written_without_any_google_involvement(ryman, tmp_path, monkeypatch):
    """
    The generic path must not depend on Google credentials existing. Point HOME
    at an empty directory so ~/.ed_gsheet_* cannot be found.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    path = MarketExporter(tmp_path).export_csv(ryman)
    assert path.exists()

    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 366
    assert list(rows[0]) == market_mod.FLAT_FIELDS
    bio = next(r for r in rows if r["commodity"] == "Biowaste")
    assert bio["stock"] == "70192"
    assert bio["buy_price"] == "54"
    assert bio["station"] == "Ryman Enterprise"


def test_ac2_json_written_without_any_google_involvement(ryman, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    path = MarketExporter(tmp_path).export_json(ryman)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["station"] == "Ryman Enterprise"
    assert payload["market_id"] == 3226578176
    assert payload["item_count"] == 366
    assert len(payload["commodities"]) == 366


def test_ac2_filenames_name_the_station(ryman, tmp_path):
    path = MarketExporter(tmp_path).export_csv(ryman)
    assert "Ryman-Enterprise" in path.name
    assert path.suffix == ".csv"


def test_ac2_a_station_with_awkward_punctuation_still_produces_a_filename(tmp_path):
    market = Market(1, "Hutton Orbital / Alpha Centauri!", "Sol",
                    datetime.now(timezone.utc), "journal",
                    (MarketItem(1, "X", "Steel", stock=5, buy_price=10),))
    path = MarketExporter(tmp_path).export_csv(market)
    assert path.exists()
    assert "/" not in path.name and "!" not in path.name


def test_ac2_an_empty_market_still_produces_a_valid_file(tmp_path):
    market = Market(None, "Nowhere", "", None, "journal", ())
    path = MarketExporter(tmp_path).export_csv(market)
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == []


# ---------------------------------------------------------------------------
# AC-6: the layering, enforced rather than intended
# ---------------------------------------------------------------------------

CORE_MODULES = ["catalog", "market", "matcher", "journal"]
PRESENTATION_MODULES = {"sheets", "gsheet"}
# One layer further down the same axis: `markers` holds ONE workbook's
# opinions, while `sheets` holds the mechanics every workbook shares. So
# `sheets` sits below `markers` and must never reach up into it, or the
# mechanics acquire a favourite presenter and stop being reusable.
OPINIONATED_MODULES = {"markers"}


def _bare_imports(module_name: str) -> set[str]:
    """
    Every module ``module_name`` imports, reduced to a bare top-level name.

    Normalizes every form an import could take -- relative (`from .sheets
    import X`), absolute (`import APITool.gsheet`), from-absolute (`from
    APITool.gsheet import Y`), and aliased -- down to the bare module name.
    Matching only the relative form would let the absolute one through, which
    is exactly the kind of gap that makes a layering test look green while the
    layering is broken. That gap was real here once.
    """
    import ast

    source = (Path(__file__).parents[1] / "APITool" / f"{module_name}.py").read_text(
        encoding="utf-8"
    )
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)

    return {name.lstrip(".").removeprefix("APITool.").split(".")[0] for name in imported}


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_ac6_core_modules_do_not_import_the_sheets_layer(module_name):
    """
    Dependency points one way: presentation may depend on core, never the
    reverse. Enforced by a test because layering kept only by convention
    erodes, and this project intends to grow several different spreadsheets on
    top of the same core.
    """
    leaked = _bare_imports(module_name) & PRESENTATION_MODULES
    assert not leaked, f"{module_name}.py imports presentation module(s): {sorted(leaked)}"


def test_the_mechanics_module_does_not_import_the_presenter():
    """
    ``sheets`` must not import ``markers`` (writer-seam DWP, AC-2).

    This is the check that keeps the split honest. Every other proof of the
    refactor -- no glyph constants left in ``sheets``, the guard in one module,
    a green suite -- would still hold if ``sheets`` quietly imported one glyph
    back for a default. That single import would re-couple the mechanics to
    this workbook's opinions and make the next renderer expensive again, which
    is the entire failure the split exists to prevent.
    """
    leaked = _bare_imports("sheets") & OPINIONATED_MODULES
    assert not leaked, (
        f"sheets.py imports the presenter: {sorted(leaked)}. The dependency runs "
        "markers -> sheets, never the reverse."
    )


def test_ac6_the_core_is_usable_with_gspread_uninstalled():
    """
    A consumer who never touches Google must not need gspread installed at all.

    Run in a subprocess with gspread forced to ImportError, because the parent
    test process has already imported it and cannot un-import it honestly.
    """
    import subprocess
    import sys
    import textwrap

    program = textwrap.dedent(
        """
        import builtins, sys
        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "gspread" or name.startswith("gspread."):
                raise ImportError("gspread is not installed")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = blocked
        for mod in ("gspread",):
            sys.modules.pop(mod, None)

        from APITool.catalog import load_catalog
        from APITool.matcher import build_requirements, compare
        from APITool import market as market_mod
        from APITool.journal import JournalReader

        import json
        raw = json.load(open("tests/fixtures/market_ryman_journal.json", encoding="utf-8"))
        cat = load_catalog()
        mkt = market_mod.from_journal(raw, cat)
        rows = market_mod.flat_rows(mkt)
        reqs = build_requirements([(6, "Biowaste", 229)], cat)
        matches = compare(reqs, mkt)

        assert len(rows) == 366
        assert matches[0].state.value == "ENOUGH"
        assert "gspread" not in sys.modules
        print("OK")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).parents[1],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, f"core needs gspread:\n{proc.stdout}\n{proc.stderr}"
    assert "OK" in proc.stdout


def test_the_tool_still_works_with_the_presenter_removed():
    """
    Issue #7, acceptance criterion 4: "the opinionated presenter is separable
    -- removing it leaves a working generic tool".

    Stronger than the layering test above, and it caught something that test
    could not: ``sheets`` not importing ``markers`` says nothing about
    ``service``, which imported the presenter at module scope and so took the
    CLI, the exports and the future HTTP API down with it when the presenter
    was absent. Every generic path here must survive ``markers.py`` being
    deleted outright.

    Subprocess, for the same reason as the gspread check: the parent process
    has already imported the presenter and cannot honestly un-import it.
    """
    import subprocess
    import sys
    import textwrap

    program = textwrap.dedent(
        """
        import sys

        class Blocked:
            # 3.12 removed find_module/load_module; only find_spec is consulted.
            def find_spec(self, name, path=None, target=None):
                if name == "APITool.markers":
                    raise ImportError("APITool.markers has been removed")
                return None

        sys.meta_path.insert(0, Blocked())

        # Control: the block must actually block, or nothing below means
        # anything. The first version of this check used the deprecated
        # find_module hook, which 3.12 never calls, and passed vacuously.
        try:
            import APITool.markers
            raise AssertionError("the presenter was not actually blocked")
        except ImportError:
            pass

        import APITool.sheets
        import APITool.service
        import APITool.cli
        from APITool.market import Market, MarketItem, flat_rows, sheet_grid

        mkt = Market(1, "S", "Sys", None, "journal",
                     (MarketItem(1, "X", "Biowaste", stock=5, buy_price=7),))
        assert flat_rows(mkt) and sheet_grid(mkt)
        assert "APITool.markers" not in sys.modules
        print("OK")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).parents[1],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, (
        f"the presenter is not separable:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "OK" in proc.stdout


# ---------------------------------------------------------------------------
# AC-8 wiring: the CLI/service path, not just the grid builder
# ---------------------------------------------------------------------------

def test_ac8_service_grid_is_empty_when_there_is_no_current_market():
    """
    The path a caller actually takes. A tab left holding the previous
    station's prices under a fresh-looking header is the same failure the
    market freshness gate prevents, relocated to another surface -- so "no
    market" must produce a grid that actively clears the tab.
    """
    from APITool.cli import _service_grid
    from APITool.service import REASON_STALE_MARKET, RefreshResult
    from APITool.journal import LocationState

    result = RefreshResult(location=LocationState(), reason=REASON_STALE_MARKET)
    grid = _service_grid(result)

    assert len(grid) == 3, "no commodity rows"
    assert "Commodity Market screen" in grid[0][2], "carries the reason"
    assert grid[2] == [""] + market_mod.SHEET_HEADERS


def test_ac8_service_grid_carries_the_market_when_there_is_one(ryman):
    from APITool.cli import _service_grid
    from APITool.service import RefreshResult
    from APITool.journal import LocationState

    result = RefreshResult(location=LocationState(), market=ryman)
    grid = _service_grid(result)
    assert len(grid) == 3 + 366
    assert grid[0][2] == "Ryman Enterprise"


def test_csv_and_json_exports_are_skipped_when_there_is_no_market(tmp_path, capsys):
    """csv/json describe a market; with none, say so rather than writing an empty file."""
    from APITool.cli import _export_market
    from APITool.service import REASON_NOT_DOCKED, RefreshResult
    from APITool.journal import LocationState
    import argparse

    args = argparse.Namespace(output=str(tmp_path))
    result = RefreshResult(location=LocationState(), reason=REASON_NOT_DOCKED)
    done = _export_market(args, result, ["csv", "json"], sheet_id=None)

    assert done == []
    assert "No current market" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_market_tab_export_requires_a_spreadsheet_id(ryman, tmp_path):
    from APITool.cli import _export_market
    from APITool.service import RefreshResult
    from APITool.journal import LocationState
    import argparse

    args = argparse.Namespace(output=str(tmp_path))
    result = RefreshResult(location=LocationState(), market=ryman)
    with pytest.raises(ValueError, match="needs a spreadsheet id"):
        _export_market(args, result, ["market-tab"], sheet_id=None)
