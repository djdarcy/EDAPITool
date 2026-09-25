"""
This settlement workbook's own conventions -- DEMOTED, deliberately.

Everything here encodes one particular spreadsheet: a Totals Tab, a marker
column, harvey-ball glyphs, a green colour ramp. The tool's supported path is
to publish generated data tabs and let the sheet's formulas decide what they
mean, which is what both computed columns now do.

This package is kept because it is how sheet writes get tested, and it is a
package rather than loose modules so that depending on it is visible in an
import line. Nothing on the generic path may import from here.

What the loader asks of a plugin -- the surface below is the whole of it:

    KIND                  what kind of target this is; selects the enforcer
    layout(**overrides)   this sheet's shape, with any command-line overrides
    writes()              what it declares it writes, as shipped; the loader
                          checks these against every other plugin's at load
    layout.writes()       the same declaration for a layout with overrides;
                          core builds the guard from this one
    supplies()            what this plugin can be ASKED for: pulled once per
                          refresh and memoised, returning data
    subscribes()          what it PUBLISHES, pushed after its needs are supplied
    construction_regions(config, override)
                          where this plugin binds construction blocks, read
                          from its own config block; optional -- a plugin
                          without it publishes no regions
    default_config()      a starter block, for `plugins describe`
    check_config(config)  what is wrong with a block, or nothing; core asks
                          and repeats the answer without reading the block

The two halves of the contract are not the same shape, and that is the
design (APITool.registry says why). This plugin supplies the requirements it
reads from its tab, and subscribes to publish the marker column beside them.
"""

from typing import Any, Callable, Optional

from ...registry import Refresh, Subscription
from .bindings import construction_regions, parse_region_spec  # noqa: F401 -- the surface above
from .layout import SheetLayout

# A Google sheet. Configuration may name a kind per target and overrides this;
# with no targets configured, this is what the shipped plugin is.
KIND = "gsheet"


def markers_for(empty_marker: Optional[str] = "hollow") -> Optional[dict]:
    """
    The glyph family ``--empty-marker`` selects, decided where the glyphs live.

    ``hollow`` keeps the graded quarter/half/three-quarter scale -- ``None``
    means the renderer's own defaults. ``small`` and ``dotted`` collapse it to
    a single PARTIAL glyph with the chosen empty one, which is what a wholesale
    override does. Core used to import four of this plugin's constants only to
    build this dict and hand it straight back; the decision is this plugin's.
    """
    if empty_marker in (None, "hollow"):
        return None
    from ...matcher import MatchState
    from .markers import MARKER_EMPTY_DOTTED, MARKER_EMPTY_SMALL, MARKER_ENOUGH, MARKER_PARTIAL

    empty = MARKER_EMPTY_SMALL if empty_marker == "small" else MARKER_EMPTY_DOTTED
    return {
        MatchState.ENOUGH: MARKER_ENOUGH,
        MatchState.PARTIAL: MARKER_PARTIAL,
        MatchState.EMPTY: empty,
    }


def layout(**overrides) -> SheetLayout:
    """
    This workbook's layout. Overrides are the command line's, when given.

    ``empty_marker`` is the one override that is not a layout field: it names
    a glyph family, and the layout carries the resulting ``markers`` map.
    """
    empty_marker = overrides.pop("empty_marker", None)
    values = {k: v for k, v in overrides.items() if v is not None}
    if empty_marker is not None and "markers" not in values:
        values["markers"] = markers_for(empty_marker)
    return SheetLayout(**values)


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


def formula_help() -> str:
    """The ``--show-formula`` text: how a sheet reproduces this plugin's markers itself."""
    from .markers import marker_formula_help

    return marker_formula_help()


def writes() -> dict[str, list[str]]:
    """What this plugin declares it writes, as shipped. One definition: the layout's."""
    return SheetLayout().writes()


# ---------------------------------------------------------------------------
# The contract: what this plugin supplies, and what it subscribes to
# ---------------------------------------------------------------------------


def _read_requirements(ctx: Refresh) -> Any:
    """
    The requirements a person maintains on this sheet, read once per refresh.

    Everything the read needs travels on the refresh: the worksheet handle,
    the layout the command built, the catalog. The snapshot is the supplier's
    value, so every consumer -- the comparison, the marker writer -- sees the
    same read; a second read could see a different sheet.
    """
    from .totals import TotalsTabReader

    if ctx.worksheet is None:
        # The same reason the marker subscriber gives: what this plugin reads
        # IS a worksheet. Core asks every supplier it is offered without
        # knowing which handle each one needs, so a supplier that needs one
        # it has not been given answers with nothing rather than reaching
        # into None.
        return None

    return TotalsTabReader(ctx.worksheet, ctx.layout, ctx.catalog,
                           target=ctx.env.get("target") or "").read()


def _publish_markers(ctx: Refresh) -> Any:
    """
    Build this sheet's marker column beside the requirements, and write it
    when the refresh was asked to.

    The writer is the toolkit's; the renderer is this plugin's unless the
    caller handed in another; the guard is the one core built from this
    layout's declaration, never this plugin's to make.
    """
    from .markers import MarketRenderer
    from .totals import TotalsTabWriter

    if ctx.worksheet is None:
        # This plugin's destination IS a worksheet; without one there is
        # nothing for it to publish. Core does not decide that -- it hands
        # every subscriber the refresh and lets each say what it can do,
        # because a plugin whose destination is a file has no worksheet and
        # publishes perfectly well.
        return "no worksheet: nothing published"

    result = ctx.result
    options = ctx.options
    renderer = ctx.renderer if ctx.renderer is not None else MarketRenderer(ctx.layout.markers)
    writer = TotalsTabWriter(ctx.worksheet, renderer, ctx.layout, guard=ctx.guard)
    plan = writer.build_plan(
        matches=result.matches,
        snapshot=ctx.get("requirements"),
        system=result.location.system,
        station=result.location.station_display,
        checked_at=ctx.checked_at,
        write_header=options["write_header"],
        show_covered=options["show_covered"],
        apply_colour=options["apply_colour"],
        include_markers=options["include_markers"],
        # `.get` rather than `[...]` for this one alone: it is the option that
        # OVERWRITES, so a context that forgot to carry it must come out as
        # "no", never as a KeyError a caller might paper over.
        force=options.get("force", False),
        # The same reasoning: writing the location cells replaces whatever
        # the sheet computes there, so a context without the option says no.
        write_location=options.get("write_location", False),
    )
    if options["write"]:
        writer.apply(plan)
    return plan


def supplies() -> dict[str, Callable[[Refresh], Any]]:
    """What this plugin can be asked for. Pulled once per refresh, memoised."""
    return {"requirements": _read_requirements}


def subscribes() -> list[Subscription]:
    """What this plugin publishes, and what must be supplied first."""
    return [Subscription("markers", ("requirements",), _publish_markers)]
