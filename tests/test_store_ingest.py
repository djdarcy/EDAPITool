"""
The journal ingest (the store design of 2026-10-09, unit 2; #22's criteria
6, 8, 9 and 10, each named in its test).

Journal files are written as the game writes them: one JSON object per
line, CRLF, a ``Fileheader`` first. The config directory is isolated by
the suite's autouse fixture, so ``store_path()`` is a scratch store.
"""

import json

import pytest

from APITool import cli
from APITool.journal import JournalWatcher
from APITool.store import open_store, store_path, verify
from APITool.store import ingest as ingest_mod


def line(event, n=0, **fields) -> bytes:
    body = {"timestamp": f"2026-10-09T0{n}:00:00Z", "event": event, **fields}
    return (json.dumps(body, separators=(",", ":")) + "\r\n").encode("utf-8")


def header(part=1) -> bytes:
    return line("Fileheader", 0, part=part, language="English/UK", Odyssey=True,
                gameversion="4.1.0.100", build="r312744/r0 ")


def loadgame(n=1) -> bytes:
    return line("LoadGame", n, Commander="Jameson", FID="F1234567")


def noise(n) -> bytes:
    return line("Music", n, MusicTrack="NoTrack")


def docked(n=2, market_id=128666762) -> bytes:
    return line("Docked", n, StationName="Jameson Memorial", StarSystem="Shinrarta Dezhra",
                SystemAddress=3932277478106, MarketID=market_id, StationType="Orbis")


def depot(n=3, site=3957057282) -> bytes:
    return line("ColonisationConstructionDepot", n, MarketID=site, ConstructionProgress=0.5,
                ConstructionComplete=False, ConstructionFailed=False,
                ResourcesRequired=[{"Name": "$steel_name;", "Name_Localised": "Steel",
                                    "RequiredAmount": 100, "ProvidedAmount": 50, "Payment": 1000}])


FIRST = "Journal.2026-10-09T010000.01.log"
SECOND = "Journal.2026-10-09T020000.01.log"


def write(directory, name, *lines):
    path = directory / name
    path.write_bytes(b"".join(lines))
    return path


@pytest.fixture
def journal(tmp_path):
    directory = tmp_path / "journal"
    directory.mkdir()
    write(directory, FIRST, header(), loadgame(), noise(1), docked(), depot(), noise(4))
    return directory


def counts() -> tuple[int, int]:
    """(sources, observations) -- only after something created the store."""
    assert store_path().is_file()
    conn = open_store(store_path())
    try:
        sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        observations = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        return sources, observations
    finally:
        conn.close()


def _query(sql, *params):
    conn = open_store(store_path())
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# -- what one ingest records ---------------------------------------------------

def test_ingest_keeps_the_named_events_and_records_the_read_position(journal):
    result = ingest_mod.ingest_dir(journal, machine="box")

    assert (result.read, result.kept, result.new, result.unchanged) == (1, 4, 4, 0)
    kinds = [r[0] for r in _query("SELECT kind FROM observations ORDER BY obs_id")]
    assert kinds == ["fileheader", "loadgame", "docked", "colonisationconstructiondepot"]
    subjects = dict(_query("SELECT kind, subject FROM observations"))
    assert subjects["docked"] == "128666762"
    assert subjects["colonisationconstructiondepot"] == "3957057282"
    assert subjects["loadgame"] == "F1234567"
    size = (journal / FIRST).stat().st_size
    row = _query("SELECT kind, machine, commander, commander_fid, read_offset, events_yielded, "
                 "ingested_bytes, game_version, liveness FROM sources")[0]
    assert row == ("journal", "box", "Jameson", "F1234567", size, 4, size, "4.1.0.100", "present")
    payload = _query("SELECT payload FROM observations WHERE kind = 'docked'")[0][0]
    assert payload == docked().rstrip(b"\r\n"), "the line's own bytes; custody intact"
    assert _query("SELECT observed_at FROM observations WHERE kind = 'docked'")[0][0] == "2026-10-09T02:00:00Z"


def test_ingesting_the_same_range_twice_leaves_counts_unchanged(journal):
    """#22 criterion 6."""
    ingest_mod.ingest_dir(journal, machine="box")
    before = counts()

    again = ingest_mod.ingest_dir(journal, machine="box")

    assert counts() == before
    assert (again.read, again.unchanged, again.kept, again.bytes) == (1, 1, 0, 0)


def test_the_same_file_under_two_machines_records_two_sources_and_one_set_of_observations(journal):
    """#22 criterion 8."""
    ingest_mod.ingest_dir(journal, machine="desk")
    ingest_mod.ingest_dir(journal, machine="laptop")

    assert counts() == (2, 4)
    assert sorted(r[0] for r in _query("SELECT machine FROM sources")) == ["desk", "laptop"]


def test_an_orphaned_observation_fails_verify(journal):
    """#22 criterion 9: every observation resolves to a source."""
    ingest_mod.ingest_dir(journal, machine="box")
    conn = open_store(store_path())
    try:
        assert verify(conn) == []
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("UPDATE observations SET source_id = 999 WHERE kind = 'docked'")
        conn.commit()
        problems = verify(conn)
    finally:
        conn.close()
    assert problems and "observations" in problems[0] and "sources" in problems[0]


