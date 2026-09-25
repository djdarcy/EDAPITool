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
from .a1 import CellRange, index_to_column
from .guard import WriteGuard
from .layout import LayoutLike, WorksheetLike
from .ledger import WriteLedger, as_text, classify
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
    # Cells left alone because something that is not the tool's was in them.
    # On the plan rather than discovered at apply time, so `--dry-run` can
    # report a skip before it happens -- which is the whole point of a dry
    # run. Kept equal to `held` so the callers that read it keep working.
    skipped: list[str] = field(default_factory=list)
    # The writes ledger's four answers (APITool.sheets.ledger), over every
    # cell the rule governs: glyph markers and, when asked, the location
    # cells. The header cell is outside it -- an opt-in label, written when
    # asked, as before.
    refreshed: list[str] = field(default_factory=list)   # ours, rewritten
    filled: list[str] = field(default_factory=list)      # empty, written
    held: list[str] = field(default_factory=list)        # someone else's, left
    forced: list[str] = field(default_factory=list)      # --force, written anyway

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
        ledger: Optional[WriteLedger] = None,
    ):
        self.worksheet = worksheet
        # The writes ledger, bound by core to this target (#25, slice 4). None
        # means no memory: nothing is ever the tool's own, so the rule is
        # v0.7.6's skip-if-occupied exactly. Never a reason to overwrite.
        self.ledger = ledger
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

        **Whose cell is it?** Every cell the plan would write -- each glyph
        marker, and the location cells when asked -- is sorted by the writes
        ledger's rule (``APITool.sheets.ledger.classify``): a cell still
        holding exactly what the tool last wrote there is the tool's own and
        is refreshed; an empty cell is filled; anything else is held, left
        alone and listed in ``plan.held`` (and ``plan.skipped``). ``force=True``
        writes them all. The clearing above was correct while the tool
        PAINTED this column and destructive once workbooks computed it
        themselves (#25); v0.7.6 answered by holding every occupied cell,
        which froze painted workbooks on the last station's glyphs. The ledger
        is what tells the two apart: what the tool wrote is recorded, as it
        read back, when the plan is applied.

        With no ledger (``ED_NO_STORE``, a store that will not open, a caller
        that passes none) nothing is ever the tool's own, and the rule is
        v0.7.6's exactly. The first run after upgrading is the same case:
        existing paint is held until one ``force`` adopts it.

        ``write_header`` defaults to False: the header cell above the markers
        belongs to the person who owns the sheet, and silently replacing
        whatever they put there is exactly the kind of unasked-for write this
        module is built to avoid. Opt in explicitly to have it labelled.

        ``write_location`` defaults to False for the same reason, and for the
        same reason as ``serve --write-location``: the system and station
        cells are better as formulas reading the generated MarketData tab, and
        a literal written over them looks right until MarketData moves on.
        When asked for, they obey the rule above like the markers: a formula
        there is held, the tool's own last literal is refreshed.

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

        # Every cell the rule governs, in plan order: the location cells when
        # asked, then the marker column. Read once, classified once.
        location = [layout.system_cell, layout.station_cell] if write_location else []
        column: list[list[str]] = []
        first, last = layout.first_data_row, snapshot.last_data_row
        marker_cells: list[str] = []

        if include_markers:
            by_row = {m.row: m for m in matches}
            for row_number in range(first, last + 1):
                match = by_row.get(row_number)
                value = (
                    self.renderer.cell(match, show_covered=show_covered) if match else ""
                )
                column.append([value])
                cell = f"{layout.marker_column}{row_number}"
                marker_cells.append(cell)
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

        planned = location + marker_cells
        held: set[str] = set()
        if planned:
            if force:
                current, readable = {}, True          # --force reads nothing
            else:
                current, readable = self._read_formulas(
                    location, layout.marker_range(last) if marker_cells else None,
                    first, len(marker_cells),
                )
            recorded = (
                self.ledger.recorded(layout.totals_tab, planned)
                if self.ledger is not None and not force else {}
            )
            verdict = classify(current, recorded, planned, force=force, readable=readable)
            plan.refreshed, plan.filled = verdict.refresh, verdict.fill
            plan.held, plan.forced = verdict.held, verdict.forced
            plan.skipped = list(verdict.held)
            held = set(verdict.held)

        values = {layout.system_cell: system, layout.station_cell: station}
        for cell in location:
            if cell not in held:
                plan.updates.append({"range": cell, "values": [[values[cell]]]})
        if write_header:
            plan.updates.append(
                {"range": layout.marker_header_cell(), "values": [[layout.marker_header]]}
            )

        if include_markers:
            if last >= first:
                occupied = {
                    first + offset for offset, cell in enumerate(marker_cells)
                    if cell in held
                }
                # Colour is a write too. Painting a cell we have just decided
                # not to touch would not destroy the formula in it, but it
                # would be an unasked-for edit to a cell that is not ours --
                # and the plan would report a skip while editing it anyway.
                if held:
                    plan.formats = [
                        f for f in plan.formats if f["range"] not in held
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

    def _read_formulas(
        self, cells: Sequence[str], marker_range: Optional[str],
        first_row: int, count: int,
    ) -> tuple[dict[str, object], bool]:
        """
        What every governed cell holds now, and whether the read worked.

        One call: the single cells and the marker range together, in one
        ``batch_get``. Read as FORMULAS, never as rendered values, and that
        distinction is the whole correctness of the rule. A marker formula can
        evaluate to the empty string -- the settlement workbook's do, whenever
        the commodity is not sold at the station currently docked at -- so a
        rendered read reports a live formula as an empty cell and the write
        destroys it. That is #25 exactly.

        A read that fails answers "unreadable", and every cell is held. If we
        cannot find out what is in the sheet, writing nothing is the safe
        answer, and the plan says so rather than swallowing it.

        This is a second read of the same tab, and deliberately so: the
        requirements read (``RequirementsReader.read``) takes rendered values,
        which is right for quantities and useless here.
        """
        ranges = list(cells) + ([marker_range] if marker_range else [])
        try:
            answers = self.worksheet.batch_get(ranges, value_render_option="FORMULA")
        except Exception:  # noqa: BLE001 -- unreadable means hands off
            return {}, False
        current: dict[str, object] = {}
        for cell, rows in zip(cells, answers):
            current[cell] = rows[0][0] if rows and rows[0] else ""
        if marker_range:
            rows = answers[len(cells)] if len(answers) > len(cells) else []
            column = self.layout.marker_column
            # Bounded by the block we are about to write, not by what came
            # back: a worksheet is free to return more rows than were asked for.
            for offset, row in enumerate(list(rows)[:count]):
                current[f"{column}{first_row + offset}"] = row[0] if row else ""
        return current, True

    def _read_back(self, ranges: Sequence[str]) -> Optional[dict[str, str]]:
        """What the ranges just written hold now, per cell, as formulas; None if unreadable."""
        try:
            answers = self.worksheet.batch_get(list(ranges), value_render_option="FORMULA")
        except Exception:  # noqa: BLE001 -- an unread cell is simply not recorded
            return None
        out: dict[str, str] = {}
        for range_name, rows in zip(ranges, answers):
            span = CellRange.parse(range_name)
            column = index_to_column(span.first_col)
            last_row = span.last_row if span.last_row is not None else span.first_row
            rows = list(rows)
            for offset, row_number in enumerate(range(span.first_row, last_row + 1)):
                row = rows[offset] if offset < len(rows) else []
                out[f"{column}{row_number}"] = as_text(row[0] if row else "")
        return out

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
        self._record(plan)
        return len(plan.updates)

    def _record(self, plan: MarkerPlan) -> None:
        """
        Remember what the governed cells hold now that they are written.

        What READS BACK, never what was sent: Sheets reinterprets entered text
        (``USER_ENTERED``), and a ledger of what was sent would call the tool's
        own cells foreign the first time it did. One ``batch_get`` over the
        ranges just written; only the governed cells are recorded.
        A read-back that fails records nothing, so those cells stay "not the
        tool's" -- held next time, the safe direction.
        """
        if self.ledger is None:
            return
        governed = set(plan.refreshed) | set(plan.filled) | set(plan.forced)
        # Everything written is read back in the one call; only the governed
        # cells are recorded, which is what keeps the header cell (outside
        # the rule) out of the ledger.
        ranges = [u["range"] for u in plan.updates]
        if not governed or not ranges:
            return
        now = self._read_back(ranges)
        if now is None:
            return
        self.ledger.record(
            self.layout.totals_tab,
            {cell: value for cell, value in now.items() if cell in governed},
        )
