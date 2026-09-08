"""
Tests for the canonical commodity catalog (build step B-1, acceptance check AC-1).

The load-bearing property is the one the design named: every commodity whose
FDev symbol does NOT normalize to its display name must still round-trip
through all three lookup paths. Those are exactly the commodities where naive
string munging silently fails.
"""

import csv
import json
import os
from pathlib import Path

import pytest

from APITool.catalog import (
    Commodity,
    CommodityCatalog,
    DEFAULT_CATALOG_PATH,
    load_catalog,
    normalize,
    strip_symbol,
)

JOURNAL_MARKET = (
    Path(os.environ.get("USERPROFILE", Path.home()))
    / "Saved Games"
    / "Frontier Developments"
    / "Elite Dangerous"
    / "Market.json"
)
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


# --------------------------------------------------------------------------
# normalize / strip_symbol
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Land Enrichment Systems", "landenrichmentsystems"),
        ("land enrichment systems", "landenrichmentsystems"),
        ("Agri-Medicines", "agrimedicines"),
        ("H.E. Suits", "hesuits"),
        ("Micro-weave Cooling Hoses", "microweavecoolinghoses"),
        ("CD-75 Kitten Brand Coffee", "cd75kittenbrandcoffee"),
        ("  Steel  ", "steel"),
        ("", ""),
    ],
)
def test_normalize_folds_punctuation_and_case(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$terrainenrichmentsystems_name;", "terrainenrichmentsystems"),
        ("$platinum_name;", "platinum"),
        ("TerrainEnrichmentSystems", "TerrainEnrichmentSystems"),
        ("Platinum", "Platinum"),
        ("$usscargorareartwork_name;", "usscargorareartwork"),
    ],
)
def test_strip_symbol_handles_journal_and_capi_forms(raw, expected):
    assert strip_symbol(raw) == expected


def test_strip_symbol_does_not_eat_a_name_ending_in_name():
    # "_name" is a suffix of the localization key, not part of the symbol.
    # A bare symbol that merely ends in the letters "name" must survive.
    assert strip_symbol("Codename") == "Codename"


# --------------------------------------------------------------------------
# The bundled table
# --------------------------------------------------------------------------

def test_bundled_catalog_exists_and_loads(catalog):
    assert DEFAULT_CATALOG_PATH.exists()
    assert len(catalog) > 400, "expected the full EDCD union (~412 commodities)"


def test_catalog_ids_are_unique():
    with open(DEFAULT_CATALOG_PATH, encoding="utf-8", newline="") as handle:
        ids = [row["id"] for row in csv.DictReader(handle)]
    assert len(ids) == len(set(ids))


