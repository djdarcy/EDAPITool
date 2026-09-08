"""
Tests for the pure comparison core (build steps B-4/B-5, acceptance check AC-4).

AC-4 pins the design's measured fixture: at Ryman Enterprise on 2026-09-08,
against the Totals Tab's 13 outstanding rows, exactly Biowaste, Power
Generators, Survival Equipment and Water Purifiers were buyable, Emergency
Power Cells was present at zero stock, and Land Enrichment Systems was sold
there but empty.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from APITool import market as market_mod
from APITool.catalog import load_catalog
from APITool.matcher import (
    ComparisonSummary,
    Match,
    MatchState,
    Requirement,
    build_requirements,
    classify,
    compare,
    compare_one,
)
from APITool.market import Market, MarketItem

FIXTURES = Path(__file__).parent / "fixtures"

# The 13 outstanding rows measured on the live Totals Tab, 2026-09-08.
# (sheet row, display name, Left to buy)
OUTSTANDING = [
    (6, "Biowaste", 229),
    (12, "Emergency power cells", 251),
    (13, "Evacuation shelter", 40),
    (15, "Fruit and vegetables", 196),
    (16, "Grain", 231),
    (18, "Land enrichment systems", 210),
    (20, "Micro Controllers", 13),
    (21, "Pesticides", 378),
    (23, "Power Generators", 9),
    (26, "Structural regulators", 116),
    (29, "Survival equipment", 8),
    (31, "Water", 22),
    (32, "Water Purifiers", 13),
]

# Rows on the sheet with nothing left to buy -- these must never be marked.
SATISFIED = [
    (5, "Aluminium", 0),
    (25, "Steel", 0),
    (30, "Titanium", 0),
]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def journal_market(catalog):
    raw = json.loads((FIXTURES / "market_ryman_journal.json").read_text(encoding="utf-8"))
    return market_mod.from_journal(raw, catalog)


@pytest.fixture(scope="module")
def capi_market(catalog):
    path = FIXTURES / "market_ryman_capi.json"
    if not path.exists():
        pytest.skip("CAPI market fixture not captured")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return market_mod.from_capi(raw, catalog, system="Lhou Mans")


@pytest.fixture
def requirements(catalog):
    return build_requirements(OUTSTANDING, catalog)


# --------------------------------------------------------------------------
# Market normalization
# --------------------------------------------------------------------------

def test_journal_market_parses(journal_market):
    assert journal_market.market_id == 3226578176
    assert journal_market.station == "Ryman Enterprise"
    assert journal_market.system == "Lhou Mans"
    assert len(journal_market) == 366
    assert journal_market.source == market_mod.SOURCE_JOURNAL
    # Pinned to the captured fixture. The game rewrites Market.json every time
    # the commodity screen is opened, so this is a property of the fixture file,
    # not of the station.
    assert journal_market.timestamp == datetime(2026, 9, 8, 5, 48, 18, tzinfo=timezone.utc)


def test_journal_timestamp_is_timezone_aware(journal_market):
    """Naive datetimes would silently compare wrong against 'now' in age checks."""
    assert journal_market.timestamp.tzinfo is not None


def test_capi_market_parses(capi_market):
    assert capi_market.market_id == 3226578176
    assert capi_market.station == "Ryman Enterprise"
    assert capi_market.system == "Lhou Mans"   # supplied by the caller
    assert len(capi_market) == 92


def test_journal_and_capi_describe_the_same_station(journal_market, capi_market):
    assert journal_market.market_id == capi_market.market_id


def test_journal_symbols_are_canonicalized(journal_market):
    """Raw journal symbols look like '$terrainenrichmentsystems_name;'."""
    item = journal_market.find(commodity_id=128049232)
    assert item is not None
    assert item.symbol == "TerrainEnrichmentSystems"
    assert item.name == "Land Enrichment Systems"


def test_market_find_works_by_all_three_identifiers(journal_market):
    by_id = journal_market.find(commodity_id=128049232)
    assert journal_market.find(symbol="TerrainEnrichmentSystems") is by_id
    assert journal_market.find(symbol="$terrainenrichmentsystems_name;") is by_id
    assert journal_market.find(name="Land Enrichment Systems") is by_id
    assert journal_market.find(name="land enrichment systems") is by_id


def test_market_find_returns_none_for_absent(journal_market):
    assert journal_market.find(name="Flurbulent Widgets") is None
    assert journal_market.find(commodity_id=1) is None
    assert journal_market.find() is None


# --------------------------------------------------------------------------
# The measured coverage asymmetry (design GT-8)
# --------------------------------------------------------------------------

def test_capi_carries_limpet_and_the_journal_does_not(journal_market, capi_market):
    """
    Measured: CAPI listed Limpet with 393,086 in stock; the journal's
    Market.json omitted it entirely. A journal-only design reports a
    purchasable commodity as unavailable.
    """
    assert capi_market.find(name="Limpet") is not None
    assert journal_market.find(name="Limpet") is None


def test_journal_knows_a_buy_price_capi_omits_entirely(journal_market, capi_market):
    """
    Measured: the journal knew Land Enrichment Systems sells here at 3,404
    with zero stock. CAPI omitted the row, so it cannot tell "out of stock"
    from "not traded here".
    """
    item = journal_market.find(commodity_id=128049232)
    assert item.buy_price == 3404
    assert item.stock == 0
    assert item.is_stocked_when_available is True
    assert capi_market.find(commodity_id=128049232) is None


def test_merge_gives_the_union(journal_market, capi_market):
    merged = market_mod.merge(capi_market, journal_market)
    assert len(merged) == 373          # 366 journal + 7 CAPI-only
    assert merged.find(name="Limpet") is not None                 # from CAPI
    assert merged.find(commodity_id=128049232) is not None        # from journal
    assert merged.source == market_mod.SOURCE_MERGED
    assert merged.system == "Lhou Mans"


def test_merge_primary_wins_on_shared_items():
    primary = Market(1, "S", "Sys", None, "capi",
                     (MarketItem(10, "A", "A", stock=5, buy_price=100, source="capi"),))
    supplement = Market(1, "S", "Sys", None, "journal",
                        (MarketItem(10, "A", "A", stock=999, buy_price=1, source="journal"),
                         MarketItem(20, "B", "B", stock=7, buy_price=2, source="journal")))
    merged = market_mod.merge(primary, supplement)
    assert merged.find(commodity_id=10).stock == 5      # primary wins
    assert merged.find(commodity_id=20).stock == 7      # supplement fills the gap


def test_merge_refuses_two_different_stations():
    a = Market(111, "Alpha", "S1", None, "capi", (MarketItem(1, "X", "X"),))
    b = Market(222, "Beta", "S2", None, "journal", (MarketItem(2, "Y", "Y"),))
    with pytest.raises(ValueError, match="different markets"):
        market_mod.merge(a, b)


def test_merge_tolerates_a_missing_supplement(journal_market):
    assert market_mod.merge(journal_market, None) is journal_market
    empty = Market(None, "", "", None, "capi", ())
    assert market_mod.merge(journal_market, empty) is journal_market


# --------------------------------------------------------------------------
# classify()
# --------------------------------------------------------------------------

def _item(stock, buy):
    return MarketItem(id=1, symbol="X", name="X", stock=stock, buy_price=buy)


@pytest.mark.parametrize(
    "need,stock,buy,expected",
    [
        (229, 70192, 54, MatchState.ENOUGH),
        (229, 229, 54, MatchState.ENOUGH),      # exactly enough is ENOUGH
        (229, 228, 54, MatchState.PARTIAL),
        (229, 1, 54, MatchState.PARTIAL),
        (229, 0, 3404, MatchState.EMPTY),       # sells it, out of stock
        (229, 0, 0, MatchState.NONE),           # not traded here
        (229, 500, 0, MatchState.NONE),         # stock but no buy price: sell-only
    ],
)
def test_classify_states(need, stock, buy, expected):
    assert classify(need, _item(stock, buy)) is expected


def test_classify_absent_item_is_none():
    assert classify(10, None) is MatchState.NONE


@pytest.mark.parametrize(
    "stock,buy,purchasable,stocked_when_available",
    [
        (70192, 54, True, False),     # normal: in stock and sold
        (0, 3404, False, True),       # sold here, out right now
        (0, 0, False, False),         # not traded
        (500, 0, False, False),       # sell-only: station buys, does not sell
        (1, 1, True, False),          # boundary
    ],
)
def test_market_item_availability_properties(stock, buy, purchasable, stocked_when_available):
    """
    These two properties are what classify() is built on, so they are tested
    directly rather than only through it.
    """
    item = _item(stock, buy)
    assert item.is_purchasable is purchasable
    assert item.is_stocked_when_available is stocked_when_available
    # The two are mutually exclusive by construction.
    assert not (item.is_purchasable and item.is_stocked_when_available)


def test_buyable_states():
    assert MatchState.ENOUGH.is_buyable
    assert MatchState.PARTIAL.is_buyable
    assert not MatchState.EMPTY.is_buyable
    assert not MatchState.NONE.is_buyable
    assert not MatchState.UNKNOWN.is_buyable


# --------------------------------------------------------------------------
# AC-4: the Ryman fixture
# --------------------------------------------------------------------------

def test_ac4_ryman_enough_set_is_exactly_the_measured_four(requirements, journal_market):
    matches = compare(requirements, journal_market)
    enough = sorted(m.name for m in matches if m.state is MatchState.ENOUGH)
    assert enough == [
        "Biowaste",
        "Power Generators",
        "Survival equipment",
        "Water Purifiers",
    ]


def test_ac4_emergency_power_cells_is_none_at_zero_stock(requirements, journal_market):
    matches = {m.name: m for m in compare(requirements, journal_market)}
    epc = matches["Emergency power cells"]
    assert epc.state is MatchState.NONE
    assert epc.stock == 0
    assert epc.buyable_qty == 0


def test_ac4_land_enrichment_systems_is_empty_not_none(requirements, journal_market):
    """The fourth state: the station sells it, and is out right now."""
    matches = {m.name: m for m in compare(requirements, journal_market)}
    les = matches["Land enrichment systems"]
    assert les.state is MatchState.EMPTY
    assert les.unit_price == 3404
    assert les.stock == 0
    assert les.buyable_qty == 0
    assert les.should_mark is True    # worth telling the commander


def test_ac4_biowaste_quantities(requirements, journal_market):
    matches = {m.name: m for m in compare(requirements, journal_market)}
    bio = matches["Biowaste"]
    assert bio.state is MatchState.ENOUGH
    assert bio.stock == 70192
    assert bio.need == 229
    assert bio.unit_price == 54
    assert bio.buyable_qty == 229                 # capped at need, not stock
    assert bio.estimated_cost == 229 * 54


def test_ac4_every_outstanding_row_resolves(requirements):
    """All 28 sheet names matched the catalog; a regression here is a real bug."""
    unresolved = [r.name for r in requirements if not r.is_resolved]
    assert not unresolved


def test_ac4_no_unknown_states_at_ryman(requirements, journal_market):
    matches = compare(requirements, journal_market)
    assert not [m for m in matches if m.state is MatchState.UNKNOWN]


def test_ac4_full_state_table(requirements, journal_market):
    """The complete measured verdict, pinned."""
    got = {m.name: m.state for m in compare(requirements, journal_market)}
    assert got == {
        "Biowaste": MatchState.ENOUGH,
        "Emergency power cells": MatchState.NONE,
        "Evacuation shelter": MatchState.EMPTY,
        "Fruit and vegetables": MatchState.NONE,
        "Grain": MatchState.NONE,
        "Land enrichment systems": MatchState.EMPTY,
        "Micro Controllers": MatchState.NONE,
        "Pesticides": MatchState.EMPTY,
        "Power Generators": MatchState.ENOUGH,
        "Structural regulators": MatchState.EMPTY,
        "Survival equipment": MatchState.ENOUGH,
        "Water": MatchState.NONE,
        "Water Purifiers": MatchState.ENOUGH,
    }


def test_merged_market_recovers_capi_only_stock(catalog, journal_market, capi_market):
    """
    A requirement for Limpet is only satisfiable from the merged view.

    Note the name: EDCD's table calls this commodity 'Limpets' with the symbol
    'Drones'; the game calls it 'Limpet'. It resolves only because the alias
    bridge is loaded -- which is why the journal-only case below is NONE
    ("catalog knows it, this market does not list it") rather than UNKNOWN.
    """
    reqs = build_requirements([(99, "Limpet", 50)], catalog)
    assert reqs[0].is_resolved, "the 'Limpet' alias should resolve via the catalog"
    assert reqs[0].commodity.id == 128066403

    assert compare(reqs, journal_market)[0].state is MatchState.NONE
    merged = market_mod.merge(capi_market, journal_market)
    match = compare(reqs, merged)[0]
    assert match.state is MatchState.ENOUGH
    assert match.stock == 393086
    assert match.buyable_qty == 50


# --------------------------------------------------------------------------
# PARTIAL (synthetic -- Ryman had no natural example)
# --------------------------------------------------------------------------

def test_partial_stock_caps_buyable_at_stock(catalog):
    market = Market(1, "Test", "Sys", None, "journal",
                    (MarketItem(128049153, "Palladium", "Palladium", stock=100, buy_price=13),))
    reqs = build_requirements([(5, "Palladium", 229)], catalog)
    match = compare(reqs, market)[0]
    assert match.state is MatchState.PARTIAL
    assert match.buyable_qty == 100          # capped at stock, not need
    assert match.estimated_cost == 100 * 13
    assert match.should_mark is True


# --------------------------------------------------------------------------
# Satisfied and unresolvable rows
# --------------------------------------------------------------------------

def test_satisfied_rows_are_skipped_even_when_the_station_sells_them(catalog, journal_market):
    """A zero-need row must never be marked. Biowaste is in stock here."""
    reqs = build_requirements(SATISFIED + [(6, "Biowaste", 0)], catalog)
    assert compare(reqs, journal_market) == []


def test_negative_need_is_skipped(catalog, journal_market):
    """Supports the signed 'What's left' column: a surplus is not a purchase."""
    reqs = build_requirements([(6, "Biowaste", -40)], catalog)
    assert compare(reqs, journal_market) == []


