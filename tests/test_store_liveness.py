"""
Liveness and the backup set (the store design of 2026-10-09, unit 4;
#22's criteria 5 and 13, each named in its test).

A source is ``present`` when the world still has it -- the journal file is
where the row says, with the first line it was recorded by -- ``absent``
when it is not, and ``retired`` when a person says it is gone for good.
The backup set is every observation whose source is not present: what a
copy of the store is the only other home of.
"""

import os

import pytest

from test_store_ingest import FIRST, SECOND, docked, header, loadgame, noise, write

from APITool import cli
from APITool.store import (StoreError, backup_set, open_store, retire, sources, store_path,
                           verify_sources)
from APITool.store import ingest as ingest_mod


@pytest.fixture
def journal(tmp_path):
    directory = tmp_path / "journal"
    directory.mkdir()
    write(directory, FIRST, header(), loadgame(), docked(2), noise(3))
    write(directory, SECOND, header(part=2), loadgame(4), docked(5, market_id=7))
    ingest_mod.ingest_dir(directory)            # this machine's name, as the verbs use it
    return directory


def liveness():
    conn = open_store(store_path())
    try:
        return [(row[0], row[3]) for row in sources(conn)]
    finally:
        conn.close()


def with_store(fn):
    conn = open_store(store_path())
    try:
        return fn(conn)
    finally:
        conn.close()


def test_verify_marks_a_journal_source_present_while_its_file_is_where_it_was(journal):
    assert liveness() == [(1, "present"), (2, "present")]
    counts = with_store(verify_sources)

    assert counts == {"present": 2, "absent": 0, "retired": 0, "elsewhere": 0}
    assert liveness() == [(1, "present"), (2, "present")]
    assert with_store(backup_set) == []


def test_the_backup_set_grows_when_a_source_goes_and_shrinks_when_it_returns(journal):
    """#22 criterion 5: the set holds exactly the rows whose source is not verifiable."""
    path = journal / SECOND
    content = path.read_bytes()
    os.remove(path)

    counts = with_store(verify_sources)
    assert counts["present"] == 1 and counts["absent"] == 1
    assert liveness() == [(1, "present"), (2, "absent")]
    gone = with_store(backup_set)
    assert len(gone) == 3, "the second file's own rows: its header, its LoadGame and its docking"

    path.write_bytes(content)
    with_store(verify_sources)
    assert liveness() == [(1, "present"), (2, "present")]
    assert with_store(backup_set) == []


def test_a_file_replaced_under_the_same_name_is_absent_not_present(journal):
    path = journal / SECOND
    path.write_bytes(b"".join([header(part=9), docked(6)]))

    with_store(verify_sources)

    assert liveness() == [(1, "present"), (2, "absent")], "the first line no longer matches"


def test_retiring_a_source_moves_its_rows_into_the_backup_set_with_no_data_movement(journal):
    """#22 criterion 13 (the design's AC-15)."""
    before = with_store(lambda c: c.execute("SELECT * FROM observations ORDER BY obs_id").fetchall())

    row = with_store(lambda c: retire(c, 2))

    assert row[0] == 2 and row[4] == "present"
    assert liveness() == [(1, "present"), (2, "retired")]
    assert with_store(backup_set) == [o[0] for o in before if o[1] == 2]
    assert with_store(lambda c: c.execute("SELECT * FROM observations ORDER BY obs_id").fetchall()) == before

    counts = with_store(verify_sources)
    assert counts["retired"] == 1 and liveness()[1] == (2, "retired"), "verify leaves a retired source alone"


def test_retire_takes_a_locator_too_and_refuses_an_unknown_source_by_name(journal):
    row = with_store(lambda c: retire(c, str(journal / FIRST)))
    assert row[0] == 1

    with pytest.raises(StoreError, match="no source 'nowhere'"):
        with_store(lambda c: retire(c, "nowhere"))
    with pytest.raises(StoreError, match="99"):
        with_store(lambda c: retire(c, 99))


def test_a_source_from_another_machine_is_counted_and_never_touched(tmp_path, journal):
    other = tmp_path / "other"
    other.mkdir()
    write(other, FIRST, header(part=3), docked(7))
    ingest_mod.ingest_dir(other, machine="laptop")
    os.remove(other / FIRST)

    counts = with_store(verify_sources)

    assert counts["elsewhere"] == 1
    assert liveness()[2] == (3, "present"), "this machine cannot say what the laptop has"


def test_a_side_file_source_stays_absent(journal):
    from APITool.store import archive
    archive("market_json", b'{"MarketID": 1, "Items": []}', locator=str(journal / "Market.json"))

    counts = with_store(verify_sources)

    assert counts["absent"] == 1
    assert liveness()[2][1] == "absent"


# -- the verbs ------------------------------------------------------------------

def test_the_verify_verb_reports_the_sources_by_liveness(journal, capsys):
    os.remove(journal / SECOND)

    assert cli.main(["store", "verify"]) == 0
    out = capsys.readouterr().out

    assert "Store OK" in out
    assert "sources: 1 present, 1 absent, 0 retired, 0 on other machines" in out


def test_the_backup_verb_reports_the_backup_set(journal, capsys):
    with_store(lambda c: retire(c, 1))

    assert cli.main(["store", "backup"]) == 0
    out = capsys.readouterr().out

    assert "Backed up to" in out
    assert "backup set: 3 observation(s)" in out


def test_the_sources_and_retire_verbs(journal, capsys):
    assert cli.main(["store", "sources"]) == 0
    out = capsys.readouterr().out
    assert "2 source(s)" in out and FIRST in out and "present" in out

    assert cli.main(["store", "retire", "2"]) == 0
    out = capsys.readouterr().out
    assert "Retired source 2" in out and "was present" in out and SECOND in out

    assert cli.main(["store", "retire", "nowhere"]) == 1
    assert "no source 'nowhere'" in capsys.readouterr().err
