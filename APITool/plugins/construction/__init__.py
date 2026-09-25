"""
Colony construction blocks, published into regions of a workbook you keep.

Split from the settlement plugin in v0.8.0 so that one directory holds one
vocabulary. This plugin owns exactly two things: where a construction block
goes (a ``construction_regions`` list in its target's config block, or the
``--construction-region`` flag, which overrides it outright), and the check
that those bindings parse. The block itself is built and written by core's
daemon, which asks this plugin only "where"; the roll-up tab, its markers
and its location cells are the ``totals`` plugin's and are not spoken here.

What the loader asks of a plugin, and this plugin's answers:

    KIND                  "gsheet" -- the regions are ranges on a Google sheet
    layout(**overrides)   none: this plugin has no tab of its own
    writes()              nothing as shipped; the regions are bound per target
    flags()               `serve --construction-region`
    construction_regions(config, override)
                          the bindings, read from this plugin's own block
    default_config()      a starter block naming one region
    check_config(config)  what is wrong with the block, or nothing
"""

from typing import Optional

from ...registry import Flag
from .bindings import construction_regions, parse_region_spec  # noqa: F401 -- the surface above

# A Google sheet: the regions this plugin binds are ranges on one.
KIND = "gsheet"


def writes() -> dict[str, list[str]]:
    """Nothing as shipped. A region is bound by a target's config, never declared here."""
    return {}


def flags() -> list[Flag]:
    """The one word this plugin owns on the command line."""
    return [
        Flag("serve", "--construction-region", "construction_region", "append",
             metavar="TAB!RANGE[=SITE]",
             help="Also keep a construction block current in a region of a tab "
                  "this tool does not own, e.g. "
                  "\"Agri Lrg. (ex)!R1:AC60=Badeaux Nutrition Centre\". The site "
                  "may be named, named by a name it USED to have, or given as a "
                  "market id; omit it and the block follows whichever site you "
                  "are docked at. Repeat the flag for more than one region. To "
                  "set this once instead of typing it each session, put a "
                  "\"construction_regions\" list in your target's \"config\" "
                  "block (docs/configuration.md); this flag then overrides it "
                  "outright rather than adding to it"),
    ]


def default_config() -> dict:
    """A starter block for someone configuring this plugin for the first time."""
    return {"construction_regions": [{"region": "Tab Name!R1:AC60", "site": "Site Name"}]}


def check_config(config: Optional[dict]) -> list[str]:
    """
    What is wrong with this target's block, as a list of plain sentences.

    The schema for ``construction_regions`` left core in v0.7.4 and this is
    the home it moved to. Core asks and repeats the answer; it does not know
    what a region is, which is the whole point of the block being opaque.

    Reported at load, so a person hears about a typo when the tool starts
    rather than when the daemon first tries to publish that region.
    """
    problems: list[str] = []
    if not config:
        return problems
    regions = config.get("construction_regions")
    if regions is None:
        return problems
    if not isinstance(regions, list):
        return [f'"construction_regions" must be a list, got {type(regions).__name__}']
    for i, entry in enumerate(regions):
        where = f"construction_regions[{i}]"
        try:
            if isinstance(entry, str):
                parse_region_spec(entry)
                continue
            if not isinstance(entry, dict):
                problems.append(f"{where} must be an object or a string, got "
                                f"{type(entry).__name__}")
                continue
            if "region" not in entry:
                problems.append(f'{where} has no "region"')
                continue
            from ...sheets import Destination
            Destination.parse(entry["region"])
        except ValueError as exc:
            problems.append(f"{where}: {exc}")
    return problems

