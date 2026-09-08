"""
Tests for journal location state and the market freshness gate
(build step B-5, acceptance check AC-5).

AC-5 is the one that prevents the worst failure mode in the whole tool:
Market.json is written only when the commander opens the commodity screen, so
it routinely describes a station already left. Measured 2026-09-08 at Ryman
Enterprise -- Docked fired at 02:14:10Z, Market.json was written at 03:13:00Z.
Comparing a shopping list against the previous station's prices produces
markers that look plausible and are wrong.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from APITool.journal import (
    JournalReader,
    JournalWatcher,
    LocationState,
    NOT_DOCKED,
    REFRESH_EVENTS,
    default_journal_dir,
    iter_events,
    journal_sort_key,
)

RYMAN = 3226578176
DIETERLE = 4323280387


def ev(name, **kw):
    payload = {"timestamp": "2026-09-08T02:00:00Z", "event": name}
    payload.update(kw)
    return payload


def docked_at(station="Ryman Enterprise", system="Lhou Mans", market_id=RYMAN, services=None):
    return ev(
        "Docked",
        StationName=station,
        StarSystem=system,
        MarketID=market_id,
        StationType="Coriolis",
        StationServices=services if services is not None else ["dock", "commodities", "refuel"],
    )


def write_journal(directory: Path, name: str, events: list[dict]) -> Path:
    path = directory / name
    path.write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )
    return path


# --------------------------------------------------------------------------
# LocationState folding
# --------------------------------------------------------------------------

def test_docked_sets_station_and_market():
    state = LocationState()
    assert state.apply(docked_at()) is True
    assert state.docked is True
    assert state.station == "Ryman Enterprise"
    assert state.system == "Lhou Mans"
    assert state.market_id == RYMAN
    assert state.has_commodity_market is True
    assert state.station_display == "Ryman Enterprise"


def test_undocked_clears_station_but_keeps_system():
    state = LocationState()
    state.apply(docked_at())
    assert state.apply(ev("Undocked", StationName="Ryman Enterprise", MarketID=RYMAN)) is True
    assert state.docked is False
    assert state.station is None
    assert state.market_id is None
    assert state.system == "Lhou Mans"          # still in the system
    assert state.station_display == NOT_DOCKED


def test_fsdjump_updates_system_and_undocks():
    state = LocationState()
    state.apply(docked_at())
    state.apply(ev("FSDJump", StarSystem="Juipedun"))
    assert state.system == "Juipedun"
    assert state.docked is False
    assert state.market_id is None


def test_carrier_jump_updates_system():
    state = LocationState()
    state.apply(ev("CarrierJump", StarSystem="Colonia"))
    assert state.system == "Colonia"


def test_location_event_while_docked():
    state = LocationState()
    state.apply(
        ev("Location", StarSystem="Lhou Mans", Docked=True,
           StationName="Ryman Enterprise", MarketID=RYMAN,
           StationServices=["dock", "commodities"])
    )
    assert state.docked is True
    assert state.market_id == RYMAN


def test_location_event_while_not_docked():
    state = LocationState()
    state.apply(docked_at())
    state.apply(ev("Location", StarSystem="Juipedun", Docked=False))
    assert state.docked is False
    assert state.station is None
    assert state.system == "Juipedun"


def test_station_without_commodity_market_is_flagged():
    state = LocationState()
    state.apply(docked_at(services=["dock", "refuel", "repair"]))
    assert state.docked is True
    assert state.has_commodity_market is False


def test_loadgame_captures_commander_without_moving():
    state = LocationState()
    assert state.apply(ev("LoadGame", Commander="Xtraeme")) is False
    assert state.commander == "Xtraeme"


def test_irrelevant_events_are_ignored():
    state = LocationState()
    state.apply(docked_at())
    assert state.apply(ev("FSSSignalDiscovered")) is False
    assert state.apply(ev("Music", MusicTrack="DockingComputer")) is False
    assert state.station == "Ryman Enterprise"


def test_apply_reports_no_change_for_a_repeated_dock():
    state = LocationState()
    state.apply(docked_at())
    assert state.apply(docked_at()) is False


def test_timestamp_is_parsed_and_utc():
    state = LocationState()
    state.apply(docked_at())
    assert state.timestamp == datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)
    assert state.timestamp.tzinfo is not None


# --------------------------------------------------------------------------
# AC-5: the market freshness gate
# --------------------------------------------------------------------------

def test_ac5_market_is_current_when_ids_agree():
    state = LocationState()
    state.apply(docked_at())
    assert state.market_is_current(RYMAN) is True
    assert state.market_is_current(str(RYMAN)) is True     # journal gives ints, be lenient


def test_ac5_stale_market_from_the_previous_station_is_rejected():
    """
    The measured scenario: undocked from Dieterle Penal Colony at 02:08:44Z,
    docked at Ryman at 02:14:10Z. A Market.json still holding Dieterle's
    MarketID must not be compared against.
    """
    state = LocationState()
    state.apply(docked_at(station="Dieterle Penal Colony", market_id=DIETERLE))
    state.apply(ev("Undocked", StationName="Dieterle Penal Colony", MarketID=DIETERLE))
    state.apply(ev("FSDJump", StarSystem="Lhou Mans"))
    state.apply(docked_at())

    assert state.market_id == RYMAN
    assert state.market_is_current(DIETERLE) is False    # the stale file
    assert state.market_is_current(RYMAN) is True


def test_ac5_not_docked_means_no_market_is_current():
    state = LocationState()
    state.apply(docked_at())
    state.apply(ev("Undocked", StationName="Ryman Enterprise", MarketID=RYMAN))
    assert state.market_is_current(RYMAN) is False


@pytest.mark.parametrize("bad", [None, "", "not-a-number", [], {}])
def test_ac5_unusable_market_id_is_not_current(bad):
    state = LocationState()
    state.apply(docked_at())
    assert state.market_is_current(bad) is False


def test_ac5_missing_market_id_on_state_is_not_current():
    state = LocationState()
    state.apply(ev("Docked", StationName="Odd Station", StarSystem="X"))
    assert state.market_id is None
    assert state.market_is_current(RYMAN) is False


def test_ac5_docked_flag_alone_blocks_a_matching_id():
    """
    The `not self.docked` guard must hold on its own, not merely because the
    event folding happens to clear market_id alongside it. The daemon can
    build a LocationState from partial information, and a matching id must
    not be enough to declare a market current while undocked.
    """
    state = LocationState(system="Lhou Mans", docked=False,
                          station="Ryman Enterprise", market_id=RYMAN)
    assert state.market_is_current(RYMAN) is False


def test_station_display_ignores_a_stale_station_when_undocked():
    """
    Same defensive property for the cell the spreadsheet actually shows.
    Reporting the last station while in flight is precisely the "looks
    plausible, is wrong" failure this design exists to avoid.
    """
    state = LocationState(system="Lhou Mans", docked=False, station="Ryman Enterprise")
    assert state.station_display == NOT_DOCKED

    state.docked = True
    assert state.station_display == "Ryman Enterprise"


# --------------------------------------------------------------------------
# Reading files
# --------------------------------------------------------------------------

def test_iter_events_skips_a_truncated_final_line(tmp_path):
    path = tmp_path / "Journal.2026-09-08T000000.01.log"
    path.write_text(
        json.dumps(ev("Docked", StationName="A")) + "\n"
        + json.dumps(ev("FSDJump", StarSystem="B")) + "\n"
        + '{"timestamp":"2026-09-08T02:00:00Z","event":"Doc',   # half-written
        encoding="utf-8",
    )
    events = list(iter_events(path))
    assert [e["event"] for e in events] == ["Docked", "FSDJump"]


def test_iter_events_on_missing_file_is_empty(tmp_path):
    assert list(iter_events(tmp_path / "nope.log")) == []


def test_journal_dir_honours_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ED_JOURNAL_DIR", str(tmp_path))
    assert default_journal_dir() == tmp_path


def test_reader_finds_the_newest_journal(tmp_path):
    write_journal(tmp_path, "Journal.2026-09-06T210653.01.log", [ev("FSDJump", StarSystem="Old")])
    newest = write_journal(
        tmp_path, "Journal.2026-09-07T192642.01.log", [ev("FSDJump", StarSystem="New")]
    )
    reader = JournalReader(tmp_path)
    assert reader.latest_journal() == newest
    assert len(reader.journal_files()) == 2


# --------------------------------------------------------------------------
# Filename ordering across the two journal formats
#
# Regression: found against a real 615-file journal directory. Sorting names as
# strings put "Journal.220221113844.01.log" (Feb 2022, legacy format) ABOVE
# "Journal.2026-09-07T192642.01.log", so state was rebuilt from a 2022 session
# and reported the wrong star system entirely.
# --------------------------------------------------------------------------

def test_legacy_and_modern_filenames_order_chronologically(tmp_path):
    for name in (
        "Journal.220221113844.01.log",      # 2022-02-21, legacy format
        "Journal.2026-09-07T192642.01.log",  # 2026-09-07, modern format
        "Journal.2025-12-09T011501.01.log",  # 2025-12-09, modern format
        "Journal.180101000000.01.log",       # 2018-01-01, legacy format
    ):
        write_journal(tmp_path, name, [ev("Music")])

    ordered = [p.name for p in JournalReader(tmp_path).journal_files()]
    assert ordered == [
        "Journal.180101000000.01.log",
        "Journal.220221113844.01.log",
        "Journal.2025-12-09T011501.01.log",
        "Journal.2026-09-07T192642.01.log",
    ]


def test_a_legacy_file_never_masks_the_current_session(tmp_path):
    """The exact failure: a 2022 log winning over a 2026 one."""
    write_journal(tmp_path, "Journal.220221113844.01.log",
                  [ev("FSDJump", StarSystem="Bumbo")])
    write_journal(tmp_path, "Journal.2026-09-07T192642.01.log", [docked_at()])

    reader = JournalReader(tmp_path)
    assert reader.latest_journal().name == "Journal.2026-09-07T192642.01.log"
    state = reader.read_state(scan_files=1)
    assert state.system == "Lhou Mans"
    assert state.station == "Ryman Enterprise"


def test_split_journal_parts_order_numerically(tmp_path):
    """A long session splits into .01, .02, ... and 10 must follow 9."""
    for part in (1, 2, 9, 10):
        write_journal(tmp_path, f"Journal.2026-09-07T192642.{part:02d}.log", [ev("Music")])
    ordered = [p.name for p in JournalReader(tmp_path).journal_files()]
    assert ordered[-1] == "Journal.2026-09-07T192642.10.log"
    assert ordered[-2] == "Journal.2026-09-07T192642.09.log"


def test_unrecognized_filename_falls_back_to_mtime(tmp_path):
    """An oddly-named file must not poison the ordering."""
    write_journal(tmp_path, "Journal.wat.01.log", [ev("Music")])
    write_journal(tmp_path, "Journal.2026-09-07T192642.01.log", [docked_at()])
    files = JournalReader(tmp_path).journal_files()
    assert len(files) == 2
    assert JournalReader(tmp_path).read_state().station == "Ryman Enterprise"


def test_impossible_date_in_legacy_name_does_not_crash(tmp_path):
    write_journal(tmp_path, "Journal.999999999999.01.log", [ev("Music")])
    write_journal(tmp_path, "Journal.2026-09-07T192642.01.log", [docked_at()])
    assert len(JournalReader(tmp_path).journal_files()) == 2


def test_journal_sort_key_decodes_both_formats(tmp_path):
    modern = tmp_path / "Journal.2026-09-07T192642.03.log"
    modern.touch()
    legacy = tmp_path / "Journal.220221113844.01.log"
    legacy.touch()

    assert journal_sort_key(modern)[0] == datetime(2026, 9, 7, 19, 26, 42, tzinfo=timezone.utc)
    assert journal_sort_key(modern)[1] == 3
    assert journal_sort_key(legacy)[0] == datetime(2022, 2, 21, 11, 38, 44, tzinfo=timezone.utc)
    assert journal_sort_key(legacy) < journal_sort_key(modern)


def test_read_state_replays_across_files(tmp_path):
    """
    A session that began in an earlier log leaves the newest file with no
    Location/Docked event. State must still be recoverable.
    """
    write_journal(tmp_path, "Journal.2026-09-06T210653.01.log", [docked_at()])
    write_journal(
        tmp_path, "Journal.2026-09-07T192642.01.log",
        [ev("Music", MusicTrack="Station"), ev("FSSSignalDiscovered")],
    )
    state = JournalReader(tmp_path).read_state()
    assert state.docked is True
    assert state.station == "Ryman Enterprise"
    assert state.market_id == RYMAN


def test_read_state_on_empty_dir(tmp_path):
    state = JournalReader(tmp_path).read_state()
    assert state.system == ""
    assert state.docked is False
    assert state.station_display == NOT_DOCKED


def test_read_market_json(tmp_path):
    (tmp_path / "Market.json").write_text(
        json.dumps({"MarketID": RYMAN, "StationName": "Ryman Enterprise", "Items": []}),
        encoding="utf-8",
    )
    data = JournalReader(tmp_path).read_market_json()
    assert data["MarketID"] == RYMAN


def test_read_market_json_absent_or_mid_write(tmp_path):
    reader = JournalReader(tmp_path)
    assert reader.read_market_json() is None
    (tmp_path / "Market.json").write_text('{"MarketID": 32265781', encoding="utf-8")
    assert reader.read_market_json() is None      # partial write, not a crash


def test_read_status(tmp_path):
    (tmp_path / "Status.json").write_text(json.dumps({"Flags": 1, "Cargo": 844.0}), encoding="utf-8")
    assert JournalReader(tmp_path).read_status()["Cargo"] == 844.0


# --------------------------------------------------------------------------
# JournalWatcher: tailing
# --------------------------------------------------------------------------

def test_watcher_prime_does_not_replay_the_backlog(tmp_path):
    write_journal(tmp_path, "Journal.2026-09-07T192642.01.log", [docked_at()])
    watcher = JournalWatcher.create(tmp_path)
    state = watcher.prime()
    assert state.docked is True             # state known...
    assert watcher.poll() == []             # ...but no events replayed


def test_watcher_sees_appended_events(tmp_path):
    path = write_journal(tmp_path, "Journal.2026-09-07T192642.01.log", [docked_at()])
    watcher = JournalWatcher.create(tmp_path)
    watcher.prime()

    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(ev("Undocked", StationName="Ryman Enterprise", MarketID=RYMAN)) + "\n")

    events = watcher.poll()
    assert [e["event"] for e in events] == ["Undocked"]
    assert watcher.state.docked is False
    assert watcher.poll() == []             # already consumed


def test_watcher_rolls_onto_a_new_journal_file(tmp_path):
    """The game starts a fresh log each session; a held offset would go blind."""
    write_journal(tmp_path, "Journal.2026-09-07T192642.01.log", [docked_at()])
    watcher = JournalWatcher.create(tmp_path)
    watcher.prime()

    write_journal(
        tmp_path, "Journal.2026-09-08T101010.01.log",
        [ev("FSDJump", StarSystem="Juipedun"), docked_at(station="New Station", market_id=99)],
    )
    events = watcher.poll()
    assert [e["event"] for e in events] == ["FSDJump", "Docked"]
    assert watcher.state.station == "New Station"


def test_watcher_leaves_a_partial_line_for_the_next_poll(tmp_path):
    path = write_journal(tmp_path, "Journal.2026-09-07T192642.01.log", [docked_at()])
    watcher = JournalWatcher.create(tmp_path)
    watcher.prime()

    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"timestamp":"2026-09-08T02:30:00Z","event":"Undoc')
    assert watcher.poll() == []             # nothing complete yet

    with open(path, "a", encoding="utf-8") as handle:
        handle.write('ked","StationName":"Ryman Enterprise","MarketID":3226578176}\n')
    events = watcher.poll()
    assert [e["event"] for e in events] == ["Undocked"]


def test_watcher_handles_truncation(tmp_path):
    path = write_journal(tmp_path, "Journal.2026-09-07T192642.01.log", [docked_at(), ev("Music")])
    watcher = JournalWatcher.create(tmp_path)
    watcher.prime()
    path.write_text(json.dumps(ev("FSDJump", StarSystem="Reset")) + "\n", encoding="utf-8")
    events = watcher.poll()
    assert [e["event"] for e in events] == ["FSDJump"]


def test_watcher_on_empty_dir_is_quiet(tmp_path):
    watcher = JournalWatcher.create(tmp_path)
    watcher.prime()
    assert watcher.poll() == []
    assert watcher.poll_for_refresh() == []


def test_poll_for_refresh_filters_to_interesting_events(tmp_path):
    path = write_journal(tmp_path, "Journal.2026-09-07T192642.01.log", [ev("Music")])
    watcher = JournalWatcher.create(tmp_path)
    watcher.prime()
    with open(path, "a", encoding="utf-8") as handle:
        for event in (ev("Music"), ev("FSSSignalDiscovered"), docked_at(),
                      ev("Market", MarketID=RYMAN), ev("ShipTargeted")):
            handle.write(json.dumps(event) + "\n")
    assert watcher.poll_for_refresh() == ["Docked", "Market"]


def test_refresh_events_include_the_dock_trigger():
    assert "Docked" in REFRESH_EVENTS
    assert "Undocked" in REFRESH_EVENTS
    assert "Market" in REFRESH_EVENTS
    assert "Music" not in REFRESH_EVENTS


# --------------------------------------------------------------------------
# Against the real journal, when present
# --------------------------------------------------------------------------

def test_real_journal_state_is_readable():
    reader = JournalReader()
    if not reader.exists() or not reader.journal_files():
        pytest.skip("no local Elite Dangerous journal directory")
    state = reader.read_state()
    assert isinstance(state.system, str)
    assert isinstance(state.station_display, str)
