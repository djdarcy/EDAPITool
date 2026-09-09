"""
The shared cargo tab column contract (issue #11).

These tests exist because of one measured hazard. A spreadsheet reads a cargo
tab with ``VLOOKUP($B5, <tab>!$B:$D, 3, FALSE)``, and that ``3`` is a literal.
Insert a column left of D and Google Sheets widens the range to ``$B:$E``
automatically while leaving the literal alone -- so every lookup silently
shifts one column right and returns the wrong field with no error.

Measured 2026-09-08 on a throwaway tab: after inserting one column at C,
index 2 returned the inserted column and index 3 returned Quantity. There
were 476 such formulas live in the workbook at the time.

So the assertions here are not style checks. They are the thing standing
between a refactor and several hundred quietly wrong numbers.
"""

import pytest

from APITool import cargo
from APITool.cargo import (
    INDEX_COMMODITY,
    INDEX_QUANTITY,
    INDEX_UNIT_PRICE,
    data_row,
    header_row,
    verify_contract,
)


# ---------------------------------------------------------------------------
# The contract itself
# ---------------------------------------------------------------------------

def test_the_published_indices_address_the_columns_they_claim():
    """
    The indices are the published part of the contract -- they appear as
    literals in the user's spreadsheet. Changing them silently is the failure
    this module exists to make impossible.
    """
    header = header_row()
    assert header[INDEX_COMMODITY] == "Commodity"
    assert header[INDEX_QUANTITY] == "Quantity"
    assert header[INDEX_UNIT_PRICE] == "Unit Price"


def test_column_a_is_an_empty_margin():
    assert header_row()[0] == ""
    assert data_row("Biowaste", 62)[0] == ""


def test_extras_land_right_of_unit_price_never_left():
    """
    Adding a column right of D is safe; left of D shifts every index. The
    helper must make the safe placement the only one available.
    """
    header = header_row(["Symbol", "Stolen"])
    assert header == ["", "Commodity", "Quantity", "Unit Price", "Symbol", "Stolen"]
    assert header.index("Symbol") > header.index("Unit Price")

    row = data_row("Biowaste", 62, extra=["biowaste", 0])
    assert row == ["", "Biowaste", 62, "", "biowaste", 0]
    assert row[INDEX_QUANTITY] == 62
    assert row[INDEX_UNIT_PRICE] == ""


def test_unit_price_defaults_to_blank_not_zero():
    """
    Blank reads as "not known"; zero reads as "worthless". For a hold whose
    price this tool has no source for, the second is a false claim -- and
    Sheets coerces the blank to 0 in arithmetic anyway, so SUM still works.
    """
    assert data_row("Biowaste", 62)[INDEX_UNIT_PRICE] == ""
    assert data_row("Biowaste", 62, unit_price=2122)[INDEX_UNIT_PRICE] == 2122


# ---------------------------------------------------------------------------
# verify_contract -- the guard a producer can call before writing
# ---------------------------------------------------------------------------

def _grid(header):
    return [["", "meta", "x"], ["", "meta", "y"], header, ["", "Biowaste", 62, ""]]


def test_verify_accepts_a_conforming_grid():
    verify_contract(_grid(header_row(["Symbol", "Stolen"])), header_row_index=2)


def test_verify_rejects_a_column_inserted_left_of_unit_price():
    """The exact hazard: Symbol pushed into D, so index 3 stops meaning price."""
    bad = ["", "Commodity", "Quantity", "Symbol", "Unit Price"]
    with pytest.raises(ValueError, match="index 3 must address 'Unit Price'"):
        verify_contract(_grid(bad), header_row_index=2)


def test_verify_rejects_a_column_inserted_left_of_quantity():
    """Category at C pushes Quantity to D, so index 2 stops meaning quantity."""
    bad = ["", "Commodity", "Category", "Quantity", "Unit Price"]
    with pytest.raises(ValueError, match="index 2 must address 'Quantity'"):
        verify_contract(_grid(bad), header_row_index=2)


def test_verify_rejects_a_renamed_key_column():
    """`CargoData` said "Display Name" for years; the contract says Commodity."""
    bad = ["", "Display Name", "Quantity", "Unit Price"]
    with pytest.raises(ValueError, match="index 1 must address 'Commodity'"):
        verify_contract(_grid(bad), header_row_index=2)


def test_verify_rejects_a_missing_margin():
    bad = ["Commodity", "Quantity", "Unit Price"]
    with pytest.raises(ValueError, match="margin"):
        verify_contract(_grid(bad), header_row_index=2)


def test_verify_rejects_a_header_too_short_to_reach_unit_price():
    """A truncated header must fail loudly, not IndexError."""
    with pytest.raises(ValueError, match="index 3 must address 'Unit Price'"):
        verify_contract(_grid(["", "Commodity", "Quantity"]), header_row_index=2)


def test_verify_rejects_a_grid_with_no_header_row_there():
    with pytest.raises(ValueError, match="no header row"):
        verify_contract([["", "meta"]], header_row_index=5)


# ---------------------------------------------------------------------------
# The rendered formula -- so docs cannot drift from the contract
# ---------------------------------------------------------------------------

