"""
APITool - Elite Dangerous API Tool

A Python tool for accessing the Elite Dangerous Companion API (CAPI)
to extract fleet carrier inventory and other game data.
"""

from .version import get_base_version

# Derived, never hardcoded: this line said "0.1.0" through three releases
# because nothing kept it in step with version.py, which the build, the CLI
# and the release tooling all read instead.
__version__ = get_base_version()
__author__ = "djdarcy"

from .capi import CAPIClient
from .auth import FrontierAuth
from .models import FleetCarrier, CargoItem

__all__ = ["CAPIClient", "FrontierAuth", "FleetCarrier", "CargoItem", "__version__"]