def test_catalog_loads_offline(tmp_path, monkeypatch):
    """Runtime must never reach the network -- a GitHub outage cannot break a docking."""
    import APITool.catalog as catalog_module

    def explode(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("catalog attempted a network call")

    monkeypatch.setattr("socket.socket", explode)
    assert len(CommodityCatalog.load()) > 400
    assert catalog_module.DEFAULT_CATALOG_PATH.is_file()


# --------------------------------------------------------------------------
# AC-1: the divergent symbols round-trip
# --------------------------------------------------------------------------

def divergent(catalog):
    """Commodities whose symbol does not normalize to their display name."""
    return [c for c in catalog if normalize(c.symbol) != normalize(c.name)]


def test_there_really_are_divergent_symbols(catalog):
    # Guards the test below from silently becoming vacuous.
    assert len(divergent(catalog)) >= 90


def test_ac1_every_divergent_symbol_round_trips(catalog):
    """
    AC-1. For every commodity whose symbol and display name disagree, all three
    lookup paths must return the same entry. This is the population where naive
    lowercase+strip matching fails.
    """
    failures = []
    for item in divergent(catalog):
        if catalog.by_id(item.id) is not item:
            failures.append((item.name, "by_id"))
        if catalog.by_symbol(item.symbol) is not item:
            failures.append((item.name, "by_symbol"))
        if catalog.by_name(item.name) is not item:
            failures.append((item.name, "by_name"))
    assert not failures, f"{len(failures)} round-trip failures: {failures[:10]}"


def test_ac1_land_enrichment_systems_resolves_all_three_ways(catalog):
    """The design's named example, in all three directions."""
    expected_id, expected_symbol = 128049232, "TerrainEnrichmentSystems"
    expected_name = "Land Enrichment Systems"

    by_id = catalog.by_id(expected_id)
    assert by_id is not None
    assert by_id.symbol == expected_symbol
    assert by_id.name == expected_name

    assert catalog.by_symbol("TerrainEnrichmentSystems") is by_id
    assert catalog.by_symbol("$terrainenrichmentsystems_name;") is by_id
    assert catalog.by_name("Land Enrichment Systems") is by_id
    # The spreadsheet writes it lowercase; that must resolve too.
    assert catalog.by_name("Land enrichment systems") is by_id


@pytest.mark.parametrize(
    "commodity_id,symbol,name",
    [
        (128049208, "AgriculturalMedicines", "Agri-Medicines"),
        (128049220, "HeliostaticFurnaces", "Microbial Furnaces"),
        (128049223, "MarineSupplies", "Marine Equipment"),
        (128682048, "SurvivalEquipment", "Survival Equipment"),
        (128673873, "MicroControllers", "Micro Controllers"),
        (128672314, "EvacuationShelter", "Evacuation Shelter"),
        (128673861, "EmergencyPowerCells", "Emergency Power Cells"),
    ],
)
def test_known_triples_resolve(catalog, commodity_id, symbol, name):
    found = catalog.by_id(commodity_id)
    assert found is not None, f"id {commodity_id} missing from catalog"
    assert found.symbol == symbol
    assert found.name == name
    assert catalog.by_symbol(symbol) is found
    assert catalog.by_name(name) is found


# --------------------------------------------------------------------------
# resolve() precedence
# --------------------------------------------------------------------------

def test_resolve_prefers_id_over_a_conflicting_but_valid_name(catalog):
    """
    id wins over display name. Both identifiers here resolve, to DIFFERENT
    commodities -- that is what makes this test able to detect a precedence
    bug. (A name that simply fails to resolve would pass under any ordering.)
    """
    found = catalog.resolve(commodity_id=128049232, name="Steel")
    assert found is not None
    assert found.name == "Land Enrichment Systems"
    assert found.id == 128049232


def test_resolve_prefers_symbol_over_a_conflicting_but_valid_name(catalog):
    """symbol wins over display name, both resolving to different commodities."""
    found = catalog.resolve(symbol="TerrainEnrichmentSystems", name="Steel")
    assert found is not None
    assert found.name == "Land Enrichment Systems"


def test_resolve_prefers_id_over_a_conflicting_but_valid_symbol(catalog):
    """id wins over symbol, both resolving to different commodities."""
    found = catalog.resolve(commodity_id=128049232, symbol="Steel")
    assert found is not None
    assert found.name == "Land Enrichment Systems"


def test_resolve_ignores_a_wrong_display_name_when_id_is_given(catalog):
    found = catalog.resolve(commodity_id=128049232, name="Totally Wrong Name")
    assert found is not None
    assert found.name == "Land Enrichment Systems"


def test_resolve_falls_through_to_symbol_then_name(catalog):
    assert catalog.resolve(symbol="$terrainenrichmentsystems_name;").id == 128049232
    assert catalog.resolve(name="Land Enrichment Systems").id == 128049232
    # An unusable id must fall through rather than abort the chain.
    assert catalog.resolve(commodity_id=None, name="Steel") is not None
    assert catalog.resolve(commodity_id="not-an-int", name="Steel") is not None


def test_resolve_returns_none_for_unknown():
    cat = CommodityCatalog([Commodity(1, "Aaa", "Cat", "Aaa")])
    assert cat.resolve(name="Nonexistent Commodity") is None
    assert cat.resolve(commodity_id=999) is None
    assert cat.resolve() is None


def test_unknown_is_distinguishable_from_absent(catalog):
    """
    The reason the catalog exists: a name we cannot resolve at all is a
    different condition from a commodity that is simply not stocked here.
    """
    assert catalog.by_name("Biowaste") is not None      # known commodity
    assert catalog.by_name("Flurbulent Widgets") is None  # unknown name


def test_missing_catalog_file_raises_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="update-commodity-catalog"):
        CommodityCatalog.load(tmp_path / "nope.csv")


