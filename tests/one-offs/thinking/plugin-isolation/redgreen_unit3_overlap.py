"""
Red-green audit for slice A, unit 3: overlap detection and its two knobs.

Eight behaviour reverts, one at a time, every signature intact. G1 is the
one the probe was written for -- `overlaps` quietly becoming `contains` is
exactly how the partial case (`L5:L24` vs `L20:L30`) would go undetected --
and G4 puts back the state before any refusal existed.

SAFETY (rule 1b): the loader tests plant plugins in tmp_path and never
construct an exporter; the overlap tests are pure arithmetic. A leftover
`MUTANT` marker under APITool/ is a failed audit.

Run:  python tests/one-offs/thinking/plugin-isolation/redgreen_unit3_overlap.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
A1 = ROOT / "APITool" / "sheets" / "a1.py"
LOADER = ROOT / "APITool" / "loader.py"
# Two invocations, not one: `-k overlap` is global to a pytest run, and the
# first version of this driver passed both files to one command -- so every
# loader test without "overlap" in its name was DESELECTED, and three mutants
# reported "stayed green" against tests that had never run. A broken audit
# reads exactly like a guard.
TESTS = [["tests/test_sheets.py", "-k", "overlap"], ["tests/test_plugin_loader.py"]]
FULL = [["tests/"]]

MUTANTS = [
    ("G1 overlaps delegates to contains", A1,
     [('        return (\n'
       '            self._meets(self.first_col, self.last_col, other.first_col, other.last_col)\n'
       '            and self._meets(self.first_row, self.last_row, other.first_row, other.last_row)\n'
       '        )\n',
       '        return self.contains(other) or other.contains(self)  # MUTANT G1\n')],
     ["test_cell_range_overlap", "test_overlap_catches_what_containment_misses"]),
    ("G2 touching ends do not overlap (<=)", A1,
     [('        if a_hi is not None and b_lo is not None and a_hi < b_lo:\n',
       '        if a_hi is not None and b_lo is not None and a_hi <= b_lo:  # MUTANT G2\n')],
     ["test_cell_range_overlap"]),
    ("G3 conflicts compares across kinds", LOADER,
     [('            if left.kind is None or left.kind != right.kind:\n                continue\n',
       '            if left.kind is None:  # MUTANT G3\n                continue\n')],
     ["test_different_kinds_never_conflict"]),
    ("G4 error records instead of raising", LOADER,
     [('        if found_conflicts and severity == SEVERITY_ERROR:\n',
       '        if False:  # MUTANT G4\n')],
     ["test_overlapping_declarations_are_refused_under_error",
      "test_error_is_the_default_severity",
      "test_a_configured_overlap_is_reported_by_the_command_not_a_traceback"]),
    ("G5 precedence ignored", LOADER,
     [('    if precedence:\n'
       '        rank = {name: i for i, name in enumerate(_unique(precedence))}\n'
       '        result.loaded.sort(key=lambda e: rank.get(e.name, len(rank)))\n',
       '    if False:  # MUTANT G5\n        pass\n')],
     ["test_precedence_decides_who_wins_without_changing_what_is_enabled",
      "test_precedence_names_it_does_not_know_go_last_and_are_ignored"]),
    ("G6 the kind asks contains, not overlaps", LOADER,
     [('                    if CellRange.parse(left).overlaps(CellRange.parse(right)):\n',
       '                    if CellRange.parse(left).contains(CellRange.parse(right)):  # MUTANT G6\n')],
     ["test_overlapping_declarations_are_refused_under_error",
      "test_overlapping_declarations_load_in_order_under_warn"]),
    ("G7 ignore behaves like warn", LOADER,
     [('    if severity != SEVERITY_IGNORE:\n',
       '    if True:  # MUTANT G7\n')],
     ["test_overlap_is_silent_under_ignore"]),
    ("G8 describe drops who takes precedence", LOADER,
     [('        return f"{self.first} / {self.second}: {self.where} ({self.first} takes precedence)"\n',
       '        return f"{self.first} / {self.second}: {self.where}"  # MUTANT G8\n')],
     ["test_overlapping_declarations_load_in_order_under_warn"]),
]


def run_tests(invocations: list[list[str]]) -> tuple[int, set[str], str]:
    code, failed, summaries = 0, set(), []
    for tests in invocations:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider", "-rf"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        code = code or proc.returncode
        for line in proc.stdout.splitlines():
            if line.startswith("FAILED "):
                failed.add(line.split("::", 1)[1].split(" ", 1)[0].split("[", 1)[0])
        summary = [ln for ln in proc.stdout.splitlines() if "passed" in ln or "failed" in ln]
        summaries.append((summary[-1] if summary else proc.stdout[-200:]).strip("= "))
    return code, failed, " | ".join(summaries)


def main() -> int:
    originals = {p: p.read_bytes() for p in {A1, LOADER}}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                   capture_output=True, text=True).stdout

    print("=" * 76)
    print(f"Red-green audit, slice A unit 3 -- HEAD {head}")
    print("=" * 76)
    code, _, summary = run_tests(TESTS)
    print(f"  baseline: {summary}")
    if code != 0:
        print("  baseline is not green; nothing below is interpretable")
        return 1

    problems = 0
    for label, path, pairs, expect_red in MUTANTS:
        text = originals[path].decode("utf-8")
        nl = "\r\n" if "\r\n" in text else "\n"
        mutated = text
        for before, after in pairs:
            before, after = before.replace("\n", nl), after.replace("\n", nl)
            assert mutated.count(before) == 1, f"{label}: anchor not unique in {path.name}: {before[:50]!r}"
            mutated = mutated.replace(before, after)
        try:
            path.write_bytes(mutated.encode("utf-8"))
            _, failed, summary = run_tests(TESTS)
        finally:
            path.write_bytes(originals[path])
            assert path.read_bytes() == originals[path], f"{path.name} not restored"
        hit = [t for t in expect_red if t in failed]
        missed = [t for t in expect_red if t not in failed]
        extra = sorted(failed - set(expect_red))
        verdict = "ANCHOR" if hit and not missed else ("PARTIAL" if hit else "GUARD -- stayed green")
        if missed:
            problems += 1
        print(f"\n  {label}")
        print(f"      {summary}")
        print(f"      {verdict}")
        for t in hit:
            print(f"        red as expected: {t}")
        for t in missed:
            print(f"        STAYED GREEN:    {t}")
        for t in extra:
            print(f"        also red:        {t}")

    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                  capture_output=True, text=True).stdout
    leftover = subprocess.run(["git", "grep", "-l", "MUTANT G", "--", "APITool/"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
    code, _, summary = run_tests(FULL)
    print("\n" + "-" * 76)
    print(f"  restored: status unchanged={status_after == status_before}, "
          f"leftover markers={'none' if not leftover else leftover}, full suite: {summary}")
    print("=" * 76)
    return problems + (0 if status_after == status_before and not leftover and code == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
