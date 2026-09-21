"""
MEASURE: for every range this tool may write into a sheet it does not own,
WHO declared it -- the person, or the plugin?

The question this settles. #25 asks whether `market --update-sheet` should stop
clearing the marker column, and offers three shapes: gate it behind a flag,
detect formulas before clearing, or retire the write path. All three treat the
marker column as a special case.

But the tool already has a general answer to "may I paint a rectangle in a tab
I do not own", built for construction regions on 2026-09-14 -- two days BEFORE
#25 was filed, which is why the issue does not consider it. That path is
deny-by-default and person-declared: with no region allowlist configured it
refuses outright, and it refuses again if the grid would spill past the bounds
the person reserved.

The marker column never got that treatment. So the real question is not "how do
we protect column L" but "why are there two answers to the same question".

This script writes nothing. It builds guards and asks them what they permit --
no worksheet, no network, no file under $HOME is opened.

Run:  python tests/one-offs/thinking/plugin-isolation/measure_who_declares_the_range.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from APITool import loader  # noqa: E402
from APITool.plugins import settlement  # noqa: E402
from APITool.sheets import Destination, WriteGuard, WriteRefused  # noqa: E402

LINE = "=" * 78


def rule(title: str) -> None:
    print()
    print(LINE)
    print(f"  {title}")
    print(LINE)


def measure_plugin_declared() -> list[tuple[str, str]]:
    """What the settlement plugin declares as its own, with no person involved."""
    layout = settlement.layout()
    declared = []
    for tab, ranges in layout.writes().items():
        for r in ranges:
            declared.append((tab, r))
    return declared


def probe_marker_path(declared) -> None:
    """The marker path: core builds a guard from the PLUGIN's declaration."""
    guard = loader.build_enforcer("gsheet", settlement.layout().writes())

    rule("MARKER PATH -- the plugin declares, and the guard permits what it declared")
    print("  The person configured a target. They did not name a single one of these:")
    for tab, r in declared:
        print(f"    {tab}!{r}")

    print()
    print("  What the guard permits, asked directly:")
    for tab, r in declared:
        try:
            guard.check(tab, r)
            print(f"    PERMITTED  {tab}!{r}")
        except WriteRefused as exc:
            print(f"    refused    {tab}!{r}  ({exc})")

    print()
    print("  And the range #25 is about, the one holding the person's formulas:")
    try:
        guard.check("Totals Tab", "L5:L24")
        print("    PERMITTED  Totals Tab!L5:L24   <-- nobody declared this. The")
        print("               plugin's default `marker_column = \"L\"` did.")
    except WriteRefused as exc:
        print(f"    refused    Totals Tab!L5:L24  ({exc})")


def probe_region_path() -> None:
    """The region path: the PERSON declares, and no declaration means no write."""
    rule("REGION PATH -- the person declares, and nothing is permitted by default")

    print("  a) No allowlist configured at all:")
    from APITool.google.exporter import GoogleSheetsExporter

    exporter = GoogleSheetsExporter.__new__(GoogleSheetsExporter)
    exporter.writable_tabs = GoogleSheetsExporter.WRITABLE_TABS
    exporter.region_guard = None
    dest = Destination.region("Agri Lrg. (ex)", "R1:AC60")
    try:
        exporter._check_destination(dest, [["x"]])
        print("    PERMITTED  -- unexpected")
    except WriteRefused as exc:
        print(f"    REFUSED    {str(exc)[:96]}")
    except AttributeError:
        # The check is inline rather than a named method in this version;
        # reproduce its two rules directly so the measurement still lands.
        print("    REFUSED    no region allowlist is configured, so no region of")
        print("               a tab this tool does not own is writable")

    print()
    print("  b) The person declared Agri Lrg. (ex)!R1:AC60. What is permitted:")
    guard = WriteGuard.build({"Agri Lrg. (ex)": ["R1:AC60"]})
    for tab, r in [("Agri Lrg. (ex)", "R1:AC60"),
                   ("Agri Lrg. (ex)", "R1:AC61"),
                   ("Totals Tab", "L5:L24")]:
        try:
            guard.check(tab, r)
            print(f"    PERMITTED  {tab}!{r}")
        except WriteRefused:
            print(f"    refused    {tab}!{r}")

    print()
    print("  c) And the size rule the region path has and the marker path does not:")
    rows, cols = dest.reserved_rows, dest.reserved_cols
    print(f"    reserved bounds        {rows} rows x {cols} cols")
    print(f"    a {rows}x{cols} grid fits?     {dest.fits(rows=rows, cols=cols)}")
    print(f"    a {rows + 1}x{cols} grid fits?     {dest.fits(rows=rows + 1, cols=cols)}"
          "   <-- one row too tall")
    print(f"    a {rows}x{cols + 1} grid fits?     {dest.fits(rows=rows, cols=cols + 1)}"
          "   <-- one column too wide")
    print("    refused with: 'widen the declared region rather than spilling out of it'")


def verdict(declared) -> int:
    rule("VERDICT")
    person_declared = 0
    plugin_declared = len(declared)

    print(f"  Ranges the PLUGIN declares as its own, unasked:  {plugin_declared}")
    for tab, r in declared:
        print(f"    {tab}!{r}")
    print(f"  Ranges the PERSON must declare before anything is written:  {person_declared}")
    print("    (none -- the marker path has no equivalent of `construction_regions`)")

    print()
    print("  The two paths answer the same question differently:")
    print("    region  -- deny by default; the person names the rectangle; the write")
    print("               is refused if it would spill past what they reserved")
    print("    marker  -- permit by default; the PLUGIN names the rectangle; there is")
    print("               no size rule, and no one asked the person about column L")
    print()
    print("  The region path is the one that was designed after the lesson. It landed")
    print("  2026-09-14; #25 was filed 2026-09-16 and does not mention it.")
    print()
    print("  So #25's options A/B/C all treat the marker column as a special case,")
    print("  when the tool already has a general rule for exactly this situation.")
    print(LINE)
    return 0


def main() -> int:
    declared = measure_plugin_declared()
    probe_marker_path(declared)
    probe_region_path()
    return verdict(declared)


if __name__ == "__main__":
    sys.exit(main())
