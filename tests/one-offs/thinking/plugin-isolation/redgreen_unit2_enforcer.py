"""
Red-green audit for slice A, unit 2: core builds the enforcer.

Six behaviour reverts, one at a time; every signature stays intact so the
tests fail on their assertions, never on TypeError. R5 is the one that
matters: it puts the original defect back in its new clothes -- the writer
building its own guard from its own declaration -- and the test written for
the fix must go red under it, or the fix is unproven.

SAFETY (rule 1b): mutants live on disk only for one pytest run each and are
restored byte-identical. Every test here plants nothing and writes nothing
outside a fake in-memory sheet. A leftover `MUTANT` marker under APITool/ is
a failed audit.

Run:  python tests/one-offs/thinking/plugin-isolation/redgreen_unit2_enforcer.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LOADER = ROOT / "APITool" / "loader.py"
SERVICE = ROOT / "APITool" / "service.py"
TOTALS = ROOT / "APITool" / "plugins" / "settlement" / "totals.py"
LOADER_TESTS = ["tests/test_plugin_loader.py"]
SERVICE_TESTS = ["tests/test_plugin_loader.py", "tests/test_service.py"]

# (id, file, [(original, mutant), ...], tests to run, tests expected red)
MUTANTS = [
    ("R1 build_enforcer widens every tab to the whole tab", LOADER,
     [('        return WriteGuard.build(dict(declaration))\n',
       '        return WriteGuard.build({tab: ["A1:ZZZ1000000"] for tab in declaration})  # MUTANT R1\n')],
     LOADER_TESTS,
     ["test_a_guard_core_builds_from_the_declaration_refuses_the_bad_write",
      "test_the_shipped_plugin_declares_rather_than_guards"]),
    ("R2 kind_for accepts any name", LOADER,
     [('    if name is None or name not in KINDS:\n'
       '        raise ValueError(\n'
       '            f"unknown target kind {name!r}; known kinds: {\', \'.join(sorted(KINDS))}"\n'
       '        )\n'
       '    return KINDS[name]\n',
       '    return KINDS.get(name, GSheetKind)  # MUTANT R2\n')],
     LOADER_TESTS,
     ["test_an_unknown_kind_is_refused_and_names_the_known_ones"]),
    ("R3 load ignores the configured kinds", LOADER,
     [('        kind = kinds.get(name) or getattr(module, "KIND", None)\n',
       '        kind = getattr(module, "KIND", None)  # MUTANT R3\n')],
     LOADER_TESTS,
     ["test_a_targets_kind_overrides_the_plugins_own_and_absence_falls_back"]),
    ("R4 kinds_from lets the last target win", LOADER,
     [('        kinds.setdefault(target.plugin, target.kind)\n',
       '        kinds[target.plugin] = target.kind  # MUTANT R4\n')],
     LOADER_TESTS,
     ["test_kinds_come_from_the_first_target_naming_a_plugin"]),
    ("R5 the writer builds its own guard again (the original defect)", TOTALS,
     [('        *,\n'
       '        guard: WriteGuard,\n'
       '    ):\n',
       '        guard: Optional[WriteGuard] = None,  # MUTANT R5\n'
       '    ):\n'),
      ('        self.guard = guard\n',
       '        self.guard = guard or WriteGuard.build(self.layout.writes())  # MUTANT R5\n')],
     LOADER_TESTS,
     ["test_the_writer_cannot_be_built_without_a_guard"]),
    ("R6 the service's fallback is built from nothing", SERVICE,
     [('            guard = build_enforcer(GSHEET, layout.writes())\n',
       '            guard = build_enforcer(GSHEET, {})  # MUTANT R6\n')],
     SERVICE_TESTS,
     ["test_the_service_builds_the_guard_from_the_declaration_when_handed_none"]),
]


def run_tests(tests: list[str]) -> tuple[int, set[str], str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider", "-rf"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    failed = set()
    for line in proc.stdout.splitlines():
        if line.startswith("FAILED "):
            failed.add(line.split("::", 1)[1].split(" ", 1)[0].split("[", 1)[0])
    summary = [ln for ln in proc.stdout.splitlines() if "passed" in ln or "failed" in ln]
    return proc.returncode, failed, (summary[-1] if summary else proc.stdout[-200:])


def main() -> int:
    originals = {p: p.read_bytes() for p in {LOADER, SERVICE, TOTALS}}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                   capture_output=True, text=True).stdout

    print("=" * 76)
    print(f"Red-green audit, slice A unit 2 -- HEAD {head}")
    print("=" * 76)
    code, _, summary = run_tests(SERVICE_TESTS)
    print(f"  baseline: {summary}")
    if code != 0:
        print("  baseline is not green; nothing below is interpretable")
        return 1

    problems = 0
    for label, path, pairs, tests, expect_red in MUTANTS:
        text = originals[path].decode("utf-8")
        nl = "\r\n" if "\r\n" in text else "\n"
        mutated = text
        for before, after in pairs:
            before, after = before.replace("\n", nl), after.replace("\n", nl)
            assert mutated.count(before) == 1, f"{label}: anchor not unique in {path.name}: {before[:40]!r}"
            mutated = mutated.replace(before, after)
        try:
            path.write_bytes(mutated.encode("utf-8"))
            _, failed, summary = run_tests(tests)
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
    leftover = subprocess.run(["git", "grep", "-l", "MUTANT R", "--", "APITool/"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
    code, _, summary = run_tests(["tests/"])
    print("\n" + "-" * 76)
    print(f"  restored: status unchanged={status_after == status_before}, "
          f"leftover markers={'none' if not leftover else leftover}, full suite: {summary}")
    print("=" * 76)
    return problems + (0 if status_after == status_before and not leftover and code == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
