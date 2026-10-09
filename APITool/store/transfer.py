"""
Export and import: the primary tables as one JSON document, lossless (the
store design of 2026-10-09, unit 5; #22's criteria 7, 14 and 16).

Only the primary tables travel -- ``sources``, ``observations``,
``writes`` -- because the derived ones are a ``rebuild`` away and a
backup that carried them would be a backup that could disagree with
itself. A payload that is UTF-8 text (every kind the tool keeps today is
JSON) is written as that text, so the file is readable; any other bytes
go as base64. Rows are written in id order and the document carries no
timestamp, so exporting the same store twice gives the same bytes.

Import into an empty store keeps the exported ids, so export -> fresh
store -> import -> export is byte-identical (criterion 16). Import into
a store that already has rows merges: a source is matched by (machine,
locator, identity), an observation by (kind, content hash), and whatever
is already there is skipped -- two overlapping backups of one machine
leave the counts unchanged (criterion 7), and two commanders' rows stay
two commanders' rows because nothing about the keys names the commander
(criterion 14).
"""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import StoreError, keep, now_utc, rebuild, store_path
from .schema import SCHEMA_VERSION

FORMAT = "edapitool-store"

_SOURCE_COLUMNS = ("source_id", "kind", "machine", "commander", "commander_fid", "locator",
                   "identity_hash", "first_seen", "last_verified", "liveness", "events_yielded",
                   "read_offset", "ingested_bytes", "game_version", "game_build")
_OBS_COLUMNS = ("obs_id", "source_id", "kind", "subject", "observed_at", "recorded_at",
                "content_sha256")
_WRITE_COLUMNS = ("target", "tab", "a1", "value", "written_at", "run_id")


def _payload_out(payload: bytes) -> dict:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return {"payload_b64": base64.b64encode(payload).decode("ascii")}
    if text.encode("utf-8") != payload:        # cannot happen for valid UTF-8, but say so
        return {"payload_b64": base64.b64encode(payload).decode("ascii")}
    return {"payload": text}


def _payload_in(row: dict) -> bytes:
    if "payload_b64" in row:
        return base64.b64decode(row["payload_b64"])
    return str(row.get("payload", "")).encode("utf-8")


def export_document(conn: sqlite3.Connection) -> dict:
    """The primary tables as one document, rows in id order."""
    sources = [dict(zip(_SOURCE_COLUMNS, row)) for row in conn.execute(
        f"SELECT {', '.join(_SOURCE_COLUMNS)} FROM sources ORDER BY source_id")]
    observations = []
    for row in conn.execute(
            f"SELECT {', '.join(_OBS_COLUMNS)}, payload FROM observations ORDER BY obs_id"):
        record = dict(zip(_OBS_COLUMNS, row[:-1]))
        record.update(_payload_out(row[-1]))
        observations.append(record)
    writes = [dict(zip(_WRITE_COLUMNS, row)) for row in conn.execute(
        f"SELECT {', '.join(_WRITE_COLUMNS)} FROM writes ORDER BY target, tab, a1")]
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "sources": sources,
        "observations": observations,
        "writes": writes,
    }


def export_store(conn: sqlite3.Connection, path: Optional[Path] = None) -> Path:
    """Write the document to ``path`` (default: ``<store>.export-<stamp>.json`` beside the store)."""
    if path is None:
        stamp = now_utc().replace(":", "").replace("-", "")
        store = store_path()
        path = store.with_name(f"{store.name}.export-{stamp}.json")
    document = export_document(conn)
    text = json.dumps(document, ensure_ascii=False, indent=1, sort_keys=False)
    Path(path).write_text(text + "\n", encoding="utf-8")
    return Path(path)


@dataclass
class ImportResult:
    sources_new: int = 0
    sources_matched: int = 0
    observations_new: int = 0
    observations_skipped: int = 0
    writes_new: int = 0
    fresh: bool = False


def _read_document(path: Path) -> dict:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise StoreError(f"import refused: {path} is not a store export ({exc})") from exc
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise StoreError(f"import refused: {path} is not a store export (no {FORMAT!r} format)")
    version = document.get("schema_version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        raise StoreError(
            f"import refused: {path} was exported at schema version {version}, newer than "
            f"this tool's {SCHEMA_VERSION}")
    return document


def import_file(conn: sqlite3.Connection, path: Path) -> ImportResult:
    """
    Bring a document's rows into the store.

    An empty store takes the rows as they are, ids included, then rebuilds
    its derived tables. A store with rows merges, keyed as the module
    docstring says, and projects each new observation as it is kept.
    """
    document = _read_document(Path(path))
    result = ImportResult()
    empty = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0 and \
        conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    sources = document.get("sources") or []
    observations = document.get("observations") or []
    writes = document.get("writes") or []
    with conn:
        if empty:
            result.fresh = True
            conn.executemany(
                f"INSERT INTO sources ({', '.join(_SOURCE_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _SOURCE_COLUMNS)})",
                [tuple(row.get(c) for c in _SOURCE_COLUMNS) for row in sources])
            conn.executemany(
                f"INSERT INTO observations ({', '.join(_OBS_COLUMNS)}, payload) "
                f"VALUES ({', '.join('?' for _ in _OBS_COLUMNS)}, ?)",
                [tuple(row.get(c) for c in _OBS_COLUMNS) + (_payload_in(row),)
                 for row in observations])
            result.sources_new = len(sources)
            result.observations_new = len(observations)
        else:
            mapping: dict[Any, int] = {}
            for row in sources:
                key = (row.get("machine"), row.get("locator"), row.get("identity_hash"))
                found = conn.execute(
                    "SELECT source_id FROM sources WHERE machine=? AND locator=? AND identity_hash=?",
                    key).fetchone()
                if found:
                    mapping[row.get("source_id")] = int(found[0])
                    result.sources_matched += 1
                    continue
                columns = [c for c in _SOURCE_COLUMNS if c != "source_id"]
                cursor = conn.execute(
                    f"INSERT INTO sources ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    tuple(row.get(c) for c in columns))
                mapping[row.get("source_id")] = int(cursor.lastrowid)
                result.sources_new += 1
            for row in observations:
                source_id = mapping.get(row.get("source_id"))
                if source_id is None:
                    raise StoreError(
                        f"import refused: observation {row.get('obs_id')} names source "
                        f"{row.get('source_id')}, which the document does not carry")
                _, fresh = keep(conn, source_id, row["kind"], _payload_in(row),
                                subject=row.get("subject"), observed_at=row.get("observed_at"))
                if fresh:
                    result.observations_new += 1
                else:
                    result.observations_skipped += 1
        before = conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0]
        conn.executemany(
            f"INSERT OR IGNORE INTO writes ({', '.join(_WRITE_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _WRITE_COLUMNS)})",
            [tuple(row.get(c) for c in _WRITE_COLUMNS) for row in writes])
        result.writes_new = conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0] - before
    if result.fresh and (sources or observations):
        rebuild(conn)
    return result
