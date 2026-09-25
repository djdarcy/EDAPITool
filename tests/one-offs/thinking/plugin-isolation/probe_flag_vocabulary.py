"""
Probe: how many flags does core `cli.py` define that belong to one plugin?

`probe_no_sheet_knowledge.py` measures VALUES -- string literals naming a tab,
a column, a header -- and reports 0. It is blind to the INTERFACE: a flag
name is not a literal it scans, so `--totals-tab` defined in core reads as
clean. The #28 restatement (2026-09-24) named the gap, and D-19 (plugins own
their flags) is the fix. This probe is the number that fix drives to zero.

Two modes, because the honest measurement changes once the contract exists:

* Before D-19: the baseline list is the classification posted on #28 -- the
  flags that only mean something to the settlement workbook. The probe
  counts how many of those `cli.py` still defines itself.
* After D-19: each loaded plugin declares its own flags; the probe asks the
  plugins and counts any core-defined flag whose name a plugin claims.
  Until a plugin offers `flags()`, this mode reports "no plugin declares
  flags yet" and falls back to the baseline.

Run from the repo root:  python tests/one-offs/thinking/plugin-isolation/probe_flag_vocabulary.py
Exit 0 when the count is 0, 1 otherwise, so it can sit beside the other probes.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CLI = ROOT / "APITool" / "cli.py"

# The #28 comment's classification, verbatim in spirit: flags whose meaning is
# one workbook's. The gray zone (--update-sheet, --dry-run, --force, --sheet-id)
# is deliberately NOT here: those are general ideas with spreadsheet-shaped
# names, and the design decides them, not this probe.
BASELINE = {
    "market": {
        "--totals-tab", "--need-header", "--need-sign",
        "--marker-column", "--write-marker-header", "--empty-marker",
        "--no-markers", "--no-show-covered", "--no-color", "--show-formula",
        # v0.7.7 added market's own --write-location, the same vocabulary as
        # serve's; the #28 comment predates it, so the baseline is 14 not 13.
        "--write-location",
    },
    "serve": {"--totals-tab", "--write-location", "--construction-region"},
}


def core_flags() -> dict[str, set[str]]:
    """Every `--flag` cli.py defines, by the subparser variable it is added under."""
    tree = ast.parse(CLI.read_text(encoding="utf-8"))
    # `_writing = market_parser.add_argument_group(...)` -> _writing belongs to market
    owner: dict[str, str] = {}
    flags: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute) and isinstance(node.targets[0], ast.Name):
                target = node.targets[0].id
                if call.func.attr == "add_parser" and call.args and isinstance(call.args[0], ast.Constant):
                    owner[target] = call.args[0].value
                elif call.func.attr == "add_argument_group" and isinstance(call.func.value, ast.Name):
                    owner[target] = owner.get(call.func.value.id, call.func.value.id)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument" and isinstance(node.func.value, ast.Name)):
            names = [a.value for a in node.args if isinstance(a, ast.Constant) and str(a.value).startswith("--")]
            if not names:
                continue
            verb = owner.get(node.func.value.id, node.func.value.id)
            flags.setdefault(verb, set()).update(names)
    return flags


def declared_by_plugins() -> dict[str, set[str]] | None:
    """What loaded-or-shipped plugins say are THEIR flags, once the contract exists."""
    claimed: dict[str, set[str]] = {}
    found_any = False
    for name in ("settlement", "jsonl"):
        module = importlib.import_module(f"APITool.plugins.{name}")
        declare = getattr(module, "flags", None)
        if declare is None:
            continue
        found_any = True
        for verb, names in declare().items():
            claimed.setdefault(verb, set()).update(names)
    return claimed if found_any else None


def main() -> int:
    defined = core_flags()
    claimed = declared_by_plugins()
    mode = "contract" if claimed is not None else "baseline (no plugin declares flags yet)"
    reference = claimed if claimed is not None else BASELINE
    leaks: list[tuple[str, str]] = []
    for verb, names in reference.items():
        for flag in sorted(names):
            if flag in defined.get(verb, set()):
                leaks.append((verb, flag))
    print(f"mode: {mode}")
    for verb in sorted(defined):
        print(f"  {verb:<12} {len(defined[verb]):>2} flags defined in core")
    print(f"{len(leaks)} plugin-vocabulary flags defined in core")
    for verb, flag in leaks:
        print(f"  {verb:<12} {flag}")
    return 0 if not leaks else 1


if __name__ == "__main__":
    sys.exit(main())
