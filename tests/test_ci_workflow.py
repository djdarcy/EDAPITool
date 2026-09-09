"""
The CI workflow is configuration, and configuration regresses silently.

Until 2026-09-09 this repository's only code check carried
``continue-on-error: true``, so every green checkmark attested that the package
imported and built -- nothing more. 369 tests and a 70-mutant audit ran only
when a human remembered. Nobody noticed for seven releases, because a gate that
cannot fail looks exactly like a gate that passes.

These tests assert the shape of that gate. They are cheap, and they fail loudly
if someone re-adds the escape hatch or drops the extra that keeps the write
allowlist tests from skipping themselves.

Refs #14.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="pyyaml is declared in the dev extra; install with pip install -e .[dev]",
)

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "main.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.exists(), f"CI workflow missing at {WORKFLOW}"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps(workflow: dict, job: str) -> list[dict]:
    assert job in workflow["jobs"], f"no {job!r} job in the CI workflow"
    return workflow["jobs"][job]["steps"]


def _run_text(workflow: dict, job: str) -> str:
    """Every shell command the job runs, concatenated."""
    return "\n".join(step.get("run", "") for step in _steps(workflow, job))


# --------------------------------------------------------------------------
# The gate must be able to fail
# --------------------------------------------------------------------------

def test_no_step_in_any_job_can_swallow_its_own_failure(workflow):
    """
    ``continue-on-error`` on a check step is a gate that cannot gate.

    This is the specific defect #14 was filed against, generalised to every
    job: no step anywhere may opt out of failing the build.
    """
    offenders = [
        (job_name, step.get("name", "<unnamed>"))
        for job_name, job in workflow["jobs"].items()
        for step in job.get("steps", [])
        if step.get("continue-on-error")
    ]
    assert not offenders, (
        "these steps cannot fail the build, so they gate nothing: " f"{offenders}"
    )


def test_no_job_can_swallow_its_own_failure(workflow):
    """The same escape hatch exists at job level. Neither is acceptable."""
    offenders = [
        name for name, job in workflow["jobs"].items() if job.get("continue-on-error")
    ]
    assert not offenders, f"these jobs cannot fail the build: {offenders}"


# --------------------------------------------------------------------------
# The suite must actually run
# --------------------------------------------------------------------------

def test_a_test_job_exists_and_runs_pytest(workflow):
    assert "pytest" in _run_text(workflow, "test"), (
        "the test job does not invoke pytest -- CI would attest only that the "
        "package imports and builds, which is the state #14 was filed against"
    )


def test_the_test_job_installs_an_extra_that_provides_gspread(workflow):
    """
    ``tests/test_gsheet_guard.py`` carries a module-level skipif on
    GSPREAD_AVAILABLE. Installed bare, CI silently runs 15 fewer tests -- the
    ones covering the deny-by-default write allowlist, which is what stands
    between the tool and an irreversible overwrite of hand-entered tabs -- and
    still reports green.

    So the install must pull an extra that includes gspread. Both ``[gsheets]``
    and ``[all]`` qualify; ``pip install -e .`` alone does not.
    """
    run = _run_text(workflow, "test")
    assert "[all]" in run or "[gsheets]" in run, (
        "the test job installs no gspread-providing extra, so the write-guard "
        f"tests would skip themselves in CI. Install commands were:\n{run}"
    )


def test_the_test_job_covers_every_supported_python(workflow):
    """The matrix should not quietly narrow to one interpreter."""
    matrix = workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert [str(v) for v in matrix] == ["3.10", "3.11", "3.12"]


def test_the_package_is_not_built_from_a_red_tree(workflow):
    """``build`` must wait for the tests, not only the linter."""
    needs = workflow["jobs"]["build"]["needs"]
    needs = [needs] if isinstance(needs, str) else needs
    assert "test" in needs, (
        "build does not depend on test, so a package can be built and checked "
        f"from a tree with failing tests. needs = {needs}"
    )


# --------------------------------------------------------------------------
# The recorded decision (criterion 6 of #14)
# --------------------------------------------------------------------------

def test_the_mutation_audit_decision_is_recorded_in_the_workflow(workflow):
    """
    #14 asks for a decision on whether the mutation audit runs in CI, and
    where. The decision is "no", and the reasoning lives as a comment beside
    the test job -- which is where someone wondering "why isn't this here?"
    will look. Comments do not survive YAML parsing, so this reads the raw text.
    """
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "mutate.py" in raw and "pre-release checklist" in raw, (
        "the workflow no longer records why the mutation audit is absent from "
        "CI; without it the next reader re-opens a settled question"
    )
