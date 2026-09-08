"""
Reading requirements from, and writing markers to, the tracking spreadsheet.

Everything here is built around one measured fact about the real sheet: the
commodity list in column B is not data, it is the tail of a formula chain.

    AA5 = SORT(UNIQUE(FILTER(TOCOL(R5:Z201,1), ...)))     <- spills from the
                                                             settlement tabs
    B5  = IF($AA5="","", HYPERLINK(inara_url_using($C$2), $AA5))
    G5  = IF($B5="","", MAX(0, $F5-$D5-$M5))              <- "Left to buy"

Three consequences drive every design choice below:

1. **Row identity is not stable.** Adding one commodity to any settlement tab
   re-sorts AA and shifts every row beneath it. A marker written against a
   remembered row number will, sooner or later, label the wrong commodity. So
   we read names and requirements in ONE call and write markers keyed to that
   same snapshot, never to cached positions.

2. **Column B must never be written.** It is a formula, and overwriting it
   would destroy the INARA hyperlinks and detach the sheet from its source
   tabs.

3. **Columns move.** Headers are discovered by text, never assumed by letter.

Writes are deny-by-default: see :class:`WriteGuard`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Iterable, Optional, Protocol, Sequence

from .catalog import CommodityCatalog
from .matcher import Match, MatchState, Requirement, build_requirements

# ---------------------------------------------------------------------------
# A1 notation
# ---------------------------------------------------------------------------

_A1_CELL = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")


def column_to_index(letters: str) -> int:
    """'A' -> 0, 'Z' -> 25, 'AA' -> 26."""
    total = 0
    for char in letters.upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"not a column reference: {letters!r}")
        total = total * 26 + (ord(char) - 64)
    return total - 1


def index_to_column(index: int) -> str:
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA'."""
    if index < 0:
        raise ValueError(f"negative column index: {index}")
    letters = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


@dataclass(frozen=True)
class CellRange:
    """
    A rectangular region in A1 notation, with open ends allowed.

    ``None`` for a bound means unbounded in that direction, so ``L5:L``
    (everything in column L from row 5 down) is expressible.
    """

    first_col: Optional[int]
    first_row: Optional[int]
    last_col: Optional[int]
    last_row: Optional[int]

    @classmethod
    def parse(cls, a1: str) -> "CellRange":
        text = a1.strip().replace("$", "")
        if not text:
            raise ValueError("empty range")
        if ":" not in text:
            match = _A1_CELL.match(text)
            if not match:
                raise ValueError(f"not a cell reference: {a1!r}")
            col, row = column_to_index(match.group(1)), int(match.group(2))
            return cls(col, row, col, row)

        start, _, end = text.partition(":")
        first_col, first_row = cls._parse_corner(start, a1)
        last_col, last_row = cls._parse_corner(end, a1)
        if (first_col, first_row, last_col, last_row) == (None, None, None, None):
            # ":" would otherwise parse as a fully unbounded range, which
            # contains every cell -- an allowlist entry of ":" would silently
            # permit writing anywhere. Refuse it.
            raise ValueError(f"not a range: {a1!r}")
        return cls(first_col, first_row, last_col, last_row)

    @staticmethod
    def _parse_corner(text: str, original: str) -> tuple[Optional[int], Optional[int]]:
        if not text:
            return None, None
        match = re.match(r"^([A-Za-z]{1,3})?(\d+)?$", text)
        if not match or (match.group(1) is None and match.group(2) is None):
            raise ValueError(f"not a range: {original!r}")
        col = column_to_index(match.group(1)) if match.group(1) else None
        row = int(match.group(2)) if match.group(2) else None
        return col, row

    def contains(self, other: "CellRange") -> bool:
        """Is ``other`` entirely inside this range?"""
        return (
            self._covers(self.first_col, self.last_col, other.first_col, other.last_col)
            and self._covers(self.first_row, self.last_row, other.first_row, other.last_row)
        )

    @staticmethod
    def _covers(lo, hi, other_lo, other_hi) -> bool:
        if lo is not None:
            if other_lo is None or other_lo < lo:
                return False
        if hi is not None:
            if other_hi is None or other_hi > hi:
                return False
        return True


# ---------------------------------------------------------------------------
# B-2: the write allowlist
# ---------------------------------------------------------------------------

class WriteRefused(Exception):
    """A write was attempted outside the allowlist."""


