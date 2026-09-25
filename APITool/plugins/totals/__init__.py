"""
The roll-up tab's own conventions -- DEMOTED, deliberately.

Until v0.8.0 this was the ``settlement`` plugin, which also carried the
construction-region bindings; those are the ``construction`` plugin's now,
so that one directory holds one vocabulary. A target that named
``"plugin": "settlement"`` names ``"totals"`` from here on, and a workbook
that keeps the old tab name sets ``"totals_tab": "Totals Tab"`` in its block.

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
    flags()               the command-line words it owns, registered only
                          when it is loaded
    default_config()      a starter block, for `plugins describe`
    check_config(config)  what is wrong with a block, or nothing; core asks
                          and repeats the answer without reading the block

The two halves of the contract are not the same shape, and that is the
design (APITool.registry says why). This plugin supplies the requirements it
reads from its tab, and subscribes to publish the marker column beside them.
"""

from typing import Any, Callable, Optional

from ...registry import Flag, Refresh, Subscription
from .layout import SheetLayout

# A Google sheet. Configuration may name a kind per target and overrides this;
# with no targets configured, this is what the shipped plugin is.
KIND = "gsheet"


def flags() -> list[Flag]:
    """
    This workbook's own words, declared here so core never has to know them.

    Every flag below means something only to a settlement roll-up tab: which
    tab, which column, which glyph family, whether to paint the location
    cells. Core registers them into `market` and `serve` only when this
    plugin is loaded, so an install without it never sees them, and hands
    the typed values back unread -- ``layout=True`` ones to ``layout()``,
    the rest in the refresh's ``options`` envelope, by the ``dest`` names
    ``_publish_markers`` reads.

    The group these appear under is titled by the plugin's name; the words
    "glyph marker" in the help are #28's rename, made where the glyphs live.
    """
    tab = "Name of the roll-up tab (default: the plugin's own, or your target's totals_tab)"
    location = ("Also write the current system and station into the roll-up "
                "tab's location cells. Off by default: those cells are better as "
                "formulas reading the generated MarketData tab, and writing "
                "literals would overwrite them. Use only for a sheet that still "
                "expects the tool to paint them. DEPRECATED: may be removed in a "
                "release after 2027-01-01")
    return [
        # the spreadsheet's shape -- layout overrides
        Flag("market", "--totals-tab", "totals_tab", "string", help=tab, layout=True),
        Flag("market", "--need-header", "need_header", "string", layout=True,
             help="Header text of the outstanding-quantity column (default: the plugin's own)"),
        Flag("market", "--need-sign", "need_sign", "choices", choices=("positive", "negative"),
             layout=True,
             help="Which sign means 'still to buy' (use 'negative' for a combined "
                  "signed column where -229 means buy 229)"),
        Flag("market", "--glyph-marker-column", "marker_column", "string", layout=True,
             help="Column to write glyph markers into (default: the plugin's own)"),
        Flag("market", "--empty-glyph-marker", "empty_marker", "choices",
             choices=("hollow", "small", "dotted"), layout=True,
             help="Glyph marker for 'station sells it but has none right now': "
                  "hollow circle (default, matches the filled/half-filled family), "
                  "small white bullet, or dotted circle"),
        # writing -- what the plan does when applied
        Flag("market", "--force", "force", "store_true",
             help="Overwrite glyph-marker cells that already hold something. By "
                  "default a cell with anything in it is left alone, because on "
                  "many sheets that column holds formulas which compute the "
                  "markers themselves. There is no undo."),
        Flag("market", "--write-location", "write_location", "store_true", help=location),
        Flag("market", "--write-glyph-marker-header", "write_marker_header", "store_true",
             help="Also label the cell above the glyph markers (default: leave it "
                  "alone, it is yours)"),
        Flag("market", "--no-glyph-markers", "no_markers", "store_true",
             help="Do not write the glyph-marker column. Pair with '--export "
                  "market-tab' to let the spreadsheet render markers from the "
                  "data using its own formulas."),
        Flag("market", "--no-show-covered", "no_show_covered", "store_true",
             help="Do not mark commodities the station sells that you already have "
                  "enough of (they are shown greyed out by default, so a blank "
                  "cell means 'not sold here')"),
        # One spelling, not two: `--no-color`, with a British dest because
        # everything behind it (`apply_colour`, the renderer) already is.
        Flag("market", "--no-color", "no_colour", "store_true",
             help="Write only the glyph markers, leaving cell background and font "
                  "color alone"),
        Flag("market", "--show-formula", "show_formula", "store_true",
             help="Print the spreadsheet formula that reproduces the glyph-marker "
                  "column from a MarketData tab, then exit"),
        # serve: the same tab and the same location cells
        Flag("serve", "--totals-tab", "totals_tab", "string", layout=True,
             help="Name of the roll-up tab whose location cells are refreshed "
                  "with --write-location (default: the plugin's own, or your "
                  "target's totals_tab)"),
        Flag("serve", "--write-location", "write_location", "store_true", help=location),
    ]


def markers_for(empty_marker: Optional[str] = "hollow") -> Optional[dict]:
    """
    The glyph family ``--empty-glyph-marker`` selects, decided where the glyphs live.

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
    """
    A starter block for someone configuring this plugin for the first time.

    The one key a roll-up target commonly sets is the tab's name, and the
    starter names the template workbook's, because that is the sheet a new
    install points at. A copy of the template that renames the tab drops
    the key and gets this plugin's own default, ``Totals``.
    """
    return {"totals_tab": "Totals Tab"}


def check_config(config: Optional[dict]) -> list[str]:
    """What is wrong with this target's block: nothing this plugin can tell yet."""
    problems: list[str] = []
    if not config:
        return problems
    tab = config.get("totals_tab")
    if tab is not None and (not isinstance(tab, str) or not tab.strip()):
        problems.append('"totals_tab" must be a non-empty string')
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
        # Every word here is this plugin's own, read by the `dest` its
        # flags() declares, with this plugin's default: a caller that carries
        # only the options it means to set (the daemon names two) gets the
        # same answer a person typing nothing would.
        write_header=options.get("write_marker_header", False),
        show_covered=not options.get("no_show_covered", False),
        apply_colour=not options.get("no_colour", False),
        include_markers=not options.get("no_markers", False),
        # The option that OVERWRITES: a context that forgot to carry it must
        # come out as "no", never as a KeyError a caller might paper over.
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
