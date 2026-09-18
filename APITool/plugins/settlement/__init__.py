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

The two halves of the contract are not the same shape, and that is the
design (APITool.registry says why). This plugin supplies the requirements it
reads from its tab, and subscribes to publish the marker column beside them.
"""

from typing import Any, Callable, Optional

from ...registry import Refresh, Subscription
from .bindings import construction_regions  # noqa: F401 -- part of the surface above
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
