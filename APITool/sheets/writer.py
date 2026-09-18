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

    def ranges(self) -> list[str]:
        return [u["range"] for u in self.updates]

    def format_ranges(self) -> list[str]:
        return [f["range"] for f in self.formats]


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

        ``include_markers=False`` builds a location-only plan: the system and
        station cells, and nothing touching the marker column. This is what a
        sheet that renders its own markers from a generated tab needs -- the
        marker column there holds the reader's formulas, and a wholesale
        rewrite would replace them with values.

        Note this is a property of the PLAN, not of whether it is applied.
        Suppressing the write instead would leave location stale too, since
        all of it travels in one batch.
        """
        layout = self.layout
        plan = MarkerPlan()

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