@dataclass(frozen=True)
class WriteGuard:
    """
    Deny-by-default gate on every spreadsheet write.

    The previous guard in ``gsheet.py`` was an allow-by-default DENY list --
    ``PROTECTED_TABS = ["Base", "1st", "2", "3", "Sheet3"]`` -- which named
    three tabs that do not exist in the real workbook while leaving every tab
    that holds irreplaceable hand-entered work (``Totals Tab``,
    ``Agri Lrg. (ex)``, ``Sat. (ex)``, ``Extr. (ex)``) unprotected. A deny list
    fails open: any tab nobody thought of is writable. This fails closed.
    """

    allowed: dict[str, tuple[CellRange, ...]] = field(default_factory=dict)

    @classmethod
    def build(cls, permissions: dict[str, Sequence[str]]) -> "WriteGuard":
        return cls(
            allowed={
                tab: tuple(CellRange.parse(r) for r in ranges)
                for tab, ranges in permissions.items()
            }
        )

    def allows(self, tab: str, a1: str) -> bool:
        ranges = self.allowed.get(tab)
        if not ranges:
            return False
        try:
            target = CellRange.parse(a1)
        except ValueError:
            return False
        return any(allowed.contains(target) for allowed in ranges)

    def check(self, tab: str, a1: str) -> None:
        """Raise :class:`WriteRefused` unless the write is allowlisted."""
        if not self.allows(tab, a1):
            permitted = ", ".join(
                f"{t}!{r}" for t, rs in self.allowed.items() for r in self._render(rs)
            ) or "(nothing)"
            raise WriteRefused(
                f"refusing to write {tab}!{a1}: outside the allowlist. Permitted: {permitted}"
            )

    @staticmethod
    def _render(ranges: Iterable[CellRange]) -> list[str]:
        out = []
        for r in ranges:
            start = f"{index_to_column(r.first_col) if r.first_col is not None else ''}" \
                    f"{r.first_row if r.first_row is not None else ''}"
            end = f"{index_to_column(r.last_col) if r.last_col is not None else ''}" \
                  f"{r.last_row if r.last_row is not None else ''}"
            out.append(start if start == end else f"{start}:{end}")
        return out


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

SIGN_POSITIVE = "positive"
SIGN_NEGATIVE = "negative"


@dataclass(frozen=True)
class SheetLayout:
    """
    Where things live in the tracking spreadsheet.

    Defaults match the measured live layout (2026-09-08): headers on row 3,
    commodity rows from 5, "Left to buy" in column G, column L empty.

    ``need_sign`` supports the planned merge of "Left to buy" and "Extra next
    rnd" into a single signed column: with ``SIGN_NEGATIVE`` a value of -229
    means "buy 229" and +40 means "40 spare".
    """

    totals_tab: str = "Totals Tab"
    cargo_tab: str = "CargoData"
    header_row: int = 3
    first_data_row: int = 5
    name_column: str = "B"
    name_header: str = "ALL SETTLEMENTS"
    need_header: str = "Left to buy"
    need_sign: str = SIGN_POSITIVE
    marker_column: str = "L"
    marker_header: str = "At Current Station"
    system_cell: str = "C2"
    station_cell: str = "G2"
    max_scan_row: int = 400
    # Overridable glyphs; see the MARKER_* constants for the alternatives.
    markers: Optional[dict] = None

    def marker_map(self) -> dict:
        return self.markers or MARKER_FOR_STATE

    @property
    def name_column_index(self) -> int:
        return column_to_index(self.name_column)

    @property
    def marker_column_index(self) -> int:
        return column_to_index(self.marker_column)

    def marker_range(self, last_row: int) -> str:
        return f"{self.marker_column}{self.first_data_row}:{self.marker_column}{last_row}"

    def marker_header_cell(self) -> str:
        return f"{self.marker_column}{self.header_row}"

    def guard(self) -> WriteGuard:
        """The only writes this tool is ever permitted to make."""
        return WriteGuard.build(
            {
                self.totals_tab: [
                    self.system_cell,
                    self.station_cell,
                    # The marker column, header row downward. Nothing else.
                    f"{self.marker_column}{self.header_row}:{self.marker_column}",
                ],
                # CargoData is fully generated by this tool; a whole-tab
                # rewrite there is the existing, intended behaviour.
                self.cargo_tab: ["A1:Z1000"],
            }
        )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

class WorksheetLike(Protocol):
    """The slice of gspread's Worksheet this module needs."""

    def get_values(self, range_name: str, **kwargs) -> list[list[str]]: ...
    def batch_update(self, data: list[dict], **kwargs): ...


class SheetLayoutError(Exception):
    """The sheet does not look the way the configuration says it should."""


def parse_quantity(raw: object) -> Optional[int]:
    """
    Parse a quantity as the sheet renders it.

    Sheets returns display strings, so thousands separators and currency-ish
    decoration are normal: '1,716' -> 1716. Returns None for blanks and for
    error values -- a formula mid-recalculation shows '#N/A', and treating
    that as zero would silently drop a real requirement.
    """
    text = str(raw).strip()
    if not text or text.startswith("#"):
        return None
    text = text.replace(",", "").replace(" ", "").replace(" ", "")
    if text in ("-", "--", "—"):
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None


