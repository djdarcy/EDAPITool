"""
Tests for ship cargo extraction (issue #6, DWP build step 1).

The fixture is a verbatim copy of the real ``Cargo.json`` as it stood on
2026-09-08, including the one entry the game writes WITHOUT a
``Name_Localised`` field. That omission is the trap this feature exists to
survive, so it is preserved rather than tidied.
"""

import json
from datetime import timezone
from pathlib import Path

import pytest

from APITool import ship
from APITool.catalog import load_catalog
from APITool.ship import ShipCargo, ShipCargoItem

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture
def raw():
    return json.loads((FIXTURES / "cargo_ship.json").read_text(encoding="utf-8"))


@pytest.fixture
def cargo(raw, catalog):
    return ship.from_journal(raw, catalog)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def test_reads_the_real_cargo_file(cargo):
    assert cargo.vessel == "Ship"
    assert cargo.count == 227
    assert len(cargo) == 4


def test_biowaste_resolves_despite_having_no_localised_name(cargo):
    """
    The whole naming caveat in one test.

    ``biowaste`` is written with no ``Name_Localised`` because its localised
    name equals its symbol. Resolving by display name alone would drop it --
    and it is 62 of the 227 tonnes aboard.
    """
    item = cargo.find(symbol="biowaste")
    assert item is not None
    assert item.name == "Biowaste"
    assert item.count == 62
    assert item.id == 128049244


def test_every_entry_resolves_to_a_catalog_commodity(cargo):
    assert all(item.id is not None for item in cargo.items)
    assert {i.name for i in cargo.items} == {
        "Biowaste",
        "Power Generators",
        "Structural Regulators",
        "Building Fabricators",
    }


def test_itemised_total_matches_the_reported_count(cargo):
    """227 reported, 227 itemised -- the sum the spreadsheet's M4 shows."""
    assert cargo.total == cargo.count == 227


def test_timestamp_is_parsed_as_utc(cargo):
    assert cargo.timestamp is not None
    assert cargo.timestamp.tzinfo is not None
    assert cargo.timestamp.astimezone(timezone.utc).hour == 6


def test_srv_cargo_is_reported_as_not_a_ship(catalog):
    """
    The SRV writes to the same file. Reporting its hold as ship cargo would
    feed the spreadsheet a number that is real but about the wrong vessel.
    """
    raw = {"Vessel": "SRV", "Count": 4, "Inventory": [
        {"Name": "biowaste", "Count": 4, "Stolen": 0},
    ]}
    cargo = ship.from_journal(raw, catalog)
    assert cargo.vessel == "SRV"
    assert cargo.is_ship is False


def test_vessel_check_is_case_insensitive(catalog):
    assert ship.from_journal({"Vessel": "ship"}, catalog).is_ship is True
    assert ship.from_journal({"Vessel": "SHIP"}, catalog).is_ship is True
    assert ship.from_journal({"Vessel": "srv"}, catalog).is_ship is False


def test_an_empty_hold_is_valid_not_a_failure(catalog):
    cargo = ship.from_journal({"Vessel": "Ship", "Count": 0, "Inventory": []}, catalog)
    assert cargo.is_ship is True
    assert len(cargo) == 0
    assert cargo.total == 0


def test_zero_count_entries_are_dropped(catalog):
    raw = {"Vessel": "Ship", "Inventory": [
        {"Name": "biowaste", "Count": 0, "Stolen": 0},
        {"Name": "powergenerators", "Count": 9, "Stolen": 0},
    ]}
    cargo = ship.from_journal(raw, catalog)
    assert len(cargo) == 1
    assert cargo.items[0].symbol == "powergenerators"


def test_a_commodity_the_catalog_does_not_know_is_kept_not_dropped(catalog):
    """
    The bundled table can lag the game. An unknown commodity is still cargo,
    and a sheet row naming it should still match -- so it survives with a
    null id rather than vanishing.
    """
    raw = {"Vessel": "Ship", "Inventory": [
        {"Name": "unobtainium", "Name_Localised": "Unobtainium", "Count": 3},
    ]}
    cargo = ship.from_journal(raw, catalog)
    assert len(cargo) == 1
    assert cargo.items[0].id is None
    assert cargo.items[0].name == "Unobtainium"
    assert cargo.quantity_of("Unobtainium") == 3


