"""
How this particular spreadsheet renders a market comparison.

This module is the OPINIONATED half of the sheet integration, and it is
optional by construction. It decides what a cell says and what colour it is;
it decides nothing about how cells are written, which ranges are permitted, or
where a column lives. Delete it and ``sheets.py`` still reads requirements and
writes whatever a different renderer hands it.

That separation is not tidiness. The project expects several spreadsheets --
settlement construction now, weapon upgrades and ship builds later -- each
asking the same structural question against a different domain, and each
wanting its own symbols. A renderer per sheet is a new file; glyph logic baked
into the writer would be a code change per sheet.

The dependency points one way and is enforced by a test: a renderer may depend
on ``sheets`` (this one happens not to need it, importing only the domain
types from ``matcher``), while ``sheets`` never imports from here.
"""

from __future__ import annotations

from typing import Optional

from ..matcher import Match, MatchState

# One glyph family: the same circle at five fill levels, so the marker column
# reads as a SCALE rather than a set of unrelated symbols. How full the circle
# is, is how much of the outstanding requirement this station can cover.
#
#   ●  ENOUGH    solid          -- buy the whole outstanding quantity here
#   ◕  PARTIAL   three-quarters -- covers most of it
#   ◑  PARTIAL   half           -- covers about half
#   ◔  PARTIAL   quarter        -- covers a little
#   ○  EMPTY     hollow         -- sells it, has none right now
#   (blank)                     -- not traded here, or nothing needed
#
# This is the "harvey ball" convention, the standard way to show a proportion
# as a single character, and it is why the hollow ring matters: an empty circle
# and a full circle are the two ends of one scale, so "sold here but out"
# reads as zero coverage rather than as a different kind of thing.
#
# Fill proceeds clockwise from the top, which is why the half glyph is U+25D1
# (RIGHT half black) rather than U+25D0.
MARKER_ENOUGH = "●"         # U+25CF BLACK CIRCLE
MARKER_THREE_QUARTER = "◕"  # U+25D5 ALL BUT UPPER LEFT QUADRANT BLACK
MARKER_HALF = "◑"           # U+25D1 RIGHT HALF BLACK
MARKER_QUARTER = "◔"        # U+25D4 UPPER RIGHT QUADRANT BLACK
MARKER_EMPTY = "○"          # U+25CB WHITE CIRCLE
MARKER_BLANK = ""

# Rows you need none of still get their glyph, but greyed out (see COLOUR
# below). That is what distinguishes "the station does not sell this" (blank)
# from "it is here, you just do not need any" -- the question that a purely
# blank cell could not answer.
MARKER_COVERED = "✓"        # U+2713 CHECK MARK, for the tick-only style


# ---------------------------------------------------------------------------
# Colour: the marker cell's fill says how much of your need is covered
# ---------------------------------------------------------------------------
#
# The glyph and the colour carry the same signal deliberately. Colour is what
# the eye finds when scanning a column; the glyph is what survives being
# printed, copied as text, or read by someone who cannot distinguish the
# greens. Neither is load-bearing alone.
#
#   dark green   buy the whole outstanding quantity here
#   ...          progressively lighter as the station covers less of it
#   near-white   sells it, out of stock right now
#   no fill      not sold here -- or you need none of it
#
# A row with nothing outstanding is never coloured. It gets grey text instead,
# so it reads as background information rather than as an action.

def _rgb(hex_colour: str) -> dict:
    """'#38761d' -> the Sheets API's 0..1 float triple."""
    text = hex_colour.lstrip("#")
    return {
        "red": int(text[0:2], 16) / 255,
        "green": int(text[2:4], 16) / 255,
        "blue": int(text[4:6], 16) / 255,
    }


COLOUR_ENOUGH = "#38761d"          # dark green
COLOUR_THREE_QUARTER = "#6aa84f"
COLOUR_HALF = "#93c47d"
COLOUR_QUARTER = "#b6d7a8"
COLOUR_EMPTY = "#e8f2e4"           # nearly white: here, but none in stock
COLOUR_TEXT_ON_DARK = "#ffffff"
COLOUR_TEXT_ON_LIGHT = "#000000"
COLOUR_TEXT_COVERED = "#999999"    # mid grey: available, but you need none

