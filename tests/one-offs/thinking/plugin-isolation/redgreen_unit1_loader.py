"""
Red-green audit for slice A, unit 1: the plugin loader.

Six behaviour reverts, one at a time. Each keeps every signature intact --
the tests must fail on their ASSERTIONS, never on TypeError -- runs the two
test files that cover the loader, and restores the source byte-identical
before the next. The finding is the split: which tests went red under the
mutant meant for them (anchors), which stayed green (guards).

SAFETY (rule 1b): every mutant is applied to a copy held in memory and
written back over the original only for the duration of one pytest run;
the original bytes are restored and verified after each. The tests plant
plugins in tmp_path only. Nothing under $HOME is touched. A leftover
`MUTANT` marker anywhere under APITool/ is a failed audit.

Run:  python tests/one-offs/thinking/plugin-isolation/redgreen_unit1_loader.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LOADER = ROOT / "APITool" / "loader.py"
SETTINGS = ROOT / "APITool" / "settings.py"
CLI = ROOT / "APITool" / "cli.py"
TESTS = ["tests/test_plugin_loader.py", "tests/test_destination_seam.py"]

# (id, file, original substring, mutant substring, tests expected red)
MUTANTS = [
    ("M1 load() swallows the failure silently", LOADER,
     '        except Exception as exc:  # noqa: BLE001 -- isolation is the point\n'
     '            result.broken.append(Broken(name, f"{type(exc).__name__}: {exc}", entry))\n'
     '            continue\n',
     '        except Exception as exc:  # noqa: BLE001 -- isolation is the point\n'
     '            continue  # MUTANT M1\n',
     ["test_a_broken_plugin_is_listed_with_its_reason_and_stops_nothing"]),
    ("M2 scan() imports what it finds", LOADER,
     '    return list(by_name.values())\n',
     '    for f in by_name.values():  # MUTANT M2\n'
     '        try:\n'
     '            (_import_user if f.origin == ORIGIN_USER else _import_shipped)(f)\n'
     '        except Exception:\n'
     '            pass\n'
     '    return list(by_name.values())\n',
     ["test_scan_imports_nothing"]),
    ("M3 no targets enables nothing", LOADER,
     '    return [f.name for f in found if f.origin == ORIGIN_SHIPPED]\n',
     '    return []  # MUTANT M3\n',
     ["test_no_targets_means_the_shipped_plugins",
      "test_discover_with_no_config_loads_the_shipped_plugin"]),
    ("M4 _Defaults reads a bare attribute", CLI,
     '        return getattr(self._layout, name, None)\n',
     '        return getattr(self._layout, name)  # MUTANT M4\n',
     ["test_a_plugin_without_this_workbooks_flags_still_lets_the_parser_build"]),
    ("M5 get_targets() skips a malformed entry", SETTINGS,
     '        if not isinstance(kind, str) or not kind:\n'
     '            raise ValueError(f\'{where} has no "kind"\')\n'
     '        if not isinstance(plugin, str) or not plugin:\n'
     '            raise ValueError(f\'{where} has no "plugin"\')\n',
     '        if not isinstance(kind, str) or not kind:\n'
     '            continue  # MUTANT M5\n'
     '        if not isinstance(plugin, str) or not plugin:\n'
     '            continue  # MUTANT M5\n',
     ["test_a_malformed_target_names_itself"]),
    ("M6 scan() forgets what a user plugin shadows", LOADER,
     '            shadows=hidden.location if hidden is not None else None,\n',
     '            shadows=None,  # MUTANT M6\n',
     ["test_a_user_plugin_shadows_a_shipped_one_and_says_so"]),
    # Added after the v0.7.2 tester sweep found layout() called outside the
    # guard: these two put that defect back, in both places it was fixed.
    ("M7 _destination_defaults calls layout() outside the guard", CLI,
     '        destination = discover().first()\n'
     '        if destination is None:\n'
     '            return _Defaults()\n'
     '        # Inside the guard, not after it: a plugin can import cleanly and\n'
     '        # still raise when asked for its layout, and the tester sweep for\n'
     '        # v0.7.2 found that case taking `--version` down with a traceback.\n'
     '        return _Defaults(destination.module.layout())\n'
     '    except Exception:  # noqa: BLE001 -- the command reports it; --help must not\n'
     '        return _Defaults()\n',
     '        destination = discover().first()\n'
     '    except Exception:  # noqa: BLE001 -- the command reports it; --help must not\n'
     '        return _Defaults()\n'
     '    if destination is None:  # MUTANT M7\n'
     '        return _Defaults()\n'
     '    return _Defaults(destination.module.layout())\n',
     ["test_a_plugin_whose_layout_raises_does_not_take_down_version"]),
    ("M8 _plugin_layout lets the plugin's exception through", CLI,
     '    try:\n'
     '        return destination.module.layout(**overrides), None\n'
     '    except Exception as exc:  # noqa: BLE001 -- reporting, not handling\n'
     '        return None, (f"Error: plugin {destination.name!r} could not build its "\n'
     '                      f"layout: {type(exc).__name__}: {exc}")\n',
     '    return destination.module.layout(**overrides), None  # MUTANT M8\n',
     ["test_a_plugin_whose_layout_raises_is_reported_by_name"]),
]


def run_tests() -> tuple[int, set[str], str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTS, "-q", "-p", "no:cacheprovider", "-rf"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    failed = set()
    for line in proc.stdout.splitlines():
        if line.startswith("FAILED "):
            # FAILED tests/x.py::test_name[param] - reason
            name = line.split("::", 1)[1].split(" ", 1)[0].split("[", 1)[0]
            failed.add(name)
    summary = [ln for ln in proc.stdout.splitlines() if "passed" in ln or "failed" in ln]
    return proc.returncode, failed, (summary[-1] if summary else proc.stdout[-200:])


def main() -> int:
    originals = {p: p.read_bytes() for p in {LOADER, SETTINGS, CLI}}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                   capture_output=True, text=True).stdout

    print("=" * 76)
    print(f"Red-green audit, slice A unit 1 -- HEAD {head}")
    print("=" * 76)
    code, failed, summary = run_tests()
    print(f"  baseline: {summary}")
    if code != 0:
        print("  baseline is not green; nothing below is interpretable")
        return 1

    problems = 0
    for label, path, before, after, expect_red in MUTANTS:
        text = originals[path].decode("utf-8")
        # cli.py is CRLF on this checkout; the anchors above are written LF.
        # Match in the file's own convention, or the anchor is never found.
        nl = "\r\n" if "\r\n" in text else "\n"
        before, after = before.replace("\n", nl), after.replace("\n", nl)
        assert text.count(before) == 1, f"{label}: anchor text not unique in {path.name}"
        try:
            path.write_bytes(text.replace(before, after).encode("utf-8"))
            _, failed, summary = run_tests()
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

    # --- restoration proof ------------------------------------------------
    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                  capture_output=True, text=True).stdout
    leftover = subprocess.run(["git", "grep", "-l", "MUTANT M", "--", "APITool/"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
    code, _, summary = run_tests()
    print("\n" + "-" * 76)
    print(f"  restored: status unchanged={status_after == status_before}, "
          f"leftover markers={'none' if not leftover else leftover}, final: {summary}")
    print("=" * 76)
    return problems + (0 if status_after == status_before and not leftover and code == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
