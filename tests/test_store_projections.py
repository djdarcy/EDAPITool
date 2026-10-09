"""
The journal-derived tables (the store design of 2026-10-09, unit 3; #22's
criteria 11, 12 and 19, each named in its test).

The fixture journal is ingested through the real path -- ``store ingest``
-- so every row here was projected as the ingest kept the line, the way
the daemon's watcher will project it live.
"""

import json

import pytest

from test_store_ingest import FIRST, header, line, loadgame, write

from APITool.store import open_store, store_path, verify
from APITool.store import ingest as ingest_mod

SHINRARTA = 3932277478106
SITE = 3957057282


def fsdjump(n, name="Shinrarta Dezhra", address=SHINRARTA, factions=(), conflicts=(),
            controlling=None, pos=(55.71875, 17.59375, 27.15625)):
    body = dict(StarSystem=name, SystemAddress=address, StarPos=list(pos),
                Factions=[dict(f) for f in factions], Conflicts=[dict(c) for c in conflicts])
    if controlling:
        body["SystemFaction"] = {"Name": controlling}
    return line("FSDJump", n, **body)


def docked(n, name, market_id=128666762, address=SHINRARTA, kind="Orbis"):
    return line("Docked", n, StationName=name, StationType=kind, StarSystem="Shinrarta Dezhra",
                SystemAddress=address, MarketID=market_id)


def depot(n, resources, site=SITE, progress=0.5, complete=False, failed=False):
    return line("ColonisationConstructionDepot", n, MarketID=site, ConstructionProgress=progress,
                ConstructionComplete=complete, ConstructionFailed=failed,
                ResourcesRequired=[{"Name": f"${sym}_name;", "Name_Localised": sym.title(),
                                    "RequiredAmount": req, "ProvidedAmount": prov, "Payment": pay}
                                   for sym, req, prov, pay in resources])


def contribution(n, contributions, site=SITE):
    return line("ColonisationContribution", n, MarketID=site,
                Contributions=[{"Name": f"${sym}_name;", "Name_Localised": sym.title(), "Amount": amt}
                               for sym, amt in contributions])


def buy(n, kind="silver", count=10, price=100, market_id=128666762):
    return line("MarketBuy", n, MarketID=market_id, Type=kind, Count=count, BuyPrice=price,
                TotalCost=count * price)


def sell(n, kind="silver", count=10, price=120, market_id=128666762):
    return line("MarketSell", n, MarketID=market_id, Type=kind, Count=count, SellPrice=price,
                TotalSale=count * price, AvgPricePaid=100)


def transfer(n, transfers):
    return line("CargoTransfer", n, Transfers=[{"Type": t, "Count": c, "Direction": d}
                                               for t, c, d in transfers])


FACTIONS = (
    {"Name": "Future of Arro Naga", "FactionState": "Boom", "Government": "Democracy",
     "Influence": 0.316683, "Allegiance": "Federation", "Happiness": "$Faction_HappinessBand1;",
     "MyReputation": 1.2835, "ActiveStates": [{"State": "Boom"}, {"State": "CivilLiberty"}],
     "PendingStates": [{"State": "Expansion", "Trend": 0}]},
    {"Name": "The Dark Wheel", "FactionState": "Expansion", "Government": "Democracy",
     "Influence": 0.305694, "Allegiance": "Independent", "Happiness": "$Faction_HappinessBand2;",
     "MyReputation": 0.0},
)
CONFLICT = {"WarType": "election", "Status": "active",
            "Faction1": {"Name": "Future of Arro Naga", "Stake": "Jameson Memorial", "WonDays": 2},
            "Faction2": {"Name": "The Dark Wheel", "Stake": "", "WonDays": 1}}


def ingest(tmp_path, *lines):
    directory = tmp_path / "journal"
    directory.mkdir(exist_ok=True)
    write(directory, FIRST, header(), loadgame(), *lines)
    result = ingest_mod.ingest_dir(directory, machine="box")
    assert result.read == 1
    return directory


def rows(sql, *params):
    conn = open_store(store_path())
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# -- identity -------------------------------------------------------------------

def test_a_renamed_system_is_one_identity_with_its_names_in_order(tmp_path):
    """#22 criterion 12: BGS observations are keyed on the system address."""
    ingest(tmp_path,
           fsdjump(2, name="Old Name", factions=FACTIONS),
           fsdjump(3, name="New Name", factions=FACTIONS))

    assert rows("SELECT system_address, name, name_history, first_seen, last_seen, x FROM system") == [
        (SHINRARTA, "New Name", '["Old Name", "New Name"]',
         "2026-10-09T02:00:00Z", "2026-10-09T03:00:00Z", 55.71875)]
    presence = rows("SELECT DISTINCT system_address FROM faction_presence")
    assert presence == [(SHINRARTA,)]
    assert rows("SELECT COUNT(*) FROM faction_presence")[0][0] == 4, "two readings of two factions"


def test_an_older_reading_arriving_later_does_not_take_the_name_back(tmp_path):
    ingest(tmp_path, fsdjump(5, name="Newest"), fsdjump(4, name="Older"))

    assert rows("SELECT name, name_history FROM system") == [("Newest", '["Newest", "Older"]')]