def test_lookup_formula_uses_ifna_and_the_contract_range():
    f = cargo.lookup_formula("$B5", "ShipCargo", INDEX_QUANTITY)
    assert f == '=IFNA(VLOOKUP($B5, ShipCargo!$B:$D, 2, FALSE), "")'
    # IFNA, not IFERROR: a renamed or deleted tab must surface as #REF! rather
    # than silently blanking a column that feeds the sheet's arithmetic.
    assert "IFERROR" not in f


def test_lookup_formula_tracks_the_index_constants():
    """If an index constant ever moves, the rendered formula moves with it."""
    f = cargo.lookup_formula("$B5", "FreighterData", INDEX_UNIT_PRICE)
    assert f"{INDEX_UNIT_PRICE}, FALSE" in f


# ---------------------------------------------------------------------------
# Every real producer honours it
# ---------------------------------------------------------------------------

def test_ship_cargo_grid_honours_the_contract():
    from APITool.ship import ShipCargo, ShipCargoItem, sheet_grid

    hold = ShipCargo(
        vessel="Ship", timestamp=None, count=62,
        items=(ShipCargoItem(id=1, symbol="biowaste", name="Biowaste", count=62),),
    )
    verify_contract(sheet_grid(hold), header_row_index=2)


def test_the_empty_ship_grid_honours_the_contract_too():
    """A tab written because there is nothing to report is still a cargo tab."""
    from APITool.ship import empty_sheet_grid

    verify_contract(empty_sheet_grid("No Cargo.json found"), header_row_index=2)


CARRIER_ROWS = [
    {"display_name": "Aluminium", "quantity": 1751, "unit_price": 2122},
    {"display_name": "Animal Meat", "quantity": 4, "unit_price": 0},
]


def test_carrier_grid_honours_the_contract():
    from APITool.gsheet import carrier_grid

    verify_contract(carrier_grid(CARRIER_ROWS), header_row_index=1)


def test_carrier_key_column_renamed_from_display_name_to_commodity():
    """
    The tab said "Display Name" from v0.2.0 until this contract landed. No
    formula read the header text, so the rename is safe -- but the contract
    names the column, so the header has to agree with it.
    """
    from APITool.gsheet import carrier_grid

    assert carrier_grid(CARRIER_ROWS)[1][INDEX_COMMODITY] == "Commodity"


def test_both_producers_agree_on_the_lookup_columns():
    """
    The whole point of the contract, asserted directly: a formula written
    against one cargo tab addresses the same fields on the other.
    """
    from APITool.gsheet import carrier_grid
    from APITool.ship import ShipCargo, ShipCargoItem, sheet_grid

    hold = ShipCargo(
        vessel="Ship", timestamp=None, count=62,
        items=(ShipCargoItem(id=1, symbol="biowaste", name="Biowaste", count=62),),
    )
    carrier_header = carrier_grid(CARRIER_ROWS)[1]
    ship_header = sheet_grid(hold)[2]

    for index in (INDEX_COMMODITY, INDEX_QUANTITY, INDEX_UNIT_PRICE):
        assert carrier_header[index] == ship_header[index]


def test_carrier_keeps_its_own_tail_and_ship_keeps_a_different_one():
    """
    Uniformity stops at D on purpose. The carrier has real prices and a human
    reads that tab, so it carries Total Value; the ship has neither, and
    carries symbol and stolen instead. Forcing either tail onto the other
    would mean emitting a column its producer cannot fill.
    """
    from APITool.gsheet import carrier_grid
    from APITool.ship import SHEET_HEADERS

    carrier_tail = carrier_grid(CARRIER_ROWS)[1][INDEX_UNIT_PRICE + 1:]
    ship_tail = SHEET_HEADERS[INDEX_UNIT_PRICE:]

    assert carrier_tail == ["Total Value"]
    assert ship_tail == ["Symbol", "Stolen"]
    assert carrier_tail != ship_tail


def test_carrier_grid_refuses_to_return_a_non_conforming_grid(monkeypatch):
    """
    The guard cannot fire on today's code, because `carrier_grid` builds every
    row from the contract helpers -- so removing the `verify_contract` call
    changes nothing observable, and a mutation run proved exactly that.

    It is wired in for the edit that comes later: someone hand-rolling a header
    row, or slipping a column in left of D. This test manufactures that future
    by corrupting the helper, so the guard's presence is actually asserted
    rather than assumed.
    """
    import APITool.gsheet as gsheet_mod

    monkeypatch.setattr(
        gsheet_mod, "header_row",
        lambda extra=(): ["", "Commodity", "Total Value", "Quantity", "Unit Price"],
    )
    with pytest.raises(ValueError, match="index 2 must address 'Quantity'"):
        gsheet_mod.carrier_grid(CARRIER_ROWS)


def test_carrier_total_value_is_a_formula_not_a_computed_number():
    """
    The tool supplies the operands; the sheet does the arithmetic. Emitting a
    product would duplicate something the spreadsheet does natively, and would
    go stale the moment anyone edited a quantity by hand.
    """
    from APITool.gsheet import carrier_grid

    first_data_row = carrier_grid(CARRIER_ROWS)[3]
    assert first_data_row[INDEX_UNIT_PRICE + 1] == "=C4*D4"
