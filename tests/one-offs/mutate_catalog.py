#!/usr/bin/env python
"""
Red-green audit for tests/test_catalog.py.

A test that has only ever been seen green has not demonstrated it can detect
anything. This injects known-wrong behaviour into APITool/catalog.py, runs the
suite, and reports which mutants survived. A surviving mutant is a test gap.

Restores the original file in a finally block. Run from the repo root:
    python tests/one-offs/mutate_catalog.py
"""

import subprocess
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[2] / "APITool" / "catalog.py"

MUTANTS = [
    (
        "aliases never loaded",
        "        catalog.load_aliases(alias_source)",
        "        pass  # MUTANT",
    ),
    (
        "by_symbol stops stripping the $..._name; wrapper",
        "        return self._by_symbol.get(normalize(strip_symbol(symbol)))",
        "        return self._by_symbol.get(normalize(symbol))  # MUTANT",
    ),
    (
        "add_alias overwrites an existing canonical name",
        "        if not key or key in self._by_name:\n            return False",
        "        if not key:\n            return False  # MUTANT",
    ),
    (
        "resolve() checks name before id (wrong precedence)",
        "            (self.by_id, commodity_id),\n            (self.by_symbol, symbol),\n            (self.by_name, name),",
        "            (self.by_name, name),\n            (self.by_symbol, symbol),\n            (self.by_id, commodity_id),  # MUTANT",
    ),
    (
        "normalize keeps punctuation",
        '    return re.sub(r"[^a-z0-9]", "", str(text).lower())',
        "    return str(text).lower()  # MUTANT",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_catalog.py", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=TARGET.parents[1],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    survivors = []
    try:
        code, line = run_suite()
        print(f"BASELINE: {'PASS' if code == 0 else 'FAIL'}  {line}")
        if code != 0:
            print("Baseline is not green; fix that before auditing.")
            return 1
        print()

        for name, find, replace in MUTANTS:
            if find not in original:
                print(f"  SKIP    {name}  (anchor not found -- update the mutant)")
                continue
            TARGET.write_text(original.replace(find, replace, 1), encoding="utf-8")
            code, line = run_suite()
            killed = code != 0
            print(f"  {'KILLED ' if killed else 'SURVIVED'} {name}")
            print(f"           {line}")
            if not killed:
                survivors.append(name)
    finally:
        TARGET.write_text(original, encoding="utf-8")
        print("\nRestored original catalog.py")

    print()
    if survivors:
        print(f"{len(survivors)} SURVIVING mutant(s) -- test gaps:")
        for s in survivors:
            print(f"  - {s}")
        return 1
    print(f"All {len(MUTANTS)} mutants killed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