def test_malformed_inventory_entries_are_skipped(catalog):
    raw = {"Vessel": "Ship", "Inventory": [
        "not a mapping",
        {"no_name_field": True, "Count": 5},
        {"Name": "biowaste", "Count": 62},
    ]}
    cargo = ship.from_journal(raw, catalog)
    assert len(cargo) == 1


def test_missing_timestamp_is_none_not_an_error(catalog):
    assert ship.from_journal({"Vessel": "Ship"}, catalog).timestamp is None


# ---------------------------------------------------------------------------
# Lookup -- what the spreadsheet wiring depends on
# ---------------------------------------------------------------------------

def test_quantity_of_matches_the_sheets_own_spelling(cargo):
    """
    The live sheet writes "Building fabricators"; the catalog says "Building
    Fabricators". Matching must be case-insensitive or column M would read
    zero for two of the four commodities aboard.
    """
    assert cargo.quantity_of("Building Fabricators") == 40
    assert cargo.quantity_of("Building fabricators") == 40
    assert cargo.quantity_of("Structural regulators") == 116


def test_quantity_of_is_zero_for_a_commodity_not_carried(cargo):
    assert cargo.quantity_of("Tritium") == 0


def test_find_precedence_is_id_then_symbol_then_name(cargo):
    assert cargo.find(commodity_id=128049244).name == "Biowaste"
    assert cargo.find(symbol="$powergenerators_name;").name == "Power Generators"
    assert cargo.find(name="power generators").name == "Power Generators"
    assert cargo.find(name="nothing here") is None


# ---------------------------------------------------------------------------
# Emission -- data, not a rendering
# ---------------------------------------------------------------------------

def test_flat_rows_are_self_contained_and_sorted(cargo):
    rows = ship.flat_rows(cargo)
    assert [r["commodity"] for r in rows] == [
        "Biowaste", "Building Fabricators", "Power Generators", "Structural Regulators",
    ]
    assert all(set(r) == set(ship.FLAT_FIELDS) for r in rows)
    # Vessel and timestamp repeat on every row, so a row means something alone.
    assert all(r["vessel"] == "Ship" and r["timestamp"] for r in rows)


def test_sheet_grid_puts_the_lookup_key_in_column_b(cargo):
    """
    The contract the spreadsheet formula depends on:
        =IFERROR(VLOOKUP($B5, ShipCargo!$B:$C, 2, FALSE), 0)
    Column A is margin, B is the commodity name, C is the quantity.
    """
    grid = ship.sheet_grid(cargo)
    assert grid[2] == ["", "Commodity", "Quantity", "Symbol", "Stolen"]
    body = grid[3:]
    assert all(row[0] == "" for row in body)
    assert [row[1] for row in body] == [
        "Biowaste", "Building Fabricators", "Power Generators", "Structural Regulators",
    ]
    assert [row[2] for row in body] == [62, 40, 9, 116]


def test_metadata_labels_sit_in_the_key_column_but_values_do_not(cargo):
    """
    Same protection MarketData uses. A whole-column VLOOKUP scans B, so B may
    hold only labels no commodity could ever be named. Putting the vessel or
    the tonnage in B would work until Frontier ships an odd commodity name.
    """
    grid = ship.sheet_grid(cargo)
    labels = {grid[0][1], grid[1][1]}
    assert labels == {"Vessel", "Total Tonnage"}
    assert grid[0][2] == "Ship"      # the value, in C
    assert grid[1][2] == 227


def test_empty_grid_carries_a_reason_rather_than_stale_contents():
    """
    Column M subtracts into "Left to buy", so a tab left holding the previous
    hold silently changes which commodities get recommended.
    """
    grid = ship.empty_sheet_grid("No Cargo.json found")
    assert grid[0][2] == "No Cargo.json found"
    assert grid[1][2] == 0
    assert grid[2] == ["", "Commodity", "Quantity", "Symbol", "Stolen"]
    assert len(grid) == 3


def test_hand_built_cargo_needs_no_catalog():
    """The value objects are usable without any game file or lookup table."""
    cargo = ShipCargo(
        vessel="Ship",
        timestamp=None,
        count=5,
        items=(ShipCargoItem(id=1, symbol="x", name="Widget", count=5),),
    )
    assert cargo.quantity_of("widget") == 5
    assert ship.flat_rows(cargo)[0]["commodity"] == "Widget"
