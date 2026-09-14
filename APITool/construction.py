"""
What a colony construction site still needs, read from the game's own journal.

Elite Dangerous writes a ``ColonisationConstructionDepot`` event carrying the
complete state of a construction site: every commodity it wants, how much has
been handed over, and what it pays per tonne. That is the whole picture, so
this module does no arithmetic of consequence -- it parses and it tells the
truth about what it parsed.

Two things are worth knowing before reading further, because both shaped the
design and neither is obvious:

**The game states what was delivered.** ``ProvidedAmount`` is the figure a
tracking spreadsheet wants in its "delivered" column. Deriving it instead --
required minus remaining -- is possible and unnecessary, and the subtraction
is one more place to be wrong.

**The site is identified by ``MarketID``, not by name.** The same id appears on
the ``Docked`` event, so a site can be matched exactly. It cannot be *declared*
that way by a person, who has no way to see it; resolving a human-typed system
and station to an id is a separate concern and deliberately not this module's
(see :mod:`APITool.journal` for the dock events that make it possible).

No CAPI, no authentication, no cooldown. This is a local file, the same class
of source as ``Market.json`` and ``Cargo.json`` -- and unlike the fleet
carrier's manifest, which a probe established cannot be tracked from the
journal at all (``tests/one-offs/thinking/carrier-delta/poc.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

from .catalog import CommodityCatalog, normalize, strip_symbol

#: How long a site may go unmentioned before it is called "stale".
#: Not a game rule -- the game exposes no deadline and never marks a lapsed
#: build failed. 60 days is simply long enough that an active build will have
#: been visited, and short enough to separate a live effort from one abandoned
#: last year. Measured on a real journal: active builds were 0-3 days old and
#: an abandoned one was 303.
STALE_AFTER_DAYS = 60

#: Events that name a place and carry its market id. Docking is NOT required
#: to learn a name: approaching a settlement, or merely requesting docking,
#: records it. Measured across a 621-file journal: 2817 ApproachSettlement and
#: 1982 DockingRequested against 2314 Docked -- so reading only Docked throws
#: away more sightings than it keeps, and leaves a site the commander flew to
#: but chose not to land at with no name at all.
NAMING_EVENTS = (
    "Docked",
    "Undocked",
    "Location",
    "ApproachSettlement",
    "DockingRequested",
    "DockingGranted",
    "DockingDenied",
)

#: The journal event carrying a construction site's full state.
DEPOT_EVENT = "ColonisationConstructionDepot"
#: Emitted when cargo is handed over. A delta, where the above is the state.
CONTRIBUTION_EVENT = "ColonisationContribution"

#: Station types that identify a construction site, independent of its name.
#: Both were observed live: a planetary depot and an orbital one, in the same
#: system. Filtering on this beats looking for "Construction" in the station
#: name, which is a display string and not a contract.
DEPOT_STATION_TYPES = frozenset({"PlanetaryConstructionDepot", "SpaceConstructionDepot"})

#: The game prefixes a construction site's station name. A person reading their
#: own spreadsheet writes "Badeaux Nutrition Centre"; the journal says
#: "Planetary Construction Site: Badeaux Nutrition Centre". Any match against a
#: human-typed name has to survive that.
NAME_PREFIXES = (
    "Planetary Construction Site:",
    "Orbital Construction Site:",
    "Construction Site:",
    # A colonisation ship -- the first structure of a build -- names itself
    # with a game localization key rather than a display string:
    #   "$EXT_PANEL_ColonisationShip; Naim Territories"
    # Observed live on three sites. Left unstripped, a person could never type
    # a name that matched it.
    "$EXT_PANEL_ColonisationShip;",
)


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _parse_timestamp(raw: object) -> Optional[datetime]:
    if not raw:
        return None
    try:
        text = str(raw).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def station_key(name: object) -> str:
    """
    Normalize a station name so a person's version matches the game's.

    Strips the construction-site prefix before normalizing, so that
    "Badeaux Nutrition Centre" and
    "Planetary Construction Site: Badeaux Nutrition Centre"
    reduce to the same key. Returns "" for nothing usable.
    """
    text = str(name or "").strip()
    for prefix in NAME_PREFIXES:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break
    return normalize(text)


@dataclass(frozen=True)
class ConstructionResource:
    """One commodity a site wants, and how much of it has arrived."""

    symbol: str
    name: str
    required: int = 0
    provided: int = 0
    payment: int = 0

    @property
    def key(self) -> str:
        """The normalized display name, for matching against a sheet row."""
        return normalize(self.name)

    @property
    def remaining(self) -> int:
        """Still to deliver. Never negative: over-delivery is not a debt."""
        return max(0, self.required - self.provided)

    @property
    def satisfied(self) -> bool:
        return self.provided >= self.required

    @property
    def coverage(self) -> float:
        """Fraction delivered, clamped to [0, 1]. Zero required reads as done."""
        if self.required <= 0:
            return 1.0
        return max(0.0, min(1.0, self.provided / self.required))


@dataclass(frozen=True)
class ConstructionSite:
    """A snapshot of one construction site's requirements."""

    market_id: Optional[int]
    timestamp: Optional[datetime] = None
    progress: float = 0.0
    complete: bool = False
    failed: bool = False
    resources: tuple[ConstructionResource, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.resources)

    @property
    def total_required(self) -> int:
        return sum(r.required for r in self.resources)

    @property
    def total_provided(self) -> int:
        return sum(r.provided for r in self.resources)

    @property
    def total_remaining(self) -> int:
        return sum(r.remaining for r in self.resources)

    @property
    def measured_progress(self) -> float:
        """
        Progress computed from the resource rows, as a cross-check.

        The game reports ``ConstructionProgress`` directly and it was measured
        to be a plain tonnage ratio -- 5168/8517 = 0.6068, matching exactly.
        This recomputes it so a caller can notice if that ever stops being
        true, rather than assuming the relationship holds forever.
        """
        required = self.total_required
        if required <= 0:
            return 1.0 if self.complete else 0.0
        return self.total_provided / required

    @property
    def outstanding(self) -> tuple[ConstructionResource, ...]:
        """Only what is still owed, in descending order of what is missing."""
        return tuple(
            sorted(
                (r for r in self.resources if r.remaining > 0),
                key=lambda r: r.remaining,
                reverse=True,
            )
        )

    def age_days(self, now: Optional[datetime] = None) -> Optional[int]:
        """Days since the game last reported this site's state."""
        if self.timestamp is None:
            return None
        reference = now or datetime.now(timezone.utc)
        return max(0, (reference - self.timestamp).days)

    def status(
        self, now: Optional[datetime] = None, stale_after_days: int = STALE_AFTER_DAYS
    ) -> str:
        """
        One word for what this site is: complete, failed, stale, or active.

        **"stale" is an inference and the others are facts**, which is why it is
        worded that way rather than as "expired" or "abandoned". A colonisation
        deadline that passes does NOT set ``ConstructionFailed``: measured
        across a 621-file journal, a site left at 15.2% and untouched for 303
        days still reports ``failed: False``. The flag exists, the game simply
        never sets it, so silence cannot be read as "still going".

        All the tool can honestly say is how long it has been since the game
        last mentioned the site. A caller that wants to hide such sites should
        do so on that basis and say so, rather than claiming a verdict the
        journal never gave.
        """
        if self.failed:
            return "failed"
        if self.complete:
            return "complete"
        age = self.age_days(now)
        if age is not None and age >= stale_after_days:
            return "stale"
        return "active"

    def find(self, name: object) -> Optional[ConstructionResource]:
        """Look a commodity up by display name, however it is capitalised."""
        wanted = normalize(name)
        for resource in self.resources:
            if resource.key == wanted:
                return resource
        return None


