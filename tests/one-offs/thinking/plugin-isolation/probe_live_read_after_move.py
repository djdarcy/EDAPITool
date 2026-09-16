"""
Does the READ path still work against the real spreadsheet after the move?

Every one of the 590 automated tests uses a mock worksheet. The refactor that
moved `SheetLayout` into `APITool/plugins/settlement/` changed exactly the code
that builds a layout and resolves a reader -- so "the suite is green" says
nothing about whether the tool can still read the live sheet. This closes that
gap for the read half.

READ-ONLY BY CONSTRUCTION, which matters more than read-only by intention.
`TotalsTabReader.read()` issues a single `get_values` and nothing else; no
writer is constructed here, no `batch_update` is reachable from this file, and
the guard is never consulted because there is nothing to guard. Safety rule 1b
says a probe must not be ABLE to do the thing it is not supposed to do, and the
way to satisfy that is to never build the object that could.

Run:  python tests/one-offs/thinking/plugin-isolation/probe_live_read_after_move.py

Needs Google credentials and network. It reads one tab and prints what it
found; it changes nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from APITool.catalog import load_catalog
    from APITool.google import GoogleSheetsExporter
    from APITool.plugins.settlement.layout import SheetLayout
    from APITool.plugins.settlement.totals import TotalsTabReader
    from APITool.settings import get_sheet_id

    sheet_id = get_sheet_id(argparse.Namespace(sheet_id=None))
    if not sheet_id:
        print("No sheet id configured. Nothing to read.")
        return 1

    layout = SheetLayout()
    print("=" * 74)
    print("LIVE READ -- after the move to APITool/plugins/settlement/")
    print("=" * 74)
    print(f"  layout class : {type(layout).__module__}.{type(layout).__name__}")
    print(f"  tab          : {layout.totals_tab!r}")
    print(f"  need header  : {layout.need_header!r}")
    print(f"  header row   : {layout.header_row}, data from {layout.first_data_row}")
    print(f"  sheet        : {sheet_id}")
    print()

    exporter = GoogleSheetsExporter()
    worksheet = exporter.worksheet(sheet_id, layout.totals_tab)
    snapshot = TotalsTabReader(worksheet, layout, load_catalog()).read()

    outstanding = snapshot.outstanding
    print(f"  requirements read : {len(snapshot.requirements)}")
    print(f"  still outstanding : {len(outstanding)}")
    print(f"  last data row     : {snapshot.last_data_row}")
    print(f"  need column index : {snapshot.need_column_index}")
    print(f"  unparsed rows     : {len(snapshot.unparsed_rows)}")
    print()

    if outstanding:
        print("  A few of the outstanding rows, as the sheet has them:")
        for req in outstanding[:8]:
            resolved = "" if req.is_resolved else "   (name not in catalog)"
            print(f"    row {req.row:>4}  {req.name:<34} {req.need:>7,}{resolved}")
    else:
        print("  Nothing outstanding right now -- which is a legitimate answer,")
        print("  not a failure. The row count above is what proves the read.")

    print()
    print("=" * 74)
    if snapshot.requirements:
        print("RESULT: the read path works against the live sheet.")
    else:
        print("RESULT: read succeeded but returned NO rows -- inspect before")
        print("        trusting this. An empty read and a broken read look")
        print("        the same from here.")
    print("=" * 74)
    return 0 if snapshot.requirements else 2


if __name__ == "__main__":
    sys.exit(main())
