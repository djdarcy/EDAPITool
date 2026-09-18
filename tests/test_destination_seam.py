"""
Pulling the destination layer must break ONLY destination features.

Issue #18's third requirement is that isolation exists so removing the
destination layer later is one move, not an excavation. Nothing asserted it,
and on 2026-09-16 it was not true: a single module-scope import in
``service.py`` meant removing ``APITool/workbook/`` also took down ``serve``,
the daemon and the whole carrier path -- none of which is one workbook's code.

WHAT A CORRECT RESULT LOOKS LIKE. Not "everything still works". Two features
genuinely belong to one particular spreadsheet and SHOULD die when it is
removed, because a fork supplies its own:

    ``--show-formula``      generates a formula for THESE glyphs and THESE
                            thresholds; a different sheet wants a different one
    the ``market`` comparison
                            reads outstanding requirements from THIS
                            workbook's Totals Tab

So the property under test is not "nothing imports the destination layer".
That is false, and asserting it would forbid what ``cli.py`` correctly does --
``cli.py`` reaches the destination layer at function scope and survives its
removal precisely because of that. The property is that the blast radius is
confined to the destination.

WHY A BLOCKER RATHER THAN DELETING THE DIRECTORY. A test must not be ABLE to
do the thing it asserts is prevented. Renaming a package on disk during a run
leaves the tree mutated if the run is hard-killed, and recovery then depends
on the work having been committed first. An import hook is process-local and
dies with the interpreter. It is also more precise -- it fails exactly at
``import``, the edge under test -- and it runs in CI, which a rename does not.

WHY A CHILD INTERPRETER. The first version of this did the blocking in-process
and cleaned up in a fixture. It passed alone and broke ELEVEN tests in the
full suite, two ways at once: a sentinel class compared by identity across the
purge, and marker constants that another test configures at module scope being
reset underneath it. Cleanup discipline was not enough, and would not have
been enough after the next test was written either. Running the probe in a
child makes the isolation structural -- this process imports nothing and
unloads nothing, so there is no cleanup that can be skipped.

The same file is both the test and the probe: ``python tests/
test_destination_seam.py --json`` is what the child runs, so there is exactly
one implementation of the blocker and no copy to drift.

The runnable diagnostic that prints the whole table at once -- the faster read
when this goes red -- stays at
``tests/one-offs/thinking/plugin-isolation/poc_pull_the_plug.py``.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

BLOCKED = "APITool.plugins.settlement"
REPO_ROOT = Path(__file__).resolve().parents[1]

# (label, module, does it belong to one particular workbook?)
#
# The labels are load-bearing: they are what a failure reports, and
# "refresh service" says more at a glance than "APITool.service".
SURFACES = [
    # Core -- a general-purpose exporter. None of this is one workbook's.
    ("journal reader", "APITool.journal", False),
    ("market model", "APITool.market", False),
    ("ship loadout", "APITool.ship", False),
    ("commodity catalog", "APITool.catalog", False),
    ("CSV/JSON export", "APITool.export", False),
    ("CAPI client", "APITool.capi", False),
    # Toolkit -- generic spreadsheet mechanics, vendor-neutral.
    ("sheets toolkit", "APITool.sheets", False),
    ("google exporter", "APITool.google", False),
    # Orchestration -- drives the above. NOT destination-specific.
    ("plugin loader", "APITool.loader", False),
    ("refresh service", "APITool.service", False),
    ("daemon", "APITool.daemon", False),
    ("CLI", "APITool.cli", False),
    # Destination -- one workbook's conventions. SHOULD die.
    ("destination layer", "APITool.plugins.settlement", True),
]

# Commands that have NOTHING to do with any spreadsheet, and must therefore
# still run with no plugin installed at all -- #18's sixth criterion, "with
# none configured it publishes open formats only".
#
# Both are chosen to work anywhere: no journal, no credentials, no network, no
# game. They do exercise the whole argument parser, which is where a plugin
# import at the top of `main()` bites.
COMMANDS = [
    ("edapitool --version", ("--version",)),
    ("edapitool market --help", ("market", "--help")),
]

EVERY = [(label, mod) for label, mod, _ in SURFACES]
SURVIVORS = [(label, mod) for label, mod, dest in SURFACES if not dest]
DESTINATION = [(label, mod) for label, mod, dest in SURFACES if dest]


# ---------------------------------------------------------------------------
# The child: everything below __main__ runs in its own interpreter.
# ---------------------------------------------------------------------------


class PluginPulled:
    """Refuse to import the destination layer, as if it had been deleted."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == BLOCKED or fullname.startswith(BLOCKED + "."):
            raise ModuleNotFoundError(
                f"No module named {fullname!r} "
                "(the destination layer has been pulled)"
            )
        return None


def _purge() -> None:
    """Drop every APITool module so the next import genuinely re-runs."""
    for name in list(sys.modules):
        if name == "APITool" or name.startswith("APITool."):
            del sys.modules[name]


