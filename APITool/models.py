"""
Data models for Elite Dangerous CAPI data.

These classes provide structured access to CAPI response data
with helper methods for common operations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
import codecs


def decode_hex_name(hex_string: str) -> str:
    """Decode hex-encoded names from CAPI."""
    if not hex_string:
        return ""
    try:
        # CAPI returns names as hex-encoded UTF-8
        return codecs.decode(hex_string, "hex").decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return hex_string


@dataclass
class CarrierIdentity:
    """Fleet carrier identity information."""

    callsign: str
    vanity_name: str
    filtered_name: str

    @classmethod
    def from_capi(cls, data: dict) -> "CarrierIdentity":
        """Create from CAPI response."""
        name_data = data.get("name", {})
        return cls(
            callsign=name_data.get("callsign", ""),
            vanity_name=decode_hex_name(name_data.get("vanityName", "")),
            filtered_name=decode_hex_name(name_data.get("filteredVanityName", "")),
        )

    @property
    def display_name(self) -> str:
        """Get the best display name."""
        return self.filtered_name or self.vanity_name or self.callsign


@dataclass
class CarrierLocation:
    """Fleet carrier location and status."""

    system: str
    state: str  # normalOperation, debtState, pendingDecommission
    docking_access: str  # all, squadronfriends, friends, none
    notorious_access: bool

    @classmethod
    def from_capi(cls, data: dict) -> "CarrierLocation":
        """Create from CAPI response."""
        return cls(
            system=data.get("currentStarSystem", "Unknown"),
            state=data.get("state", "unknown"),
            docking_access=data.get("dockingAccess", "none"),
            notorious_access=data.get("notoriousAccess", False),
        )


def _to_int(value, default: int = 0) -> int:
    """Convert value to int, handling strings."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


@dataclass
class CarrierFinance:
    """Fleet carrier financial information."""

    balance: int
    reserved_balance: int
    core_cost: int
    services_cost: int
    jumps_cost: int
    maintenance: int
    maintenance_to_date: int

    @classmethod
    def from_capi(cls, data: dict) -> "CarrierFinance":
        """Create from CAPI response."""
        finance = data.get("finance", {})
        return cls(
            balance=_to_int(finance.get("bankBalance")),
            reserved_balance=_to_int(finance.get("bankReservedBalance")),
            core_cost=_to_int(finance.get("coreCost")),
            services_cost=_to_int(finance.get("servicesCost")),
            jumps_cost=_to_int(finance.get("jumpsCost")),
            maintenance=_to_int(finance.get("maintenance")),
            maintenance_to_date=_to_int(finance.get("maintenanceToDate")),
        )

    @property
    def weekly_upkeep(self) -> int:
        """Total weekly upkeep cost."""
        return self.core_cost + self.services_cost


@dataclass
class CommodityOrder:
    """A commodity buy or sell order."""

    name: str
    stock: int = 0  # For sell orders
    demand: int = 0  # For buy orders (total order)
    outstanding: int = 0  # For buy orders (remaining)
    price: int = 0
    blackmarket: bool = False
    order_type: str = "sell"  # "sell" or "buy"

    @classmethod
    def from_sale(cls, data: dict) -> "CommodityOrder":
        """Create from sale order data."""
        return cls(
            name=data.get("name", "Unknown"),
            stock=_to_int(data.get("stock")),
            price=_to_int(data.get("price")),
            blackmarket=data.get("blackmarket", False),
            order_type="sell",
        )

    @classmethod
    def from_purchase(cls, data: dict) -> "CommodityOrder":
        """Create from purchase order data."""
        return cls(
            name=data.get("name", "Unknown"),
            demand=_to_int(data.get("total")),
            outstanding=_to_int(data.get("outstanding")),
            price=_to_int(data.get("price")),
            order_type="buy",
        )


@dataclass
class MicroResourceOrder:
    """An on-foot microresource buy or sell order."""

    id: int
    name: str
    localized_name: str
    stock: int = 0
    demand: int = 0
    outstanding: int = 0
    price: int = 0
    order_type: str = "sell"

    @classmethod
    def from_sale(cls, data: dict) -> "MicroResourceOrder":
        """Create from sale order data."""
        return cls(
            id=_to_int(data.get("id")),
            name=data.get("name", "Unknown"),
            localized_name=data.get("locName", data.get("name", "Unknown")),
            stock=_to_int(data.get("stock")),
            price=_to_int(data.get("price")),
            order_type="sell",
        )

    @classmethod
    def from_purchase(cls, data: dict) -> "MicroResourceOrder":
        """Create from purchase order data."""
        return cls(
            id=0,  # Buy orders don't have ID
            name=data.get("name", "Unknown"),
            localized_name=data.get("name", "Unknown"),
            demand=_to_int(data.get("total")),
            outstanding=_to_int(data.get("outstanding")),
            price=_to_int(data.get("price")),
            order_type="buy",
        )


