"""
Tests for the tab-level write guard in gsheet.py (build step B-2, AC-7).

`export_cargo` calls `worksheet.clear()` -- a whole-tab wipe. It used to be
governed by a DENY list:

    PROTECTED_TABS = ["Base", "1st", "2", "3", "Sheet3"]

which failed open. Three of those five tabs do not exist in the real workbook,
while every tab holding irreplaceable hand-entered work was absent from the
list and therefore writable. These tests pin the inverted, fail-closed rule.

The tab check runs before any network call, so none of this needs credentials.
"""

import pytest

from APITool.gsheet import GSPREAD_AVAILABLE, GoogleSheetsExporter
from APITool.models import FleetCarrier

pytestmark = pytest.mark.skipif(
    not GSPREAD_AVAILABLE, reason="gspread not installed (pip install edapitool[gsheets])"
)

# The real workbook's tabs, measured 2026-09-08.
LIVE_TABS = ["Base", "Totals Tab", "Agri Lrg. (ex)", "Sat. (ex)", "Extr. (ex)", "CargoData"]


@pytest.fixture
def exporter():
    return GoogleSheetsExporter()


@pytest.fixture
def carrier():
    return FleetCarrier.from_capi({"name": {"callsign": "Q9G-6HX"}})


@pytest.mark.parametrize(
    "tab", [t for t in LIVE_TABS if t != "CargoData"] + ["Sheet1", "Anything", ""]
)
def test_wholesale_rewrite_refused_for_every_tab_but_cargodata(exporter, carrier, tab):
    with pytest.raises(ValueError, match="Refusing to rewrite"):
        exporter.export_cargo(carrier, sheet_id="irrelevant", tab_name=tab)


def test_the_four_tabs_the_old_deny_list_left_unprotected(exporter, carrier):
    """
    These hold hand-entered settlement data and live formulas. Under the old
    PROTECTED_TABS deny list every one of them was writable.
    """
    for tab in ("Totals Tab", "Agri Lrg. (ex)", "Sat. (ex)", "Extr. (ex)"):
        with pytest.raises(ValueError):
            exporter.export_cargo(carrier, sheet_id="irrelevant", tab_name=tab)


def test_cargodata_is_the_default_and_is_allowed(exporter):
    """AC-7: the existing `--export google` path must keep working."""
    assert "CargoData" in exporter.writable_tabs
    assert exporter.writable_tabs == GoogleSheetsExporter.WRITABLE_TABS


def test_error_message_names_what_is_allowed(exporter, carrier):
    with pytest.raises(ValueError) as excinfo:
        exporter.export_cargo(carrier, sheet_id="irrelevant", tab_name="Totals Tab")
    assert "CargoData" in str(excinfo.value)


def test_allow_list_is_overridable_for_a_deliberate_target(carrier):
    """An explicit override exists, but it must be opt-in and per-instance."""
    custom = GoogleSheetsExporter(writable_tabs={"MyGeneratedTab"})
    assert "MyGeneratedTab" in custom.writable_tabs
    assert "CargoData" not in custom.writable_tabs
    with pytest.raises(ValueError):
        custom.export_cargo(carrier, sheet_id="irrelevant", tab_name="CargoData")
    # ...and the override does not leak into other instances.
    assert GoogleSheetsExporter().writable_tabs == GoogleSheetsExporter.WRITABLE_TABS


def test_old_deny_list_attribute_is_gone():
    """
    Guards against someone reintroducing the fail-open pattern, and against
    code elsewhere still reading the old name.
    """
    assert not hasattr(GoogleSheetsExporter, "PROTECTED_TABS")


def test_guard_runs_before_any_network_call(exporter, carrier):
    """
    The refusal must not depend on credentials being present, or a
    misconfigured tab name would surface as an auth error instead.
    """
    exporter._client = object()      # any use of this would fail loudly
    with pytest.raises(ValueError, match="Refusing to rewrite"):
        exporter.export_cargo(carrier, sheet_id="irrelevant", tab_name="Base")
