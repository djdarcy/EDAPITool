"""
The regions plugin's binding parser -- now a shim over the tool's own.

Region binding moved into the tool on 2026-10-02 (#34): ``APITool.regions``
holds the record, the parsers and the rules, verbatim from here. This module
keeps the plugin's spelling of them so the plugin, and the one configuration
known to use it (the maintainer's, counted 2026-10-02), keep working until
the plugin retires. Nothing is defined here.
"""

from ...regions import (  # noqa: F401 -- the plugin's surface, re-exported
    DATA_KINDS, DEFAULT_DATA, Binding, parse_entry, parse_region_spec, region_bindings,
)
