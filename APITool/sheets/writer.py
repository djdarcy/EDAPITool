"""
Assembling, guarding and applying a single-column write plan.

Generic spreadsheet mechanics. What a cell SAYS is a renderer's business
(:class:`CellRenderer`); where the column is and which tab it is on are the
layout's; whether a range may be written at all is the guard's -- and the
guard is built by core from the layout's declaration, never here. What
remains is identical for every sheet: build the block, check every range,
batch the calls.

Moved here from the settlement plugin, where it had been filed as that
workbook's writer. A second plugin would have rewritten it -- and rewritten
the guard checks with it, which is the copy this project already paid for
once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

from ..matcher import Match
from .guard import WriteGuard
from .layout import LayoutLike, WorksheetLike
from .reader import RequirementSnapshot


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
    # Marker cells left alone because something was already in them. On the
    # plan rather than discovered at apply time, so `--dry-run` can report a
    # skip before it happens -- which is the whole point of a dry run.
    skipped: list[str] = field(default_factory=list)

    def ranges(self) -> list[str]:
        return [u["range"] for u in self.updates]

    def format_ranges(self) -> list[str]:
        return [f["range"] for f in self.formats]


def _free_runs(
    column: Sequence[Sequence[str]], first_row: int, occupied: set[int]
) -> list[tuple[int, list]]:
    """
    Split a column block into the contiguous runs nobody is sitting in.

    One range per run rather than one per cell, so the ordinary case -- a
    column with nothing in the way -- still travels as a single write and
    costs a single range. A column with one occupied cell in the middle costs
    two; that is the price of not overwriting it.
    """
    runs: list[tuple[int, list]] = []
    start: Optional[int] = None
    values: list = []
    for offset, cell in enumerate(column):
        row = first_row + offset
        if row in occupied:
            if start is not None:
                runs.append((start, values))
                start, values = None, []
            continue
        if start is None:
            start, values = row, []
        values.append(cell)
    if start is not None:
        runs.append((start, values))
    return runs


class CellRenderer(Protocol):
    """
    What a presenter supplies: what a cell says, how it looks, what it notes.

    Three methods and no machinery. Everything else -- assembling the block,
    checking it against the write guard, batching the API calls -- belongs to
    the writer and is identical for every sheet.

    That division was measured rather than assumed. A proof-of-concept built a
    second presenter for a different domain (ship outfitting: binary
    availability, different symbols, no colour) against both structures. With
    the writer inside the presentation module it had to reimplement 22 lines of
    machinery, about six of them ``guard.check`` calls; with the writer generic
    it wrote 10 lines and none. The guard duplication is what decided it -- this
    project has already shipped one guard that turned out to be decorative, and
    a safety check copied per presenter is that failure waiting to recur.

    See the design record for the full reasoning and the rejected alternatives.
    """

    def cell(self, match: Match, show_covered: bool = True) -> str:
        """What this row's cell says. Empty string for no mark."""
        ...

    def cell_format(self, match: Optional[Match], value: str) -> Optional[dict]:
        """The cell's format, or None to leave formatting alone."""
        ...

    def cell_note(self, match: Match, checked_at: str = "") -> str:
        """The hover note, or empty for none."""
        ...


