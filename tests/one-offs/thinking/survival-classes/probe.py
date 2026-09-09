"""
Does "which deletions does this module survive?" produce a hierarchy or a lattice?

Arc A wants to move APITool's modules into three destinations: Google-specific,
generic spreadsheet mechanics, and this workbook's demoted presentation. That
shape is only correct if survival sets NEST -- if every module that survives
losing a spreadsheet backend also survives losing the presenter, and so on.

If instead module A survives losing `markers` but not `gsheet`, while module B
survives losing `gsheet` but not `markers`, the structure is a lattice and
"three destinations" is the wrong shape. This probe settles which.

Mechanism borrowed from ../presenter-removable/probe.py: a sys.meta_path finder
that raises ImportError for one named module, then an import attempt in a fresh
subprocess. That file's docstring records why it uses find_spec -- an earlier
version used find_module, which Python 3.12 ignores, so it passed vacuously.

CONTROL ARMS (predicted to FAIL -- if either passes, the blocker is not working
and every cell below is meaningless):
  * block `matcher`, import `markers`  -- markers imports matcher at module
    scope, so it must die
  * block `markers`, import `markers`  -- must die trivially

Run: python tests/one-offs/thinking/survival-classes/probe.py
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

MODULES = [
    "auth", "capi", "cargo", "catalog", "cli", "config", "export",
    "google", "journal", "market", "matcher", "models", "service",
    "sheets", "ship", "version", "workbook.markers", "workbook.totals",
]

# What we remove, one at a time.
BLOCKS = ["workbook.markers", "google", "sheets"]

CONTROLS = [("matcher", "workbook.markers"),
            ("workbook.markers", "workbook.markers")]

PROBE = r"""
import sys

class Blocked:
    # find_spec only: Python 3.12 removed find_module, and a probe built on it
    # silently does nothing. That bug is why this file exists in this form.
    def find_spec(self, name, path=None, target=None):
        if name == "APITool.{blocked}":
            raise ImportError("APITool.{blocked} removed (probe)")
        return None

sys.meta_path.insert(0, Blocked())

import APITool.{target}
print("SURVIVED")
"""


def attempt(blocked: str, target: str) -> bool:
    """True if APITool.<target> imports while APITool.<blocked> is unavailable."""
    proc = subprocess.run(
        [sys.executable, "-c", PROBE.format(blocked=blocked, target=target)],
        cwd=REPO, capture_output=True, text=True,
    )
    return proc.returncode == 0 and "SURVIVED" in proc.stdout


# --------------------------------------------------------------------------
# Controls first. No results are reported unless both fail as predicted.
# --------------------------------------------------------------------------

print("Control arms (both predicted to FAIL)\n")
control_ok = True
for blocked, target in CONTROLS:
    survived = attempt(blocked, target)
    verdict = "*** PASSED -- METHOD BROKEN ***" if survived else "died as predicted"
    print(f"  block {blocked:<8} import {target:<8} {verdict}")
    if survived:
        control_ok = False

if not control_ok:
    print("\nMETHOD BROKEN: a control survived, so the blocker is not taking")
    print("effect. No survival results are reported.")
    sys.exit(2)

# --------------------------------------------------------------------------
# The matrix.
# --------------------------------------------------------------------------

print("\nSurvival matrix -- does <module> still import when <blocked> is gone?\n")
W = max(len(m) for m in MODULES + BLOCKS) + 2
header = "  " + "module".ljust(W) + "".join(b.ljust(W) for b in BLOCKS)
print(header)
print("  " + "-" * (len(header) - 2))

survival = {}
for module in MODULES:
    row = {b: attempt(b, module) for b in BLOCKS}
    survival[module] = row
    cells = "".join(("survives" if row[b] else "DIES").ljust(W) for b in BLOCKS)
    print(f"  {module.ljust(W)}{cells}")

# --------------------------------------------------------------------------
# Does it nest? A hierarchy means the survival sets are totally ordered by
# inclusion: for any two modules, one's set contains the other's.
# --------------------------------------------------------------------------

print("\nStructure\n")
# Comparing survival SETS is invalid here: each module can only ever survive
# the blocks that are not itself, so `markers` (max 2) and `catalog` (max 3)
# are incomparable by construction rather than by coupling. The question that
# actually has content is which NON-TRIVIAL edges exist -- module X dies when
# a DIFFERENT module Y is removed.
edges = [
    (m, b) for m in MODULES for b in BLOCKS if b != m and not survival[m][b]
]

print(f"  non-trivial module-scope dependency edges: {len(edges)}")
for target, blocked in edges:
    print(f"    {target} needs {blocked} at import time")

depends = sorted({t for t, _ in edges})
free = [m for m in MODULES if m not in depends and m not in BLOCKS]
print(f"\n  modules coupled to the spreadsheet stack at import: "
      f"{', '.join(depends) if depends else '(none)'}")
print(f"  modules free of it entirely: {len(free)} of {len(MODULES)}")

if len(edges) <= 1:
    print("\n  The import-scope graph is essentially FLAT. Survival does not")
    print("  discriminate the modules into layers, because the codebase")
    print("  already imports the spreadsheet stack lazily almost everywhere.")
    print("  => a 3-tier survival hierarchy cannot be derived from this.")

# --------------------------------------------------------------------------
# The specific claim about `service`.
# --------------------------------------------------------------------------

print("\nThe `service` claim\n")
svc = survival["service"]
for b in BLOCKS:
    print(f"  survives {b} deleted: {svc[b]}")

# Exit 1 when the graph is flat enough that survival cannot define layers --
# which is the refutation this probe was built to look for.
sys.exit(1 if len(edges) <= 1 else 0)
