"""
Red-green audit for slice C, unit 1: the configuration namespace.

Eleven behaviour reverts across six files. Q1-Q3, Q5 put back a settings
module that does not alias a bare sheet_id, drops the config block, or
ignores targets; Q6-Q8 put back a composition root that hands the plugin
nothing, carries no target, or imports the shipped plugin's parser by name;
Q4 and Q9 drop the origin prefix at the reader and on the refresh; Q10 and
Q11 break the MOVED bodies, which is the proof that the retargeted tests
still bite after the move.

SAFETY (rule 1b): every CLI-level test stubs ``daemon.build`` with a
BaseException so that a refusal that stops firing aborts rather than starting
a real daemon; every settings test redirects CONFIG_FILE. Reverting Q1, Q6,
Q7 and Q10 removes refusals -- the stub is what makes that safe. No MUTANT
marker survives.

Run:  python tests/one-offs/thinking/plugin-isolation/redgreen_slicec_unit1_namespace.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SETTINGS = ROOT / "APITool" / "settings.py"
LOADER = ROOT / "APITool" / "loader.py"
CLI = ROOT / "APITool" / "cli.py"
READER = ROOT / "APITool" / "sheets" / "reader.py"
SERVICE = ROOT / "APITool" / "service.py"
BINDINGS = ROOT / "APITool" / "plugins" / "settlement" / "bindings.py"
# One invocation per file: a -k that names tests in two files selects from one.
TESTS = [["tests/test_config_regions.py"], ["tests/test_plugin_loader.py"],
         ["tests/test_settings.py"], ["tests/test_supplier_registry.py"]]
FULL = [["tests/"]]

MUTANTS = [
    ("Q1 default_target never aliases a bare sheet_id", SETTINGS,
     [('    if not sheet_id and not extra:\n        return None\n',
       '    if True:  # MUTANT Q1\n        return None\n')],
     ["test_a_bare_sheet_id_resolves_to_a_default_target",
      "test_a_legacy_file_carries_its_bindings_into_the_default_target",
      "test_the_bindings_reach_the_daemon_unchanged_in_both_shapes"]),
    ("Q2 get_targets drops the config block", SETTINGS,
     [('        out[str(name)] = Target(str(name), kind, plugin, dict(config), params)\n',
       '        out[str(name)] = Target(str(name), kind, plugin, {}, params)  # MUTANT Q2\n')],
     ["test_a_targets_entry_carries_its_config_block_and_the_kinds_keys",
      "test_the_bindings_reach_the_daemon_unchanged_in_both_shapes"]),
    ("Q3 get_sheet_id never reads a target's id", SETTINGS,
     [('        if target.kind == "gsheet" and target.params.get("id"):\n            return target.params["id"]\n',
       '        if False:  # MUTANT Q3\n            return target.params["id"]\n')],
     ["test_carrier_honours_the_first_sheet_targets_id",
      "test_the_first_sheet_targets_id_wins_over_the_bare_key"]),
    ("Q4 the reader never prefixes the origin", READER,
     [('        prefix = f"{self.target}!" if self.target else ""\n',
       '        prefix = ""  # MUTANT Q4\n')],
     ["test_a_configured_targets_name_prefixes_the_origin",
      "test_the_target_name_rides_the_refresh_to_the_reader"]),
    ("Q5 a malformed targets map crashes a sheet-id lookup", SETTINGS,
     [('    except ValueError:\n        return {}\n',
       '    except ValueError:\n        raise  # MUTANT Q5\n')],
     ["test_a_malformed_targets_map_does_not_turn_a_sheet_id_lookup_into_a_traceback"]),
    ("Q6 cmd_serve hands the plugin an empty block", CLI,
     [('    block = destination.target.config if destination.target is not None else {}\n',
       '    block = {}  # MUTANT Q6\n')],
     ["test_a_malformed_config_entry_refuses_the_run_through_the_cli",
      "test_the_index_named_is_the_real_index",
      "test_the_bindings_reach_the_daemon_unchanged_in_both_shapes"]),
    ("Q7 a loaded plugin never carries its target", LOADER,
     [('        result.loaded.append(Loaded(name, module, entry, kind, declaration, targets.get(name)))\n',
       '        result.loaded.append(Loaded(name, module, entry, kind, declaration, None))  # MUTANT Q7\n')],
     ["test_a_targets_entry_carries_its_config_block_and_the_kinds_keys",
      "test_a_bare_sheet_id_resolves_to_a_default_target",
      "test_the_bindings_reach_the_daemon_unchanged_in_both_shapes"]),
    ("Q8 cmd_serve imports the shipped plugin's parser instead of asking", CLI,
     [('    bind = getattr(destination.module, "construction_regions", None)\n',
       '    from .plugins.settlement.bindings import construction_regions as bind  # MUTANT Q8\n')],
     ["test_a_plugin_with_no_bindings_publishes_no_regions"]),
    ("Q9 the refresh drops the target name", SERVICE,
     [('            target=self.target,\n',
       '            target="",  # MUTANT Q9\n')],
     ["test_the_target_name_rides_the_refresh_to_the_reader"]),
    ("Q10 (moved body) a binding with no region is skipped, not refused", BINDINGS,
     [('        if "region" not in entry:\n            raise ValueError(f\'{where} has no "region"\')\n',
       '        if "region" not in entry:  # MUTANT Q10\n            continue\n')],
     ["test_a_config_entry_with_no_region_is_refused",
      "test_a_malformed_config_entry_refuses_the_run_through_the_cli",
      "test_the_index_named_is_the_real_index"]),
    ("Q12 a flag the plugin cannot honour is dropped, not refused", CLI,
     [('    if not callable(bind) and args.construction_region:\n',
       '    if False:  # MUTANT Q12\n')],
     ["test_a_flag_the_plugin_cannot_honour_is_refused_rather_than_dropped"]),
    ("Q11 (moved body) the flag no longer wins over the block", BINDINGS,
     [('    if specs:\n        return [parse_region_spec(s) for s in specs]\n',
       '    if False:  # MUTANT Q11\n        return [parse_region_spec(s) for s in specs]\n')],
     ["test_the_flag_is_read", "test_the_flag_repeats",
      "test_the_flag_wins_outright_over_config",
      "test_a_bad_flag_value_refuses_without_a_trailing_blank_line"]),
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
    originals = {p: p.read_bytes() for p in {SETTINGS, LOADER, CLI, READER, SERVICE, BINDINGS}}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                   capture_output=True, text=True).stdout

    print("=" * 76)
    print(f"Red-green audit, slice C unit 1 -- HEAD {head}")
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
    leftover = subprocess.run(["git", "grep", "-l", "MUTANT Q", "--", "APITool/"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
    code, _, summary = run_tests(FULL)
    print("\n" + "-" * 76)
    print(f"  restored: status unchanged={status_after == status_before}, "
          f"leftover markers={'none' if not leftover else leftover}, full suite: {summary}")
    print("=" * 76)
    return problems + (0 if status_after == status_before and not leftover and code == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
