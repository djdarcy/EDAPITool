"""
The archive: every side-file read and every CAPI answer becomes a row.

The store is additive (AC-10 of the store design): a command's output is
byte-identical whether the store is on or off, and a store failure never
reaches the command. These tests hold both ends of that -- the rows appear,
and nothing else changes.

Everything runs under the conftest's ``ED_CONFIG_DIR``; the store these
tests fill is a scratch one.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from APITool import store
from APITool.cli import main
from APITool.journal import JournalReader, LocationState

FIXTURES = Path(__file__).parent / "fixtures"
RYMAN = 3226578176


def ev(name, **kw):
    payload = {"timestamp": "2026-09-08T02:00:00Z", "event": name}
    payload.update(kw)
    return payload


def docked_event(station="Ryman Enterprise", system="Lhou Mans", market_id=RYMAN):
    return ev("Docked", StationName=station, StarSystem=system, MarketID=market_id,
              StationType="Coriolis", StationServices=["dock", "commodities"])


def load_game(commander="Extreme", fid="F1234567"):
    return ev("LoadGame", Commander=commander, FID=fid)


def ryman_market_json(market_id=RYMAN, stamp="2026-09-08T05:48:18Z"):
    data = json.loads((FIXTURES / "market_ryman_journal.json").read_text(encoding="utf-8"))
    data["MarketID"] = market_id
    data["timestamp"] = stamp
    return data


def make_journal(tmp_path, events, market_json=None):
    (tmp_path / "Journal.2026-09-08T021410.01.log").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    if market_json is not None:
        (tmp_path / "Market.json").write_bytes(json.dumps(market_json).encode("utf-8"))
    return tmp_path


def rows(sql):
    conn = sqlite3.connect(store.store_path())
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# the journal's side files
# --------------------------------------------------------------------------

def test_reading_market_json_archives_it_once(tmp_path):
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    reader = JournalReader(directory)
    assert reader.read_market_json()["MarketID"] == RYMAN
    assert reader.read_market_json()["MarketID"] == RYMAN
    assert rows("SELECT kind, subject FROM observations") == [("market_json", str(RYMAN))]
    assert rows("SELECT COUNT(*) FROM market_snapshot") == [(1,)]


def test_the_game_overwriting_the_file_loses_nothing(tmp_path):
    """The whole reason the archive exists: the first read's bytes survive the rewrite."""
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    reader = JournalReader(directory)
    reader.read_market_json()
    first_bytes = (directory / "Market.json").read_bytes()

    later = ryman_market_json(market_id=4323280387, stamp="2026-09-08T06:00:00Z")
    (directory / "Market.json").write_bytes(json.dumps(later).encode("utf-8"))
    reader.read_market_json()

    kept = rows("SELECT subject, payload FROM observations ORDER BY obs_id")
    assert [subject for subject, _ in kept] == [str(RYMAN), "4323280387"]
    assert kept[0][1] == first_bytes
    assert rows("SELECT market_id FROM market_snapshot ORDER BY obs_id") == \
        [(RYMAN,), (4323280387,)]


def test_cargo_and_status_archive_under_their_own_kinds(tmp_path):
    (tmp_path / "Cargo.json").write_bytes(
        (FIXTURES / "cargo_ship.json").read_bytes())
    (tmp_path / "Status.json").write_bytes(
        json.dumps({"timestamp": "2026-09-08T06:46:29Z", "event": "Status",
                    "Flags": 16777240}).encode("utf-8"))
    reader = JournalReader(tmp_path)
    assert reader.read_cargo_json()["Vessel"] == "Ship"
    assert reader.read_status()["event"] == "Status"
    assert rows("SELECT kind, subject, observed_at FROM observations ORDER BY obs_id") == [
        ("cargo_json", "Ship", "2026-09-08T06:46:29Z"),
        ("status_json", None, "2026-09-08T06:46:29Z"),
    ]
    assert rows("SELECT COUNT(*) FROM market_snapshot") == [(0,)]


def test_a_file_that_does_not_parse_is_no_data_and_no_row(tmp_path):
    """The game mid-write is not a round; the next read gets the whole file."""
    (tmp_path / "Market.json").write_bytes(b'{"timestamp": "2026-09-08T05:48:18Z", "Ite')
    reader = JournalReader(tmp_path)
    assert reader.read_market_json() is None
    assert not store.store_path().exists()


def test_the_source_row_carries_the_commander_from_load_game(tmp_path):
    directory = make_journal(tmp_path, [load_game(), docked_event()], ryman_market_json())
    reader = JournalReader(directory)
    reader.read_state()                       # the service reads location before the market
    reader.read_market_json()
    assert rows("SELECT kind, commander, commander_fid, liveness FROM sources") == \
        [("market_json", "Extreme", "F1234567", "absent")]


def test_load_game_folds_the_fid_into_the_state():
    state = LocationState()
    state.apply(load_game(commander="Jameson", fid="F42"))
    assert (state.commander, state.commander_fid) == ("Jameson", "F42")


def test_the_newest_load_game_wins_for_the_fid_as_for_the_name():
    """Switching commander mid-session is a second LoadGame; the row must name the second."""
    state = LocationState()
    state.apply(load_game(commander="Jameson", fid="F42"))
    state.apply(load_game(commander="Ryder", fid="F99"))
    assert (state.commander, state.commander_fid) == ("Ryder", "F99")


