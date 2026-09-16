"""
POC: pull the plug on the destination layer and see exactly what dies.

#18's third requirement is that isolation exists so that removing the
destination layer later is ONE MOVE, not an excavation. Nothing has ever
tested that. This does, without deleting anything: a `sys.meta_path` finder
refuses to import `APITool.workbook`, and then each surface is imported and
classified.

WHY A BLOCKER RATHER THAN DELETING THE DIRECTORY. Three reasons, and the
first is a safety rule: a probe must not be able to do the thing it asserts
is prevented. Renaming a package on disk during a test run leaves the tree
mutated if the run is hard-killed, and recovery then depends on the work
having been committed first. A meta_path hook is process-local and vanishes
when the interpreter exits. It is also more precise -- it fails exactly at
`import`, which is the edge under test -- and it is re-runnable in CI, which
a directory rename is not.

WHAT A CORRECT RESULT LOOKS LIKE. Not "everything still works". The two
destination-specific features SHOULD die, because a fork supplies its own:

  `--show-formula`  generates a formula for THESE glyphs and THESE
                    thresholds; a different sheet wants a different one
  `market --update-sheet` / the comparison
                    reads requirements from THIS workbook's Totals Tab

What must NOT die is anything a general-purpose exporter does: reading the
journal, reading the CAPI, writing CSV/JSON, publishing a generated data tab,
and the daemon that drives them.

Run:  python tests/one-offs/thinking/plugin-isolation/poc_pull_the_plug.py

SAFETY: imports and pure calls only. Nothing here constructs a daemon,
opens a socket, or touches a spreadsheet.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

BLOCKED = "APITool.workbook"


class PluginPulled:
    """Refuse to import the destination layer, as if it had been deleted."""

    def find_module(self, fullname, path=None):  # legacy API, harmless
        return None

    def find_spec(self, fullname, path=None, target=None):
        if fullname == BLOCKED or fullname.startswith(BLOCKED + "."):
            raise ModuleNotFoundError(
                f"No module named {fullname!r} "
                "(the destination layer has been pulled)"
            )
        return None


def _purge() -> None:
    for name in list(sys.modules):
        if name == "APITool" or name.startswith("APITool."):
            del sys.modules[name]


# Each row: (label, module to import, is it destination-specific?)
SURFACES = [
    # Core -- a general-purpose exporter. None of this is one workbook's.
    ("journal reader",          "APITool.journal",  False),
    ("market model",            "APITool.market",   False),
    ("ship loadout",            "APITool.ship",     False),
    ("commodity catalog",       "APITool.catalog",  False),
    ("CSV/JSON export",         "APITool.export",   False),
    ("CAPI client",             "APITool.capi",     False),
    # Toolkit -- generic spreadsheet mechanics, vendor-neutral.
    ("sheets toolkit",          "APITool.sheets",   False),
    ("google exporter",         "APITool.google",   False),
    # Orchestration -- drives the above. NOT destination-specific.
    ("refresh service",         "APITool.service",  False),
    ("daemon",                  "APITool.daemon",   False),
    ("CLI",                     "APITool.cli",      False),
    # Destination -- one workbook's conventions. SHOULD die.
    ("destination layer",       "APITool.workbook", True),
]


def main() -> None:
    print("=" * 78)
    print("BASELINE -- destination layer present")
    print("=" * 78)
    _purge()
    baseline = {}
    for label, mod, _ in SURFACES:
        try:
            importlib.import_module(mod)
            baseline[mod] = None
        except Exception as exc:  # noqa: BLE001 -- reporting, not handling
            baseline[mod] = f"{type(exc).__name__}: {exc}"
        state = "ok" if baseline[mod] is None else "FAILED"
        print(f"  {label:<22} {mod:<20} {state}")

    broken_at_baseline = [m for m, e in baseline.items() if e]
    if broken_at_baseline:
        print(f"\n  !! baseline is not clean: {broken_at_baseline}")
        print("     Everything below is uninterpretable. Stopping.")
        return

    print()
    print("=" * 78)
    print("PLUG PULLED -- `import APITool.workbook` raises")
    print("=" * 78)
    _purge()
    sys.meta_path.insert(0, PluginPulled())
    try:
        rows = []
        for label, mod, is_destination in SURFACES:
            try:
                importlib.import_module(mod)
                died = False
                detail = ""
            except Exception as exc:  # noqa: BLE001
                died = True
                detail = str(exc).split("(")[0].strip()
            rows.append((label, mod, is_destination, died, detail))
    finally:
        sys.meta_path.pop(0)
        _purge()

    print(f"  {'surface':<22} {'expected':<14} {'actual':<10} verdict")
    print("  " + "-" * 72)

    surgical = True
    for label, mod, is_destination, died, detail in rows:
        expected = "dies" if is_destination else "survives"
        actual = "dies" if died else "survives"
        if is_destination == died:
            verdict = "as designed"
        else:
            verdict = "*** COLLATERAL ***" if died else "*** LEAKED ***"
            surgical = False
        print(f"  {label:<22} {expected:<14} {actual:<10} {verdict}")

    print()
    collateral = [(lbl, d) for lbl, _, dest, died, d in rows
                  if died and not dest for _ in (0,)]
    if collateral:
        print("  Collateral damage -- these are NOT one workbook's code and")
        print("  should not have died with it:")
        for lbl, detail in collateral:
            print(f"    - {lbl:<20} {detail}")

    print()
    print("=" * 78)
    if surgical:
        print("RESULT: the plug pulls cleanly. Requirement 3 of #18 is MET.")
    else:
        print("RESULT: the plug does NOT pull cleanly. Requirement 3 is UNMET.")
        print()
        print("This is the property the isolation half exists to create, and")
        print("it is the assertion the permanent test should carry: not")
        print("'nothing imports the destination layer' -- cli.py legitimately")
        print("does -- but 'removing it breaks ONLY destination features'.")
    print("=" * 78)


if __name__ == "__main__":
    main()
