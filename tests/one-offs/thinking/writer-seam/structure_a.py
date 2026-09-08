"""
STRUCTURE A -- the writer moves wholesale into the presentation module.

`sheets.py` keeps A1/guard/reader/Plan. `markers.py` owns the glyphs AND the
writer that assembles and applies the plan. A second presenter for a different
domain therefore has to bring its own writer.

Lines of NON-PRESENTATION logic the second presenter is forced to write are
marked `# GENERIC` -- those are the ones that would not exist if the writer
had stayed generic.
"""

from common import Guard, Plan, Row, Snapshot


# ===========================================================================
# markers.py -- the existing market presenter, writer included
# ===========================================================================

MARKET_GLYPHS = {"enough": "●", "partial": "◑", "empty": "○"}
MARKET_FILLS = {"●": "#38761d", "◑": "#93c47d", "○": "#e8f2e4"}


class MarketMarkerWriter:
    """The market presenter. Owns rendering AND the write machinery."""

    def __init__(self, worksheet, guard, tab="Totals Tab", column="L"):
        self.worksheet, self.guard, self.tab, self.column = worksheet, guard, tab, column

    def _glyph(self, row: Row) -> str:
        if row.need <= 0 or row.price == 0:
            return ""
        if row.available == 0:
            return MARKET_GLYPHS["empty"]
        return MARKET_GLYPHS["enough"] if row.available >= row.need else MARKET_GLYPHS["partial"]

    def _fmt(self, glyph: str) -> dict:
        return {"backgroundColor": MARKET_FILLS.get(glyph, "#ffffff")}

    def build_plan(self, snap: Snapshot) -> Plan:
        plan = Plan()                                                    # GENERIC
        by_row = {r.row: r for r in snap.rows}                           # GENERIC
        column = []                                                      # GENERIC
        for n in range(snap.first_data_row, snap.last_data_row + 1):     # GENERIC
            row = by_row.get(n)                                          # GENERIC
            glyph = self._glyph(row) if row else ""
            column.append([glyph])                                       # GENERIC
            if glyph:                                                    # GENERIC
                plan.marked_rows.append(n)                               # GENERIC
            plan.formats.append({"range": f"{self.column}{n}",           # GENERIC
                                 "format": self._fmt(glyph)})            # GENERIC
        rng = f"{self.column}{snap.first_data_row}:{self.column}{snap.last_data_row}"  # GENERIC
        plan.updates.append({"range": rng, "values": column})            # GENERIC
        for u in plan.updates:                                           # GENERIC
            self.guard.check(self.tab, u["range"])                       # GENERIC
        for f in plan.formats:                                           # GENERIC
            self.guard.check(self.tab, f["range"])                       # GENERIC
        return plan                                                      # GENERIC

    def apply(self, plan: Plan) -> int:
        for u in plan.updates:                                           # GENERIC
            self.guard.check(self.tab, u["range"])                       # GENERIC
        payload = [{"range": u["range"], "values": u["values"]}          # GENERIC
                   for u in plan.updates]                                # GENERIC
        self.worksheet.batch_update(payload, value_input_option="USER_ENTERED")  # GENERIC
        if plan.formats:                                                 # GENERIC
            self.worksheet.batch_format(                                 # GENERIC
                [{"range": f["range"], "format": f["format"]} for f in plan.formats])  # GENERIC
        return len(plan.updates)                                         # GENERIC


# ===========================================================================
# THE SECOND PRESENTER -- ship outfitting. Must bring its own writer.
# ===========================================================================

OUTFIT_GLYPHS = {"here": "✓", "absent": "✗"}


class OutfittingWriter:
    """
    A different domain: binary availability, different symbols, no colour ramp,
    different tab and column. Everything marked GENERIC below is machinery
    copied from MarketMarkerWriter because there was nowhere else to get it.
    """

    def __init__(self, worksheet, guard, tab="ShipBuild", column="F"):
        self.worksheet, self.guard, self.tab, self.column = worksheet, guard, tab, column

    def _glyph(self, row: Row) -> str:
        if row.need <= 0:
            return ""
        return OUTFIT_GLYPHS["here"] if row.available else OUTFIT_GLYPHS["absent"]

    def build_plan(self, snap: Snapshot) -> Plan:
        plan = Plan()                                                    # GENERIC
        by_row = {r.row: r for r in snap.rows}                           # GENERIC
        column = []                                                      # GENERIC
        for n in range(snap.first_data_row, snap.last_data_row + 1):     # GENERIC
            row = by_row.get(n)                                          # GENERIC
            glyph = self._glyph(row) if row else ""
            column.append([glyph])                                       # GENERIC
            if glyph:                                                    # GENERIC
                plan.marked_rows.append(n)                               # GENERIC
        rng = f"{self.column}{snap.first_data_row}:{self.column}{snap.last_data_row}"  # GENERIC
        plan.updates.append({"range": rng, "values": column})            # GENERIC
        for u in plan.updates:                                           # GENERIC
            self.guard.check(self.tab, u["range"])                       # GENERIC
        return plan                                                      # GENERIC

    def apply(self, plan: Plan) -> int:
        for u in plan.updates:                                           # GENERIC
            self.guard.check(self.tab, u["range"])                       # GENERIC
        payload = [{"range": u["range"], "values": u["values"]}          # GENERIC
                   for u in plan.updates]                                # GENERIC
        self.worksheet.batch_update(payload, value_input_option="USER_ENTERED")  # GENERIC
        if plan.formats:                                                 # GENERIC
            self.worksheet.batch_format(                                 # GENERIC
                [{"range": f["range"], "format": f["format"]} for f in plan.formats])  # GENERIC
        return len(plan.updates)                                         # GENERIC
