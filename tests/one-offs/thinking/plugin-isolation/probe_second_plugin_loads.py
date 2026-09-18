"""
Does a second plugin load, and does a broken one stay out of the way?

Check C5 of the migration's stop condition. Before v0.7.2 the answer to the
first question was structurally NO: the plugin was chosen by a hardcoded
import in `cli.py`, so a directory called `plugins/mysheet/` was a directory
nothing would ever read. This plants two plugins in a temporary user
directory -- one that imports cleanly, one whose `__init__` raises -- and asks
the loader about both.

WHAT A CORRECT RESULT LOOKS LIKE:

    scan       finds both, and imports NEITHER (sys.modules is untouched)
    load       the good one is LOADED; the bad one is BROKEN with its reason
    --version  still runs, with both plugins enabled in configuration

The third line is the one that matters most. A broken plugin that takes the
tool down with it is the failure two-phase discovery exists to prevent, and
`--version` is chosen because it has nothing to do with any plugin.

SAFETY (rule 1b): the configuration file is a temp file, patched in via
`settings.CONFIG_FILE`; the plugin directory is a temp directory, passed via
`ED_PLUGIN_DIR`. Nothing under $HOME is read or written. Exit code = failures.

Run:  python tests/one-offs/thinking/plugin-isolation/probe_second_plugin_loads.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

GOOD = "probe_good"
BAD = "probe_bad"

GOOD_INIT = '''
"""A plugin that imports cleanly and offers the one thing the loader asks for."""


class _Layout:
    totals_tab = "Probe Tab"


def layout(**overrides):
    return _Layout()
'''

BAD_INIT = '''
"""A plugin whose import fails, as a real one would with a typo or a missing dependency."""
raise RuntimeError("planted: this plugin does not import")
'''


def plant(user_dir: Path) -> None:
    (user_dir / GOOD).mkdir()
    (user_dir / GOOD / "__init__.py").write_text(GOOD_INIT, encoding="utf-8")
    (user_dir / BAD).mkdir()
    (user_dir / BAD / "__init__.py").write_text(BAD_INIT, encoding="utf-8")


def main() -> int:
    from APITool import loader, settings

    rows: list[tuple[str, bool, str]] = []
    tmp = Path(tempfile.mkdtemp(prefix="edapi-plugin-probe-"))
    try:
        user_dir = tmp / "plugins"
        user_dir.mkdir()
        plant(user_dir)

        # --- scan: finds both, imports neither -------------------------------
        before = set(sys.modules)
        found = loader.scan(loader.SHIPPED_DIR, user_dir)
        after = set(sys.modules)
        names = {f.name for f in found}
        rows.append(("scan finds both planted plugins",
                     {GOOD, BAD} <= names, f"found={sorted(names)}"))
        imported = sorted(m for m in after - before
                          if m.startswith(loader.USER_PACKAGE) or m.startswith("APITool.plugins."))
        rows.append(("scan imports nothing", not imported,
                     f"new plugin modules after scan: {imported or 'none'}"))

        # --- load: good is LOADED, bad is BROKEN with its reason ---------------
        result = loader.load(found, [GOOD, BAD])
        loaded = [e.name for e in result.loaded]
        broken = {e.name: e.reason for e in result.broken}
        rows.append((f"{GOOD} is LOADED", loaded == [GOOD], f"loaded={loaded}"))
        rows.append((f"{BAD} is BROKEN, with the reason",
                     BAD in broken and "planted" in broken[BAD],
                     f"broken={broken}"))
        rows.append(("the loaded plugin answers layout()",
                     result.first() is not None
                     and result.first().module.layout().totals_tab == "Probe Tab",
                     "layout().totals_tab read back"))

        # --- the tool still runs with BOTH enabled in configuration -----------
        cfg = tmp / "config.json"
        cfg.write_text(json.dumps({"targets": {
            "good": {"kind": "gsheet", "plugin": GOOD},
            "bad": {"kind": "gsheet", "plugin": BAD},
        }}), encoding="utf-8")
        real_cfg = settings.CONFIG_FILE
        settings.CONFIG_FILE = cfg
        os.environ["ED_PLUGIN_DIR"] = str(user_dir)
        try:
            from APITool.cli import main as cli_main

            sink = io.StringIO()
            try:
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    code = cli_main(["--version"])
            except SystemExit as exc:
                code = exc.code
            ran = code in (0, None)
            rows.append(("edapitool --version runs with a broken plugin enabled",
                         ran, f"exit={code}; printed {sink.getvalue().strip()[:40]!r}"))

            via_config = loader.discover()
            rows.append(("discover() enables exactly what targets name, in order",
                         [e.name for e in via_config.loaded] == [GOOD]
                         and [e.name for e in via_config.broken] == [BAD],
                         "; ".join(via_config.describe())))
        finally:
            settings.CONFIG_FILE = real_cfg
            os.environ.pop("ED_PLUGIN_DIR", None)
    finally:
        for p in sorted(tmp.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        tmp.rmdir()

    print("=" * 76)
    print("A second plugin loads; a broken one is listed, not fatal")
    print("=" * 76)
    failures = 0
    for claim, ok, detail in rows:
        mark = "ok  " if ok else "FAIL"
        failures += 0 if ok else 1
        print(f"  {mark}  {claim}")
        print(f"        {detail}")
    print("-" * 76)
    if failures:
        print(f"  {failures} of {len(rows)} checks FAILED. Check C5 is NOT met.")
    else:
        print(f"  {len(rows)}/{len(rows)} checks held. LOADED / BROKEN: listed. Check C5 is met.")
    print("=" * 76)
    return failures


if __name__ == "__main__":
    sys.exit(main())
