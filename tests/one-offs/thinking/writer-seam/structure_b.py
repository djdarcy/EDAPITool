"""
STRUCTURE B -- the writer stays generic and takes a renderer.

`sheets.py` keeps A1/guard/reader/Plan AND a SheetWriter that knows how to
assemble a column, guard it and apply it -- but not what to put in the cells.
A renderer supplies that. `markers.py` provides the market renderer; a second
domain provides its own.

Same convention: lines of NON-PRESENTATION logic the second presenter is
forced to write are marked `# GENERIC`.
"""

from typing import Protocol

from common import Guard, Plan, Row, Snapshot


# ===========================================================================
# sheets.py -- generic. Knows nothing about glyphs or colours.
# ===========================================================================

class Renderer(Protocol):
    """What a presenter must supply. Two methods, no machinery."""

    def cell(self, row: Row) -> str: ...
    def cell_format(self, row: Row, value: str) -> dict | None: ...


class SheetWriter:
    """
    Assembles, guards and applies a single-column plan. Reusable by any
    presenter, in any domain, because it never decides what a cell says.
    """

    def __init__(self, worksheet, guard, tab, column, renderer: Renderer):
        self.worksheet, self.guard = worksheet, guard
        self.tab, self.column, self.renderer = tab, column, renderer

    def build_plan(self, snap: Snapshot) -> Plan:
        plan = Plan()
        by_row = {r.row: r for r in snap.rows}
        column = []
        for n in range(snap.first_data_row, snap.last_data_row + 1):
            row = by_row.get(n)
            value = self.renderer.cell(row) if row else ""
            column.append([value])
            if value:
                plan.marked_rows.append(n)
            fmt = self.renderer.cell_format(row, value) if row else None
            if fmt is not None:
                plan.formats.append({"range": f"{self.column}{n}", "format": fmt})
        rng = f"{self.column}{snap.first_data_row}:{self.column}{snap.last_data_row}"
        plan.updates.append({"range": rng, "values": column})
        for u in plan.updates:
            self.guard.check(self.tab, u["range"])
        for f in plan.formats:
            self.guard.check(self.tab, f["range"])
        return plan

    def apply(self, plan: Plan) -> int:
        for u in plan.updates:
            self.guard.check(self.tab, u["range"])
        payload = [{"range": u["range"], "values": u["values"]} for u in plan.updates]
        self.worksheet.batch_update(payload, value_input_option="USER_ENTERED")
        if plan.formats:
            self.worksheet.batch_format(
                [{"range": f["range"], "format": f["format"]} for f in plan.formats])
        return len(plan.updates)


# ===========================================================================
# markers.py -- the market presenter. Rendering only.
# ===========================================================================

MARKET_GLYPHS = {"enough": "●", "partial": "◑", "empty": "○"}
MARKET_FILLS = {"●": "#38761d", "◑": "#93c47d", "○": "#e8f2e4"}


class MarketRenderer:
    def cell(self, row: Row) -> str:
        if row.need <= 0 or row.price == 0:
            return ""
        if row.available == 0:
            return MARKET_GLYPHS["empty"]
        return MARKET_GLYPHS["enough"] if row.available >= row.need else MARKET_GLYPHS["partial"]

    def cell_format(self, row: Row, value: str) -> dict:
        return {"backgroundColor": MARKET_FILLS.get(value, "#ffffff")}


# ===========================================================================
# THE SECOND PRESENTER -- ship outfitting. Rendering only; no machinery.
# ===========================================================================

OUTFIT_GLYPHS = {"here": "✓", "absent": "✗"}


class OutfittingRenderer:
    """
    The same second domain as structure A: binary availability, different
    symbols, no colour ramp. Note what is absent -- no plan assembly, no
    guard calls, no batch apply.
    """

    def cell(self, row: Row) -> str:
        if row.need <= 0:
            return ""
        return OUTFIT_GLYPHS["here"] if row.available else OUTFIT_GLYPHS["absent"]

    def cell_format(self, row: Row, value: str) -> None:
        return None      # this sheet uses no colour at all
