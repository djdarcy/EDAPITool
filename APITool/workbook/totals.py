"""
This workbook's Totals Tab: reading its requirements, writing its markers.

DEMOTED. Everything here encodes one particular spreadsheet's conventions --
a Totals Tab, a marker column, a "Left to buy" header. The tool's supported
path is to publish a generated data tab and let the sheet's own formulas
decide what it means; this module is how sheet writes get tested, and how the
workbook was driven before both computed columns became formulas.

It is kept, not deleted, and it is kept here rather than beside the generic
mechanics so that its status is visible in an import line. See the retirement
ledger in private/claude/ for the condition that would remove it.

Everything this module builds on lives in ``APITool.sheets`` and is generic;
the dependency points one way and a layering test enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

from ..catalog import CommodityCatalog
from ..matcher import Match, Requirement, build_requirements
from ..sheets.a1 import CellRange, index_to_column
from ..sheets.guard import WriteGuard, WriteRefused
from ..sheets.layout import (
    SIGN_NEGATIVE,
    SIGN_POSITIVE,
    SheetLayout,
    SheetLayoutError,
    WorksheetLike,
    parse_quantity,
)

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


class TotalsTabWriter:
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
        layout: Optional[SheetLayout] = None,
        guard: Optional[WriteGuard] = None,
    ):
        self.worksheet = worksheet
        # Required, and deliberately not defaulted to this workbook's renderer.
        # A default would mean importing `markers` here -- even lazily, inside a
        # method -- and that is exactly the dependency this split exists to
        # remove. Callers name their presenter; the module stays domain-neutral.
        self.renderer = renderer
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