def test_include_satisfied_opt_in(catalog, journal_market):
    reqs = build_requirements([(6, "Biowaste", 0)], catalog)
    matches = compare(reqs, journal_market, include_satisfied=True)
    assert len(matches) == 1
    assert matches[0].buyable_qty == 0


def test_unresolvable_name_is_unknown_not_none(catalog, journal_market):
    """Never silently treat an unrecognized commodity as unavailable."""
    reqs = build_requirements([(40, "Flurbulent Widgets", 10)], catalog)
    match = compare(reqs, journal_market)[0]
    assert match.state is MatchState.UNKNOWN
    assert match.should_mark is False


def test_unknown_to_catalog_but_present_in_market_still_matches(journal_market):
    """
    A name the catalog cannot resolve but the market lists by that exact name
    must still be compared -- the market is ground truth for its own station.
    """
    req = Requirement(row=7, name="Biowaste", need=229, commodity=None)
    match = compare_one(req, journal_market)
    assert match.state is MatchState.ENOUGH


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

def test_summary_counts_the_measured_fixture(requirements, journal_market):
    summary = ComparisonSummary(compare(requirements, journal_market))
    assert summary.enough == 4
    assert summary.partial == 0
    assert summary.empty == 4
    assert summary.none == 5
    assert summary.unknown == []
    assert len(summary.marked) == 8       # 4 ENOUGH + 0 PARTIAL + 4 EMPTY
    assert len(summary.buyable) == 4


