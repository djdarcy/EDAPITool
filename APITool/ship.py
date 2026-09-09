"""
The current ship's cargo hold, from the game's ``Cargo.json``.

This is the ship you are flying, not the fleet carrier. The two are different
inventories that happen to share a vocabulary, and the project keeps them in
separate tabs for that reason: they hold different commodity sets, so merging
them would mean maintaining a union with gaps in it.

The module emits DATA and nothing else -- no glyphs, no colours, no cell
addresses. A caller may want it as CSV, as JSON, or as a lookup grid for a
spreadsheet to read with its own formulas; all three come from the same
structures here, and none of them requires a spreadsheet to exist.

Two traps the game sets, both handled below:

1. ``Name_Localised`` is OMITTED when the localised name equals the raw one.
   ``biowaste`` has no localised name while ``powergenerators`` does, so a
   display-name-only lookup silently drops the first. Resolution goes through
   the catalog by SYMBOL first, then name.

2. ``Vessel`` distinguishes the ship's hold from the SRV's. They are written
   to the same file, so reporting SRV contents as ship cargo is a live
   possibility rather than a theoretical one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Optional

from .cargo import data_row, header_row
from .catalog import CommodityCatalog, normalize, strip_symbol

VESSEL_SHIP = "Ship"
VESSEL_SRV = "SRV"


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _parse_timestamp(raw: object) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class ShipCargoItem:
    """One commodity in the hold."""

    id: Optional[int]
    symbol: str
    name: str
    count: int = 0
    stolen: int = 0

    @property
    def key(self) -> str:
        """The normalized display name, for matching against a sheet row."""
        return normalize(self.name)


@dataclass(frozen=True)
class ShipCargo:
    """A snapshot of one vessel's hold."""

    vessel: str
    timestamp: Optional[datetime]
    count: int = 0
    items: tuple[ShipCargoItem, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def is_ship(self) -> bool:
        """
        Is this the ship's hold rather than the SRV's?

        Compared case-insensitively because the field is a game-written
        string, and a caller that gates a spreadsheet write on it should not
        be defeated by capitalisation.
        """
        return normalize(self.vessel) == normalize(VESSEL_SHIP)

    @property
    def age_seconds(self) -> Optional[float]:
        if self.timestamp is None:
            return None
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()

    @property
    def total(self) -> int:
        """Tonnage actually itemised, which may differ from the reported count."""
        return sum(item.count for item in self.items)

    def find(
        self,
        commodity_id: object = None,
        symbol: object = None,
        name: object = None,
    ) -> Optional[ShipCargoItem]:
        """Locate a held commodity by id, then symbol, then normalized name."""
        if commodity_id not in (None, ""):
            wanted = _as_int(commodity_id, -1)
            for item in self.items:
                if item.id == wanted:
                    return item
        if symbol not in (None, ""):
            wanted_symbol = normalize(strip_symbol(symbol))
            for item in self.items:
                if normalize(item.symbol) == wanted_symbol:
                    return item
        if name not in (None, ""):
            wanted_name = normalize(name)
            for item in self.items:
                if item.key == wanted_name:
                    return item
        return None

    def quantity_of(self, name: object) -> int:
        """How many of this commodity are aboard. Zero when none."""
        item = self.find(name=name)
        return item.count if item else 0


def _item_from_journal(
    raw: Mapping, catalog: Optional[CommodityCatalog]
) -> Optional[ShipCargoItem]:
    symbol = str(raw.get("Name") or "")
    if not symbol:
        return None
    localised = raw.get("Name_Localised")

    entry = None
    if catalog is not None:
        # Symbol first. `biowaste` arrives with no Name_Localised at all, so a
        # name-led lookup would miss precisely the commodity most likely to be
        # in the hold.
        entry = catalog.resolve(symbol=symbol, name=localised)

    if entry is not None:
        commodity_id, display = entry.id, entry.name
    else:
        # Unknown to the catalog: keep it rather than drop it. A commodity the
        # bundled table has not caught up with is still cargo, and a sheet row
        # matching its localised name should still find it.
        commodity_id = None
        display = str(localised or symbol)

    return ShipCargoItem(
        id=commodity_id,
        symbol=strip_symbol(symbol),
        name=display,
        count=_as_int(raw.get("Count")),
        stolen=_as_int(raw.get("Stolen")),
    )


def from_journal(
    data: Mapping, catalog: Optional[CommodityCatalog] = None
) -> ShipCargo:
    """
    Build a snapshot from a parsed ``Cargo.json``.

    The vessel is recorded rather than enforced: this function reports what
    the file says, and the caller decides whether an SRV hold is acceptable
    for its purpose. That keeps the refusal at the boundary where a useful
    message can be produced, instead of returning a bare ``None`` that
    discards the reason.
    """
    items: list[ShipCargoItem] = []
    for raw in data.get("Inventory") or ():
        if not isinstance(raw, Mapping):
            continue
        item = _item_from_journal(raw, catalog)
        if item is not None and item.count > 0:
            items.append(item)

    return ShipCargo(
        vessel=str(data.get("Vessel") or ""),
        timestamp=_parse_timestamp(data.get("timestamp")),
        count=_as_int(data.get("Count")),
        items=tuple(items),
    )


# ---------------------------------------------------------------------------
# Emission: the same snapshot as flat records or as a lookup grid
# ---------------------------------------------------------------------------

FLAT_FIELDS = [
    "vessel",
    "timestamp",
    "commodity",
    "commodity_id",
    "symbol",
    "count",
    "stolen",
]

# Right of Unit Price, where a cargo tab may carry whatever it actually has.
# The ship knows a commodity's internal symbol and whether it is stolen; it
# does not know a price, so column D stays blank until a reference price is
# wired in (issue #13 -- MeanPrice is verified as a galaxy-wide constant, so
# the column is prepared for data that is coming, not a shoehorn).
SHIP_EXTRA_HEADERS = ["Symbol", "Stolen"]

SHEET_HEADERS = header_row(SHIP_EXTRA_HEADERS)[1:]


def flat_rows(cargo: ShipCargo) -> list[dict]:
    """
    One self-contained record per commodity, sorted by display name.

    Vessel and timestamp repeat on every row so a row stays meaningful alone,
    which is what makes concatenating snapshots over time worth doing.
    """
    stamp = cargo.timestamp.isoformat() if cargo.timestamp else ""
    return [
        {
            "vessel": cargo.vessel,
            "timestamp": stamp,
            "commodity": item.name,
            "commodity_id": item.id if item.id is not None else "",
            "symbol": item.symbol,
            "count": item.count,
            "stolen": item.stolen,
        }
        for item in sorted(cargo.items, key=lambda i: i.key)
    ]


def sheet_grid(cargo: ShipCargo) -> list[list]:
    """
    The hold as a lookup table for a spreadsheet.

    Follows the shared cargo contract (see :mod:`APITool.cargo`): column A is
    a margin, and B/C/D are Commodity, Quantity and Unit Price on every cargo
    tab, so one VLOOKUP idiom works against all of them:

        =IFNA(VLOOKUP($B5, ShipCargo!$B:$D, 2, FALSE), "")   -> quantity
        =IFNA(VLOOKUP($B5, ShipCargo!$B:$D, 3, FALSE), "")   -> unit price

    Unit Price is emitted blank: the game's Cargo.json carries no prices. It
    is present rather than omitted because the indices are a published
    contract -- if this tab put Symbol at D, a unit-price lookup written
    against any cargo tab would return a symbol string here.

    Metadata occupies the first two rows, and as in MarketData its LABELS sit
    in the key column while its VALUES do not. No commodity is named "Vessel"
    or "Total Tonnage", so a lookup can never land on a metadata row; putting
    the values in column B would work today and become a latent collision the
    first time Frontier ships an oddly-named commodity.
    """
    stamp = cargo.timestamp.isoformat() if cargo.timestamp else ""
    grid: list[list] = [
        ["", "Vessel", cargo.vessel, "Updated (UTC)", stamp],
        ["", "Total Tonnage", cargo.total, "Items", len(cargo.items)],
        header_row(SHIP_EXTRA_HEADERS),
    ]
    for item in sorted(cargo.items, key=lambda i: i.key):
        grid.append(
            data_row(item.name, item.count, extra=[item.symbol, item.stolen])
        )
    return grid


def empty_sheet_grid(reason: str = "No ship cargo data") -> list[list]:
    """
    The grid to write when there is nothing current to report.

    Deliberately not "leave the previous contents alone". A tab still holding
    the last hold's contents, with nothing saying it is stale, would feed the
    spreadsheet's arithmetic a number that looks current and is not -- and
    column M subtracts into "Left to buy", so a stale value there quietly
    changes which commodities the tool recommends buying.
    """
    return [
        ["", "Vessel", reason, "Updated (UTC)", ""],
        ["", "Total Tonnage", 0, "Items", 0],
        header_row(SHIP_EXTRA_HEADERS),
    ]


"""
No ``learn_names`` here, deliberately, unlike ``market.py``.

The market path learns aliases because the GAME supplies the display names
there and they sometimes diverge from the reference table. Ship cargo names
come out of ``catalog.resolve`` already canonical, so there is nothing to
learn -- an alias function here would only ever re-register names the catalog
supplied in the first place.
"""

__all__ = [
    "FLAT_FIELDS",
    "SHEET_HEADERS",
    "VESSEL_SHIP",
    "VESSEL_SRV",
    "ShipCargo",
    "ShipCargoItem",
    "empty_sheet_grid",
    "flat_rows",
    "from_journal",
    "sheet_grid",
]
