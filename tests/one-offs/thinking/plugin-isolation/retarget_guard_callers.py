"""
Retarget every test that built its own guard through the plugin.

Slice A, unit 2: `SheetLayout.guard()` became `SheetLayout.writes()` -- a
DECLARATION -- and `TotalsTabWriter` now requires a guard it did not build.
Seventeen test sites in two files constructed a writer without one, or asked
the layout for one. This is the bulk edit that moves them to the shape core
uses: `WriteGuard.build(layout.writes())`.

A script rather than seventeen hand edits because they are one replacement
repeated (the house rule's sed-class case), and because it REFUSES to finish
if any `TotalsTabWriter(` site is left without a guard -- so a site the
patterns missed is a printed line, not a silent failure at test time.

Run once:  python tests/one-offs/thinking/plugin-isolation/retarget_guard_callers.py
Idempotent: a second run changes nothing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SHEETS = ROOT / "tests" / "test_sheets.py"
SERVICE = ROOT / "tests" / "test_service.py"


def edit(path: Path, replacements: list[tuple[str, str]], regex: list[tuple[str, str]]) -> list[str]:
    # Bytes, not read_text: universal-newline mode would hand back LF for a
    # CRLF file and the write below would silently re-end every line. The
    # first run of this script did exactly that to two files.
    text = path.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    changed: list[str] = []
    for old, new in replacements:
        old, new = old.replace("\n", nl), new.replace("\n", nl)
        if old in text:
            text = text.replace(old, new)
            changed.append(f"  {path.name}: {old.strip()[:60]!r} -> {new.strip()[:60]!r}")
    for pattern, repl in regex:
        text, n = re.subn(pattern, repl, text)
        if n:
            changed.append(f"  {path.name}: {n} x /{pattern[:50]}/")
    path.write_text(text, encoding="utf-8", newline="")
    return changed


def main() -> int:
    changed: list[str] = []

    # --- tests/test_sheets.py ----------------------------------------------
    changed += edit(
        SHEETS,
        replacements=[
            # one core-built guard for the default layout, defined once
            ("from APITool.plugins.settlement.layout import SheetLayout\n",
             "from APITool.plugins.settlement.layout import SheetLayout\n\n"
             "# The guard core builds from the plugin's declaration. Tests are the\n"
             "# caller here, and the caller is the only place a guard may come from.\n"
             "DEFAULT_GUARD = WriteGuard.build(SheetLayout().writes())\n"),
            ("@pytest.fixture\ndef guard():\n    return SheetLayout().guard()\n",
             "@pytest.fixture\ndef guard():\n    return DEFAULT_GUARD\n"),
            ("    guard = layout.guard()\n",
             "    guard = WriteGuard.build(layout.writes())\n"),
            ("guard=SheetLayout().guard()", "guard=DEFAULT_GUARD"),
            ("    guard = SheetLayout().guard()\n",
             "    guard = DEFAULT_GUARD\n"),
            # the one site with a custom layout and no guard
            ("TotalsTabWriter(FakeWorksheet(grid), MarketRenderer(layout.markers), layout=layout)",
             "TotalsTabWriter(FakeWorksheet(grid), MarketRenderer(layout.markers), layout=layout,\n"
             "                           guard=WriteGuard.build(layout.writes()))"),
        ],
        regex=[
            # every `TotalsTabWriter(<ws>, <Renderer>())` with no guard on the line
            (r"(TotalsTabWriter\((?:[^()\n]|\([^()\n]*(?:\([^()\n]*\))?[^()\n]*\))*?Renderer\(\))\)(?![^\n]*guard=)",
             r"\1, guard=DEFAULT_GUARD)"),
        ],
    )

    # --- tests/test_service.py ---------------------------------------------
    changed += edit(
        SERVICE,
        replacements=[
            ("from APITool.sheets import WriteRefused\n",
             "from APITool.sheets import WriteGuard, WriteRefused\n"),
            ("SheetLayout().guard()", "WriteGuard.build(SheetLayout().writes())"),
        ],
        regex=[],
    )

    print("changed:")
    print("\n".join(changed) or "  nothing")

    # --- refuse to finish with a writer built without a guard ----------------
    left = []
    for path in (SHEETS, SERVICE):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "TotalsTabWriter(" in line and "guard=" not in line:
                window = " ".join(lines[i:i + 3])
                if "guard=" not in window:
                    left.append(f"  {path.name}:{i + 1}: {line.strip()}")
        if ".guard()" in path.read_text(encoding="utf-8"):
            left.append(f"  {path.name}: still calls .guard()")
    if left:
        print("\nUNHANDLED -- fix by hand:")
        print("\n".join(left))
        return 1
    print("\nevery TotalsTabWriter( site carries a guard; no .guard() calls remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
