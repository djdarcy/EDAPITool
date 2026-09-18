"""
Red-green audit for slice B, unit 2: the supplier/subscriber registry and R5.

Nine behaviour reverts. N1 is the one the whole unit exists for -- a registry
that pulls the supplier every time instead of once -- and N4/N5 put back a
service that ignores what the plugin offers. Every signature stays intact.

SAFETY (rule 1b): the registry tests use counters and in-memory fakes; the
service-level tests build a journal in tmp_path and write to a fake sheet.
Nothing under APITool/ keeps a MUTANT marker at the end.

Run:  python tests/one-offs/thinking/plugin-isolation/redgreen_sliceb_unit2_registry.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / "APITool" / "registry.py"
SERVICE = ROOT / "APITool" / "service.py"
READER = ROOT / "APITool" / "sheets" / "reader.py"
CLI = ROOT / "APITool" / "cli.py"
PLUGIN = ROOT / "APITool" / "plugins" / "settlement" / "__init__.py"
TESTS = [["tests/test_supplier_registry.py"], ["tests/test_service.py"]]
FULL = [["tests/"]]

MUTANTS = [
    ("N1 the supplier is pulled every time", REGISTRY,
     [('        if name in self._cache:\n            return self._cache[name]\n        try:\n',
       '        try:  # MUTANT N1\n')],
     ["test_a_supplier_is_pulled_once_for_two_subscribers",
      "test_supplied_lists_pulls_in_first_ask_order_and_never_twice",
      "test_one_acquisition_feeds_every_consumer_of_the_carrier",
      "test_refresh_reads_the_worksheet_once_for_the_comparison_and_the_writer"]),
    ("N2 a subscription publishes before its needs are pulled", REGISTRY,
     [('            for need in subscription.needs:\n                self.get(need)\n            statuses[subscription.name] = subscription.publish(self)\n',
       '            statuses[subscription.name] = subscription.publish(self)  # MUTANT N2\n')],
     ["test_a_subscription_needing_an_unknown_supplier_fails_before_publishing"]),
    ("N3 the last offerer of a supplier wins silently", REGISTRY,
     [('            if name in merged:\n'
       '                raise ValueError(\n'
       '                    f"supplier {name!r} is offered by both {offered_by[name]!r} "\n'
       '                    f"and {offerer!r}; a supplier has one source"\n'
       '                )\n'
       '            merged[name] = supply\n',
       '            merged[name] = supply  # MUTANT N3\n')],
     ["test_two_offerers_of_one_supplier_are_refused_by_name"]),
    ("N4 the service ignores what the plugin supplies", SERVICE,
     [('        supplies = getattr(plugin, "supplies", None)\n',
       '        supplies = None  # MUTANT N4\n')],
     ["test_refresh_reads_the_worksheet_once_for_the_comparison_and_the_writer"]),
    ("N5 the service runs no subscriptions", SERVICE,
     [('        statuses = ctx.run(self.subscriptions)\n',
       '        statuses = {}  # MUTANT N5\n')],
     ["test_refresh_reads_the_worksheet_once_for_the_comparison_and_the_writer"]),
    ("N6 the reader records no origin", READER,
     [('            requirements=build_requirements(rows, self.catalog, origin_for=origin_for),\n',
       '            requirements=build_requirements(rows, self.catalog),  # MUTANT N6\n')],
     ["test_a_requirement_read_from_a_sheet_says_where_it_came_from"]),
    ("N7 market --json drops origin", CLI,
     [('                "row": m.row,\n                "origin": m.origin,\n',
       '                "row": m.row,  # MUTANT N7\n')],
     ["test_market_json_carries_origin_and_still_carries_row"]),
    ("N8 the plugin never applies the plan it built", PLUGIN,
     [('    if options["write"]:\n        writer.apply(plan)\n    return plan\n',
       '    return plan  # MUTANT N8\n')],
     ["test_refresh_reads_the_worksheet_once_for_the_comparison_and_the_writer"]),
    ("N9 an unknown environment name reads as None", REGISTRY,
     [('        if name in env:\n            return env[name]\n        raise AttributeError(name)\n',
       '        return env.get(name)  # MUTANT N9\n')],
     ["test_the_environment_reads_as_attributes_and_nothing_else_does"]),
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
    originals = {p: p.read_bytes() for p in {REGISTRY, SERVICE, READER, CLI, PLUGIN}}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                   capture_output=True, text=True).stdout

    print("=" * 76)
    print(f"Red-green audit, slice B unit 2 -- HEAD {head}")
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
            print(f"        also red:        {len(extra)} other test(s), e.g. {extra[0]}")

    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                  capture_output=True, text=True).stdout
    leftover = subprocess.run(["git", "grep", "-l", "MUTANT N", "--", "APITool/"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
    code, _, summary = run_tests(FULL)
    print("\n" + "-" * 76)
    print(f"  restored: status unchanged={status_after == status_before}, "
          f"leftover markers={'none' if not leftover else leftover}, full suite: {summary}")
    print("=" * 76)
    return problems + (0 if status_after == status_before and not leftover and code == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