@dataclass(frozen=True)
class RequirementSnapshot:
    """
    One consistent read of the Totals Tab.

    Everything downstream keys off this single snapshot, because the row
    numbering it describes is only guaranteed valid for this read.
    """

    requirements: list[Requirement]
    last_data_row: int
    need_column_index: int
    header_row: int
    unparsed_rows: list[tuple[int, str, str]] = field(default_factory=list)

    @property
    def outstanding(self) -> list[Requirement]:
        return [r for r in self.requirements if r.is_outstanding]


class TotalsTabReader:
    """Reads commodity names and outstanding quantities by header discovery."""

    def __init__(
        self,
        worksheet: WorksheetLike,
        layout: Optional[SheetLayout] = None,
        catalog: Optional[CommodityCatalog] = None,
    ):
        self.worksheet = worksheet
        self.layout = layout or SheetLayout()
        self.catalog = catalog

    def find_column(self, header_row_values: Sequence[str], header: str) -> int:
        """
        Locate a column by exact header text.

        Fails loudly on both missing and duplicate headers. Guessing at either
        would put markers in an arbitrary column.
        """
        wanted = header.strip().casefold()
        hits = [
            i for i, value in enumerate(header_row_values)
            if str(value).strip().casefold() == wanted
        ]
        if not hits:
            present = [str(v).strip() for v in header_row_values if str(v).strip()]
            raise SheetLayoutError(
                f"header {header!r} not found in row {self.layout.header_row} "
                f"of {self.layout.totals_tab!r}. Headers present: {present}"
            )
        if len(hits) > 1:
            columns = ", ".join(index_to_column(i) for i in hits)
            raise SheetLayoutError(
                f"header {header!r} appears in multiple columns ({columns}) "
                f"of {self.layout.totals_tab!r}; cannot choose one safely"
            )
        return hits[0]

    def read(self) -> RequirementSnapshot:
        """Read the whole commodity block in a single API call."""
        layout = self.layout
        grid = self.worksheet.get_values(f"A1:AZ{layout.max_scan_row}")
        if len(grid) < layout.header_row:
            raise SheetLayoutError(
                f"{layout.totals_tab!r} has fewer than {layout.header_row} rows; "
                "is the tab name or header row misconfigured?"
            )

        header_values = grid[layout.header_row - 1]
        need_col = self.find_column(header_values, layout.need_header)
        name_col = layout.name_column_index

        rows: list[tuple[int, str, int]] = []
        unparsed: list[tuple[int, str, str]] = []
        last_row = layout.first_data_row - 1

        for row_number in range(layout.first_data_row, len(grid) + 1):
            row = grid[row_number - 1]
            name = str(row[name_col]).strip() if len(row) > name_col else ""
            if not name:
                continue
            last_row = row_number

            raw = row[need_col] if len(row) > need_col else ""
            quantity = parse_quantity(raw)
            if quantity is None:
                # Blank is a legitimate "nothing needed"; an error value is
                # not, and the caller should hear about it.
                if str(raw).strip():
                    unparsed.append((row_number, name, str(raw).strip()))
                quantity = 0
            rows.append((row_number, name, self._apply_sign(quantity)))

        return RequirementSnapshot(
            requirements=build_requirements(rows, self.catalog),
            last_data_row=last_row,
            need_column_index=need_col,
            header_row=layout.header_row,
            unparsed_rows=unparsed,
        )

    def _apply_sign(self, quantity: int) -> int:
        """
        Normalize the sheet's convention to "positive means still to buy".

        With ``SIGN_NEGATIVE`` the column is the planned combined
        "What's left", where negative means outstanding and positive means
        surplus.
        """
        if self.layout.need_sign == SIGN_NEGATIVE:
            return -quantity
        return quantity


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

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


@dataclass
class MarkerPlan:
    """
    Exactly what will be written, computed before anything is sent.

    Having this as a value lets ``--dry-run`` print the real plan, and lets
    tests assert on writes without a network.
    """

    updates: list[dict] = field(default_factory=list)
    formats: list[dict] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    marked_rows: list[int] = field(default_factory=list)
    covered_rows: list[int] = field(default_factory=list)

    def ranges(self) -> list[str]:
        return [u["range"] for u in self.updates]

    def format_ranges(self) -> list[str]:
        return [f["range"] for f in self.formats]