# Which fill goes with which glyph. Keyed by glyph so the two scales cannot
# drift apart.
FILL_FOR_MARKER = {
    MARKER_ENOUGH: COLOUR_ENOUGH,
    MARKER_THREE_QUARTER: COLOUR_THREE_QUARTER,
    MARKER_HALF: COLOUR_HALF,
    MARKER_QUARTER: COLOUR_QUARTER,
    MARKER_EMPTY: COLOUR_EMPTY,
}
# Only the darkest fill needs light text to stay legible.
LIGHT_TEXT_MARKERS = frozenset({MARKER_ENOUGH})

# Lighter alternatives for the empty state, for anyone who prefers a smaller
# mark. Both break the size symmetry with the filled glyph, which is what makes
# the scale legible at a glance -- so they are offered, not defaulted.
MARKER_EMPTY_SMALL = "◦"    # U+25E6 WHITE BULLET
MARKER_EMPTY_DOTTED = "◌"   # U+25CC DOTTED CIRCLE, Unicode's own placeholder

# Coverage thresholds, applied to buyable/need. Rounding is to the NEAREST
# quarter, so a station covering 60% shows a half rather than a three-quarter.
_PARTIAL_SCALE = (
    (0.375, MARKER_QUARTER),
    (0.625, MARKER_HALF),
    (1.0, MARKER_THREE_QUARTER),
)

# Backwards-compatible flat mapping, used when a caller supplies no scale.
MARKER_PARTIAL = MARKER_HALF
MARKER_FOR_STATE = {
    MatchState.ENOUGH: MARKER_ENOUGH,
    MatchState.PARTIAL: MARKER_PARTIAL,
    MatchState.EMPTY: MARKER_EMPTY,
}


def coverage(match: Match) -> float:
    """
    What fraction of the outstanding requirement this station can supply.

    Clamped to [0, 1]: a station with far more stock than we need still only
    covers 100% of the need, and that is what the glyph should say.
    """
    if match.need <= 0:
        return 0.0
    return max(0.0, min(1.0, match.buyable_qty / match.need))


def marker_for(
    match: Match,
    markers: Optional[dict] = None,
    show_covered: bool = False,
) -> str:
    """
    The glyph for one match. Blank unless the row earns a mark.

    ``markers`` overrides the ENOUGH/PARTIAL/EMPTY glyphs wholesale. When it is
    supplied, PARTIAL collapses to a single glyph; the graded quarter/half/
    three-quarter scale applies only to the default family.

    ``show_covered`` disambiguates the two reasons a cell would otherwise be
    blank: "the station does not sell this" and "the station sells it but you
    already have all you need". Off by default because on a real sheet the
    second case was 13 of 28 rows -- useful when cross-checking against the
    station screen, clutter when deciding what to buy.
    """
    if match.is_covered:
        if not (show_covered and match.is_sold_here):
            return MARKER_BLANK
        if markers is not None:
            return MARKER_COVERED
        # Same glyph the row would have earned if you needed it -- greyed out
        # by the cell format rather than replaced. "There are 731,096 here"
        # and "you need none" are two facts, and the reader wants both.
        return _fill_glyph(match)
    if not match.should_mark:
        return MARKER_BLANK
    if markers is not None:
        return markers.get(match.state, MARKER_BLANK)
    return _fill_glyph(match)


def _fill_glyph(match: Match) -> str:
    """
    The fill-scale glyph for a match, ignoring whether anything is outstanding.

    Split out so a covered row can show the same glyph it would have earned,
    distinguished by colour rather than by symbol.
    """
    if match.item is None:
        return MARKER_BLANK
    if match.item.is_stocked_when_available:
        return MARKER_EMPTY
    if not match.item.is_purchasable:
        return MARKER_BLANK
    if match.is_covered:
        # No outstanding quantity to measure against, but the station has
        # stock -- that is the top of the scale.
        return MARKER_ENOUGH
    if match.state is MatchState.ENOUGH:
        return MARKER_ENOUGH
    ratio = coverage(match)
    for threshold, glyph in _PARTIAL_SCALE:
        if ratio < threshold:
            return glyph
    return MARKER_THREE_QUARTER