def test_summary_total_cost(requirements, journal_market):
    summary = ComparisonSummary(compare(requirements, journal_market))
    expected = 229 * 54 + 9 * 2015 + 8 * 440 + 13 * 240
    assert summary.total_estimated_cost == expected


def test_summary_describe_mentions_unknowns(catalog, journal_market):
    reqs = build_requirements([(40, "Flurbulent Widgets", 10)], catalog)
    text = ComparisonSummary(compare(reqs, journal_market)).describe()
    assert "unrecognized" in text


# --------------------------------------------------------------------------
# Purity
# --------------------------------------------------------------------------

def test_comparison_performs_no_io(requirements, journal_market, monkeypatch):
    """
    The matcher is Phase 2's reusable core. If it ever reaches the network,
    scoring N candidate stations becomes N round trips.
    """
    def explode(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("matcher attempted network I/O")

    monkeypatch.setattr("socket.socket", explode)
    assert len(compare(requirements, journal_market)) == 13


def test_market_age(journal_market):
    assert journal_market.age_seconds > 0
    fresh = Market(1, "S", "Sys", datetime.now(timezone.utc) - timedelta(seconds=30),
                   "capi", ())
    assert 25 < fresh.age_seconds < 60
    assert Market(1, "S", "Sys", None, "capi", ()).age_seconds is None
