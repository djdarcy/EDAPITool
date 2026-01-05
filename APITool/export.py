"""
Export functionality for Elite Dangerous data.

Supports exporting fleet carrier and other data to:
- CSV files
- JSON files
- (Future) Google Sheets
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Union, TextIO

from .models import (
    FleetCarrier,
    CargoItem,
    CommodityOrder,
    MicroResourceOrder,
    LockerItem,
    ServiceCrew,
    JumpRecord,
)


class CSVExporter:
    """Export data to CSV format."""

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize CSV exporter.

        Args:
            output_dir: Directory for output files (default: current directory)
        """
        self.output_dir = output_dir or Path.cwd()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _generate_filename(self, prefix: str, callsign: str = "") -> Path:
        """Generate a timestamped filename."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if callsign:
            return self.output_dir / f"{prefix}_{callsign}_{timestamp}.csv"
        return self.output_dir / f"{prefix}_{timestamp}.csv"

    def export_carrier_summary(
        self,
        carrier: FleetCarrier,
        filepath: Optional[Path] = None,
    ) -> Path:
        """
        Export carrier summary to CSV.

        Args:
            carrier: FleetCarrier data
            filepath: Optional specific filepath

        Returns:
            Path to created file
        """
        filepath = filepath or self._generate_filename(
            "carrier_summary", carrier.identity.callsign
        )

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            # Header info
            writer.writerow(["Fleet Carrier Summary"])
            writer.writerow(["Export Date", datetime.now().isoformat()])
            writer.writerow([])

            # Identity
            writer.writerow(["Identity"])
            writer.writerow(["Callsign", carrier.identity.callsign])
            writer.writerow(["Name", carrier.identity.display_name])
            writer.writerow([])

            # Location
            writer.writerow(["Location & Status"])
            writer.writerow(["Current System", carrier.location.system])
            writer.writerow(["State", carrier.location.state])
            writer.writerow(["Docking Access", carrier.location.docking_access])
            writer.writerow(["Tritium Fuel", carrier.fuel])
            writer.writerow(["Theme", carrier.theme])
            writer.writerow([])

            # Finances
            writer.writerow(["Finances"])
            writer.writerow(["Bank Balance", carrier.finance.balance])
            writer.writerow(["Reserved Balance", carrier.finance.reserved_balance])
            writer.writerow(["Weekly Core Cost", carrier.finance.core_cost])
            writer.writerow(["Weekly Services Cost", carrier.finance.services_cost])
            writer.writerow(["Weekly Upkeep", carrier.finance.weekly_upkeep])
            writer.writerow([])

            # Capacity
            writer.writerow(["Capacity"])
            writer.writerow(["Ship Packs", carrier.capacity.ship_packs])
            writer.writerow(["Module Packs", carrier.capacity.module_packs])
            writer.writerow(["Cargo For Sale", carrier.capacity.cargo_for_sale])
            writer.writerow(["Cargo Not For Sale", carrier.capacity.cargo_not_for_sale])
            writer.writerow(["Cargo Reserved", carrier.capacity.cargo_reserved])
            writer.writerow([])

            # Services
            writer.writerow(["Enabled Services"])
            for service in carrier.enabled_services:
                writer.writerow(["", service])

        return filepath

    def export_commodity_orders(
        self,
        carrier: FleetCarrier,
        filepath: Optional[Path] = None,
    ) -> Path:
        """
        Export commodity orders to CSV.

        Args:
            carrier: FleetCarrier data
            filepath: Optional specific filepath

        Returns:
            Path to created file
        """
        filepath = filepath or self._generate_filename(
            "commodities", carrier.identity.callsign
        )

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow([
                "Commodity",
                "Type",
                "Stock/Demand",
                "Outstanding",
                "Price",
                "Black Market",
            ])

            # Sales
            for order in carrier.commodity_sales:
                writer.writerow([
                    order.name,
                    "SELL",
                    order.stock,
                    "",
                    order.price,
                    "Yes" if order.blackmarket else "No",
                ])

            # Purchases
            for order in carrier.commodity_purchases:
                writer.writerow([
                    order.name,
                    "BUY",
                    order.demand,
                    order.outstanding,
                    order.price,
                    "",
                ])

        return filepath

    def export_microresources(
        self,
        carrier: FleetCarrier,
        filepath: Optional[Path] = None,
    ) -> Path:
        """
        Export microresource orders to CSV.

        Args:
            carrier: FleetCarrier data
            filepath: Optional specific filepath

        Returns:
            Path to created file
        """
        filepath = filepath or self._generate_filename(
            "microresources", carrier.identity.callsign
        )

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow([
                "Resource",
                "Localized Name",
                "Type",
                "Stock/Demand",
                "Outstanding",
                "Price",
            ])

            # Sales
            for order in carrier.micro_sales:
                writer.writerow([
                    order.name,
                    order.localized_name,
                    "SELL",
                    order.stock,
                    "",
                    order.price,
                ])

            # Purchases
            for order in carrier.micro_purchases:
                writer.writerow([
                    order.name,
                    order.localized_name,
                    "BUY",
                    order.demand,
                    order.outstanding,
                    order.price,
                ])

        return filepath

    def export_locker_inventory(
        self,
        carrier: FleetCarrier,
        filepath: Optional[Path] = None,
    ) -> Path:
        """
        Export carrier locker inventory to CSV.

        Args:
            carrier: FleetCarrier data
            filepath: Optional specific filepath

        Returns:
            Path to created file
        """
        filepath = filepath or self._generate_filename(
            "locker", carrier.identity.callsign
        )

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow([
                "Item",
                "Localized Name",
                "Category",
                "Quantity",
            ])

            for item in carrier.locker_items:
                writer.writerow([
                    item.name,
                    item.localized_name,
                    item.category.title(),
                    item.quantity,
                ])

        return filepath

    def export_cargo(
        self,
        carrier: FleetCarrier,
        filepath: Optional[Path] = None,
    ) -> Path:
        """
        Export fleet carrier cargo inventory to CSV.

        This is the main commodity storage on the carrier - the items
        like Meta-Alloys, Tea, Steel, etc. that the user needs to track.

        Args:
            carrier: FleetCarrier data
            filepath: Optional specific filepath

        Returns:
            Path to created file
        """
        filepath = filepath or self._generate_filename(
            "cargo", carrier.identity.callsign
        )

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow([
                "Commodity",
                "Display Name",
                "Quantity",
                "Value (CR)",
                "Stolen",
                "Mission",
                "Origin System",
            ])

            # Sort by localized name for easier reading
            sorted_cargo = sorted(carrier.cargo, key=lambda c: c.localized_name)

            for item in sorted_cargo:
                writer.writerow([
                    item.commodity,
                    item.localized_name,
                    item.quantity,
                    item.value,
                    "Yes" if item.stolen else "No",
                    "Yes" if item.mission else "No",
                    item.origin_system or "",
                ])

            # Add summary row
            if carrier.cargo:
                writer.writerow([])
                total_qty = sum(c.quantity for c in carrier.cargo)
                total_value = sum(c.value for c in carrier.cargo)
                writer.writerow(["TOTAL", "", total_qty, total_value, "", "", ""])

        return filepath

    def export_cargo_aggregated(
        self,
        carrier: FleetCarrier,
        filepath: Optional[Path] = None,
    ) -> Path:
        """
        Export fleet carrier cargo with quantities aggregated by commodity.

        Same commodity from different sources is combined into a single row.
        This is the simplified view for inventory tracking.

        Args:
            carrier: FleetCarrier data
            filepath: Optional specific filepath

        Returns:
            Path to created file
        """
        filepath = filepath or self._generate_filename(
            "cargo_summary", carrier.identity.callsign
        )

        # Aggregate by commodity name
        aggregated: dict[str, dict] = {}
        for item in carrier.cargo:
            key = item.commodity
            if key not in aggregated:
                aggregated[key] = {
                    "commodity": item.commodity,
                    "localized_name": item.localized_name,
                    "quantity": 0,
                    "value": 0,
                }
            aggregated[key]["quantity"] += item.quantity
            aggregated[key]["value"] += item.value

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow([
                "Commodity",
                "Display Name",
                "Quantity",
                "Value (CR)",
            ])

            # Sort by localized name
            sorted_items = sorted(aggregated.values(), key=lambda x: x["localized_name"])

            for item in sorted_items:
                writer.writerow([
                    item["commodity"],
                    item["localized_name"],
                    item["quantity"],
                    item["value"],
                ])

            # Add summary row
            if aggregated:
                writer.writerow([])
                total_qty = sum(item["quantity"] for item in aggregated.values())
                total_value = sum(item["value"] for item in aggregated.values())
                writer.writerow(["TOTAL", "", total_qty, total_value])

        return filepath

    def export_crew(
        self,
        carrier: FleetCarrier,
        filepath: Optional[Path] = None,
    ) -> Path:
        """
        Export crew information to CSV.

        Args:
            carrier: FleetCarrier data
            filepath: Optional specific filepath

        Returns:
            Path to created file
        """
        filepath = filepath or self._generate_filename(
            "crew", carrier.identity.callsign
        )

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow([
                "Service",
                "Crew Name",
                "Gender",
                "Faction",
                "Weekly Salary",
                "Enabled",
            ])

            for crew in carrier.crew:
                writer.writerow([
                    crew.service,
                    crew.name,
                    crew.gender,
                    crew.faction,
                    crew.salary,
                    "Yes" if crew.enabled else "No",
                ])

        return filepath

    def export_jump_history(
        self,
        carrier: FleetCarrier,
        filepath: Optional[Path] = None,
    ) -> Path:
        """
        Export jump history to CSV.

        Args:
            carrier: FleetCarrier data
            filepath: Optional specific filepath

        Returns:
            Path to created file
        """
        filepath = filepath or self._generate_filename(
            "jumps", carrier.identity.callsign
        )

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow([
                "System",
                "Arrival Time",
                "Departure Time",
                "Visit Duration (hrs)",
                "Success",
            ])

            for jump in carrier.jump_history:
                duration_hrs = jump.visit_duration / 3600
                writer.writerow([
                    jump.system,
                    jump.arrival_time.isoformat() if jump.arrival_time else "",
                    jump.departure_time.isoformat() if jump.departure_time else "",
                    f"{duration_hrs:.1f}",
                    "Yes" if jump.success else "No",
                ])

        return filepath

    def export_all(
        self,
        carrier: FleetCarrier,
        prefix: str = "",
    ) -> dict[str, Path]:
        """
        Export all carrier data to separate CSV files.

        Args:
            carrier: FleetCarrier data
            prefix: Optional prefix for filenames

        Returns:
            Dictionary mapping export type to file path
        """
        callsign = carrier.identity.callsign

        return {
            "summary": self.export_carrier_summary(carrier),
            "cargo": self.export_cargo(carrier),
            "cargo_summary": self.export_cargo_aggregated(carrier),
            "commodities": self.export_commodity_orders(carrier),
            "microresources": self.export_microresources(carrier),
            "locker": self.export_locker_inventory(carrier),
            "crew": self.export_crew(carrier),
            "jumps": self.export_jump_history(carrier),
        }


class JSONExporter:
    """Export data to JSON format."""

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize JSON exporter.

        Args:
            output_dir: Directory for output files (default: current directory)
        """
        self.output_dir = output_dir or Path.cwd()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_carrier(
        self,
        carrier: FleetCarrier,
        filepath: Optional[Path] = None,
        include_raw: bool = False,
    ) -> Path:
        """
        Export carrier data to JSON.

        Args:
            carrier: FleetCarrier data
            filepath: Optional specific filepath
            include_raw: Include raw CAPI response

        Returns:
            Path to created file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = filepath or (
            self.output_dir
            / f"carrier_{carrier.identity.callsign}_{timestamp}.json"
        )

        data = {
            "export_date": datetime.now().isoformat(),
            "identity": {
                "callsign": carrier.identity.callsign,
                "name": carrier.identity.display_name,
            },
            "location": {
                "system": carrier.location.system,
                "state": carrier.location.state,
                "docking_access": carrier.location.docking_access,
            },
            "finance": {
                "balance": carrier.finance.balance,
                "weekly_upkeep": carrier.finance.weekly_upkeep,
            },
            "fuel": carrier.fuel,
            "commodity_orders": [
                {
                    "name": o.name,
                    "type": o.order_type,
                    "quantity": o.stock if o.order_type == "sell" else o.demand,
                    "price": o.price,
                }
                for o in carrier.all_commodities
            ],
            "microresource_orders": [
                {
                    "name": o.localized_name,
                    "type": o.order_type,
                    "quantity": o.stock if o.order_type == "sell" else o.demand,
                    "price": o.price,
                }
                for o in carrier.all_microresources
            ],
            "locker": [
                {
                    "name": i.localized_name,
                    "category": i.category,
                    "quantity": i.quantity,
                }
                for i in carrier.locker_items
            ],
        }

        if include_raw:
            data["raw_capi_response"] = carrier.raw_data

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return filepath