def _cell_format(match: Optional[Match], glyph: str) -> dict:
    """
    The CellFormat for one marker cell.

    Every cell in the block gets an explicit format, including the empty ones.
    That is deliberate: a cell that stops qualifying must have last run's
    colour actively cleared, exactly as its glyph is actively blanked. Leaving
    formatting behind would be the visual equivalent of a stale marker.
    """
    fmt: dict = {
        "backgroundColor": _rgb("#ffffff"),
        "textFormat": {"bold": False, "foregroundColor": _rgb(COLOUR_TEXT_ON_LIGHT)},
        "horizontalAlignment": "CENTER",
    }
    if not glyph or match is None:
        return fmt

    if match.is_covered:
        # Available here, but nothing outstanding: grey text, no fill, so it
        # reads as information rather than as something to act on.
        fmt["textFormat"] = {
            "bold": False,
            "foregroundColor": _rgb(COLOUR_TEXT_COVERED),
        }
        return fmt

    fill = FILL_FOR_MARKER.get(glyph)
    if fill:
        fmt["backgroundColor"] = _rgb(fill)
    text_colour = (
        COLOUR_TEXT_ON_DARK if glyph in LIGHT_TEXT_MARKERS else COLOUR_TEXT_ON_LIGHT
    )
    fmt["textFormat"] = {"bold": True, "foregroundColor": _rgb(text_colour)}
    return fmt