def _resource_from_journal(
    entry: Mapping, catalog: Optional[CommodityCatalog] = None
) -> ConstructionResource:
    symbol = strip_symbol(entry.get("Name"))
    # Prefer the localised name the game supplies; fall back to the catalog,
    # then to the bare symbol, so an unrecognised commodity still appears
    # rather than vanishing from a total the sheet depends on.
    name = str(entry.get("Name_Localised") or "").strip()
    if not name and catalog is not None:
        commodity = catalog.by_symbol(symbol) if hasattr(catalog, "by_symbol") else None
        name = getattr(commodity, "display_name", "") or ""
    return ConstructionResource(
        symbol=symbol,
        name=name or symbol,
        required=_as_int(entry.get("RequiredAmount")),
        provided=_as_int(entry.get("ProvidedAmount")),
        payment=_as_int(entry.get("Payment")),
    )


def from_journal(
    event: Mapping, catalog: Optional[CommodityCatalog] = None
) -> ConstructionSite:
    """Build a site snapshot from one ``ColonisationConstructionDepot`` event."""
    entries = event.get("ResourcesRequired") or []
    resources = tuple(
        _resource_from_journal(entry, catalog)
        for entry in entries
        if isinstance(entry, Mapping)
    )
    return ConstructionSite(
        market_id=_as_int(event.get("MarketID"), default=0) or None,
        timestamp=_parse_timestamp(event.get("timestamp")),
        progress=float(event.get("ConstructionProgress") or 0.0),
        complete=bool(event.get("ConstructionComplete")),
        failed=bool(event.get("ConstructionFailed")),
        resources=resources,
    )