def test_a_file_with_no_events_of_interest_still_records_a_source_and_is_skipped_next_time(tmp_path):
    """#22 criterion 10."""
    directory = tmp_path / "journal"
    directory.mkdir()
    write(directory, FIRST, noise(1), noise(2))

    first = ingest_mod.ingest_dir(directory, machine="box")
    assert (first.read, first.kept) == (1, 0)
    assert counts() == (1, 0)
    size = (directory / FIRST).stat().st_size
    assert _query("SELECT events_yielded, read_offset FROM sources")[0] == (0, size)

    second = ingest_mod.ingest_dir(directory, machine="box")
    assert (second.read, second.unchanged, second.bytes) == (1, 1, 0)


def test_appended_events_are_read_from_the_recorded_position_and_a_half_written_line_waits(journal):
    ingest_mod.ingest_dir(journal, machine="box")
    path = journal / FIRST
    whole = docked(5, market_id=1)
    with open(path, "ab") as handle:
        handle.write(docked(5, market_id=3228342528) + whole[:-7])

    result = ingest_mod.ingest_dir(journal, machine="box")

    assert (result.kept, result.new) == (1, 1)
    assert counts() == (1, 5)
    assert _query("SELECT read_offset FROM sources")[0][0] == path.stat().st_size - (len(whole) - 7)

    with open(path, "ab") as handle:
        handle.write(whole[-7:])
    result = ingest_mod.ingest_dir(journal, machine="box")
    assert result.new == 1
    assert counts() == (1, 6)
    assert _query("SELECT read_offset FROM sources")[0][0] == path.stat().st_size


def test_a_second_file_is_its_own_source_and_an_identical_line_is_kept_once(journal):
    write(journal, SECOND, header(part=2), loadgame(), docked(6, market_id=7))

    result = ingest_mod.ingest_dir(journal, machine="box")

    assert result.read == 2
    # The second file's LoadGame line is byte-identical to the first's: one
    # observation, under the source that kept it first.
    assert counts() == (2, 6)
    assert _query("SELECT events_yielded FROM sources ORDER BY source_id") == [(4,), (3,)]


def test_a_file_without_a_complete_first_line_is_left_for_next_time(journal):
    write(journal, SECOND, header()[:-5])

    result = ingest_mod.ingest_dir(journal, machine="box")

    assert (result.read, result.pending) == (1, 1)
    assert counts() == (1, 4)


def test_ingest_under_the_guard_touches_nothing(journal, monkeypatch):
    monkeypatch.setenv("ED_NO_STORE", "1")

    result = ingest_mod.ingest_dir(journal)

    assert result.guarded and result.files == []
    assert not store_path().exists()


# -- the watcher shares the position -------------------------------------------

def test_the_watcher_primes_from_the_store_and_replays_nothing(journal):
    ingest_mod.ingest_dir(journal)
    before = counts()
    watcher = JournalWatcher.create(journal)
    watcher.prime()

    assert watcher.poll() == []
    assert counts() == before

    with open(journal / FIRST, "ab") as handle:
        handle.write(docked(7, market_id=5))
    events = watcher.poll()

    assert [e["event"] for e in events] == ["Docked"]
    assert counts() == (before[0], before[1] + 1), "the poll fed the store"


def test_the_watcher_prime_ingests_the_newest_file_into_a_fresh_store(journal):
    assert not store_path().exists()
    watcher = JournalWatcher.create(journal)
    watcher.prime()

    assert counts() == (1, 4)
    assert watcher.poll() == []


def test_the_watcher_primes_at_the_store_s_position_not_past_a_half_written_line(journal):
    path = journal / FIRST
    whole = docked(5, market_id=1)
    with open(path, "ab") as handle:
        handle.write(whole[:-7])
    watcher = JournalWatcher.create(journal)
    watcher.prime()

    with open(path, "ab") as handle:
        handle.write(whole[-7:])

    assert [e["MarketID"] for e in watcher.poll()] == [1], "the completed line is delivered"


def test_the_watcher_without_a_store_behaves_as_before(journal, monkeypatch):
    monkeypatch.setenv("ED_NO_STORE", "1")
    watcher = JournalWatcher.create(journal)
    watcher.prime()

    assert watcher.poll() == []
    with open(journal / FIRST, "ab") as handle:
        handle.write(docked(7, market_id=5))
    assert [e["event"] for e in watcher.poll()] == ["Docked"]
    assert not store_path().exists()


# -- the verb -------------------------------------------------------------------

def test_cli_store_ingest_creates_the_store_and_reports(journal, capsys):
    assert not store_path().exists()

    rc = cli.main(["store", "ingest", str(journal), "--machine", "box"])
    out = capsys.readouterr().out

    assert rc == 0 and store_path().is_file()
    assert "1 file(s) read, 0 unchanged" in out and "4 event(s) kept, 4 new" in out

    rc = cli.main(["store", "ingest", str(journal), "--machine", "box"])
    out = capsys.readouterr().out
    assert rc == 0 and "1 unchanged" in out and "0 event(s) kept" in out


def test_cli_store_ingest_refuses_a_missing_directory(tmp_path, capsys):
    rc = cli.main(["store", "ingest", str(tmp_path / "nowhere")])

    assert rc == 2
    assert "no such directory" in capsys.readouterr().err
    assert not store_path().exists()


def test_cli_store_ingest_under_the_guard_refuses(journal, capsys, monkeypatch):
    monkeypatch.setenv("ED_NO_STORE", "1")

    rc = cli.main(["store", "ingest", str(journal)])

    assert rc == 1
    assert "ED_NO_STORE" in capsys.readouterr().err
    assert not store_path().exists()
