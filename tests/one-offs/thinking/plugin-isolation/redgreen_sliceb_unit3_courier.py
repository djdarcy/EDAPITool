"""
Red-green audit for slice B, unit 3: the courier removed.

Four behaviour reverts. P1 and P3 put back a plugin that ignores the glyph
choice core now hands it as a word; P4 puts back a CLI that calls a help
function without asking whether the plugin has one.

SAFETY (rule 1b): every test here plants plugins in tmp_path or reads the
shipped plugin's constants; nothing is written. No MUTANT marker survives.

Run:  python tests/one-offs/thinking/plugin-isolation/redgreen_sliceb_unit3_courier.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PLUGIN = ROOT / "APITool" / "plugins" / "settlement" / "__init__.py"
CLI = ROOT / "APITool" / "cli.py"
TESTS = [["tests/test_plugin_loader.py"]]
FULL = [["tests/"]]

MUTANTS = [
    ("P1 markers_for returns the default family for every choice", PLUGIN,
     [('    if empty_marker in (None, "hollow"):\n        return None\n',
       '    if True:  # MUTANT P1\n        return None\n')],
     ["test_the_shipped_plugin_builds_the_glyph_map_the_cli_used_to"]),
    ("P2 small and dotted collapse to one glyph", PLUGIN,
     [('    empty = MARKER_EMPTY_SMALL if empty_marker == "small" else MARKER_EMPTY_DOTTED\n',
       '    empty = MARKER_EMPTY_DOTTED  # MUTANT P2\n')],
     ["test_the_shipped_plugin_builds_the_glyph_map_the_cli_used_to"]),
    ("P3 layout() drops the empty-marker choice", PLUGIN,
     [('    if empty_marker is not None and "markers" not in values:\n        values["markers"] = markers_for(empty_marker)\n',
       '    pass  # MUTANT P3\n')],
     ["test_the_shipped_plugin_builds_the_glyph_map_the_cli_used_to"]),
    ("P4 the CLI calls formula help without asking whether it exists", CLI,
     [('        if not callable(formula_help):\n',
       '        if False:  # MUTANT P4\n')],
     ["test_a_plugin_without_formula_help_says_so"]),
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
    originals = {p: p.read_bytes() for p in {PLUGIN, CLI}}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                   capture_output=True, text=True).stdout

    print("=" * 76)
    print(f"Red-green audit, slice B unit 3 -- HEAD {head}")
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
        if extra:
            print(f"        also red:        {extra}")

    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                  capture_output=True, text=True).stdout
    leftover = subprocess.run(["git", "grep", "-l", "MUTANT P", "--", "APITool/"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
    code, _, summary = run_tests(FULL)
    print("\n" + "-" * 76)
    print(f"  restored: status unchanged={status_after == status_before}, "
          f"leftover markers={'none' if not leftover else leftover}, full suite: {summary}")
    print("=" * 76)
    return problems + (0 if status_after == status_before and not leftover and code == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
