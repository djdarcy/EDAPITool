"""
Red-green audit for slice E: #25's skip, the derived allow list, the
narrowed declaration, and the grouped help output.

Twenty-two behaviour reverts across four units. Each puts back one piece of
the pre-slice code while every signature stays exactly where it was, so a
test that goes red goes red on its assertion and not on a TypeError -- the
distinction that makes this audit mean anything. (Named for unit 1, which it
started as; units 2 and 3 were added rather than given files of their own,
because they share a floor and one restore-verify.)

E1-E4 revert the skip itself: the whole block written wholesale as before
(E1); the occupancy read asking for rendered values instead of formulas (E2),
which is the subtle half of the defect, because a settlement formula renders
as "" when the commodity is not sold at the current station; the skipped
cells never recorded on the plan (E3); a failed read read as "the column is
empty" rather than "hands off" (E4).

E5-E7 revert the plumbing that carries --force from the command line to the
plan: the CLI not passing it (E5), the plugin not passing it (E6), the
service dropping it between the two (E7).

E8-E9 revert the reporting: the skip report never printed on the dry run
(E8) or on the real write (E9). A silent skip looks exactly like a write that
worked, which is the same shape of invisibility that let #25 sit unnoticed.

E10-E12 revert the three quieter properties: free cells written one API range
per cell rather than per contiguous run (E10), the occupancy read no longer
bounded by the block being written (E11), and a cell the plan says it left
alone being coloured anyway (E12).

E13-E14 and E17 revert unit 2's derivation: the allow list as a literal
again (E13), a builder's declaration never recorded (E14), and the eager
import dropped so the answer depends on what happened to be imported (E17).
E18 makes an explicit "permit nothing" fall back to permitting everything.

E15-E16 revert unit 3: the declaration widened back to one range spanning
the TOTAL row (E15), and the header cell dropped from it (E16).

E19-E22 revert unit 5, the grouping: market's write flags back in the flat
options block (E19), `--force` no longer saying the write cannot be undone
(E20), `--force` filed with the glyph flags instead of the write flags
(E21), and serve no longer separating cells the tool does not own (E22).
E20 is the one that matters most -- a person reading the v0.7.6 checklist
reported the warning's text as adequate and its PLACEMENT as the problem,
and nothing in the suite asserted either until this unit.

SAFETY (rule 1b): every revert here makes the writer MORE willing to write,
so the tests that assert a refusal must be structurally unable to perform
one. They are: every worksheet in `tests/test_marker_skip_occupied.py` is a
fake that appends to a list, has no network and no file access, and the CLI
tests monkeypatch `GoogleSheetsExporter` before `main()` can construct a real
one. No revert here touches a delete, a path outside the repository, or a
process that does not return.

Run:  python tests/one-offs/thinking/plugin-isolation/redgreen_slicee_unit1_skip.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
WRITER = ROOT / "APITool" / "sheets" / "writer.py"
SERVICE = ROOT / "APITool" / "service.py"
SETTLEMENT = ROOT / "APITool" / "plugins" / "settlement" / "__init__.py"
CLI = ROOT / "APITool" / "cli.py"
GENERATED = ROOT / "APITool" / "generated.py"
LAYOUT = ROOT / "APITool" / "plugins" / "settlement" / "layout.py"
EXPORTER = ROOT / "APITool" / "google" / "exporter.py"

# One invocation per file: a -k naming tests in two files selects from one.
TESTS = [["tests/test_marker_skip_occupied.py"], ["tests/test_sheets.py"],
         ["tests/test_supplier_registry.py"], ["tests/test_generated_tabs.py"],
         ["tests/test_help_output.py"]]
FULL = [["tests/"]]

MUTANTS = [
    ("E1 the whole marker block is written wholesale again", WRITER,
     [("                for start, run in _free_runs(column, first, occupied):",
       "                for start, run in [(first, column)]:  # MUTANT E1")],
     ["test_a_cell_holding_a_formula_is_not_written",
      "test_a_cell_holding_a_literal_is_not_written_either",
      "test_only_the_free_cells_are_written",
      "test_the_free_runs_are_written_as_ranges_not_one_call_per_cell",
      "test_the_cli_leaves_a_planted_formula_alone"]),

    ("E2 the occupancy read asks for rendered values, not formulas", WRITER,
     [('                range_name, value_render_option="FORMULA"',
       "                range_name  # MUTANT E2")],
     ["test_the_occupancy_read_asks_for_formulas_not_values"]),

    ("E3 the skipped cells are computed but never recorded on the plan", WRITER,
     [("                plan.skipped.extend(",
       "                [].extend(  # MUTANT E3")],
     ["test_a_cell_holding_a_formula_is_not_written",
      "test_a_cell_holding_a_literal_is_not_written_either",
      "test_the_cli_says_which_cells_it_left_alone"]),

    ("E4 an unreadable column is read as empty rather than as hands-off", WRITER,
     [("            return set(range(first_row, first_row + count))",
       "            return set()  # MUTANT E4")],
     ["test_an_unreadable_column_is_treated_as_occupied"]),

    ("E5 the CLI stops passing --force to the refresh", CLI,
     [("            force=args.force,\n", "            force=False,  # MUTANT E5\n")],
     ["test_force_through_the_cli_writes_the_whole_block"]),

    ("E6 the plugin stops passing force to the plan", SETTLEMENT,
     [('        force=options.get("force", False),',
       "        force=False,  # MUTANT E6")],
     ["test_force_through_the_cli_writes_the_whole_block"]),

    ("E7 the service drops force between the CLI and the plugin", SERVICE,
     [("            force=force,\n", "            force=False,  # MUTANT E7\n")],
     ["test_force_through_the_cli_writes_the_whole_block"]),

    ("E8 the dry run stops saying what it left alone", CLI,
     [("            print(f\"  marked rows: {result.plan.marked_rows or '(none)'}\")\n"
       "            _report_skipped(result.plan, layout)\n",
       "            print(f\"  marked rows: {result.plan.marked_rows or '(none)'}\")\n"
       "            # MUTANT E8\n")],
     ["test_the_cli_says_which_cells_it_left_alone"]),

    ("E9 the real write stops saying what it left alone", CLI,
     [("            print(f\"Marked rows: {result.plan.marked_rows or '(none)'}\")\n"
       "            _report_skipped(result.plan, layout)\n",
       "            print(f\"Marked rows: {result.plan.marked_rows or '(none)'}\")\n"
       "            # MUTANT E9\n")],
     ["test_a_real_write_also_says_what_it_left_alone"]),

    ("E10 free cells are written one range per cell, not per run", WRITER,
     [("        if start is None:\n            start, values = row, []\n"
       "        values.append(cell)",
       "        runs.append((row, [cell]))  # MUTANT E10\n"
       "        start, values = None, []")],
     ["test_an_all_empty_column_is_written_as_one_range",
      "test_the_free_runs_are_written_as_ranges_not_one_call_per_cell",
      "test_a_clean_sheet_is_unchanged_by_the_new_check"]),

    ("E11 the occupancy read is no longer bounded by the block", WRITER,
     [("        for offset, row in enumerate(rows[:count]):",
       "        for offset, row in enumerate(rows):  # MUTANT E11")],
     ["test_the_occupancy_read_is_bounded_by_the_block_being_written"]),

    ("E12 a skipped cell is coloured anyway", WRITER,
     [("                if plan.skipped:\n                    left_alone = set(plan.skipped)",
       "                if False:  # MUTANT E12\n                    left_alone = set(plan.skipped)")],
     ["test_a_skipped_cell_is_not_coloured_either"]),

    # -- unit 2: WRITABLE_TABS derived, not enumerated -----------------------

    ("E13 the allow list goes back to being a literal", GENERATED,
     [("    return frozenset(_BUILDERS.values())\n\n\ndef builders",
       "    return frozenset(  # MUTANT E13\n"
       "        {\"FreighterData\", \"MarketData\", \"ShipCargo\"})\n\n\ndef builders")],
     ["test_adding_a_generated_tab_grows_the_set_without_editing_the_exporter",
      "test_the_class_and_an_instance_cannot_disagree"]),

    ("E14 a builder's declaration is never recorded", GENERATED,
     [("        _BUILDERS[f\"{builder.__module__}.{builder.__qualname__}\"] = tab",
       "        pass  # MUTANT E14")],
     ["test_the_three_tabs_this_tool_generates_are_all_writable",
      "test_each_writable_tab_is_claimed_by_a_named_builder",
      "test_adding_a_generated_tab_grows_the_set_without_editing_the_exporter"]),

    # -- unit 3: the declaration narrowed ------------------------------------

    ("E15 the declaration goes back to one range spanning the TOTAL row", LAYOUT,
     [("                self.marker_header_cell(),",
       "                f\"{self.marker_column}{self.header_row}:\"  # MUTANT E15\n"
       "                f\"{self.marker_column}\",")],
     ["test_ac2_writes_outside_the_allowlist_are_refused"]),

    ("E16 the header cell drops out of the declaration", LAYOUT,
     [("                self.marker_header_cell(),\n", "")],
     ["test_ac2_permitted_writes_are_allowed"]),

    ("E17 the allow list goes back to being import-order dependent", GENERATED,
     [("    for module in _GRID_MODULES:\n        importlib.import_module(module, __package__)\n",
       "    pass  # MUTANT E17\n")],
     ["test_the_set_is_complete_in_an_interpreter_that_imported_nothing_else",
      "test_the_allow_list_is_complete_for_a_caller_that_imported_only_the_exporter",
      "test_the_builder_map_is_complete_in_a_fresh_interpreter_too"]),

    ("E18 permitting nothing falls back to permitting everything", EXPORTER,
     [("            frozenset(writable_tabs) if writable_tabs is not None else self.WRITABLE_TABS",
       "            frozenset(writable_tabs) if writable_tabs else self.WRITABLE_TABS  # E18")],
     ["test_permitting_nothing_is_honoured_rather_than_falling_back"]),

    # -- unit 5: the help output grouped ------------------------------------

    ("E19 market's write flags fall back into the flat options block", CLI,
     [('    _writing = market_parser.add_argument_group(\n'
       '        "writing to it",\n'
       '        "Nothing here happens unless you ask for it.",\n'
       '    )',
       "    _writing = market_parser  # MUTANT E19")],
     ["test_the_market_help_is_grouped",
      "test_force_sits_with_the_other_writing_flags"]),

    ("E20 --force stops saying the write cannot be undone", CLI,
     [('             "There is no undo.",', '             "",  # MUTANT E20')],
     ["test_force_says_there_is_no_undo"]),

    ("E21 --force is filed with the glyph flags instead of the write flags", CLI,
     [('    _writing.add_argument(\n        "--force",',
       '    _glyphs.add_argument(  # MUTANT E21\n        "--force",')],
     ["test_force_sits_with_the_other_writing_flags"]),

    ("E22 serve stops separating cells the tool does not own", CLI,
     [('    _theirs = serve_parser.add_argument_group(\n'
       '        "writing to cells the tool does not own",\n'
       '        "Off unless asked. These may be cells you have put formulas in.",\n'
       '    )',
       "    _theirs = serve_parser  # MUTANT E22")],
     ["test_the_serve_help_separates_cells_the_tool_does_not_own"]),
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
    originals = {
        p: p.read_bytes()
        for p in {WRITER, SERVICE, SETTLEMENT, CLI, GENERATED, LAYOUT, EXPORTER}
    }
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                   capture_output=True, text=True).stdout

    print("=" * 76)
    print(f"Red-green audit, slice E unit 1 (#25) -- HEAD {head}")
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
    leftover = subprocess.run(["git", "grep", "-l", "MUTANT E", "--", "APITool/"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
    code, _, summary = run_tests(FULL)
    print("\n" + "-" * 76)
    print(f"  restored: status unchanged={status_after == status_before}, "
          f"leftover markers={'none' if not leftover else leftover}, full suite: {summary}")
    print("=" * 76)
    return problems + (0 if status_after == status_before and not leftover and code == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
