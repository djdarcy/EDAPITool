"""
Blocks of the tool's data, published into regions of a workbook you keep.

Split from the settlement plugin in v0.8.0 so that one directory holds one
vocabulary. This plugin owns exactly two things: where a block goes (a
``bindings`` list in its target's config block, or the
``--construction-region`` flag, which overrides it outright), and the check
that those bindings parse. The block itself is built and written by core's
daemon, which asks this plugin only "where"; the roll-up tab, its markers
and its location cells are the ``totals`` plugin's and are not spoken here.

Since v0.8.2 a binding names its data: a construction block (the default),
the market, the ship's cargo, or the carrier's hold -- which is why this
plugin, called ``construction`` in v0.8.0 and v0.8.1, is now ``regions``, and
its key, once ``construction_regions``, is ``bindings``. It is a test of the
plugin system: routing the tool's own data belongs to the tool, and this
binding is meant to move there.

What the loader asks of a plugin, and this plugin's answers:

    KIND                  "gsheet" -- the regions are ranges on a Google sheet
    layout(**overrides)   none: this plugin has no tab of its own
    writes()              nothing as shipped; the regions are bound per target
    flags()               `serve --construction-region`
    regions(config, override)
                          the bindings, read from this plugin's own block
    default_config()      a starter block naming one region
    check_config(config)  what is wrong with the block, or nothing
"""

from typing import Optional

from ...registry import Flag
from .bindings import region_bindings, parse_entry, parse_region_spec  # noqa: F401 -- the surface above

# A Google sheet: the regions this plugin binds are ranges on one.
KIND = "gsheet"


def writes() -> dict[str, list[str]]:
    """Nothing as shipped. A region is bound by a target's config, never declared here."""
    return {}


def flags() -> list[Flag]:
    """
    No words of its own any more. ``--construction-region`` was this
    plugin's until #34 made a region the tool's to route; `serve` declares
    it now, whether or not any plugin is loaded.
    """
    return []


def default_config() -> dict:
    """A starter block for someone configuring this plugin for the first time."""
    return {"bindings": [{"region": "Tab Name!R1:AC60", "site": "Site Name"}]}


def check_config(config: Optional[dict]) -> list[str]:
    """
    What is wrong with this target's block, as a list of plain sentences.

    The schema for ``regions`` left core in v0.7.4 and this is
    the home it moved to. Core asks and repeats the answer; it does not know
    what a region is, which is the whole point of the block being opaque.

    Reported at load, so a person hears about a typo when the tool starts
    rather than when the daemon first tries to publish that region.
    """
    problems: list[str] = []
    if not config:
        return problems
    regions = config.get("bindings")
    if regions is None:
        return problems
    if not isinstance(regions, list):
        return [f'"bindings" must be a list, got {type(regions).__name__}']
    # The same parser `serve` uses, so what passes here is what publishes.
    for i, entry in enumerate(regions):
        try:
            parse_entry(entry, f"bindings[{i}]")
        except ValueError as exc:
            problems.append(str(exc))
    if not problems:
        # Since #34 (0.11.0) a region is the tool's: the same entries go
        # under the target's own "regions" key, with no plugin at all. This
        # plugin is an alias on its way out -- one configuration was known
        # to use it when this was written (the maintainer's, 2026-10-02).
        # Said once the block parses, so a typo is fixed before the move.
        problems.append(
            'move "bindings" to the target\'s own "regions" key and drop "plugin": "regions" '
            '-- this plugin is retired in 0.11.0 (docs/configuration.md)'
        )
    return problems

