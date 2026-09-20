"""
Red-green audit for slice D: the second kind, and the config schema's home.

Twenty-one behaviour reverts, added as the slice grew.

D1-D4 put back the assumption that a destination is a worksheet -- core
gating subscriptions on one kind's handle, and the settlement plugin relying
on that gate instead of guarding itself. D5-D9 put back a core that either
does not ask a plugin about its own configuration or does not repeat the
answer. D10 blunts the file kind's enforcer. D11 ignores the environment's
config-directory override. D14-D18 put back a `plugins` verb that imports
without consent, or reports a fact without its reason. D19-D23 put back the
core that shipped a destination: an unconfigured install handed the shipped
plugin anyway, a `market` that refused the whole command rather than the one
flag that needed a plugin, a core that reads inside a plugin's config block,
and a listing that opens on a blank line.

D12 and D13 were deleted rather than retargeted; the comment where they sat
says why.

SAFETY (rule 1b): D3 and D4 remove the settlement plugin's own guards, so
under those reverts its reader and writer are handed a None worksheet -- they
raise AttributeError rather than touching anything, and no test here holds a
real worksheet. D10 removes a refusal, so the test that asserts it must not
be able to perform the write: it asserts on the guard object and never opens
a file. Every jsonl path writes under tmp_path only. No MUTANT marker
survives.

Run:  python tests/one-offs/thinking/plugin-isolation/redgreen_sliced_units.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SERVICE = ROOT / "APITool" / "service.py"
SETTLEMENT = ROOT / "APITool" / "plugins" / "settlement" / "__init__.py"
LOADER = ROOT / "APITool" / "loader.py"
SETTINGS = ROOT / "APITool" / "settings.py"
GUARD = ROOT / "APITool" / "guard.py"
CLI = ROOT / "APITool" / "cli.py"
# One invocation per file: a -k naming tests in two files selects from one.
TESTS = [["tests/test_supplier_registry.py"], ["tests/test_plugin_loader.py"],
         ["tests/test_service.py"], ["tests/test_settings.py"],
         ["tests/test_plugins_verb.py"], ["tests/test_config_regions.py"],
         ["tests/test_jsonl_plugin.py"]]
FULL = [["tests/"]]

MUTANTS = [
    ("D1 refresh returns before the subscribers instead of finishing", SERVICE,
     [("            return self._finish(result, ctx)\n",
       "            return result  # MUTANT D1\n")],
     ["test_a_plugin_with_no_worksheet_still_has_its_subscriptions_pushed"]),
    ("D2 _finish gates the subscribers on one kind's handle again", SERVICE,
     [("        if result.snapshot is None and ctx.has(\"requirements\"):\n",
       "        if ctx.worksheet is None:  # MUTANT D2\n            return result\n"
       "        if result.snapshot is None and ctx.has(\"requirements\"):\n")],
     ["test_a_plugin_with_no_worksheet_still_has_its_subscriptions_pushed"]),
    ("D3 the marker subscriber stops guarding itself", SETTLEMENT,
     [("    if ctx.worksheet is None:\n        # This plugin's destination IS a worksheet",
       "    if False:  # MUTANT D3\n        # This plugin's destination IS a worksheet")],
     ["test_refresh_without_a_worksheet_reports_state_only"]),
    ("D4 the requirements supplier stops guarding itself", SETTLEMENT,
     [("    if ctx.worksheet is None:\n        # The same reason the marker subscriber gives",
       "    if False:  # MUTANT D4\n        # The same reason the marker subscriber gives")],
     ["test_refresh_without_a_worksheet_reports_state_only",
      "test_missing_market_json_is_reported"]),
    ("D5 core never asks a plugin about its own block", LOADER,
     [("    ask = getattr(module, \"check_config\", None)\n",
       "    ask = None  # MUTANT D5\n")],
     ["test_a_plugin_reports_what_is_wrong_with_its_own_block",
      "test_a_check_config_that_raises_is_the_plugins_defect_and_is_isolated",
      "test_one_targets_bad_block_does_not_take_down_another_target"]),
    ("D6 a plugin's broken check_config takes the load down with it", LOADER,
     [("    except Exception as exc:  # noqa: BLE001 -- the plugin's defect, isolated\n"
       "        return (f\"{type(exc).__name__} while checking its configuration: {exc}\",)\n",
       "    except Exception:  # MUTANT D6\n        raise\n")],
     ["test_a_check_config_that_raises_is_the_plugins_defect_and_is_isolated"]),
    ("D7 the answer is collected and then dropped", LOADER,
     [("            Loaded(name, module, entry, kind, declaration, target,\n"
       "                   check_config(module, target))\n",
       "            Loaded(name, module, entry, kind, declaration, target, ())  # MUTANT D7\n")],
     ["test_a_plugin_reports_what_is_wrong_with_its_own_block",
      "test_a_check_config_that_raises_is_the_plugins_defect_and_is_isolated",
      "test_one_targets_bad_block_does_not_take_down_another_target"]),
    ("D8 the listing stops printing what a plugin complained about", LOADER,
     [("            for complaint in entry.complaints:\n",
       "            for complaint in ():  # MUTANT D8\n")],
     ["test_a_plugin_reports_what_is_wrong_with_its_own_block",
      "test_one_targets_bad_block_does_not_take_down_another_target"]),
    ("D9 the settlement plugin validates nothing", SETTLEMENT,
     [("    problems: list[str] = []\n    if not config:\n        return problems\n"
       "    regions = config.get(\"construction_regions\")\n",
       "    problems: list[str] = []\n    if True:  # MUTANT D9\n        return problems\n"
       "    regions = config.get(\"construction_regions\")\n")],
     ["test_the_settlement_plugins_schema_lives_with_the_plugin"]),
    ("D11 an explicit ED_CONFIG_DIR is ignored", SETTINGS,
     [("    named = os.environ.get(CONFIG_DIR_VAR)\n",
       "    named = None  # MUTANT D11\n")],
     ["test_an_explicit_directory_wins_outright_and_never_falls_back",
      "test_a_subprocess_can_be_isolated_by_the_environment_alone",
      "test_the_explicit_directory_expands_a_home_relative_path"]),
    # D12 and D13 were here: "a file already in the home folder is ignored"
    # and "the shared directory is never preferred". Both reverted branches
    # of a resolver that SEARCHED for each file -- an existing dotfile first,
    # then the shared directory. That search was removed when the resolver
    # became one rule and no search, and the three tests those reverts
    # expected to turn red went with it. A revert whose subject no longer
    # exists cannot be adapted into a useful one, so they are deleted rather
    # than retargeted at whatever happens to sit nearby.
    ("D14 `plugins list` imports everything it finds, consented or not", CLI,
     [("    enabled = enabled_from(targets, found)\n",
       "    enabled = [f.name for f in found]  # MUTANT D14\n")],
     ["test_list_does_not_import_a_plugin_nobody_configured"]),
    ("D15 a plugin that did not load is named without the reason", CLI,
     [("            print(f\"  {entry.name:<18} {entry.reason}\")\n",
       "            print(f\"  {entry.name:<18}\")  # MUTANT D15\n")],
     ["test_list_reports_loaded_broken_and_available_each_with_a_reason"]),
    ("D16 a malformed targets map reaches the person as a traceback", CLI,
     [("    try:\n        targets = settings.get_targets()\n"
       "    except ValueError as exc:\n        print(f\"Error: {exc}\")\n        return 1\n",
       "    targets = settings.get_targets()  # MUTANT D16\n")],
     ["test_list_reports_a_malformed_targets_map_rather_than_crashing"]),
    ("D17 describe stops reporting what a plugin supplies and subscribes to", CLI,
     [("        names = sorted(offered) if isinstance(offered, dict) else [\n"
       "            getattr(s, \"name\", str(s)) for s in offered]\n",
       "        names = []  # MUTANT D17\n")],
     ["test_describe_imports_the_one_plugin_named_and_shows_its_contract"]),
    ("D18 a flag the plugin cannot take is a traceback again", CLI,
     [("    except TypeError as exc:\n        unknown = _unknown_override(exc, overrides)\n",
       "    except TypeError as exc:  # MUTANT D18\n        unknown = None\n")],
     ["test_a_flag_one_plugin_does_not_speak_names_the_flag_not_the_traceback"]),
    ("D10 the file kind's enforcer refuses nothing", GUARD,
     [("        if not self.allows(path):\n", "        if False:  # MUTANT D10\n")],
     ["test_the_file_kinds_guard_refuses_a_path_it_did_not_declare"]),
    # --- R1: the core ships no destination ---------------------------------
    ("D19 an unconfigured install is given the shipped plugin anyway", LOADER,
     [("    return _unique(t.plugin for t in targets.values()) if targets else []\n",
       "    if targets:  # MUTANT D19\n"
       "        return _unique(t.plugin for t in targets.values())\n"
       "    return [f.name for f in found if f.origin == ORIGIN_SHIPPED]\n")],
     ["test_no_targets_means_no_plugin_is_enabled",
      "test_a_file_naming_no_target_enables_nothing",
      "test_discover_with_no_config_loads_nothing_and_offers_everything",
      "test_a_bare_sheet_id_names_a_spreadsheet_and_enables_nothing",
      "test_market_reads_the_station_with_no_destination_configured"]),
    ("D20 market refuses the whole command when no destination is configured", CLI,
     [("    destination, problem = _resolve_destination()\n"
       "    if destination is None:\n"
       "        needed = [flag for attribute, flag in DESTINATION_ONLY_FLAGS\n",
       "    destination, problem = _resolve_destination()\n"
       "    if destination is None:  # MUTANT D20\n"
       "        print(problem)\n"
       "        return 1\n"
       "    if destination is None:\n"
       "        needed = [flag for attribute, flag in DESTINATION_ONLY_FLAGS\n")],
     ["test_market_reads_the_station_with_no_destination_configured",
      "test_market_exports_csv_with_no_destination_configured",
      "test_market_refuses_update_sheet_by_name_with_no_destination"]),
    ("D21 core filters a plugin's config block to keys it recognises", SETTINGS,
     [("        config = entry.get(\"config\", {})\n",
       "        config = entry.get(\"config\", {})  # MUTANT D21\n"
       "        if isinstance(config, dict):\n"
       "            config = {k: v for k, v in config.items()\n"
       "                      if k == \"construction_regions\"}\n")],
     ["test_a_config_block_is_handed_over_whole"]),
    ("D22 top-level keys are swept into a plugin's block again", SETTINGS,
     [("        params = {k: v for k, v in entry.items() if k not in (\"kind\", \"plugin\", \"config\")}\n",
       "        params = {k: v for k, v in entry.items() if k not in (\"kind\", \"plugin\", \"config\")}\n"
       "        config = dict(config)  # MUTANT D22\n"
       "        config.update({k: v for k, v in load().items() if k != \"targets\"})\n")],
     ["test_a_core_key_at_the_top_level_never_reaches_a_plugin"]),
    ("D23 the plugins listing opens on a blank line again", CLI,
     [("        print(f\"\\n{heading}\" if written else heading)\n",
       "        print(f\"\\n{heading}\")  # MUTANT D23\n")],
     ["test_the_listing_never_opens_on_a_blank_line"]),
    # --- the second plugin, wired to its target ----------------------------
    ("D24 a target's own keys never reach the plugin's layout", CLI,
     [("    overrides = {**_target_overrides(destination), **supplied}\n",
       "    overrides = supplied  # MUTANT D24\n")],
     # NOT test_only_narrows_what_a_record_carries: that one builds the
     # layout directly, so a revert of the CLI's wiring cannot reach it.
     # Listed here once by mistake, and the audit said PARTIAL until the
     # expectation was corrected rather than the test.
     ["test_a_targets_path_reaches_the_plugins_layout",
      "test_market_publishes_to_a_file_destination_end_to_end"]),
    ("D25 core hands every plugin the first plugin's vocabulary again", CLI,
     [("            need_sign=None if args.need_sign is None else (\n"
       "                SIGN_NEGATIVE if args.need_sign == \"negative\" else SIGN_POSITIVE),\n",
       "            need_sign=SIGN_NEGATIVE if args.need_sign == \"negative\" "
       "else SIGN_POSITIVE,  # MUTANT D25\n")],
     # This revert restores only --need-sign's always-a-value default, and
     # the flags test types --need-sign in both of its calls, so it cannot
     # see the difference. The end-to-end test can: it types nothing.
     ["test_market_publishes_to_a_file_destination_end_to_end"]),
    ("D27 describe answers as shipped, ignoring the configured target", CLI,
     [("    return configured or shipped\n",
       "    return shipped  # MUTANT D27\n")],
     ["test_describe_shows_what_the_configured_target_makes_it_write"]),
    ("D28 a plugin whose layout declares less is reported as declaring less", CLI,
     [("    shipped = declared(entry.declaration)\n",
       "    shipped = {}  # MUTANT D28\n")],
     ["test_describe_imports_the_one_plugin_named_and_shows_its_contract"]),
    ("D26 a layout is offered keys it never said it accepts", CLI,
     [("    return {k: v for k, v in offered.items() if k in accepted and v is not None}\n",
       "    return {k: v for k, v in offered.items() if v is not None}  # MUTANT D26\n")],
     ["test_a_sheet_targets_id_does_not_become_a_layout_override"]),
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
    originals = {p: p.read_bytes() for p in {SERVICE, SETTLEMENT, LOADER, GUARD, SETTINGS, CLI}}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                   capture_output=True, text=True).stdout

    print("=" * 76)
    print(f"Red-green audit, slice D -- HEAD {head}")
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
            assert mutated.count(before) == 1, \
                f"{label}: anchor not unique in {path.name}: {before[:60]!r}"
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
    leftover = subprocess.run(["git", "grep", "-l", "MUTANT D", "--", "APITool/"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
    code, _, summary = run_tests(FULL)
    print("\n" + "-" * 76)
    print(f"  restored: status unchanged={status_after == status_before}, "
          f"leftover markers={'none' if not leftover else leftover}, full suite: {summary}")
    print("=" * 76)
    return problems + (0 if status_after == status_before and not leftover and code == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