@dataclass
class CargoItem:
    """A cargo item stored on the fleet carrier."""

    commodity: str  # Internal name (e.g., "Metaalloys")
    localized_name: str  # Display name (e.g., "Meta-Alloys")
    quantity: int
    value: int  # Total value in credits
    stolen: bool
    mission: bool  # If true, reserved for a mission
    origin_system: Optional[str]  # Where it was acquired

    @classmethod
    def from_capi(cls, data: dict) -> "CargoItem":
        """Create from CAPI cargo array item."""
        return cls(
            commodity=data.get("commodity", "Unknown"),
            localized_name=data.get("locName", data.get("commodity", "Unknown")),
            quantity=_to_int(data.get("qty")),
            value=_to_int(data.get("value")),
            stolen=data.get("stolen", False),
            mission=data.get("mission", False),
            origin_system=data.get("originSystem"),
        )


@dataclass
class LockerItem:
    """An item stored in the carrier locker."""

    id: int
    name: str
    localized_name: str
    quantity: int
    category: str  # "assets", "goods", "data"

    @classmethod
    def from_capi(cls, data: dict, category: str) -> "LockerItem":
        """Create from CAPI response."""
        return cls(
            id=data.get("id", 0),
            name=data.get("name", "Unknown"),
            localized_name=data.get("locName", data.get("name", "Unknown")),
            quantity=data.get("quantity", 0),
            category=category,
        )


@dataclass
class CarrierCapacity:
    """Fleet carrier capacity information."""

    ship_packs: int
    module_packs: int
    cargo_for_sale: int
    cargo_not_for_sale: int
    cargo_reserved: int
    crew: int
    micro_total: int
    micro_free: int
    micro_used: int
    micro_reserved: int

    @classmethod
    def from_capi(cls, data: dict) -> "CarrierCapacity":
        """Create from CAPI response."""
        cap = data.get("capacity", {})
        return cls(
            ship_packs=cap.get("shipPacks", 0),
            module_packs=cap.get("modulePacks", 0),
            cargo_for_sale=cap.get("cargoForSale", 0),
            cargo_not_for_sale=cap.get("cargoNotForSale", 0),
            cargo_reserved=cap.get("cargoSpaceReserved", 0),
            crew=cap.get("crew", 0),
            micro_total=cap.get("microresourceCapacityTotal", 0),
            micro_free=cap.get("microresourceCapacityFree", 0),
            micro_used=cap.get("microresourceCapacityUsed", 0),
            micro_reserved=cap.get("microresourceCapacityReserved", 0),
        )

    @property
    def total_cargo_used(self) -> int:
        """Total cargo space in use."""
        return self.cargo_for_sale + self.cargo_not_for_sale + self.cargo_reserved


@dataclass
class ServiceCrew:
    """A service crew member."""

    service: str
    name: str
    gender: str
    salary: int
    faction: str
    enabled: bool

    @classmethod
    def from_capi(cls, service_name: str, data: dict) -> "ServiceCrew":
        """Create from CAPI response."""
        # Structure: {"crewMember": {"name": ..., "enabled": "YES"/"NO", ...}}
        crew_member = data.get("crewMember", {})
        enabled_str = crew_member.get("enabled", "NO")
        enabled = enabled_str.upper() == "YES" if isinstance(enabled_str, str) else bool(enabled_str)

        return cls(
            service=service_name,
            name=crew_member.get("name", ""),
            gender=crew_member.get("gender", ""),
            salary=crew_member.get("salary", 0),
            faction=crew_member.get("faction", ""),
            enabled=enabled,
        )


@dataclass
class JumpRecord:
    """A completed jump record."""

    departure_time: Optional[datetime]
    arrival_time: Optional[datetime]
    system: str
    visit_duration: int  # seconds
    success: bool

    @classmethod
    def from_capi(cls, data: dict) -> "JumpRecord":
        """Create from CAPI response."""
        # Times can be null or string format "YYYY-MM-DD HH:MM:SS"
        departure = data.get("departureTime")
        arrival = data.get("arrivalTime")

        departure_dt = None
        arrival_dt = None

        if departure:
            try:
                if isinstance(departure, str):
                    departure_dt = datetime.strptime(departure, "%Y-%m-%d %H:%M:%S")
                else:
                    departure_dt = datetime.fromtimestamp(departure)
            except (ValueError, TypeError):
                pass

        if arrival:
            try:
                if isinstance(arrival, str):
                    arrival_dt = datetime.strptime(arrival, "%Y-%m-%d %H:%M:%S")
                else:
                    arrival_dt = datetime.fromtimestamp(arrival)
            except (ValueError, TypeError):
                pass

        return cls(
            departure_time=departure_dt,
            arrival_time=arrival_dt,
            system=data.get("starsystem", "Unknown"),
            visit_duration=data.get("visitDurationSeconds", 0),
            success=data.get("state", "success") == "success",
        )


