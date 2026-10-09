"""
The observation store: what the tool has read, kept where the game cannot
overwrite it.

One SQLite file, ``store.db``, beside ``config.json`` in the directory the
settings module owns -- so the environment variable that module honours
redirects the store too, and the test suite never touches a real one. The
path is resolved on every call, never frozen at import, for the same
reason; only ``settings`` knows how the directory is found.

Three verbs, each a function here and a subcommand of ``edapitool store``:

``verify``
    Is the file sound? SQLite's own ``integrity_check``; every table known
    to the registry and no table it does not know; no row pointing at a
    parent that is gone. Returns the problems, empty when there are none.

``backup``
    An online copy, ``store.db.bak-<stamp>``, made with SQLite's backup
    API -- and only after ``verify`` passes. The rule is the settings
    module's: a corrupt file never overwrites a good copy.

``rebuild``
    Drop every table registered ``derived`` and re-project it from the
    primary ones. Never touches a primary table; refuses, by name, when
    there is nothing derived to rebuild.

The store is additive. ``archive()`` (the fourth function, used by the
readers rather than a verb) never raises into its caller: a failure to
record is reported once and the command it was recording for continues,
because a spreadsheet update must not fail over a bookkeeping file.
"""

from __future__ import annotations

import hashlib
import os
import socket
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .. import settings
from . import registry
from .schema import INDEXES, MIGRATIONS, SCHEMA_VERSION, STORE_DB  # noqa: F401  (registers tables)

__all__ = [
    "StoreError", "StoreVersionError", "store_path", "open_store",
    "verify", "verify_sources", "backup", "backup_set", "retire", "sources",
    "rebuild", "archive", "keep", "now_utc", "sha256", "LIVENESS",
]


#: Set to any value to turn archiving off for a run -- the switch a test, a
#: checklist or a person who wants a command with no bookkeeping reaches for.
GUARD_VAR = "ED_NO_STORE"


class StoreError(Exception):
    """A store operation refused, with the reason in the message."""


class StoreVersionError(StoreError):
    """The file's schema version is one this code cannot read or migrate."""


def now_utc() -> str:
    """ISO-8601, whole seconds, ``Z`` -- the one stamp format the store writes."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def store_path() -> Path:
    """Where the store is, resolved now, through ``settings.resolve`` -- per call."""
    return settings.resolve(STORE_DB)


def _file_of(conn: sqlite3.Connection) -> Path:
    for _, name, file in conn.execute("PRAGMA database_list"):
        if name == "main":
            return Path(file)
    raise StoreError("connection has no main database file")  # pragma: no cover


def _create(conn: sqlite3.Connection) -> None:
    for table in registry.tables():
        conn.execute(table.ddl)
    for statement in INDEXES:
        conn.execute(statement)


def open_store(path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Open (creating if absent) the store, and bring it to this code's version.

    A fresh file is created at ``SCHEMA_VERSION``. A file at that version is
    opened as it is. A file at an older version is migrated one step at a
    time through ``MIGRATIONS``; a version with no step, or one newer than
    this code, is refused with both versions and the path in the message --
    silently reading a newer schema is how a tool corrupts a file it does
    not understand.
    """
    target = Path(path) if path is not None else store_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return conn
    if version > SCHEMA_VERSION:
        conn.close()
        raise StoreVersionError(
            f"{target} is schema version {version}, newer than this tool's "
            f"{SCHEMA_VERSION}; upgrade edapitool rather than let it guess")
    try:
        with conn:
            if version == 0:
                _create(conn)
            else:
                for step in range(version + 1, SCHEMA_VERSION + 1):
                    migrate = MIGRATIONS.get(step)
                    if migrate is None:
                        raise StoreVersionError(
                            f"{target} is schema version {version} and there is no "
                            f"migration step to {step} (this tool writes {SCHEMA_VERSION})")
                    migrate(conn)
            conn.execute(f"PRAGMA user_version={int(SCHEMA_VERSION)}")
    except Exception:
        conn.close()
        raise
    return conn


def _user_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return {name for (name,) in rows}


# (child table, child column, parent table, parent column)
_LINKS = (
    ("observations", "source_id", "sources", "source_id"),
    ("market_snapshot", "obs_id", "observations", "obs_id"),
    ("market_item", "obs_id", "market_snapshot", "obs_id"),
    ("faction_presence", "obs_id", "observations", "obs_id"),
    ("conflict", "obs_id", "observations", "obs_id"),
    ("construction_reading", "obs_id", "observations", "obs_id"),
    ("construction_contribution", "obs_id", "observations", "obs_id"),
    ("trade", "obs_id", "observations", "obs_id"),
)