def _import_every_surface() -> dict[str, str | None]:
    """Import each surface; map module name to its error, or None."""
    outcome: dict[str, str | None] = {}
    for _, module, _dest in SURFACES:
        try:
            importlib.import_module(module)
            outcome[module] = None
        except Exception as exc:  # noqa: BLE001 -- reporting, not handling
            outcome[module] = f"{type(exc).__name__}: {exc}"
    return outcome


def _run_every_command() -> dict[str, str | None]:
    """
    Actually invoke each command; map its label to its error, or None.

    ``--help`` and ``--version`` exit through ``SystemExit`` by argparse's
    design, and a zero code is success rather than a failure to be reported.
    """
    outcome: dict[str, str | None] = {}
    from APITool.cli import main

    for label, argv in COMMANDS:
        # These commands PRINT -- that is what makes them a real test rather
        # than an import check -- and this process reports its findings as
        # JSON on stdout. Swallow theirs, or the caller parses a version
        # banner as a result object.
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                code = main(list(argv))
            outcome[label] = None if code in (0, None) else f"exit {code}"
        except SystemExit as exc:
            outcome[label] = None if exc.code in (0, None) else f"exit {exc.code}"
        except Exception as exc:  # noqa: BLE001 -- reporting, not handling
            outcome[label] = f"{type(exc).__name__}: {exc}"
    return outcome


def _probe() -> dict:
    """
    Three phases in one child process.

    The baseline phase matters: without it, a run where imports fail for some
    unrelated reason -- a syntax error, a missing dependency -- produces the
    same shape as success, because "it did not import" is exactly what the
    blocked phase expects of the destination layer.

    The third phase exists because the first two are not enough, which this
    test learned the hard way. They ask whether a module IMPORTS. v0.7.0 --
    the release whose whole purpose was this isolation -- put a plugin import
    at the top of ``main()`` so that ``--help`` could derive its defaults, and
    every one of these tests stayed green while ``edapitool --version`` could
    no longer run without the plugin present. Importable is not runnable, and
    only the second one is what a person experiences.

    Purging between the phases is safe here and nowhere else: this process
    exits immediately afterwards and nothing holds a reference across it.
    """
    sys.path.insert(0, str(REPO_ROOT))
    _purge()
    baseline = _import_every_surface()

    _purge()
    sys.meta_path.insert(0, PluginPulled())
    blocked = _import_every_surface()
    commands = _run_every_command()

    return {"baseline": baseline, "blocked": blocked, "commands": commands}


# ---------------------------------------------------------------------------
# The tests: these run in pytest's process and import nothing from APITool.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def verdict() -> dict:
    """Run the probe once, in a child, and hand back its two phases."""
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        pytest.fail(
            "the destination-seam probe did not run:\n"
            f"exit {proc.returncode}\nstdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}"
        )
    return json.loads(proc.stdout)


@pytest.mark.parametrize("label,module", EVERY)
def test_baseline_every_surface_imports_with_the_layer_present(
    verdict, label, module
):
    """Every surface imports cleanly BEFORE anything is blocked."""
    error = verdict["baseline"][module]
    assert error is None, (
        f"{label} ({module}) does not import even with the destination "
        f"layer present: {error}. Nothing below this is interpretable."
    )


@pytest.mark.parametrize("label,module", SURVIVORS)
def test_pulling_the_destination_layer_leaves_the_tool_working(
    verdict, label, module
):
    """
    Nothing outside the destination layer may die with it.

    A failure here names the surface that took collateral damage. The usual
    cause is a module-scope ``from .plugins.settlement...`` import somewhere -- move it
    to function scope, the way ``service.py``'s ``_totals_reader`` and
    ``cli.py``'s ``--show-formula`` path already do.
    """
    error = verdict["blocked"][module]
    assert error is None, (
        f"{label} ({module}) died with the destination layer: {error}. "
        "It is not one workbook's code and must survive its removal "
        "(issue #18, requirement 3)."
    )


@pytest.mark.parametrize("label,argv", COMMANDS)
def test_commands_unrelated_to_a_spreadsheet_still_RUN_without_a_plugin(
    verdict, label, argv
):
    """
    The property the import checks above cannot see.

    They ask whether a module loads. This asks whether a person can use the
    tool. v0.7.0 shipped with every import test green and ``edapitool
    --version`` unable to run with the plugin absent, because the plugin was
    imported at the top of ``main()`` to build argparse defaults.

    A failure here means core acquired a hard dependency on a destination
    somewhere on the startup path. Look for a plugin import that is not inside
    the function that needs it.
    """
    error = verdict["commands"][label]
    assert error is None, (
        f"`{label}` does not run with the destination layer absent: {error}. "
        "This command has nothing to do with any spreadsheet, so it must not "
        "require one (issue #18, criterion 6)."
    )


@pytest.mark.parametrize("label,module", DESTINATION)
def test_the_destination_layer_itself_is_what_was_pulled(
    verdict, label, module
):
    """
    The blocker is really in force.

    Without this the tests above could pass because nothing was ever blocked,
    which is the other way this file could be green for no reason.
    """
    error = verdict["blocked"][module]
    assert error is not None, (
        f"{label} ({module}) imported even though it was supposed to be "
        "blocked -- the probe proved nothing."
    )


if __name__ == "__main__":
    print(json.dumps(_probe()))