@dataclass
class FleetCarrier:
    """Complete fleet carrier data model."""

    identity: CarrierIdentity
    location: CarrierLocation
    finance: CarrierFinance
    capacity: CarrierCapacity
    fuel: int
    theme: str
    total_distance_jumped: float

    # Cargo - the main inventory of commodities stored on the carrier
    cargo: list[CargoItem] = field(default_factory=list)

    # Orders and inventory
    commodity_sales: list[CommodityOrder] = field(default_factory=list)
    commodity_purchases: list[CommodityOrder] = field(default_factory=list)
    micro_sales: list[MicroResourceOrder] = field(default_factory=list)
    micro_purchases: list[MicroResourceOrder] = field(default_factory=list)
    locker_items: list[LockerItem] = field(default_factory=list)

    # Crew and services
    crew: list[ServiceCrew] = field(default_factory=list)

    # Travel history
    jump_history: list[JumpRecord] = field(default_factory=list)
    current_jump_destination: Optional[str] = None

    # Raw data for additional access
    raw_data: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_capi(cls, data: dict) -> "FleetCarrier":
        """Create FleetCarrier from CAPI /fleetcarrier response."""
        # Parse orders
        orders = data.get("orders", {})
        commodities = orders.get("commodities", {})
        microresources = orders.get("onfootmicroresources", {})

        commodity_sales = [
            CommodityOrder.from_sale(item)
            for item in commodities.get("sales", [])
        ]
        commodity_purchases = [
            CommodityOrder.from_purchase(item)
            for item in commodities.get("purchases", [])
        ]

        # Microresources can be a dict keyed by ID or a list
        micro_sales_data = microresources.get("sales", {})
        if isinstance(micro_sales_data, dict):
            # Dict format: {"128962598": {"id": ..., "name": ...}, ...}
            micro_sales = [
                MicroResourceOrder.from_sale(item)
                for item in micro_sales_data.values()
            ]
        else:
            # List format
            micro_sales = [
                MicroResourceOrder.from_sale(item)
                for item in micro_sales_data
            ]

        micro_purchases_data = microresources.get("purchases", {})
        if isinstance(micro_purchases_data, dict):
            micro_purchases = [
                MicroResourceOrder.from_purchase(item)
                for item in micro_purchases_data.values()
            ]
        else:
            micro_purchases = [
                MicroResourceOrder.from_purchase(item)
                for item in micro_purchases_data
            ]

        # Parse cargo - the main commodity inventory
        cargo = [
            CargoItem.from_capi(item)
            for item in data.get("cargo", [])
        ]

        # Parse locker
        locker_items = []
        locker = data.get("carrierLocker", {})
        for category in ["assets", "goods", "data"]:
            for item in locker.get(category, []):
                locker_items.append(LockerItem.from_capi(item, category))

        # Parse crew - structure is {"service": {"crewMember": {...}, ...}}
        crew = []
        services_crew = data.get("servicesCrew", {})
        for service_name, service_data in services_crew.items():
            if isinstance(service_data, dict) and "crewMember" in service_data:
                crew.append(ServiceCrew.from_capi(service_name, service_data))

        # Parse jump history
        itinerary = data.get("itinerary", {})
        jump_history = [
            JumpRecord.from_capi(jump)
            for jump in itinerary.get("completed", [])
        ]

        return cls(
            identity=CarrierIdentity.from_capi(data),
            location=CarrierLocation.from_capi(data),
            finance=CarrierFinance.from_capi(data),
            capacity=CarrierCapacity.from_capi(data),
            fuel=_to_int(data.get("fuel")),
            theme=data.get("theme", ""),
            total_distance_jumped=float(data.get("totalDistanceJumpedLY", 0) or 0),
            cargo=cargo,
            commodity_sales=commodity_sales,
            commodity_purchases=commodity_purchases,
            micro_sales=micro_sales,
            micro_purchases=micro_purchases,
            locker_items=locker_items,
            crew=crew,
            jump_history=jump_history,
            current_jump_destination=data.get("currentJump"),
            raw_data=data,
        )

    @property
    def all_commodities(self) -> list[CommodityOrder]:
        """Get all commodity orders (sales and purchases)."""
        return self.commodity_sales + self.commodity_purchases

    @property
    def all_microresources(self) -> list[MicroResourceOrder]:
        """Get all microresource orders (sales and purchases)."""
        return self.micro_sales + self.micro_purchases

    @property
    def enabled_services(self) -> list[str]:
        """Get list of enabled services."""
        return [c.service for c in self.crew if c.enabled]

    def get_commodity_by_name(self, name: str) -> Optional[CommodityOrder]:
        """Find a commodity order by name (case-insensitive)."""
        name_lower = name.lower()
        for order in self.all_commodities:
            if order.name.lower() == name_lower:
                return order
        return None
