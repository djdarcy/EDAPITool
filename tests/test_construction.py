"""
Tests for reading colony construction sites from the journal.

These are guards: the module is new, so there is no prior behaviour to revert
and nothing here can be an anchor. What they fence is the set of things that
would be silently wrong rather than loudly broken -- a site keyed by the wrong
field, a delivered figure derived instead of read, an over-delivery producing
negative work, or a station name that does not match because the game prefixes
it and a person does not.

The fixture below is shaped from a real event measured 2026-09-14 against
`Planetary Construction Site: Badeaux Nutrition Centre` (MarketID 4312376579),
trimmed to four commodities. Its numbers are real: Aluminium really was
1677 required / 1148 provided / 3239 payment, and those three figures also
appear in the maintainer's spreadsheet, which is what made the whole feature
worth building.
"""

import pytest

from APITool.construction import (
    DEPOT_EVENT,
    DEPOT_STATION_TYPES,
    ConstructionResource,
    from_journal,
    sites_from_events,
    station_key,
)


def depot_event(market_id=4312376579, progress=0.606786, complete=False, **over):
    event = {
        "timestamp": "2026-09-14T20:53:36Z",
        "event": DEPOT_EVENT,
        "MarketID": market_id,
        "ConstructionProgress": progress,
        "ConstructionComplete": complete,
        "ConstructionFailed": False,
        "ResourcesRequired": [
            {"Name": "$aluminium_name;", "Name_Localised": "Aluminium",
             "RequiredAmount": 1677, "ProvidedAmount": 1148, "Payment": 3239},
            {"Name": "$biowaste_name;", "Name_Localised": "Biowaste",
             "RequiredAmount": 840, "ProvidedAmount": 0, "Payment": 667},
            {"Name": "$ceramiccomposites_name;", "Name_Localised": "Ceramic Composites",
             "RequiredAmount": 84, "ProvidedAmount": 84, "Payment": 724},
            {"Name": "$copper_name;", "Name_Localised": "Copper",
             "RequiredAmount": 63, "ProvidedAmount": 63, "Payment": 481},
        ],
    }
    event.update(over)
    return event


# ---------------------------------------------------------------------------
# Reading one site
# ---------------------------------------------------------------------------

def test_delivered_is_read_from_the_event_not_derived():
    """
    The contract: `provided` comes from ProvidedAmount, full stop.

    It can also be reached as required-minus-remaining, and an early design of
    this feature proposed exactly that. Deriving it would be a second way to
    compute a number the game already states, and the two can only ever
    disagree. This test exists so nobody reintroduces the subtraction.
    """
    site = from_journal(depot_event())
    aluminium = site.find("Aluminium")
    assert aluminium.provided == 1148
    assert aluminium.required == 1677
    assert aluminium.remaining == 529


def test_a_commodity_is_found_however_it_is_capitalised():
    site = from_journal(depot_event())
    for spelling in ("Ceramic Composites", "ceramic composites", "  CERAMIC COMPOSITES "):
        assert site.find(spelling) is not None, spelling


def test_the_symbol_is_stripped_to_something_matchable():
    site = from_journal(depot_event())
    assert site.find("Aluminium").symbol == "aluminium"


def test_payment_is_carried_because_the_sheet_does_not_have_it():
    site = from_journal(depot_event())
    assert site.find("Aluminium").payment == 3239


def test_totals_sum_the_resource_rows():
    site = from_journal(depot_event())
    assert site.total_required == 1677 + 840 + 84 + 63
    assert site.total_provided == 1148 + 0 + 84 + 63
    assert site.total_remaining == 529 + 840


def test_reported_progress_is_a_plain_tonnage_ratio():
    """
    Measured on the live site: 5168/8517 == 0.6068 == ConstructionProgress.

    `measured_progress` recomputes it so a caller can notice if the game ever
    stops using that definition, rather than assuming the relationship holds
    forever. If this ever fails, the game changed -- not this module.
    """
    site = from_journal(depot_event())
    assert site.measured_progress == pytest.approx(site.total_provided / site.total_required)


# ---------------------------------------------------------------------------
# The states a site can be in
# ---------------------------------------------------------------------------

def test_over_delivery_does_not_produce_negative_work():
    """A station that took more than it asked for owes nothing, not a debt."""
    event = depot_event()
    event["ResourcesRequired"][0]["ProvidedAmount"] = 2000      # over 1677
    site = from_journal(event)
    aluminium = site.find("Aluminium")
    assert aluminium.remaining == 0
    assert aluminium.satisfied
    assert aluminium.coverage == 1.0
    assert site.total_remaining == 840, "one over-delivery must not reduce another row's debt"


def test_a_completed_site_is_reported_complete():
    site = from_journal(depot_event(progress=1.0, complete=True))
    assert site.complete
    assert not site.failed


def test_a_site_with_no_resources_does_not_divide_by_zero():
    site = from_journal(depot_event(ResourcesRequired=[]))
    assert len(site) == 0
    assert site.total_required == 0
    assert site.measured_progress == 0.0


def test_outstanding_lists_only_what_is_owed_worst_first():
    site = from_journal(depot_event())
    outstanding = site.outstanding
    assert [r.name for r in outstanding] == ["Biowaste", "Aluminium"]
    assert all(r.remaining > 0 for r in outstanding)