@dataclass(frozen=True)
class SiteLocation:
    """Where a construction site is, and what it is and was called."""

    market_id: int
    station: str = ""
    system: str = ""
    station_type: str = ""
    #: Every earlier name this market id has carried, oldest first.
    #: Sites really are renamed mid-build, and really do drop the
    #: "Planetary Construction Site: " prefix on completion -- measured on one
    #: market id that went "Abara Drilling Enterprise" -> "Beginning" ->
    #: "Beginning" (unprefixed) over two days, keeping its id throughout.
    previous_names: tuple[str, ...] = ()

    @property
    def short_station(self) -> str:
        """The station name without the game's construction-site prefix."""
        text = self.station.strip()
        for prefix in NAME_PREFIXES:
            if text.lower().startswith(prefix.lower()):
                return text[len(prefix):].strip()
        return text

    @property
    def former_names(self) -> tuple[str, ...]:
        """Earlier names, prefix-stripped, excluding the current one.

        A build renamed halfway leaves a spreadsheet declared under the old
        name matching nothing, with no indication why. Keeping the history is
        what lets a declaration go on working across a rename.
        """
        current = station_key(self.station)
        out, seen = [], {current}
        for name in self.previous_names:
            key = station_key(name)
            if key and key not in seen:
                seen.add(key)
                stripped = name
                for prefix in NAME_PREFIXES:
                    if stripped.lower().startswith(prefix.lower()):
                        stripped = stripped[len(prefix):].strip()
                        break
                out.append(stripped)
        return tuple(out)

    def answers_to(self, name: object) -> bool:
        """Whether this site has EVER been called `name`."""
        key = station_key(name)
        if not key:
            return False
        return key == station_key(self.station) or any(
            key == station_key(n) for n in self.previous_names
        )

    @property
    def describe(self) -> str:
        if not self.station and not self.system:
            return ""
        return f"{self.station} / {self.system}".strip(" /")


def locations_from_events(
    events: Iterable[Mapping], market_ids: Optional[Iterable[int]] = None
) -> dict[int, SiteLocation]:
    """
    Map ``MarketID`` to the name and system of the place it identifies.

    The depot event carries a site's contents but never its name; the ``Docked``
    event carries the name but not the contents. They share the market id, so
    joining them turns an opaque integer into something a person recognises --
    which matters in both directions. Reporting a site as "4312376579" is
    useless to a reader, and a person declaring one in a spreadsheet can only
    type the name.

    **This function does not decide what counts as a construction site**, and
    an earlier version that did was wrong in a way worth recording. It filtered
    docks by ``StationType``, accepting only the two depot types -- which
    silently hid three real sites, because a colonisation ship docks as a plain
    ``SurfaceStation`` and is indistinguishable by type from any surface port.
    The symptom was three builds reported as "(name unknown)" at every scan
    depth, which reads as missing data rather than as a filter excluding it.

    So identity comes from the depot events, which is the only source that
    actually knows; pass their market ids as ``market_ids`` and this resolves
    names for exactly those. With no ids it resolves every dock it sees.
    """
    wanted = set(market_ids) if market_ids is not None else None
    found: dict[int, SiteLocation] = {}
    for event in events:
        if not isinstance(event, Mapping) or event.get("event") not in NAMING_EVENTS:
            continue
        market_id = _as_int(event.get("MarketID"), default=0)
        if not market_id or (wanted is not None and market_id not in wanted):
            continue
        # ApproachSettlement names the place in `Name`; the docking events use
        # `StationName`. Same fact, two spellings.
        name = str(event.get("StationName") or event.get("Name") or "")
        if not name:
            continue
        history = found[market_id].previous_names if market_id in found else ()
        earlier = found[market_id].station if market_id in found else ""
        if earlier and earlier != name and earlier not in history:
            history = history + (earlier,)
        # MERGE, never replace. Only some naming events carry a system or a
        # station type -- ApproachSettlement and DockingRequested give a name
        # and nothing else -- so overwriting wholesale erases fields a richer
        # earlier event had already supplied. Taking the latest event and
        # letting it null out the system is how four sites lost theirs.
        previous = found.get(market_id)
        found[market_id] = SiteLocation(
            market_id=market_id,
            station=name,
            system=str(event.get("StarSystem") or "") or (previous.system if previous else ""),
            station_type=(
                str(event.get("StationType") or "")
                or (previous.station_type if previous else "")
            ),
            previous_names=history,
        )
    return found


def sites_from_events(
    events: Iterable[Mapping], catalog: Optional[CommodityCatalog] = None
) -> dict[int, ConstructionSite]:
    """
    The latest state of every construction site in a run of journal events.

    Keyed by ``MarketID`` and last-one-wins, because the event carries the
    site's whole state rather than a delta -- a commander bouncing between two
    builds emits interleaved events for both, and each must end up with its own
    most recent snapshot rather than a merge of the two.
    """
    sites: dict[int, ConstructionSite] = {}
    for event in events:
        if not isinstance(event, Mapping) or event.get("event") != DEPOT_EVENT:
            continue
        site = from_journal(event, catalog)
        if site.market_id is not None:
            sites[site.market_id] = site
    return sites


__all__ = [
    "CONTRIBUTION_EVENT",
    "NAMING_EVENTS",
    "STALE_AFTER_DAYS",
    "SiteLocation",
    "locations_from_events",
    "DEPOT_EVENT",
    "DEPOT_STATION_TYPES",
    "ConstructionResource",
    "ConstructionSite",
    "from_journal",
    "sites_from_events",
    "station_key",
]
