"""
The suite does not read the machine it runs on.

Until this file existed, isolation was per-test and opt-in: a handful of
tests called `monkeypatch.delenv("ED_CONFIG_DIR")` or pointed it at a
scratch directory, and every other test in the suite read
`~/edapitool/config.json` — the developer's own, with their own plugins
enabled and their own spreadsheet named.

That is not a small tidiness problem. It means a green suite says
"passes on this machine" while reading as "passes". Measured on
2026-09-21: 836 passed with the maintainer's config present and 11 failed
without it, and CI had been unable to see the difference because the two
releases that introduced the breakage were committed but never pushed.
Six of those failures had been latent since v0.7.5.

So isolation is now the default and opting OUT is the deliberate act. A
test that wants a configuration builds one in its own `tmp_path` and
points `ED_CONFIG_DIR` at it; a test that wants none gets none, which is
what a fresh install looks like and therefore what most tests should be
asserting against.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_config(tmp_path_factory, monkeypatch):
    """
    Point every test at an empty configuration directory of its own.

    Autouse, so it applies without being asked for -- the failure mode
    this prevents is precisely a test that did not think to ask.

    The directory comes from `tmp_path_factory` rather than `tmp_path`
    ON PURPOSE. Putting it inside the test's own `tmp_path` made this
    fixture visible to the tests: one of them asserts that `tmp_path` is
    empty after a run that should write nothing, and a config directory
    sitting there is an export it never made. An isolation fixture that
    changes what a test observes is not isolation.

    A test needing real configuration overrides this by setting
    `ED_CONFIG_DIR` itself; monkeypatch applies the later value and
    unwinds both at teardown.
    """
    config_dir = tmp_path_factory.mktemp("edapitool-config")
    monkeypatch.setenv("ED_CONFIG_DIR", str(config_dir))

    # The environment variable alone is not enough, and the reason is the
    # whole of why this suite was not hermetic:
    #
    #     APITool/settings.py:92   CONFIG_FILE = config_path()
    #
    # That is evaluated at IMPORT time, once. pytest imports every test
    # module during collection, before a single fixture runs, so by the
    # time any `monkeypatch.setenv` executes the path is already frozen to
    # whatever the developer's environment said. Setting the variable and
    # walking away would look like isolation and provide none.
    #
    # So the module attribute is patched too. The variable is still set,
    # because subprocesses read it and a child interpreter has its own
    # import.
    from APITool import settings

    monkeypatch.setattr(settings, "CONFIG_FILE", config_dir / settings.CONFIG_JSON)

    # The tool writes a stock config on a first run (#30), and every test
    # here IS a first run. Without this guard each CLI test would leave a
    # file it never asked for. A test of the first-run write lifts it with
    # `monkeypatch.delenv("ED_NO_STOCK_CONFIG")`.
    monkeypatch.setenv("ED_NO_STOCK_CONFIG", "1")

    # The older single-file variables, for any path still consulting them.
    # Absent rather than empty: a test must not be able to pick up a real
    # one from the environment CI or a developer shell happens to carry.
    for stale in ("ED_SHEET_ID", "ED_CAPI_CONFIG", "ED_CAPI_TOKENS"):
        monkeypatch.delenv(stale, raising=False)


@pytest.fixture
def configured_totals(monkeypatch):
    """
    A configured `totals` target, written into the isolated config.

    Its config block pins ``totals_tab`` to ``Totals Tab``: the suite's grids,
    the fixture golden and the marker formulas all name that tab, and from
    v0.8.0 the plugin's own default is ``Totals``. Pinning it here is what
    keeps every pre-0.8.0 assertion byte-identical while the default moved.

    Request this when a test's scenario PRESUPPOSES a destination -- every
    `--update-sheet` path, and the comparison tests whose subject is "no
    sheet id" rather than "no plugin". Without it a fresh install resolves
    no destination at all, and the command under test refuses before
    reaching the behaviour the test is about; the assertion then fails on
    a different sentence and says nothing about what it was written for.

    The sheet id is deliberately a placeholder that cannot be opened. No
    test in this suite may reach a real spreadsheet, and a test that
    somehow tried would fail on the id rather than succeed against
    somebody's workbook.
    """
    import json

    from APITool import settings

    settings.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.CONFIG_FILE.write_text(json.dumps({
        "targets": {
            "test-workbook": {
                "kind": "gsheet",
                "plugin": "totals",
                "id": "FAKE_SHEET_ID_NEVER_CONTACTED",
                "config": {"totals_tab": "Totals Tab"},
            }
        }
    }), encoding="utf-8")
    return settings.CONFIG_FILE


@pytest.fixture
def configured_construction(monkeypatch):
    """
    A configured `construction` target beside whatever else is configured.

    Merged into the existing file rather than replacing it, so a test may
    request this with ``configured_totals`` and get both plugins on the
    one fake workbook -- the v0.8.0 shape of the stock configuration.
    """
    import json

    from APITool import settings

    settings.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"targets": {}}
    if settings.CONFIG_FILE.exists():
        data = settings.load() or data
    data.setdefault("targets", {})["test-construction"] = {
        "kind": "gsheet",
        "plugin": "construction",
        "id": "FAKE_SHEET_ID_NEVER_CONTACTED",
        "config": {},
    }
    settings.CONFIG_FILE.write_text(json.dumps(data), encoding="utf-8")
    return settings.CONFIG_FILE
