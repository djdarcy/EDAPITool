"""
What would the layering test say about `service` and `daemon` today?

The existing check -- tests/test_market_data.py:308 -- walks EVERY import node
with `ast.walk`, so a `from .workbook.markers import X` sitting inside a
function body counts exactly the same as one at module scope. That matters for
the #18 isolation design, because the two are not the same kind of coupling:

  - a MODULE-scope import is a hard dependency. Importing `service` imports
    `workbook`, always, whether or not a Totals Tab is ever touched.
  - a FUNCTION-scope import is a deferred one. It costs nothing until the
    branch that needs it runs, and deleting the destination package leaves
    every other path working.

`cli.py` already uses the deferred form (286, 292) and `service.py` uses it
once too (142). Only `service.py:34` is module scope. So the rule the design
wants to assert is "no module-scope reach into the destination layer", and
this probe measures the gap between that rule and the one the test can
currently express.

Run:  python tests/one-offs/thinking/plugin-isolation/probe_layer_edges.py
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4] / "APITool"

PRESENTATION = {"sheets", "google", "workbook"}
DESTINATION = {"workbook"}


def _sources(module_name: str) -> list[Path]:
    single = ROOT / f"{module_name}.py"
    if single.exists():
        return [single]
    return sorted((ROOT / module_name).glob("*.py"))


def _bare(name: str) -> str:
    return name.lstrip(".").removeprefix("APITool.").split(".")[0]


def edges(module_name: str) -> tuple[set[str], set[str]]:
    """Return (module-scope imports, function-scope imports), bare names."""
    module_scope: set[str] = set()
    deferred: set[str] = set()

    for path in _sources(module_name):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        multi = len(_sources(module_name)) > 1

        # Module scope is the tree's own direct children -- nothing else.
        top = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.level == 1 and multi:
                    continue
                top.add(_bare(node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top.add(_bare(alias.name))
        module_scope |= top

        # Everything ast.walk finds, minus what was at the top, is deferred.
        everywhere = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.level == 1 and multi:
                    continue
                everywhere.add(_bare(node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    everywhere.add(_bare(alias.name))
        deferred |= everywhere - top

    return module_scope, deferred


def main() -> None:
    candidates = [
        "catalog", "market", "matcher", "journal", "ship",   # today's CORE
        "service", "daemon",                                  # in NEITHER list
        "cli", "export",
    ]

    print(f"{'module':<12} {'mod-scope -> presentation':<28} "
          f"{'deferred -> presentation':<26} verdict")
    print("-" * 96)

    for name in candidates:
        mod, defer = edges(name)
        mod_leak = sorted(mod & PRESENTATION)
        def_leak = sorted(defer & PRESENTATION)
        if set(mod_leak) & DESTINATION:
            verdict = "HARD dependency on destination"
        elif set(def_leak) & DESTINATION:
            verdict = "deferred only -- deletable"
        elif mod_leak or def_leak:
            verdict = "toolkit only"
        else:
            verdict = "clean"
        print(f"{name:<12} {str(mod_leak):<28} {str(def_leak):<26} {verdict}")

    print()
    print("The question the design must answer: which of these belong in a")
    print("list the test enforces, and under WHICH rule -- 'no import at all'")
    print("or 'no module-scope import'?")


if __name__ == "__main__":
    main()
