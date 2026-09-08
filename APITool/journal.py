"""
Elite Dangerous journal reader: where the commander is, and whether the market
data on disk actually belongs to that place.

Why the journal rather than CAPI
--------------------------------
The game writes a ``Docked`` event the instant the commander docks, carrying
``StationName``, ``StarSystem`` and ``MarketID``. That is the trigger the whole
auto-update design rests on: no button, no polling of a remote service, no
certificate. CAPI remains the fallback for when the game is not running.

The freshness trap
------------------
``Market.json`` is rewritten ONLY when the commander opens the station's
commodity screen. Measured on 2026-09-08: the ``Docked`` event at Ryman
Enterprise fired at 02:14:10Z, but ``Market.json`` was not written until
03:13:00Z -- 59 minutes later. So the file on disk can easily describe a
station the commander has already left.

Comparing a shopping list against the previous station's prices produces
markers that look completely plausible and are entirely wrong. That is the
failure mode :meth:`LocationState.market_is_current` exists to prevent, and it
is why the comparison refuses rather than guesses.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

# Elite Dangerous has used two journal filename formats, and BOTH are present in
# a long-lived Saved Games folder:
#
#   Journal.220221113844.01.log          (legacy, YYMMDDHHMMSS)
#   Journal.2026-09-07T192642.01.log     (current, YYYY-MM-DDTHHMMSS)
#
# They cannot be compared as strings. Lexically "220221113844" sorts ABOVE
# "2026-09-07T192642" -- the third character decides it, '2' > '0' -- so a naive
# sort picks a 2022 file as "newest". Observed against a real 615-file journal
# directory: state was rebuilt from February 2022 and reported the wrong system.
_LEGACY_NAME = re.compile(r"^Journal\.(\d{12})\.(\d+)\.log$", re.IGNORECASE)
_MODERN_NAME = re.compile(
    r"^Journal\.(\d{4})-(\d{2})-(\d{2})T(\d{2})(\d{2})(\d{2})\.(\d+)\.log$", re.IGNORECASE
)

# Events that move the commander or change docking state, newest wins.
LOCATION_EVENTS = frozenset(
    {"Location", "Docked", "Undocked", "FSDJump", "CarrierJump", "CarrierJumpRequest"}
)

# Events worth waking the daemon for.
REFRESH_EVENTS = frozenset({"Docked", "Undocked", "Location", "FSDJump", "CarrierJump", "Market"})

NOT_DOCKED = "Not docked"


def default_journal_dir() -> Path:
    """
    Locate the journal directory.

    ``ED_JOURNAL_DIR`` overrides everything, which is what makes this testable
    and what lets a commander with a relocated Saved Games folder configure it.
    """
    override = os.environ.get("ED_JOURNAL_DIR")
    if override:
        return Path(override)

    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / "Saved Games" / "Frontier Developments" / "Elite Dangerous"


def journal_sort_key(path: Path) -> tuple[datetime, int, str]:
    """
    Order journal files chronologically across BOTH filename formats.

    Returns ``(recorded_time, part_number, name)``. Files whose name matches
    neither format fall back to their modification time, so an oddly-named
    file still sorts somewhere sane instead of poisoning the ordering.
    """
    name = path.name

    modern = _MODERN_NAME.match(name)
    if modern:
        year, month, day, hour, minute, second, part = modern.groups()
        return (
            datetime(int(year), int(month), int(day), int(hour), int(minute), int(second),
                     tzinfo=timezone.utc),
            int(part),
            name,
        )

    legacy = _LEGACY_NAME.match(name)
    if legacy:
        stamp, part = legacy.groups()
        try:
            return (
                datetime(
                    2000 + int(stamp[0:2]), int(stamp[2:4]), int(stamp[4:6]),
                    int(stamp[6:8]), int(stamp[8:10]), int(stamp[10:12]),
                    tzinfo=timezone.utc,
                ),
                int(part),
                name,
            )
        except ValueError:
            pass  # impossible date in the name; fall through to mtime

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (datetime.fromtimestamp(mtime, tz=timezone.utc), 0, name)


def _parse_timestamp(raw: object) -> Optional[datetime]:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class LocationState:
    """Where the commander is, as of the last event seen."""

    system: str = ""
    docked: bool = False
    station: Optional[str] = None
    station_type: Optional[str] = None
    market_id: Optional[int] = None
    has_commodity_market: bool = False
    commander: Optional[str] = None
    timestamp: Optional[datetime] = None

    @property
    def station_display(self) -> str:
        """What to write into the spreadsheet's station cell."""
        return self.station if (self.docked and self.station) else NOT_DOCKED

    def market_is_current(self, market_id: object) -> bool:
        """
        Is a market snapshot describing the station we are docked at *now*?

        False when not docked, when either id is missing, or when the ids
        differ. Callers must refuse to compare rather than fall back to
        whatever was on disk.
        """
        if not self.docked or self.market_id is None or market_id in (None, ""):
            return False
        try:
            return int(market_id) == int(self.market_id)
        except (TypeError, ValueError):
            return False

    def apply(self, event: dict) -> bool:
        """
        Fold one journal event into the state. Returns True if anything changed.
        """
        name = event.get("event")
        if name == "LoadGame":
            self.commander = event.get("Commander") or self.commander
            return False
        if name not in LOCATION_EVENTS:
            return False

        before = (self.system, self.docked, self.station, self.market_id)
        self.timestamp = _parse_timestamp(event.get("timestamp")) or self.timestamp

        if name == "Undocked":
            self.docked = False
            self.station = None
            self.station_type = None
            self.market_id = None
            self.has_commodity_market = False
            return before != (self.system, self.docked, self.station, self.market_id)

        if event.get("StarSystem"):
            self.system = str(event["StarSystem"])

        if name == "Docked" or (name == "Location" and event.get("Docked")):
            self.docked = True
            self.station = event.get("StationName") or self.station
            self.station_type = event.get("StationType") or self.station_type
            market_id = event.get("MarketID")
            self.market_id = int(market_id) if market_id is not None else None
            services = event.get("StationServices")
            if services is not None:
                self.has_commodity_market = "commodities" in services
            elif name == "Location":
                # A Location event does not always carry the service list.
                # Leave the previous belief rather than asserting there is no
                # market -- absence of evidence is not evidence of absence.
                pass
        elif name in ("FSDJump", "CarrierJump") or (name == "Location" and not event.get("Docked")):
            self.docked = False
            self.station = None
            self.station_type = None
            self.market_id = None
            self.has_commodity_market = False

        return before != (self.system, self.docked, self.station, self.market_id)