def test_a_station_keeps_its_names_in_order_under_one_market_id(tmp_path):
    ingest(tmp_path, docked(2, "Site Alpha", market_id=SITE, kind="PlanetaryConstructionDepot"),
           docked(3, "Alpha Terminal", market_id=SITE, kind="CraterOutpost"))

    assert rows("SELECT market_id, system_address, name, type, name_history FROM station") == [
        (SITE, SHINRARTA, "Alpha Terminal", "CraterOutpost", '["Site Alpha", "Alpha Terminal"]')]


# -- the BGS ----------------------------------------------------------------------------

def test_faction_rows_carry_influence_states_and_the_controlling_flag(tmp_path):
    ingest(tmp_path, fsdjump(2, factions=FACTIONS, conflicts=(CONFLICT,),
                             controlling="Future of Arro Naga"))

    got = rows("SELECT faction, influence, state, government, allegiance, happiness, "
               "my_reputation, controlling, active, pending, recovering "
               "FROM faction_presence ORDER BY faction")
    assert got == [
        ("Future of Arro Naga", 0.316683, "Boom", "Democracy", "Federation",
         "$Faction_HappinessBand1;", 1.2835, 1,
         json.dumps([{"State": "Boom"}, {"State": "CivilLiberty"}]),
         json.dumps([{"State": "Expansion", "Trend": 0}]), None),
        ("The Dark Wheel", 0.305694, "Expansion", "Democracy", "Independent",
         "$Faction_HappinessBand2;", 0.0, 0, None, None, None),
    ]
    assert rows("SELECT war_type, status, faction1, faction1_stake, faction1_won_days, "
                "faction2, faction2_won_days FROM conflict") == [
        ("election", "active", "Future of Arro Naga", "Jameson Memorial", 2, "The Dark Wheel", 1)]


# -- construction -------------------------------------------------------------------------

def test_construction_readings_are_one_row_per_resource_with_the_event_s_progress(tmp_path):
    ingest(tmp_path, depot(2, [("steel", 100, 40, 500), ("titanium", 50, 10, 900)],
                           progress=0.25, complete=False))

    assert rows("SELECT market_id, symbol, name_localised, required, provided, payment, progress, "
                "complete, failed FROM construction_reading ORDER BY symbol") == [
        (SITE, "steel", "Steel", 100, 40, 500, 0.25, 0, 0),
        (SITE, "titanium", "Titanium", 50, 10, 900, 0.25, 0, 0)]


def test_the_construction_delta_is_the_provided_range_minus_the_commander_s_own(tmp_path):
    """#22 criterion 19, in miniature: delivered 250 of which the commander handed in 50."""
    ingest(tmp_path,
           depot(2, [("steel", 1000, 60, 500), ("titanium", 500, 40, 900)]),
           contribution(3, [("steel", 50)]),
           depot(4, [("steel", 1000, 300, 500), ("titanium", 500, 50, 900)], progress=0.35))

    assert rows("SELECT market_id, readings, provided_low, provided_high, delivered, own, "
                "by_others, contributions, progress, first_seen, last_seen "
                "FROM construction_delta") == [
        (SITE, 2, 100, 350, 250, 50, 200, 1, 0.35, "2026-10-09T02:00:00Z", "2026-10-09T04:00:00Z")]
    assert rows("SELECT symbol, amount FROM construction_contribution") == [("steel", 50)]


def test_a_second_site_has_its_own_delta_row(tmp_path):
    ingest(tmp_path, depot(2, [("steel", 10, 1, 1)]), depot(3, [("steel", 10, 2, 1)], site=4312376579),
           contribution(4, [("steel", 1)], site=4312376579))

    assert rows("SELECT market_id, delivered, own, by_others FROM construction_delta "
                "ORDER BY market_id") == [(SITE, 0, 0, 0), (4312376579, 0, 1, -1)]


# -- trades -----------------------------------------------------------------------------------

def test_each_transaction_resolves_to_a_catalog_symbol_or_is_flagged_unknown(tmp_path):
    """#22 criterion 11."""
    ingest(tmp_path, buy(2, "silver", 10, 100), sell(3, "frobnicator", 3, 7),
           transfer(4, [("gold", 5, "toship"), ("frobnicator", 1, "tocarrier")]))

    got = rows("SELECT direction, symbol, name, commodity_id IS NOT NULL, count, unit_price, total, "
               "unknown, market_id FROM trade ORDER BY observed_at, direction")
    assert got[0] == ("buy", "silver", "Silver", 1, 10, 100, 1000, 0, 128666762)
    assert got[1] == ("sell", "frobnicator", None, 0, 3, 7, 21, 1, 128666762)
    assert got[2] == ("transfer:tocarrier", "frobnicator", None, 0, 1, None, None, 1, None)
    assert got[3] == ("transfer:toship", "gold", "Gold", 1, 5, None, None, 0, None)


# -- verify knows the new tables ------------------------------------------------------------

def test_verify_is_clean_after_an_ingest_and_names_an_orphan_in_a_derived_table(tmp_path):
    ingest(tmp_path, buy(2), fsdjump(3, factions=FACTIONS))
    conn = open_store(store_path())
    try:
        assert verify(conn) == []
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("UPDATE trade SET obs_id = 999")
        conn.commit()
        problems = verify(conn)
    finally:
        conn.close()
    assert problems == ["1 row(s) in trade point at a observations row that is gone"]


@pytest.mark.parametrize("table", ["system", "station", "faction_presence", "conflict",
                                   "construction_reading", "construction_contribution",
                                   "construction_delta", "trade"])
def test_every_journal_table_is_registered_derived(table):
    from APITool.store import registry
    assert table in {t.name for t in registry.derived()}