def verify(conn: sqlite3.Connection) -> list[str]:
    """Every problem found, as one sentence each. Empty means sound."""
    problems: list[str] = []
    try:
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:      # a file SQLite cannot even read
        check = str(exc)
    if check != "ok":
        problems.append(f"integrity_check: {check}")
        return problems       # nothing below can be trusted on a broken file
    present = _user_tables(conn)
    known = registry.names()
    for name in sorted(present - known):
        problems.append(f"table {name} is not registered (this tool did not make it)")
    for name in sorted(known - present):
        problems.append(f"table {name} is missing")
    for child, column, parent, key in _LINKS:
        if child not in present or parent not in present:
            continue
        count = conn.execute(
            f"SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p "
            f"ON c.{column} = p.{key} WHERE p.{key} IS NULL").fetchone()[0]
        if count:
            problems.append(f"{count} row(s) in {child} point at a {parent} row that is gone")
    return problems


LIVENESS = ("present", "absent", "retired")


def verify_sources(conn: sqlite3.Connection, machine: Optional[str] = None) -> dict:
    """
    Re-check every journal source recorded for this machine against the world.

    A journal file that is where the row says, with the first line it was
    recorded by, is ``present`` and the row's ``last_verified`` moves; one
    that is missing, or whose first line no longer matches, is ``absent``.
    ``retired`` is a person's statement and is never changed here. Side
    files are ``absent`` from the start and stay so; sources recorded by
    another machine cannot be checked from this one and are counted, not
    touched. Returns the counts by liveness, plus ``elsewhere``.
    """
    from .ingest import SOURCE_KIND, identity_of

    host = machine or socket.gethostname()
    stamp = now_utc()
    counts = {name: 0 for name in LIVENESS}
    counts["elsewhere"] = 0
    with conn:
        rows = conn.execute(
            "SELECT source_id, kind, machine, locator, identity_hash, liveness FROM sources").fetchall()
        for source_id, kind, where, locator, identity, liveness in rows:
            if liveness == "retired":
                counts["retired"] += 1
                continue
            if where != host:
                counts["elsewhere"] += 1
                continue
            if kind != SOURCE_KIND:
                counts[liveness] += 1          # a side file: never verifiable, stays absent
                continue
            found = identity_of(Path(locator)) == identity
            state = "present" if found else "absent"
            if found:
                conn.execute("UPDATE sources SET liveness = 'present', last_verified = ? "
                             "WHERE source_id = ?", (stamp, source_id))
            else:
                conn.execute("UPDATE sources SET liveness = 'absent' WHERE source_id = ?",
                             (source_id,))
            counts[state] += 1
    return counts


def backup_set(conn: sqlite3.Connection) -> list[int]:
    """
    The observations the world cannot regenerate: every row whose source is
    not ``present``. This is what a backup is the only other home of; it
    shrinks when a source comes back and grows when one goes.
    """
    rows = conn.execute(
        "SELECT o.obs_id FROM observations o JOIN sources s USING (source_id) "
        "WHERE s.liveness != 'present' ORDER BY o.obs_id").fetchall()
    return [int(obs_id) for (obs_id,) in rows]


def retire(conn: sqlite3.Connection, source: object) -> tuple:
    """
    Mark one source ``retired`` -- known permanently gone -- by id or locator.

    No row moves: the observations stay where they are and join the backup
    set by virtue of the flag, and ``verify`` leaves a retired source alone
    until a person says otherwise. Refuses, by name, a source it cannot find.
    """
    row = None
    try:
        row = conn.execute("SELECT source_id, kind, machine, locator, liveness FROM sources "
                           "WHERE source_id = ?", (int(str(source)),)).fetchone()
    except ValueError:
        pass
    if row is None:
        row = conn.execute("SELECT source_id, kind, machine, locator, liveness FROM sources "
                           "WHERE locator = ?", (str(source),)).fetchone()
    if row is None:
        raise StoreError(f"retire refused: no source {source!r} (by id or locator)")
    with conn:
        conn.execute("UPDATE sources SET liveness = 'retired' WHERE source_id = ?", (row[0],))
    return row


def sources(conn: sqlite3.Connection) -> list[tuple]:
    """Every source row the verbs name: (id, kind, machine, liveness, events, locator)."""
    return conn.execute(
        "SELECT source_id, kind, machine, liveness, "
        "(SELECT COUNT(*) FROM observations o WHERE o.source_id = s.source_id), locator "
        "FROM sources s ORDER BY source_id").fetchall()