def iter_events(path: Path) -> Iterator[dict]:
    """
    Yield JSON events from one journal file.

    Tolerates a truncated final line: the game appends while we read, so the
    last line is routinely half-written. A malformed line is skipped, never
    fatal.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


class JournalReader:
    """Reads journal files and Market.json from a journal directory."""

    def __init__(self, journal_dir: Optional[Path] = None):
        self.journal_dir = Path(journal_dir) if journal_dir else default_journal_dir()

    def exists(self) -> bool:
        return self.journal_dir.is_dir()

    def journal_files(self) -> list[Path]:
        """
        All journal logs, oldest first.

        Ordered by the timestamp embedded in the filename, decoded per format
        -- NOT by raw string comparison, which mixes the two formats up, and
        not by mtime, which a file copy or a backup restore would scramble.
        """
        if not self.exists():
            return []
        return sorted(self.journal_dir.glob("Journal.*.log"), key=journal_sort_key)

    def latest_journal(self) -> Optional[Path]:
        files = self.journal_files()
        return files[-1] if files else None

    def read_state(self, scan_files: int = 3) -> LocationState:
        """
        Rebuild location state by replaying recent journal files.

        Replays more than one file because a session that began in a previous
        log leaves the newest file with no ``Location``/``Docked`` event at
        all -- the daemon must not conclude the commander is nowhere just
        because it started up mid-session.
        """
        state = LocationState()
        for path in self.journal_files()[-max(1, scan_files):]:
            for event in iter_events(path):
                state.apply(event)
        return state

    def read_market_json(self) -> Optional[dict]:
        """Read the game's Market.json, or None if absent/unreadable."""
        path = self.journal_dir / "Market.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # The game may be mid-write. Treat as "no data right now".
            return None

    def read_status(self) -> Optional[dict]:
        path = self.journal_dir / "Status.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


@dataclass
class JournalWatcher:
    """
    Follows the newest journal file and yields new events as they appear.

    Handles the two things that break naive tailing:
      * the game rolls to a NEW journal file on each session, so a held file
        handle silently stops receiving events;
      * the last line is often half-written, so a parse failure is normal and
        the offset must not advance past it.
    """

    reader: JournalReader
    _path: Optional[Path] = None
    _offset: int = 0
    state: LocationState = field(default_factory=LocationState)

    @classmethod
    def create(cls, journal_dir: Optional[Path] = None) -> "JournalWatcher":
        return cls(reader=JournalReader(journal_dir))

    def prime(self, scan_files: int = 3) -> LocationState:
        """
        Establish current state without emitting events for the backlog.

        Call once at startup: the daemon should know where the commander is,
        but must not fire an update for every dock in the session's history.
        """
        self.state = self.reader.read_state(scan_files=scan_files)
        latest = self.reader.latest_journal()
        if latest is not None:
            self._path = latest
            try:
                self._offset = latest.stat().st_size
            except OSError:
                self._offset = 0
        return self.state

    def poll(self) -> list[dict]:
        """
        Return journal events appended since the last call.

        Rolls onto a newer journal file when the game creates one, reading it
        from the beginning so no event is missed across the boundary.
        """
        latest = self.reader.latest_journal()
        if latest is None:
            return []

        if self._path is None or latest != self._path:
            self._path = latest
            self._offset = 0

        try:
            size = latest.stat().st_size
        except OSError:
            return []

        if size < self._offset:
            # File truncated or replaced under us; restart from the top.
            self._offset = 0
        if size == self._offset:
            return []

        events: list[dict] = []
        try:
            with open(latest, "r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self._offset)
                data = handle.read()
                consumed = self._offset
                for line in data.splitlines(keepends=True):
                    if not line.endswith("\n"):
                        # Partial final line -- leave it for the next poll.
                        break
                    consumed += len(line.encode("utf-8", errors="replace"))
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        events.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        continue
                self._offset = consumed
        except OSError:
            return []

        for event in events:
            self.state.apply(event)
        return events

    def poll_for_refresh(self) -> list[str]:
        """
        Poll and return the names of events that should trigger a sheet update.

        Returns a list rather than a bool so the caller can log what happened
        and debounce a burst -- 19 ``Market`` events were observed in a single
        play session.
        """
        return [
            event.get("event", "")
            for event in self.poll()
            if event.get("event") in REFRESH_EVENTS
        ]


__all__ = [
    "JournalReader",
    "JournalWatcher",
    "LOCATION_EVENTS",
    "LocationState",
    "NOT_DOCKED",
    "REFRESH_EVENTS",
    "default_journal_dir",
    "iter_events",
    "journal_sort_key",
]