def test_a_commodity_with_no_localised_name_still_appears():
    """
    An unrecognised commodity must not vanish from a total the sheet depends on.

    Falling back to the symbol keeps the row visible and wrong-looking, which
    is recoverable; dropping it makes the totals quietly disagree with the
    game, which is not.
    """
    event = depot_event()
    event["ResourcesRequired"].append(
        {"Name": "$somethingnew_name;", "RequiredAmount": 10, "ProvidedAmount": 2}
    )
    site = from_journal(event)
    assert len(site) == 5
    assert site.find("somethingnew") is not None
    assert site.total_required == 1677 + 840 + 84 + 63 + 10


# ---------------------------------------------------------------------------
# Several sites at once
# ---------------------------------------------------------------------------

def test_sites_are_keyed_by_market_id():
    events = [depot_event(market_id=111), depot_event(market_id=222)]
    sites = sites_from_events(events)
    assert set(sites) == {111, 222}


def test_the_latest_event_wins_because_it_carries_whole_state():
    """
    The depot event is state, not a delta, so the newest one replaces the old.

    A commander bouncing between two builds emits interleaved events; each site
    must end with its own most recent snapshot rather than a merge.
    """
    stale = depot_event(market_id=111)
    fresh = depot_event(market_id=111)
    fresh["ResourcesRequired"][0]["ProvidedAmount"] = 1677
    sites = sites_from_events([stale, fresh])
    assert sites[111].find("Aluminium").provided == 1677
    assert len(sites) == 1


def test_other_events_are_ignored():
    sites = sites_from_events([
        {"event": "Docked", "MarketID": 999},
        depot_event(market_id=111),
        {"event": "FSDJump"},
        "not a mapping at all",
    ])
    assert set(sites) == {111}


# ---------------------------------------------------------------------------
# Matching a site a person declared by name
# ---------------------------------------------------------------------------

def test_station_key_survives_the_games_prefix():
    """
    The reason this function exists.

    A person writes what they can see -- "Badeaux Nutrition Centre". The
    journal says "Planetary Construction Site: Badeaux Nutrition Centre".
    Exact comparison fails, and the feature that depends on it would silently
    never match.
    """
    typed = station_key("Badeaux Nutrition Centre")
    assert typed
    for as_the_game_writes_it in (
        "Planetary Construction Site: Badeaux Nutrition Centre",
        "Orbital Construction Site: Badeaux Nutrition Centre",
        "Construction Site: Badeaux Nutrition Centre",
        "  badeaux nutrition centre  ",
    ):
        assert station_key(as_the_game_writes_it) == typed, as_the_game_writes_it


def test_station_key_does_not_swallow_a_real_name():
    """Stripping must not turn two different stations into one key."""
    assert station_key("Ryman Enterprise") != station_key("Willis Dock")
    assert station_key("") == ""
    assert station_key(None) == ""


def test_both_depot_station_types_are_recognised():
    """
    Both were observed live, in the SAME system -- so a system alone cannot
    identify a site, and a name check alone would miss the type entirely.
    """
    assert "PlanetaryConstructionDepot" in DEPOT_STATION_TYPES
    assert "SpaceConstructionDepot" in DEPOT_STATION_TYPES


def test_resource_coverage_is_clamped():
    assert ConstructionResource("x", "X", required=0, provided=0).coverage == 1.0
    assert ConstructionResource("x", "X", required=100, provided=250).coverage == 1.0
    assert ConstructionResource("x", "X", required=100, provided=25).coverage == 0.25


# ---------------------------------------------------------------------------
# Telling a live build from an abandoned one
# ---------------------------------------------------------------------------

def _aged(days, **over):
    """A depot event stamped `days` in the past."""
    from datetime import datetime, timedelta, timezone

    when = datetime.now(timezone.utc) - timedelta(days=days)
    return depot_event(timestamp=when.isoformat().replace("+00:00", "Z"), **over)


def test_the_game_never_marks_a_lapsed_build_failed():
    """
    The measurement this whole feature's staleness handling rests on.

    A site left at 15.2% and untouched for 303 days still reported
    `ConstructionFailed: false` across a 621-file journal. The flag exists and
    the game does not set it, so an unset flag cannot be read as "still going"
    -- which is why `status()` infers from elapsed time and says so.
    """
    site = from_journal(_aged(303, progress=0.152))
    assert site.failed is False
    assert site.complete is False
    assert site.status() == "stale", "time is the only signal there is"


def test_an_active_build_is_not_called_stale():
    site = from_journal(_aged(0))
    assert site.status() == "active"
    assert site.age_days() == 0


def test_completion_outranks_staleness():
    """
    A build finished last year is complete, not stale.

    Three of the maintainer's six sites are complete and ~300 days old; calling
    those stale would bury a real outcome under an inference about time.
    """
    site = from_journal(_aged(301, progress=1.0, complete=True))
    assert site.status() == "complete"


def test_an_explicit_failure_outranks_everything():
    site = from_journal(_aged(0, ConstructionFailed=True))
    assert site.status() == "failed"


def test_the_staleness_threshold_is_caller_tunable():
    site = from_journal(_aged(90))
    assert site.status(stale_after_days=60) == "stale"
    assert site.status(stale_after_days=365) == "active"


def test_a_site_with_no_timestamp_is_not_guessed_at():
    """No stamp means no basis for an inference, so it stays active."""
    event = depot_event()
    event.pop("timestamp")
    site = from_journal(event)
    assert site.age_days() is None
    assert site.status() == "active"