def test_the_off_switch_leaves_no_store(tmp_path, monkeypatch):
    monkeypatch.setenv(store.GUARD_VAR, "1")
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    assert JournalReader(directory).read_market_json()["MarketID"] == RYMAN
    assert not store.store_path().exists()


# --------------------------------------------------------------------------
# AC-10: the command's output does not change
# --------------------------------------------------------------------------

def _market_argv(directory):
    return ["market", "--journal-dir", str(directory), "--no-sheet", "--json"]


def test_market_json_output_is_byte_identical_with_the_store_on_and_off(
        tmp_path, monkeypatch, capsys, configured_totals):
    from APITool import cli as cli_mod
    monkeypatch.setattr(cli_mod, "get_sheet_id", lambda args: None)
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())

    monkeypatch.setenv(store.GUARD_VAR, "1")
    assert main(_market_argv(directory)) == 0
    without = capsys.readouterr().out
    assert not store.store_path().exists()

    monkeypatch.delenv(store.GUARD_VAR)
    assert main(_market_argv(directory)) == 0
    with_store = capsys.readouterr().out

    # The payload carries the market's age in seconds against the wall clock,
    # which moves between the two runs; everything else must be identical.
    def settled(text):
        payload = json.loads(text)
        payload["market"].pop("age_seconds")
        return json.dumps(payload, indent=2, sort_keys=True)

    assert settled(with_store) == settled(without)
    assert rows("SELECT kind, subject FROM observations") == [("market_json", str(RYMAN))]


def test_a_store_failure_never_reaches_the_command(
        tmp_path, monkeypatch, capsys, configured_totals):
    from APITool import cli as cli_mod
    monkeypatch.setattr(cli_mod, "get_sheet_id", lambda args: None)
    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())

    def broken(path=None):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(store, "open_store", broken)

    assert main(_market_argv(directory)) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["market_id"] == RYMAN
    assert captured.err.count("could not archive") == 1


# --------------------------------------------------------------------------
# CAPI answers
# --------------------------------------------------------------------------

class StubAuth:
    def get_auth_header(self):
        return {"Authorization": "Bearer x"}

    def refresh(self):
        return False


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.status_code = status
        self.content = json.dumps(payload).encode("utf-8")
        self.text = self.content.decode("utf-8")

    def json(self):
        return json.loads(self.content)


def _client(monkeypatch, answers: dict):
    from APITool import capi as capi_mod
    from APITool.capi import CAPIClient

    def fake_get(url, headers=None, timeout=None):
        for endpoint, payload in answers.items():
            if url.endswith(endpoint):
                return FakeResponse(payload)
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(capi_mod.requests, "get", fake_get)
    monkeypatch.setattr(capi_mod.time, "sleep", lambda seconds: None)   # the query cooldown
    client = CAPIClient(StubAuth())
    monkeypatch.setattr(client, "_get_headers", lambda: {})
    monkeypatch.setattr(client, "_save_debug", lambda endpoint, data: None)
    return client


def test_a_capi_market_answer_is_archived_as_read(monkeypatch):
    capi_market = json.loads((FIXTURES / "market_ryman_capi.json").read_text(encoding="utf-8"))
    client = _client(monkeypatch, {"/market": capi_market})
    data = client.get_market()
    assert data == capi_market                                   # unchanged for the caller
    kept = rows("SELECT kind, subject, payload FROM observations")
    assert len(kept) == 1
    kind, subject, payload = kept[0]
    assert kind == "capi_market" and subject == str(capi_market["id"])
    assert json.loads(payload) == capi_market                    # the bytes as received
    assert rows("SELECT market_id, items_count FROM market_snapshot")[0][0] == capi_market["id"]


def test_profile_and_fleetcarrier_answers_archive_under_their_kinds(monkeypatch):
    client = _client(monkeypatch, {
        "/profile": {"commander": {"name": "Extreme", "id": 1}},
        "/fleetcarrier": {"name": {"callsign": "X7Y-9ZZ", "vanityName": "Wanderer"}},
    })
    client.get_profile()
    client._request("/fleetcarrier", is_fleet_carrier=True)
    assert rows("SELECT kind, subject FROM observations ORDER BY obs_id") == [
        ("capi_profile", "Extreme"),
        ("capi_fleetcarrier", "X7Y-9ZZ"),
    ]


def test_the_capi_source_is_located_by_its_full_url(monkeypatch):
    """Live, legacy and beta servers answer the same path; the URL is what tells them apart."""
    client = _client(monkeypatch, {"/profile": {"commander": {"name": "Extreme"}}})
    client.get_profile()
    (locator,) = rows("SELECT locator FROM sources")[0]
    assert locator.startswith("https://") and locator.endswith("/profile")


def test_an_endpoint_that_merely_shares_a_prefix_is_not_archived_as_that_kind():
    from APITool.capi import _archive

    _archive("/marketplace", b"{}", {}, "https://example/marketplace")
    _archive("/profiles", b"{}", {}, "https://example/profiles")
    assert not store.store_path().exists()


def test_the_same_capi_answer_twice_is_one_row(monkeypatch):
    client = _client(monkeypatch, {"/profile": {"commander": {"name": "Extreme"}}})
    client.get_profile()
    client.get_profile()
    assert rows("SELECT COUNT(*) FROM observations") == [(1,)]
