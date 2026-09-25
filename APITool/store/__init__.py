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
    "verify", "backup", "rebuild", "archive", "now_utc", "sha256",
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
            existing = conn.execute(
                "SELECT obs_id FROM observations WHERE kind=? AND content_sha256=?",
                (kind, digest)).fetchone()
            if existing:
                return int(existing[0])
            cursor = conn.execute(
                "INSERT INTO observations (source_id, kind, subject, observed_at, recorded_at, "
                "content_sha256, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source_id, kind, subject, observed_at or stamp, stamp, digest, payload))
            obs_id = int(cursor.lastrowid)
            from .market import project_one
            project_one(conn, obs_id, kind, payload, observed_at or stamp)
            return obs_id
    except Exception as exc:                      # the store is additive
        settings.report_once(store_path(), f"store: could not archive {kind}: {exc}")
        return None
    finally:
        if own and conn is not None:
            conn.close()
