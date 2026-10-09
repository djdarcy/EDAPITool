"""
The journal ingest: every journal file read once, from the position the
store last recorded for it, and the events the store indexes kept as
observations (the store design of 2026-10-09, unit 2; #22's criteria 6,
8, 9 and 10).

A journal file is a SOURCE the store can go back to -- unlike a side file,
which the game overwrites -- so one ``sources`` row stands for the file:
keyed by (machine, path, the hash of its first line), carrying the read
position (``read_offset``) the next ingest resumes from, the commander the
file named, and the game version its header gave. A file read to the end
with nothing worth keeping still gets its row, so the next ingest skips it
by position rather than reading it again. The events kept are the ones the
criteria name (``KEPT``); the rest of the 600,000-odd lines in a real
journal directory are read past and never parsed.

The daemon's watcher feeds the same path: it primes from the store's
position for the newest file (which stops short of a half-written last
line, where the file's size does not) and hands each poll's new bytes to
``sync``. ``ED_NO_STORE`` turns all of it off, and the watcher then
behaves as it did before the store.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .. import settings
from . import GUARD_VAR, keep, now_utc, open_store, sha256, store_path
from .projections import delta

#: The journal events the store keeps, each with the field naming its subject
#: (``None`` when the event has no one subject). The kind an observation is
#: recorded under is the event's name lower-cased, so ``market`` is the
#: journal event and ``market_json`` the side file read beside it.
KEPT: dict[str, Optional[str]] = {
    # where the commander is: the BGS criteria key on the system address
    "Location": "SystemAddress",
    "FSDJump": "SystemAddress",
    "CarrierJump": "SystemAddress",
    "Docked": "MarketID",
    # colonisation
    "ColonisationConstructionDepot": "MarketID",
    "ColonisationContribution": "MarketID",
    # transactions
    "MarketBuy": "MarketID",
    "MarketSell": "MarketID",
    "CargoTransfer": None,
    # identity
    "Fileheader": None,
    "LoadGame": "FID",
    "Commander": "FID",
    # the side-file markers (the file itself is archived when it is read)
    "Market": "MarketID",
    "Cargo": None,
    "Shipyard": "MarketID",
    "Outfitting": "MarketID",
    # the carrier
    "CarrierStats": "CarrierID",
    "CarrierTradeOrder": "CarrierID",
    "CarrierDepositFuel": "CarrierID",
    "CarrierFinance": "CarrierID",
}

SOURCE_KIND = "journal"
CONSTRUCTION_EVENTS = ("ColonisationConstructionDepot", "ColonisationContribution")

# The game writes ``"event":"Name"`` with no spaces; the tolerant form costs
# nothing and spares a parse of every line that is not kept.
_EVENT = re.compile(rb'"event"\s*:\s*"([A-Za-z]+)"')


@dataclass(frozen=True)
class FileResult:
    """One file's ingest: where the read began and ended, and what it kept."""

    path: Path
    source_id: int
    read_from: int
    read_to: int
    kept: int = 0
    new: int = 0

    @property
    def unchanged(self) -> bool:
        return self.read_from == self.read_to


@dataclass
class IngestResult:
    """A directory's ingest, file by file, with the totals the verb prints."""

    store: Optional[Path]
    files: list[FileResult] = field(default_factory=list)
    pending: int = 0          # files with no complete first line yet
    guarded: bool = False     # ED_NO_STORE was set; nothing was touched

    @property
    def read(self) -> int:
        return len(self.files)

    @property
    def unchanged(self) -> int:
        return sum(1 for f in self.files if f.unchanged)

    @property
    def kept(self) -> int:
        return sum(f.kept for f in self.files)

    @property
    def new(self) -> int:
        return sum(f.new for f in self.files)

    @property
    def bytes(self) -> int:
        return sum(f.read_to - f.read_from for f in self.files)


def identity_of(path: Path) -> Optional[str]:
    """
    A journal file's identity: the hash of its first line, which the game
    writes once (the ``Fileheader``) and never rewrites, so the identity
    holds while the file grows. ``None`` when the file has no complete
    first line yet -- the game has created it and not written it -- and
    the ingest leaves it for next time rather than record a source it
    would have to rename.
    """
    try:
        with open(path, "rb") as handle:
            first = handle.readline()
    except OSError:
        return None
    if not first.endswith(b"\n"):
        return None
    return sha256(first.rstrip(b"\r\n"))


def _learned(name: str, event: dict) -> dict:
    """What a kept event tells the source row about itself."""
    if name == "Fileheader":
        return {"game_version": event.get("gameversion"), "game_build": event.get("build")}
    if name == "LoadGame":
        return {"commander": event.get("Commander"), "commander_fid": event.get("FID")}
    if name == "Commander":
        return {"commander": event.get("Name"), "commander_fid": event.get("FID")}
    return {}


