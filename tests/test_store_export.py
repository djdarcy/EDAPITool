"""
Export and import (the store design of 2026-10-09, unit 5; #22's criteria
7, 14 and 16, each named in its test).

Every test that imports does so into a second, empty configuration
directory, the way a person would carry a backup to another machine.
"""

import json

import pytest

from test_store_ingest import FIRST, SECOND, docked, header, line, write
from test_store_projections import ingest
from test_store_rebuild import EVERYTHING

from APITool import cli
from APITool.store import StoreError, archive, open_store, store_path
from APITool.store import ingest as ingest_mod
from APITool.store import transfer


@pytest.fixture
def elsewhere(tmp_path_factory, monkeypatch):
    """Switch to a fresh configuration directory, as the conftest fixture does."""
    def switch():
        directory = tmp_path_factory.mktemp("edapitool-elsewhere")
        monkeypatch.setenv("ED_CONFIG_DIR", str(directory))
        return directory
    return switch


def counts():
    conn = open_store(store_path())
    try:
        return tuple(conn.execute(
            "SELECT (SELECT COUNT(*) FROM sources), (SELECT COUNT(*) FROM observations), "
            "(SELECT COUNT(*) FROM construction_delta)").fetchone())
    finally:
        conn.close()


def export_to(path):
    conn = open_store(store_path())
    try:
        return transfer.export_store(conn, path)
    finally:
        conn.close()


def import_from(path):
    conn = open_store(store_path())
    try:
        return transfer.import_file(conn, path)
    finally:
        conn.close()


def test_export_import_into_a_fresh_store_and_export_again_is_byte_identical(tmp_path, elsewhere):
    """#22 criterion 16."""
    ingest(tmp_path, *EVERYTHING)
    original = counts()
    first = export_to(tmp_path / "a.json")
    document = json.loads(first.read_text(encoding="utf-8"))
    assert document["format"] == "edapitool-store" and document["schema_version"] == 2
    assert all("payload" in row for row in document["observations"]), "JSON text travels as text"

    elsewhere()
    assert not store_path().exists()
    result = import_from(first)
    second = export_to(tmp_path / "b.json")

    assert result.fresh and result.observations_new == original[1]
    assert second.read_bytes() == first.read_bytes()
    assert counts() == original, "the derived tables were rebuilt after the import"


def test_importing_two_overlapping_backups_of_the_same_machine_leaves_counts_unchanged(tmp_path, elsewhere):
    """#22 criterion 7."""
    directory = tmp_path / "journal"
    directory.mkdir()
    write(directory, FIRST, header(), docked(2), docked(3, market_id=5))
    ingest_mod.ingest_dir(directory, machine="box")
    older = export_to(tmp_path / "older.json")
    write(directory, SECOND, header(part=2), docked(4, market_id=6))
    ingest_mod.ingest_dir(directory, machine="box")
    newer = export_to(tmp_path / "newer.json")
    whole = counts()

    elsewhere()
    import_from(older)
    merged = import_from(newer)
    assert counts() == whole
    assert (merged.sources_matched, merged.sources_new) == (1, 1)
    assert (merged.observations_skipped, merged.observations_new) == (3, 2)

    again = import_from(newer)
    assert counts() == whole
    assert (again.sources_new, again.observations_new) == (0, 0)


def test_two_commanders_on_one_installation_do_not_merge(tmp_path, elsewhere):
    """#22 criterion 14."""
    one = tmp_path / "one"
    two = tmp_path / "two"
    for directory, who, fid in ((one, "Jameson", "F1"), (two, "Mostly Harmless", "F2")):
        directory.mkdir()
        write(directory, FIRST, header(), line("LoadGame", 1, Commander=who, FID=fid),
              docked(2, market_id=1 if fid == "F1" else 2))
        ingest_mod.ingest_dir(directory, machine="box")
    exported = export_to(tmp_path / "both.json")
    whole = counts()

    elsewhere()
    import_from(exported)

    conn = open_store(store_path())
    try:
        rows = conn.execute(
            "SELECT s.commander, s.commander_fid, COUNT(o.obs_id) FROM sources s "
            "JOIN observations o USING (source_id) GROUP BY s.source_id ORDER BY s.source_id").fetchall()
    finally:
        conn.close()
    assert counts() == whole
    # The header line is byte-identical in both files and is kept once, under the first.
    assert rows == [("Jameson", "F1", 3), ("Mostly Harmless", "F2", 2)]


def test_a_payload_that_is_not_text_travels_as_base64_and_comes_back_whole(tmp_path, elsewhere):
    raw = b"\xff\x00\x01 not utf-8"
    assert archive("blob", raw, locator="x") is not None
    exported = export_to(tmp_path / "blob.json")
    document = json.loads(exported.read_text(encoding="utf-8"))
    assert "payload_b64" in document["observations"][0]

    elsewhere()
    import_from(exported)
    conn = open_store(store_path())
    try:
        assert conn.execute("SELECT payload FROM observations").fetchone()[0] == raw
    finally:
        conn.close()


def test_import_refuses_a_file_that_is_not_an_export_and_one_from_a_newer_tool(tmp_path):
    (tmp_path / "x.json").write_text('{"hello": 1}', encoding="utf-8")
    with pytest.raises(StoreError, match="not a store export"):
        import_from(tmp_path / "x.json")
    (tmp_path / "y.json").write_text(json.dumps({"format": "edapitool-store", "schema_version": 99}),
                                     encoding="utf-8")
    with pytest.raises(StoreError, match="newer than this tool"):
        import_from(tmp_path / "y.json")


# -- the verbs -------------------------------------------------------------------

def test_the_export_and_import_verbs(tmp_path, elsewhere, capsys):
    ingest(tmp_path, *EVERYTHING)

    assert cli.main(["store", "export"]) == 0
    out = capsys.readouterr().out
    assert "Exported 1 source(s)" in out and ".export-" in out
    written = next(store_path().parent.glob("store.db.export-*.json"))

    elsewhere()
    assert cli.main(["store", "import", str(written)]) == 0
    out = capsys.readouterr().out
    assert "into an empty store, ids kept" in out and "new observation(s)" in out
    assert store_path().is_file()

    assert cli.main(["store", "import", str(written)]) == 0
    assert "merged by source and content" in capsys.readouterr().out

    assert cli.main(["store", "import", str(tmp_path / "missing.json")]) == 2
    assert "no such file" in capsys.readouterr().err
    (tmp_path / "bad.json").write_text("[]", encoding="utf-8")
    assert cli.main(["store", "import", str(tmp_path / "bad.json")]) == 1
    assert "not a store export" in capsys.readouterr().err


def test_export_needs_a_store_and_import_is_refused_under_the_guard(tmp_path, capsys, monkeypatch):
    assert cli.main(["store", "export"]) == 2
    capsys.readouterr()
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ED_NO_STORE", "1")
    assert cli.main(["store", "import", str(tmp_path / "x.json")]) == 1
    assert "ED_NO_STORE" in capsys.readouterr().err
    assert not store_path().exists()
