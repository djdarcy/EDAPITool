"""
A station's commodity market, normalized across its two possible sources.

Elite Dangerous exposes the same market twice, and the two do not agree on
coverage. Measured at Ryman Enterprise (2026-09-08, MarketID 3226578176):

    journal Market.json : 366 items, 21 with stock
    Frontier CAPI       :  92 items, 22 with stock

Every item the journal reported as stocked was present in CAPI, and the six
numeric disagreements were all off-by-one -- a timing artifact, not a conflict.
But each source knows something the other does not:

  * The journal carries a buy price for commodities the station normally sells
    but is currently out of (Land Enrichment Systems: BuyPrice 3404, Stock 0).
    CAPI omits those rows entirely, so it cannot tell "out of stock" from
    "not traded here".
  * CAPI carries items the journal's Market.json omits, including Limpet with
    393,086 in stock -- a journal-only design would report it unavailable.

So neither source is a superset. :func:`merge` unions them: the live source
wins on shared items, the broader source fills the gaps.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

from .catalog import CommodityCatalog, normalize, strip_symbol

SOURCE_JOURNAL = "journal"
SOURCE_CAPI = "capi"
SOURCE_MERGED = "merged"


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _parse_timestamp(raw: object) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class MarketItem:
    """One commodity as offered by one station."""

    id: int
    symbol: str
    name: str
    stock: int = 0
    buy_price: int = 0
    demand: int = 0
    sell_price: int = 0
    category: str = ""
    source: str = ""

    @property
    def key(self) -> str:
        return normalize(self.name)

    @property
    def is_purchasable(self) -> bool:
        """
        True only when the station will actually sell units right now.

        Both conditions matter: a zero buy price means the station does not
        sell it regardless of the stock figure, and zero stock means there is
        nothing to buy regardless of the price.
        """
        return self.stock > 0 and self.buy_price > 0

    @property
    def is_stocked_when_available(self) -> bool:
        """
        True when the station trades this commodity but currently has none.

        Distinct from "not sold here", and worth surfacing: it means come back,
        and it is a real signal for route planning.
        """
        return self.stock <= 0 and self.buy_price > 0


@dataclass(frozen=True)
class Market:
    """A station market snapshot, from whichever source produced it."""

    market_id: Optional[int]
    station: str
    system: str
    timestamp: Optional[datetime]
    source: str
    items: tuple[MarketItem, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def age_seconds(self) -> Optional[float]:
        if self.timestamp is None:
            return None
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()

    def by_id(self) -> dict[int, MarketItem]:
        return {item.id: item for item in self.items}

    def find(
        self,
        commodity_id: object = None,
        symbol: object = None,
        name: object = None,
    ) -> Optional[MarketItem]:
        """Locate an item by id, then symbol, then normalized display name."""
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


def _item_from_journal(raw: Mapping, catalog: Optional[CommodityCatalog]) -> Optional[MarketItem]:
    commodity_id = _as_int(raw.get("id"), -1)
    if commodity_id < 0:
        return None
    symbol = strip_symbol(raw.get("Name", ""))
    name = raw.get("Name_Localised") or symbol
    category = raw.get("Category_Localised") or raw.get("Category") or ""

    if catalog is not None:
        known = catalog.resolve(commodity_id=commodity_id, symbol=symbol, name=name)
        if known is not None:
            symbol = known.symbol
            category = category or known.category

    return MarketItem(
        id=commodity_id,
        symbol=symbol,
        name=str(name),
        stock=_as_int(raw.get("Stock")),
        buy_price=_as_int(raw.get("BuyPrice")),
        demand=_as_int(raw.get("Demand")),
        sell_price=_as_int(raw.get("SellPrice")),
        category=str(category).strip("$;"),
        source=SOURCE_JOURNAL,
    )


def _item_from_capi(raw: Mapping, catalog: Optional[CommodityCatalog]) -> Optional[MarketItem]:
    commodity_id = _as_int(raw.get("id"), -1)
    if commodity_id < 0:
        return None
    symbol = strip_symbol(raw.get("name", ""))
    name = raw.get("locName") or symbol

    if catalog is not None:
        known = catalog.resolve(commodity_id=commodity_id, symbol=symbol, name=name)
        if known is not None:
            symbol = known.symbol
            name = known.name if not raw.get("locName") else name

    return MarketItem(
        id=commodity_id,
        symbol=symbol,
        name=str(name),
        stock=_as_int(raw.get("stock")),
        buy_price=_as_int(raw.get("buyPrice")),
        demand=_as_int(raw.get("demand")),
        sell_price=_as_int(raw.get("sellPrice")),
        category=str(raw.get("categoryname") or ""),
        source=SOURCE_CAPI,
    )


def from_journal(data: Mapping, catalog: Optional[CommodityCatalog] = None) -> Market:
    """
    Build a Market from the game's ``Market.json``.

    Note this file is rewritten only when the commander opens the station's
    commodity screen, so it can describe a station already left behind. Callers
    must compare ``market_id`` against the latest Docked event before trusting
    it -- see :func:`APITool.journal.LocationState.market_is_current`.
    """
    items = []
    for raw in data.get("Items", []) or []:
        item = _item_from_journal(raw, catalog)
        if item is not None:
            items.append(item)
    return Market(
        market_id=_as_int(data.get("MarketID"), 0) or None,
        station=str(data.get("StationName") or ""),
        system=str(data.get("StarSystem") or ""),
        timestamp=_parse_timestamp(data.get("timestamp")),
        source=SOURCE_JOURNAL,
        items=tuple(items),
    )


def from_capi(
    data: Mapping,
    catalog: Optional[CommodityCatalog] = None,
    system: str = "",
    timestamp: Optional[datetime] = None,
) -> Market:
    """
    Build a Market from the Frontier CAPI ``/market`` response.

    CAPI does not report the star system, so callers pass it in from the
    journal or ``/profile``.
    """
    items = []
    for raw in data.get("commodities", []) or []:
        item = _item_from_capi(raw, catalog)
        if item is not None:
            items.append(item)
    return Market(
        market_id=_as_int(data.get("id"), 0) or None,
        station=str(data.get("name") or ""),
        system=system,
        timestamp=timestamp or datetime.now(timezone.utc),
        source=SOURCE_CAPI,
        items=tuple(items),
    )


def merge(primary: Market, supplement: Optional[Market]) -> Market:
    """
    Union two views of the same station.

    ``primary`` wins for every commodity both sources report -- pass the LIVE
    source there (CAPI), because stock and price are the volatile fields.
    ``supplement`` contributes only the commodities primary omits -- pass the
    BROADER source there (the journal), because it is the one that knows about
    commodities the station sells but is currently out of.

    Raises ValueError if the two describe different markets; comparing a
    commander against the wrong station's prices is the failure mode this
    whole module exists to prevent.
    """
    if supplement is None or not supplement.items:
        return primary
    if not primary.items:
        return supplement

    if (
        primary.market_id is not None
        and supplement.market_id is not None
        and primary.market_id != supplement.market_id
    ):
        raise ValueError(
            f"refusing to merge different markets: "
            f"{primary.station!r} (id {primary.market_id}) vs "
            f"{supplement.station!r} (id {supplement.market_id})"
        )

    combined = {item.id: item for item in supplement.items}
    combined.update({item.id: item for item in primary.items})

    return Market(
        market_id=primary.market_id or supplement.market_id,
        station=primary.station or supplement.station,
        # CAPI does not report the system, so fall back to the journal's.
        system=primary.system or supplement.system,
        timestamp=primary.timestamp or supplement.timestamp,
        source=SOURCE_MERGED,
        items=tuple(combined[k] for k in sorted(combined)),
    )


def learn_names(catalog: CommodityCatalog, markets: Iterable[Optional[Market]]) -> int:
    """
    Teach the catalog whatever display names these markets actually used.

    Lets EDCD-vs-game spelling drift self-heal within a session.
    """
    learned = 0
    for market in markets:
        if market is None:
            continue
        for item in market.items:
            known = catalog.by_id(item.id)
            if known is not None and catalog.add_alias(item.name, known):
                learned += 1
    return learned


__all__ = [
    "Market",
    "MarketItem",
    "SOURCE_CAPI",
    "SOURCE_JOURNAL",
    "SOURCE_MERGED",
    "from_capi",
    "from_journal",
    "learn_names",
    "merge",
    "replace",
]
