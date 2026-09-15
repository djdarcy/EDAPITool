"""A Destination is a value: writable down, storable, and free of live handles.

The constraints these tests hold come from two places. Issue #18 says the core
ships no destination and no workbook-specific defaults, so nothing here may
carry one. Issue #22's first two acceptance criteria say a Destination must
round-trip as plain data and that nothing under ``APITool/sheets/`` may reach
for a Google symbol -- because a stored binding has to be able to produce a
Destination later, with no spreadsheet open and no network available.
"""

import json
from pathlib import Path

import pytest

from APITool.sheets import a1
from APITool.sheets.destination import Destination

SHEETS_DIR = Path(a1.__file__).resolve().parent


# --- it is a value ------------------------------------------------------


def test_round_trips_through_json_with_equality_preserved():
    original = Destination.region("Agri Lrg. (ex)", "R1:AD60")
    revived = Destination.from_dict(json.loads(json.dumps(original.to_dict())))
    assert revived == original


def test_whole_tab_round_trips_too():
    original = Destination.whole_tab("MarketData")
    revived = Destination.from_dict(json.loads(json.dumps(original.to_dict())))
    assert revived == original
    assert revived.owns_whole_tab


def test_builds_from_a_plain_dict_with_no_network_and_no_spreadsheet():
    d = Destination.from_dict({"tab": "Sat. (ex)", "bounds": "R1:AD60"})
    assert d.tab == "Sat. (ex)"
    assert d.anchor == "R1"


def test_is_frozen():
    d = Destination.region("T", "A1:B2")
    with pytest.raises(Exception):
        d.tab = "other"


def test_holds_no_live_handle():
    """Every field must be plain data -- no client, worksheet or credential."""
    d = Destination.region("T", "A1:B2")
    for value in vars(d).values():
        assert value is None or isinstance(value, (str, int, a1.CellRange))


# --- bounds are required and closed -------------------------------------


def test_a_region_without_bounds_is_refused():
    with pytest.raises(ValueError):
        Destination.region("T", None)


def test_an_open_ended_reserve_is_refused():
    """'R1:AD' cannot be cleared to its own extent, so it is not a reserve."""
    with pytest.raises(ValueError) as excinfo:
        Destination.region("T", "R1:AD")
    assert "closed rectangle" in str(excinfo.value)


def test_a_column_only_reserve_is_refused():
    with pytest.raises(ValueError):
        Destination.region("T", "R:AD")


def test_a_destination_needs_a_tab():
    with pytest.raises(ValueError):
        Destination.region("", "A1:B2")
    with pytest.raises(ValueError):
        Destination.whole_tab("   ")


def test_whole_tab_is_reachable_only_by_naming_it():
    """bounds=None is a decision, never an omission."""
    assert Destination.whole_tab("MarketData").bounds is None
    with pytest.raises(TypeError):
        Destination.region("MarketData")          # bounds is not optional


# --- what it reports ----------------------------------------------------


def test_anchor_is_derived_from_bounds_not_stored_separately():
    assert Destination.region("T", "R1:AD60").anchor == "R1"
    assert Destination.region("T", "C5:F9").anchor == "C5"
    assert Destination.whole_tab("T").anchor == "A1"


def test_reserve_extent_is_inclusive():
    d = Destination.region("T", "R1:AD60")
    assert d.reserved_rows == 60
    assert d.reserved_cols == 13          # R..AD
    assert d.range_a1() == "R1:AD60"


def test_fits_reports_whether_a_grid_sits_inside_the_reserve():
    d = Destination.region("T", "R1:AD60")
    assert d.fits(rows=60, cols=13)
    assert d.fits(rows=1, cols=1)
    assert not d.fits(rows=61, cols=13)
    assert not d.fits(rows=60, cols=14)


def test_a_whole_tab_fits_anything():
    assert Destination.whole_tab("T").fits(rows=10**6, cols=10**3)


def test_describe_names_the_region():
    assert Destination.region("Agri Lrg. (ex)", "R1:AD60").describe() == (
        "Agri Lrg. (ex)!R1:AD60"
    )
    assert Destination.whole_tab("MarketData").describe() == (
        "MarketData (whole tab)"
    )


# --- the layering constraint (#22 criterion 2) --------------------------


def test_no_module_under_sheets_imports_a_google_symbol():
    offenders = []
    for path in sorted(SHEETS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for needle in ("import gspread", "from gspread", "googleapiclient",
                       "google.oauth2", "google.auth"):
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert offenders == [], (
        "APITool/sheets/ is the vendor-neutral toolkit; these reach for a "
        f"vendor: {offenders}"
    )


def test_destination_carries_no_default_tab_anchor_or_bounds():
    """#18: the core ships no destination and no workbook-specific defaults."""
    import inspect

    source = inspect.getsource(Destination)
    for literal in ("MarketData", "ShipCargo", "FreighterData", "Totals Tab",
                    "Agri Lrg"):
        assert f'"{literal}"' not in source, (
            f"{literal!r} is workbook data and must not appear in the "
            f"generic layer"
        )


# --- parsing what a person types ----------------------------------------


def test_parse_reads_the_form_people_already_know():
    d = Destination.parse("Agri Lrg. (ex)!R1:AC60")
    assert d.tab == "Agri Lrg. (ex)"
    assert d.range_a1() == "R1:AC60"


def test_parse_is_the_inverse_of_describe():
    original = Destination.region("Copy of Agri Lrg. (ex)", "R1:AC60")
    assert Destination.parse(original.describe()) == original


def test_parse_splits_on_the_last_bang_so_tab_names_stay_intact():
    """Real tab names carry spaces, periods and parentheses."""
    d = Destination.parse("Sat. (ex)! B2:D10 ")
    assert d.tab == "Sat. (ex)"
    assert d.range_a1() == "B2:D10"


def test_a_bare_tab_name_is_refused():
    """Owning a whole tab is declared, never arrived at by omission."""
    with pytest.raises(ValueError) as excinfo:
        Destination.parse("MarketData")
    assert "names no region" in str(excinfo.value)


def test_parse_still_refuses_an_open_ended_reserve():
    with pytest.raises(ValueError):
        Destination.parse("Tab!R1:AC")