class TotalsTabWriter:
    """
    Writes location cells and markers, and nothing else.

    Every range passes through :class:`WriteGuard` before it is sent, so a
    misconfigured layout fails with an exception instead of overwriting
    formulas.
    """

    def __init__(
        self,
        worksheet: WorksheetLike,
        layout: Optional[SheetLayout] = None,
        guard: Optional[WriteGuard] = None,
    ):
        self.worksheet = worksheet
        self.layout = layout or SheetLayout()
        self.guard = guard or self.layout.guard()

    def build_plan(
        self,
        matches: Sequence[Match],
        snapshot: RequirementSnapshot,
        system: str,
        station: str,
        checked_at: str = "",
        write_header: bool = False,
        show_covered: bool = True,
        apply_colour: bool = True,
    ) -> MarkerPlan:
        """
        Build the full write plan from ONE requirement snapshot.

        The marker column is rewritten wholesale from the first data row to
        the snapshot's last data row -- never patched cell by cell. That is
        what keeps stale markers from surviving a row shift.

        ``write_header`` defaults to False: the header cell above the markers
        belongs to the person who owns the sheet, and silently replacing
        whatever they put there is exactly the kind of unasked-for write this
        module is built to avoid. Opt in explicitly to have it labelled.
        """
        layout = self.layout
        plan = MarkerPlan()

        plan.updates.append({"range": layout.system_cell, "values": [[system]]})
        plan.updates.append({"range": layout.station_cell, "values": [[station]]})
        if write_header:
            plan.updates.append(
                {"range": layout.marker_header_cell(), "values": [[layout.marker_header]]}
            )

        by_row = {m.row: m for m in matches}
        first, last = layout.first_data_row, snapshot.last_data_row
        column: list[list[str]] = []
        for row_number in range(first, last + 1):
            match = by_row.get(row_number)
            glyph = (
                marker_for(match, layout.markers, show_covered=show_covered)
                if match
                else MARKER_BLANK
            )
            column.append([glyph])
            cell = f"{layout.marker_column}{row_number}"
            if glyph:
                covered = match is not None and match.is_covered
                (plan.covered_rows if covered else plan.marked_rows).append(row_number)
                note = marker_note(match, checked_at)
                if note:
                    plan.notes[cell] = note
            if apply_colour:
                plan.formats.append(
                    {"range": cell, "format": _cell_format(match, glyph)}
                )

        if last >= first:
            plan.updates.append(
                {"range": layout.marker_range(last), "values": column}
            )

        for update in plan.updates:
            self.guard.check(layout.totals_tab, update["range"])
        # Formatting is a write like any other and goes through the same gate.
        for entry in plan.formats:
            self.guard.check(layout.totals_tab, entry["range"])
        return plan

    def apply(self, plan: MarkerPlan) -> int:
        """Send the plan in one batch. Returns the number of ranges written."""
        for update in plan.updates:
            self.guard.check(self.layout.totals_tab, update["range"])
        if not plan.updates:
            return 0
        # gspread rewrites each dict's "range" in place, prefixing the sheet
        # title ("L3" -> "'Totals Tab'!L3"). Handing it our own dicts would
        # corrupt the plan: a second apply would re-prefix an already-qualified
        # range, and the guard check above would reject the mangled result. So
        # send copies and keep the plan as a clean, reusable record of intent.
        payload = [{"range": u["range"], "values": u["values"]} for u in plan.updates]
        self.worksheet.batch_update(payload, value_input_option="USER_ENTERED")

        if plan.formats:
            # Same copy-don't-hand-over-our-dicts rule as above.
            self.worksheet.batch_format(
                [{"range": f["range"], "format": f["format"]} for f in plan.formats]
            )
        return len(plan.updates)


__all__ = [
    "CellRange",
    "COLOUR_EMPTY",
    "COLOUR_ENOUGH",
    "COLOUR_TEXT_COVERED",
    "FILL_FOR_MARKER",
    "MARKER_BLANK",
    "MARKER_COVERED",
    "MARKER_EMPTY",
    "MARKER_EMPTY_DOTTED",
    "MARKER_EMPTY_SMALL",
    "MARKER_ENOUGH",
    "MARKER_FOR_STATE",
    "MARKER_HALF",
    "MARKER_PARTIAL",
    "MARKER_QUARTER",
    "MARKER_THREE_QUARTER",
    "coverage",
    "MarkerPlan",
    "RequirementSnapshot",
    "SIGN_NEGATIVE",
    "SIGN_POSITIVE",
    "SheetLayout",
    "SheetLayoutError",
    "TotalsTabReader",
    "TotalsTabWriter",
    "WriteGuard",
    "WriteRefused",
    "column_to_index",
    "index_to_column",
    "marker_for",
    "marker_note",
    "parse_quantity",
    "replace",
]