def ingest_file(conn: sqlite3.Connection, path: Path, *,
                machine: Optional[str] = None) -> Optional[FileResult]:
    """
    Read one journal file from the store's position for it to its end.

    One transaction per file, so a crash leaves the position and the
    observations it covers consistent. A half-written last line is not
    consumed; the position stops before it. A file shorter than its
    recorded position (replaced under the same name) is read from the top,
    and the content hash on every observation makes that safe.
    """
    identity = identity_of(path)
    if identity is None:
        return None
    host = machine or socket.gethostname()
    locator = str(path)
    stamp = now_utc()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO sources (kind, machine, locator, identity_hash, "
            "first_seen, last_verified, liveness) VALUES (?, ?, ?, ?, ?, ?, 'present')",
            (SOURCE_KIND, host, locator, identity, stamp, stamp))
        source_id, offset, yielded = conn.execute(
            "SELECT source_id, read_offset, events_yielded FROM sources "
            "WHERE machine=? AND locator=? AND identity_hash=?",
            (host, locator, identity)).fetchone()
        try:
            size = path.stat().st_size
        except OSError:
            return FileResult(path, source_id, offset, offset)
        if size < offset:
            offset = 0
        if size == offset:
            return FileResult(path, source_id, offset, offset)

        with open(path, "rb") as handle:
            handle.seek(offset)
            data = handle.read()
        consumed = offset
        kept = new = 0
        learned: dict = {}
        sites: set[int] = set()       # whose delta row is recomputed once, below
        for raw in data.splitlines(keepends=True):
            if not raw.endswith(b"\n"):
                break                     # half-written: next time
            consumed += len(raw)
            line = raw.rstrip(b"\r\n")
            match = _EVENT.search(line)
            if match is None:
                continue
            name = match.group(1).decode("ascii")
            if name not in KEPT:
                continue
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(event, dict) or event.get("event") != name:
                continue
            learned.update({k: v for k, v in _learned(name, event).items() if v is not None})
            field_name = KEPT[name]
            subject = event.get(field_name) if field_name else None
            _, fresh = keep(conn, source_id, name.lower(), line,
                            subject=str(subject) if subject is not None else None,
                            observed_at=event.get("timestamp"), deltas=False)
            kept += 1
            new += int(fresh)
            if fresh and name in CONSTRUCTION_EVENTS and isinstance(subject, int):
                sites.add(subject)
        # A site's delta row aggregates every reading it has; recomputing it
        # per depot event made a long build's ingest quadratic (two minutes
        # for one site's 4,973 readings). Once per file is the same answer.
        for site in sites:
            delta(conn, site)
        conn.execute(
            "UPDATE sources SET read_offset=?, ingested_bytes=?, events_yielded=?, "
            "last_verified=?, liveness='present', "
            "commander=COALESCE(?, commander), commander_fid=COALESCE(?, commander_fid), "
            "game_version=COALESCE(?, game_version), game_build=COALESCE(?, game_build) "
            "WHERE source_id=?",
            (consumed, consumed, yielded + kept, stamp,
             learned.get("commander"), learned.get("commander_fid"),
             learned.get("game_version"), learned.get("game_build"), source_id))
    return FileResult(path, source_id, offset, consumed, kept, new)


def ingest_dir(directory: Path, *, machine: Optional[str] = None,
               conn: Optional[sqlite3.Connection] = None) -> IngestResult:
    """
    Every journal file in ``directory``, oldest first, each from its position.

    The one door that CREATES the store: ``verify``, ``backup`` and
    ``rebuild`` never do, but an ingest with nothing to write into would be
    an ingest of nothing.
    """
    if os.environ.get(GUARD_VAR):
        return IngestResult(store=None, guarded=True)
    from ..journal import journal_sort_key

    own = conn is None
    if own:
        conn = open_store()
    result = IngestResult(store=store_path())
    try:
        for path in sorted(Path(directory).glob("Journal.*.log"), key=journal_sort_key):
            outcome = ingest_file(conn, path, machine=machine)
            if outcome is None:
                result.pending += 1
            else:
                result.files.append(outcome)
    finally:
        if own:
            conn.close()
    return result


def sync(path: Path, *, machine: Optional[str] = None) -> Optional[int]:
    """
    The watcher's door: bring the store up to date with one file and return
    the position it stopped at. ``None`` means there is no store to speak
    of -- the guard is set, or the store could not take the file (reported
    once) -- and the watcher falls back to the file's size.
    """
    if os.environ.get(GUARD_VAR):
        return None
    try:
        conn = open_store()
        try:
            outcome = ingest_file(conn, Path(path), machine=machine)
        finally:
            conn.close()
    except Exception as exc:                      # the store is additive
        settings.report_once(store_path(), f"store: could not ingest {path}: {exc}")
        return None
    return None if outcome is None else outcome.read_to