def test_empty_catalog_file_raises(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("id,symbol,category,name,rare\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable rows"):
        CommodityCatalog.load(path)


def test_malformed_rows_are_skipped_not_fatal(tmp_path):
    path = tmp_path / "partial.csv"
    path.write_text(
        "id,symbol,category,name,rare\n"
        "not-a-number,Bad,Cat,Bad Row,0\n"
        "128049152,Platinum,Metals,Platinum,0\n",
        encoding="utf-8",
    )
    cat = CommodityCatalog.load(path)
    assert len(cat) == 1
    assert cat.by_name("Platinum").id == 128049152


# --------------------------------------------------------------------------
# Coverage against real market data
# --------------------------------------------------------------------------

def _load_market_items():
    fixture = FIXTURES / "market_ryman_journal.json"
    if fixture.exists():
        return json.loads(fixture.read_text(encoding="utf-8"))["Items"]
    if JOURNAL_MARKET.exists():
        return json.loads(JOURNAL_MARKET.read_text(encoding="utf-8"))["Items"]
    return None


def _load_all_display_names():
    """
    Every display name the GAME used, across both sources.

    Both are needed: the journal's 366 items do not include Limpet, and CAPI's
    92 do -- and Limpet is one of the two names where EDCD and the game
    disagree. Testing only the journal would have missed it.
    """
    names = []
    items = _load_market_items()
    if items:
        names += [i["Name_Localised"] for i in items if i.get("Name_Localised")]

    capi = FIXTURES / "market_ryman_capi.json"
    if capi.exists():
        data = json.loads(capi.read_text(encoding="utf-8"))
        names += [c["locName"] for c in data.get("commodities", []) if c.get("locName")]
    return names or None


def test_catalog_covers_every_item_in_a_real_market(catalog):
    """
    Measured ground truth: the EDCD union covered 366 of 366 journal items.
    A regression here means the bundled table went stale.
    """
    items = _load_market_items()
    if items is None:
        pytest.skip("no market fixture and no local journal Market.json")

    missing = [
        (i["id"], i.get("Name"), i.get("Name_Localised"))
        for i in items
        if catalog.by_id(i["id"]) is None
    ]
    assert not missing, f"{len(missing)} market items absent from catalog: {missing[:10]}"


def test_every_market_display_name_is_resolvable(catalog):
    """
    The property that actually matters: whatever the GAME calls a commodity
    must resolve, because that is the spelling a commander copies into their
    spreadsheet.

    Note this is deliberately not "the catalog's name equals the game's name".
    Those genuinely differ -- EDCD says "Low Temperature Diamonds", the game
    says "Low Temp. Diamonds" (1 of 366 at Ryman Enterprise, 2026-09-08). The
    alias bridge is what closes that gap, and this test is what proves it.
    """
    names = _load_all_display_names()
    if names is None:
        pytest.skip("no market fixture and no local journal Market.json")

    unresolvable = sorted({n for n in names if catalog.by_name(n) is None})
    assert not unresolvable, (
        f"{len(unresolvable)} game display names do not resolve; "
        f"add them to APITool/data/name_aliases.json: {unresolvable[:10]}"
    )


def test_bundled_aliases_cover_the_known_drift(catalog):
    """
    The two measured EDCD-vs-game divergences, pinned so they cannot regress.

    Both were found empirically, not predicted -- and the second only showed
    up in the CAPI fixture, which is why the resolvability test above reads
    both sources.
    """
    low_temp = catalog.by_id(128673848)
    assert low_temp is not None
    assert low_temp.name == "Low Temperature Diamonds"        # EDCD's spelling
    assert catalog.by_name("Low Temp. Diamonds") is low_temp  # the game's spelling

    limpet = catalog.by_id(128066403)
    assert limpet is not None
    assert limpet.symbol == "Drones"      # EDCD's symbol is nothing like the name
    assert limpet.name == "Limpets"       # EDCD's plural
    assert catalog.by_name("Limpet") is limpet   # the game's singular


# --------------------------------------------------------------------------
# Alias bridge
# --------------------------------------------------------------------------

def _tiny_catalog():
    return CommodityCatalog(
        [
            Commodity(1, "Steel", "Metals", "Steel"),
            Commodity(2, "TerrainEnrichmentSystems", "Technology", "Land Enrichment Systems"),
        ]
    )


def test_add_alias_makes_a_variant_spelling_resolvable():
    cat = _tiny_catalog()
    assert cat.by_name("Land Enrich. Systems") is None
    assert cat.add_alias("Land Enrich. Systems", cat.by_id(2)) is True
    assert cat.by_name("Land Enrich. Systems") is cat.by_id(2)


def test_alias_never_displaces_a_real_commodity_name():
    """A bad alias must not shadow a genuine commodity."""
    cat = _tiny_catalog()
    assert cat.add_alias("Steel", cat.by_id(2)) is False
    assert cat.by_name("Steel") is cat.by_id(1)


def test_learn_from_market_registers_journal_and_capi_shapes():
    cat = _tiny_catalog()
    learned = cat.learn_from_market(
        [
            {"id": 2, "Name_Localised": "Land Enrich. Systems"},   # journal shape
            {"id": 1, "locName": "Steel Alloy"},                   # CAPI shape
            {"id": 999, "Name_Localised": "Unknown Thing"},        # unknown id, ignored
        ]
    )
    assert learned == 2
    assert cat.by_name("Land Enrich. Systems") is cat.by_id(2)
    assert cat.by_name("Steel Alloy") is cat.by_id(1)
    assert cat.by_name("Unknown Thing") is None


def test_load_aliases_accepts_id_symbol_and_name_targets(tmp_path):
    cat = _tiny_catalog()
    path = tmp_path / "aliases.json"
    path.write_text(
        json.dumps(
            {
                "_comment": "ignored",
                "By Id": 2,
                "By Symbol": "TerrainEnrichmentSystems",
                "By Name": "Land Enrichment Systems",
                "Unresolvable": "No Such Commodity",
            }
        ),
        encoding="utf-8",
    )
    assert cat.load_aliases(path) == 3
    for alias in ("By Id", "By Symbol", "By Name"):
        assert cat.by_name(alias) is cat.by_id(2)
    assert cat.by_name("Unresolvable") is None


def test_load_aliases_tolerates_a_broken_file(tmp_path):
    """A typo in a hand-edited alias file must not stop a docking."""
    cat = _tiny_catalog()
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert cat.load_aliases(bad) == 0
    assert cat.load_aliases(tmp_path / "absent.json") == 0
    wrong_type = tmp_path / "list.json"
    wrong_type.write_text("[1, 2, 3]", encoding="utf-8")
    assert cat.load_aliases(wrong_type) == 0
    # catalog still works
    assert cat.by_name("Steel").id == 1
