"""POC: does a published REGION need declared bounds, or can it derive them?

The question, from the region/Destination design: when a grid is published to a
rectangle inside a tab that also holds hand-maintained content, what clears the
cells the new grid no longer covers?

    Destination(tab, anchor, bounds)   -- bounds declared
    Destination(tab, anchor)           -- extent derived from the grid

PREDICTION (written before building):
    A derived-extent strategy CANNOT clear a shrinking region without either
    persistent state or an extra read per publish. A declared-bounds strategy
    can, statelessly -- it wipes a known rectangle regardless of history.

CONTROL ARM (predicted to FAIL):
    Strategy A writes the new grid and clears nothing. It MUST leave orphans in
    the shrink scenario. If it does not, the instrument cannot detect orphaning
    and no result here means anything.

This runs entirely against a fake worksheet. No live sheet, no quota, no creds.

Run:  python tests/one-offs/thinking/region-bounds/poc.py
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# A fake worksheet that records every call and holds real cell state, so an
# orphan is something we can SEE rather than something we reason about.
# ---------------------------------------------------------------------------


def a1(col: int, row: int) -> str:
    """0-indexed col -> A1. Enough for the column counts this POC uses."""
    letters = ""
    col += 1
    while col:
        col, rem = divmod(col - 1, 26)
        letters = string.ascii_uppercase[rem] + letters
    return f"{letters}{row + 1}"


@dataclass
class FakeWorksheet:
    cells: dict[tuple[int, int], str] = field(default_factory=dict)
    api_calls: list[str] = field(default_factory=list)

    def write_block(self, anchor_col, anchor_row, grid):
        self.api_calls.append(
            f"update {a1(anchor_col, anchor_row)}:"
            f"{a1(anchor_col + max((len(r) for r in grid), default=1) - 1, anchor_row + len(grid) - 1)}"
        )
        for dr, row in enumerate(grid):
            for dc, value in enumerate(row):
                self.cells[(anchor_col + dc, anchor_row + dr)] = value

    def clear_block(self, anchor_col, anchor_row, width, height):
        self.api_calls.append(
            f"clear {a1(anchor_col, anchor_row)}:"
            f"{a1(anchor_col + width - 1, anchor_row + height - 1)}"
        )
        for dr in range(height):
            for dc in range(width):
                self.cells.pop((anchor_col + dc, anchor_row + dr), None)

    def read_extent(self, anchor_col, anchor_row, max_probe=500):
        """A real read-back costs an API call and returns the used extent."""
        self.api_calls.append(f"read {a1(anchor_col, anchor_row)}:probe")
        rows = cols = 0
        for (c, r) in self.cells:
            if c >= anchor_col and r >= anchor_row:
                rows = max(rows, r - anchor_row + 1)
                cols = max(cols, c - anchor_col + 1)
        return cols, rows

    def region_snapshot(self, anchor_col, anchor_row, width, height):
        return {
            (c, r): v for (c, r), v in self.cells.items()
            if anchor_col <= c < anchor_col + width
            and anchor_row <= r < anchor_row + height
        }


# ---------------------------------------------------------------------------
# Three publishing strategies.
# ---------------------------------------------------------------------------

ANCHOR_COL, ANCHOR_ROW = 17, 0          # column R, row 1
RESERVED_W, RESERVED_H = 12, 250        # the declared region, for strategy C


def strategy_a_derived_no_clear(ws, grid, _state):
    """CONTROL. Write the grid, clear nothing. Predicted to orphan."""
    ws.write_block(ANCHOR_COL, ANCHOR_ROW, grid)


def strategy_b_derived_with_readback(ws, grid, _state):
    """Derive the extent, but read the sheet first to learn what to clear."""
    old_w, old_h = ws.read_extent(ANCHOR_COL, ANCHOR_ROW)
    if old_w and old_h:
        ws.clear_block(ANCHOR_COL, ANCHOR_ROW, old_w, old_h)
    if grid:
        ws.write_block(ANCHOR_COL, ANCHOR_ROW, grid)


def strategy_c_declared_bounds(ws, grid, _state):
    """Clear the DECLARED rectangle, then write. Stateless and self-correcting."""
    ws.clear_block(ANCHOR_COL, ANCHOR_ROW, RESERVED_W, RESERVED_H)
    if grid:
        ws.write_block(ANCHOR_COL, ANCHOR_ROW, grid)


def strategy_d_derived_with_state(ws, grid, state):
    """Derive, but remember last extent in process state. Fails across runs."""
    old = state.get("extent")
    if old:
        ws.clear_block(ANCHOR_COL, ANCHOR_ROW, old[0], old[1])
    if grid:
        ws.write_block(ANCHOR_COL, ANCHOR_ROW, grid)
        state["extent"] = (max(len(r) for r in grid), len(grid))
    else:
        state["extent"] = None


STRATEGIES = [
    ("A derived, no clear (CONTROL)", strategy_a_derived_no_clear),
    ("B derived + read-back", strategy_b_derived_with_readback),
    ("C declared bounds", strategy_c_declared_bounds),
    ("D derived + in-process state", strategy_d_derived_with_state),
]


def make_grid(rows, cols, tag):
    if rows == 0:
        return []
    return [[f"{tag}{r}.{c}" for c in range(cols)] for r in range(rows)]


# ---------------------------------------------------------------------------
# Scenarios. Each is a sequence of publishes; we then look for orphans --
# cells left behind by an EARLIER publish that the latest one does not cover.
# ---------------------------------------------------------------------------

SCENARIOS = [
    ("S1 shrink 197 -> 40 rows",
     [make_grid(197, 3, "old"), make_grid(40, 3, "new")]),
    ("S2 grow 40 -> 197 rows",
     [make_grid(40, 3, "old"), make_grid(197, 3, "new")]),
    ("S3 shrink to EMPTY (site completed)",
     [make_grid(197, 3, "old"), make_grid(0, 0, "new")]),
    ("S4 widen 3 -> 8 cols (the store lands)",
     [make_grid(50, 3, "old"), make_grid(50, 8, "new")]),
    ("S5 restart between publishes (fresh process)",
     [make_grid(197, 3, "old"), "RESTART", make_grid(40, 3, "new")]),
]


def orphans_in(ws, final_grid):
    """Cells inside the reserved region not written by the final publish."""
    live = ws.region_snapshot(ANCHOR_COL, ANCHOR_ROW, RESERVED_W, RESERVED_H)
    expected = set()
    for dr, row in enumerate(final_grid or []):
        for dc in range(len(row)):
            expected.add((ANCHOR_COL + dc, ANCHOR_ROW + dr))
    return {k: v for k, v in live.items() if k not in expected}


def run():
    rows = []
    for scenario, steps in SCENARIOS:
        for label, fn in STRATEGIES:
            ws = FakeWorksheet()
            state = {}
            final = []
            for step in steps:
                if step == "RESTART":
                    state = {}          # a new process: in-memory state is gone
                    continue
                fn(ws, step, state)
                final = step
            orph = orphans_in(ws, final)
            rows.append((scenario, label, len(orph), len(ws.api_calls)))

    # ---- report
    width = max(len(s) for s, _, _, _ in rows)
    print(f"{'scenario'.ljust(width)}  {'strategy'.ljust(30)}  orphans  api")
    print("-" * (width + 48))
    last = None
    for scenario, label, orph, calls in rows:
        shown = scenario if scenario != last else ""
        last = scenario
        flag = "  <-- ORPHANS" if orph else ""
        print(f"{shown.ljust(width)}  {label.ljust(30)}  {orph:7}  {calls:3}{flag}")

    # ---- verdicts
    print()
    by_strategy = {}
    for scenario, label, orph, calls in rows:
        d = by_strategy.setdefault(label, {"orphans": 0, "calls": 0})
        d["orphans"] += orph
        d["calls"] += calls

    control = by_strategy["A derived, no clear (CONTROL)"]
    if control["orphans"] == 0:
        print("*** CONTROL LEFT NO ORPHANS -- the instrument cannot detect")
        print("*** orphaning. Discarding every result above.")
        return 1
    print(f"[CONTROL-OK] A orphaned {control['orphans']} cells across all "
          f"scenarios, as predicted -- the instrument works.")
    print()
    for label, d in by_strategy.items():
        if label.startswith("A "):
            continue
        verdict = "CLEAN" if d["orphans"] == 0 else f"ORPHANS({d['orphans']})"
        print(f"  {label.ljust(30)} {verdict:14} total api calls: {d['calls']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