def backup(conn: sqlite3.Connection, stamp: Optional[str] = None) -> Path:
    """
    Copy the store to ``<file>.bak-<stamp>`` beside it, after ``verify`` passes.

    Refuses (``StoreError``) when verify finds anything: the previous backup
    is a known-good copy and a corrupt store must not replace it.
    """
    problems = verify(conn)
    if problems:
        raise StoreError("backup refused; verify found: " + "; ".join(problems))
    source = _file_of(conn)
    when = stamp or now_utc().replace(":", "").replace("-", "")
    destination = source.with_name(f"{source.name}.bak-{when}")
    copy = sqlite3.connect(destination)
    try:
        conn.backup(copy)
    finally:
        copy.close()
    return destination


def rebuild(conn: sqlite3.Connection) -> list[str]:
    """
    Drop and re-project every derived table. Returns their names.

    Primary tables are not read for writing and not written at all: the
    projectors only ``SELECT`` from them. Refuses when the registry holds
    nothing derived -- a rebuild that could drop nothing would be a no-op
    that looked like an action.
    """
    derived = registry.derived()
    if not derived:
        raise StoreError(
            "rebuild refused: nothing derived -- every table in this store is "
            "primary, and rebuild only regenerates derived ones")
    with conn:
        for table in reversed(derived):
            conn.execute(f"DROP TABLE IF EXISTS {table.name}")
        for table in derived:
            conn.execute(table.ddl)
        for statement in INDEXES:
            conn.execute(statement)
        for table in derived:
            if table.projector is not None:
                table.projector(conn)
    return [table.name for table in derived]


def archive(kind: str, payload: bytes, *, locator: str, subject: Optional[str] = None,
            observed_at: Optional[str] = None, commander: Optional[str] = None,
            commander_fid: Optional[str] = None, machine: Optional[str] = None,
            conn: Optional[sqlite3.Connection] = None) -> Optional[int]:
    """
    Keep one read: the bytes, where they came from, and when. Never raises.

    Returns the ``obs_id`` -- the existing one when these exact bytes of
    this kind were kept before, since a re-read of an unchanged file is not
    a new observation. ``None`` means the store could not take it; that was
    reported once and the caller carries on, because the store is additive
    and a spreadsheet update must not fail over bookkeeping.

    The source row is keyed by (machine, locator, content) and is marked
    ``absent`` from the start for a side file: the game overwrites it, so
    it can never be re-verified against what it held.
    """
    if os.environ.get(GUARD_VAR):
        return None
    own = conn is None
    try:
        if own:
            conn = open_store()
        stamp = now_utc()
        digest = sha256(payload)
        host = machine or socket.gethostname()
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO sources (kind, machine, commander, commander_fid, "
                "locator, identity_hash, first_seen, last_verified, liveness, ingested_bytes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'absent', ?)",
                (kind, host, commander, commander_fid, locator, digest, stamp, stamp, len(payload)))
            source_id = conn.execute(
                "SELECT source_id FROM sources WHERE machine=? AND locator=? AND identity_hash=?",
                (host, locator, digest)).fetchone()[0]
            obs_id, _ = keep(conn, source_id, kind, payload, subject=subject, observed_at=observed_at)
            return obs_id
    except Exception as exc:                      # the store is additive
        settings.report_once(store_path(), f"store: could not archive {kind}: {exc}")
        return None
    finally:
        if own and conn is not None:
            conn.close()


def keep(conn: sqlite3.Connection, source_id: int, kind: str, payload: bytes, *,
         subject: Optional[str] = None, observed_at: Optional[str] = None,
         deltas: bool = True) -> tuple[int, bool]:
    """
    One observation under an existing source, or the row these bytes already have.

    Returns ``(obs_id, new)``. The caller holds the transaction: ``archive``
    for a side file, the journal ingest for a line of a file it is reading.
    The row is projected as it is kept; ``deltas=False`` leaves the per-site
    construction delta for the caller to recompute once, which the ingest
    does per file rather than per event.
    """
    stamp = now_utc()
    digest = sha256(payload)
    existing = conn.execute(
        "SELECT obs_id FROM observations WHERE kind=? AND content_sha256=?",
        (kind, digest)).fetchone()
    if existing:
        return int(existing[0]), False
    cursor = conn.execute(
        "INSERT INTO observations (source_id, kind, subject, observed_at, recorded_at, "
        "content_sha256, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (source_id, kind, subject, observed_at or stamp, stamp, digest, payload))
    obs_id = int(cursor.lastrowid)
    from .projections import project_one
    project_one(conn, obs_id, kind, payload, observed_at or stamp, deltas=deltas)
    return obs_id, True
