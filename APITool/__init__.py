"""
APITool - Elite Dangerous API Tool

A Python tool for accessing the Elite Dangerous Companion API (CAPI)
to extract fleet carrier inventory and other game data.
"""

__version__ = "0.1.0"
__author__ = "djdarcy"

from .capi import CAPIClient
from .auth import FrontierAuth
from .models import FleetCarrier, CargoItem

__all__ = ["CAPIClient", "FrontierAuth", "FleetCarrier", "CargoItem", "__version__"]