def marker_note(match: Match, checked_at: str = "") -> str:
    """The cell note carrying the numbers behind a glyph."""
    if not match.should_mark:
        return ""
    lines = [f"{match.name}", f"Need: {match.need:,}"]
    if match.state is MatchState.EMPTY:
        lines.append("Stock: 0 (sold here, currently out)")
        if match.unit_price:
            lines.append(f"Unit price: {match.unit_price:,} cr")
    else:
        lines.append(f"Stock: {match.stock:,}")
        lines.append(f"Buy now: {match.buyable_qty:,}")
        lines.append(f"Unit price: {match.unit_price:,} cr")
        lines.append(f"Estimated cost: {match.estimated_cost:,} cr")
    if checked_at:
        lines.append(f"Market checked: {checked_at}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The renderer: this workbook's answers to the writer's three questions
# ---------------------------------------------------------------------------


class MarketRenderer:
    """
    Renders the settlement-tracking sheet's marker column.

    Satisfies :class:`APITool.sheets.CellRenderer` structurally -- there is no
    inheritance, because the protocol is what a renderer must *do*, not what it
    must *be*. A weapon-upgrade or ship-build sheet supplies its own class with
    the same three methods and reuses every line of the writer.

    ``markers`` optionally overrides the glyph vocabulary; passing one collapses
    the graded quarter/half/three-quarter scale to a single PARTIAL symbol,
    which is what ``--empty-marker`` does.
    """

    def __init__(self, markers: Optional[dict] = None):
        self.markers = markers

    def cell(self, match: Match, show_covered: bool = True) -> str:
        return marker_for(match, self.markers, show_covered=show_covered)

    def cell_format(self, match: Optional[Match], value: str) -> dict:
        return _cell_format(match, value)

    def cell_note(self, match: Match, checked_at: str = "") -> str:
        return marker_note(match, checked_at)


# ---------------------------------------------------------------------------
# The formula that reproduces this scale inside the spreadsheet
#
# A sheet reading a generated MarketData tab renders its own markers, so the
# glyphs and thresholds have to be stated in a formula. Rendered here, from the
# same constants the writer uses, for the reason cargo.lookup_formula gives:
# documentation that restates a rule is a second definition of it, and the two
# drift silently. This one had already drifted into being the ONLY definition
# the owner's live sheet was built from -- 197 formulas came from a docstring.
# ---------------------------------------------------------------------------

def _threshold(value: float) -> str:
    """0.375 -> '0.375', 1.0 -> '1'. Sheets does not want trailing zeros."""
    return f"{value:g}"


def marker_formula(
    key_cell: str = "$B5",
    need_cell: str = "$G5",
    tab: str = "MarketData",
    lookup_range: str = "$B:$G",
    stock_index: int = 2,
    buy_index: int = 3,
) -> str:
    """
    The marker formula, built from :data:`_PARTIAL_SCALE` and the glyphs.

    Every threshold and symbol comes from the module constants, so changing
    the scale changes this formula and the tool's own output together.
    """
    partial = list(_PARTIAL_SCALE)
    if not partial:
        raise ValueError("_PARTIAL_SCALE is empty; there is no scale to render")

    # All but the last band become a test; the last band is the final else,
    # since anything not below the earlier thresholds falls into it.
    *bands, (_, top_glyph) = partial

    branches = [
        'IF(buy=0,""',
        f'IF(stock=0,"{MARKER_EMPTY}"',
        f'IF(need<=0,"{MARKER_ENOUGH}"',
        f'IF(stock>=need,"{MARKER_ENOUGH}"',
    ]
    branches += [
        f'IF(stock/need<{_threshold(limit)},"{glyph}"' for limit, glyph in bands
    ]

    body = ""
    for depth, branch in enumerate(branches):
        body += "\n" + "   " + " " * depth + branch + ","
    body += f'"{top_glyph}"' + ")" * len(branches)

    return (
        f'=IF({key_cell}="","",LET('
        f"\n   need,  {need_cell},"
        f"\n   stock, IFERROR(VLOOKUP({key_cell},{tab}!{lookup_range},"
        f"{stock_index},FALSE),0),"
        f"\n   buy,   IFERROR(VLOOKUP({key_cell},{tab}!{lookup_range},"
        f"{buy_index},FALSE),0),"
        f"{body}))"
    )


#: What each glyph means, in the order the scale runs. Read by the help text.
MARKER_LEGEND = (
    (MARKER_ENOUGH, "buy the whole outstanding quantity here"),
    (MARKER_THREE_QUARTER, "covers most of it"),
    (MARKER_HALF, "covers about half"),
    (MARKER_QUARTER, "covers a little"),
    (MARKER_EMPTY, "sold here, out of stock right now"),
    ("(blank)", "not sold here"),
)


def marker_formula_help(tab: str = "MarketData") -> str:
    """The full --show-formula text, generated rather than transcribed."""
    legend = "\n".join(f"   {glyph}  {meaning}" for glyph, meaning in MARKER_LEGEND)
    fills = "\n".join(
        f"     {glyph}  {colour}"
        + ("  (white bold text)" if glyph in LIGHT_TEXT_MARKERS else "")
        for glyph, colour in FILL_FOR_MARKER.items()
    )
    return f"""\
Reproducing the marker column from a {tab} tab
{'=' * (len('Reproducing the marker column from a  tab') + len(tab))}

`edapitool market --export market-tab` writes the station's market to a
generated {tab} tab. Your spreadsheet can then produce the markers itself,
which means you own the symbols and the colours -- change them without touching
any code.

1. Put this in the first commodity row of your marker column (e.g. L5) and fill
   it down. It assumes commodity names in column B and the outstanding quantity
   in column G; adjust those two references if your layout differs.

{marker_formula(tab=tab)}

{legend}

   A grey {MARKER_ENOUGH} or {MARKER_EMPTY} means it is available but you need
   none -- that falls out of the `need<=0` branch above combined with the
   colour rules below.

2. Add conditional formatting on the same range, one rule per state, using
   "Text is exactly" on each symbol. Suggested fills:

{fills}
     ...and a rule matching G=0 for grey {COLOUR_TEXT_COVERED} text, no fill.

3. Then run with --no-markers so the tool writes only data:

     edapitool market --sheet-id ID --export market-tab --no-markers

   --no-markers still refreshes the location cells; it only leaves your marker
   column alone.

The tool keeps writing markers directly by default, so nothing changes until
you choose to switch."""