class MarkerWriter:
    """
    Assembles, guards and applies a single-column plan.

    Knows nothing about what a cell says -- a :class:`CellRenderer` decides
    that. Every range passes through :class:`WriteGuard` before it is sent, so
    a misconfigured layout fails with an exception instead of overwriting
    formulas, and that check lives here exactly once rather than in every
    presenter.
    """

    def __init__(
        self,
        worksheet: WorksheetLike,
        renderer: CellRenderer,
        layout: LayoutLike,
        *,
        guard: WriteGuard,
    ):
        self.worksheet = worksheet
        # Required, and deliberately not defaulted to any workbook's renderer.
        # A default would mean importing a presenter here -- even lazily,
        # inside a method -- and that is exactly the dependency this split
        # exists to remove. Callers name their presenter; the module stays
        # domain-neutral.
        self.renderer = renderer
        # Required too: the toolkit has no sheet of its own to default to.
        self.layout = layout
        # Required too, and keyword-only so it cannot be mistaken for the
        # layout. This writer never builds its own guard: it used to fall back
        # to `layout.guard()`, which made the plugin its own safety boundary,
        # and a plugin that builds its own guard can build a permissive one.
        # Core builds the enforcer from `layout.writes()` and hands it in.
        self.guard = guard

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
        include_markers: bool = True,
        force: bool = False,
        write_location: bool = False,
    ) -> MarkerPlan:
        """
        Build the full write plan from ONE requirement snapshot.

        The marker column is computed from the first data row to the
        snapshot's last data row, so a row that no longer has a marker is
        blanked rather than left showing the previous station's answer. That
        clearing is what keeps a stale glyph from surviving a row shift.

        **A cell that already holds anything is skipped**, and lands in
        ``plan.skipped`` instead of ``plan.updates``. The clearing above was
        correct while the tool PAINTED this column; it became destructive when
        workbooks started computing the column themselves, which is #25.
        ``force=True`` writes the block regardless, and is the only way to get
        the old behaviour back.

        The trade this makes, stated rather than hidden: on a workbook that
        really is painted by the tool, every glyph it painted makes that cell
        occupied, so a later run leaves the old glyph in place -- in every
        row that held one, whether or not there is a new answer for it --
        until ``force``. Only cells that were blank get filled. The tool
        cannot tell its own leftover from something a person typed; telling
        them apart needs a memory of what the tool wrote (#29), and until
        there is one, keeping a person's formulas is worth more than
        refreshing the tool's own glyphs.

        ``write_header`` defaults to False: the header cell above the markers
        belongs to the person who owns the sheet, and silently replacing
        whatever they put there is exactly the kind of unasked-for write this
        module is built to avoid. Opt in explicitly to have it labelled.

        ``write_location`` defaults to False for the same reason, and for the
        same reason as ``serve --write-location``: the system and station
        cells are better as formulas reading the generated MarketData tab, and
        a literal written over them looks right until MarketData moves on.
        The skip above does not cover them -- a stale literal the skip left in
        place would never refresh -- so they are opt-in instead.

        ``include_markers=False`` builds a location-only plan: the system and
        station cells (when ``write_location`` asks for them), and nothing
        touching the marker column. This is what a sheet that renders its
        own markers from a generated tab needs -- the
        marker column there holds the reader's formulas, and a wholesale
        rewrite would replace them with values.

        Note this is a property of the PLAN, not of whether it is applied.
        Suppressing the write instead would leave location stale too, since
        all of it travels in one batch.
        """
        layout = self.layout
        plan = MarkerPlan()

        if write_location:
            plan.updates.append({"range": layout.system_cell, "values": [[system]]})
            plan.updates.append({"range": layout.station_cell, "values": [[station]]})
        if write_header:
            plan.updates.append(
                {"range": layout.marker_header_cell(), "values": [[layout.marker_header]]}
            )

        if include_markers:
            by_row = {m.row: m for m in matches}
            first, last = layout.first_data_row, snapshot.last_data_row
            column: list[list[str]] = []
            for row_number in range(first, last + 1):
                match = by_row.get(row_number)
                value = (
                    self.renderer.cell(match, show_covered=show_covered) if match else ""
                )
                column.append([value])
                cell = f"{layout.marker_column}{row_number}"
                if value:
                    covered = match is not None and match.is_covered
                    (plan.covered_rows if covered else plan.marked_rows).append(
                        row_number
                    )
                    note = self.renderer.cell_note(match, checked_at)
                    if note:
                        plan.notes[cell] = note
                if apply_colour:
                    fmt = self.renderer.cell_format(match, value)
                    if fmt is not None:
                        plan.formats.append({"range": cell, "format": fmt})

            if last >= first:
                occupied = (
                    set() if force
                    else self._occupied_rows(
                        layout.marker_range(last), first, len(column)
                    )
                )
                plan.skipped.extend(
                    f"{layout.marker_column}{row}" for row in sorted(occupied)
                )
                # Colour is a write too. Painting a cell we have just decided
                # not to touch would not destroy the formula in it, but it
                # would be an unasked-for edit to a cell that is not ours --
                # and the plan would report a skip while editing it anyway.
                if plan.skipped:
                    left_alone = set(plan.skipped)
                    plan.formats = [
                        f for f in plan.formats if f["range"] not in left_alone
                    ]
                for start, run in _free_runs(column, first, occupied):
                    end = start + len(run) - 1
                    span = (
                        f"{layout.marker_column}{start}"
                        if start == end
                        else f"{layout.marker_column}{start}:"
                             f"{layout.marker_column}{end}"
                    )
                    plan.updates.append({"range": span, "values": run})

        for update in plan.updates:
            self.guard.check(layout.totals_tab, update["range"])
        # Formatting is a write like any other and goes through the same gate.
        for entry in plan.formats:
            self.guard.check(layout.totals_tab, entry["range"])
        return plan

    def _occupied_rows(self, range_name: str, first_row: int, count: int) -> set[int]:
        """
        Which rows of the marker range already hold something.

        Read as FORMULAS, never as rendered values, and that distinction is
        the whole correctness of this check. A marker formula can evaluate to
        the empty string -- the settlement workbook's do, whenever the
        commodity is not sold at the station currently docked at -- so a
        rendered read reports a live formula as an empty cell and the write
        destroys it. That is #25 exactly. Asking for the formula text sees the
        cell as it really is.

        A read that fails is treated as "occupied everywhere". If we cannot
        find out what is in the column, writing nothing is the safe answer,
        and the plan says so: every row lands in ``skipped``, which the CLI
        reports rather than swallowing.

        This is a second read of the same tab, and deliberately so: the
        requirements read (``RequirementsReader.read``) takes rendered values,
        which is right for quantities and useless here.
        """
        try:
            rows = self.worksheet.get_values(
                range_name, value_render_option="FORMULA"
            )
        except Exception:  # noqa: BLE001 -- unreadable means hands off
            return set(range(first_row, first_row + count))
        occupied = set()
        # Bounded by the block we are about to write, not by what came back:
        # a worksheet is free to return more rows than were asked for.
        for offset, row in enumerate(rows[:count]):
            value = row[0] if row else ""
            if str(value).strip():
                occupied.add(first_row + offset)
        return occupied

    def apply(self, plan: MarkerPlan) -> int:
        """Send the plan in one batch. Returns the number of ranges written."""
        for update in plan.updates:
            self.guard.check(self.layout.totals_tab, update["range"])
        if not plan.updates:
            return 0
        # gspread rewrites each dict's "range" in place, prefixing the sheet
        # title ("L3" -> "'<tab>'!L3"). Handing it our own dicts would
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
