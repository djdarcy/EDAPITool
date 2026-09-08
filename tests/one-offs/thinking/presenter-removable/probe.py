"""
Issue #7, acceptance criterion 4: "The opinionated presenter is separable --
removing it leaves a working generic tool."

The layering test proves ``sheets`` does not import ``markers``. That is a
weaker claim than this criterion, which is about the TOOL still working when
the presenter is gone -- so this probe actually removes it and tries the
generic paths.

Run: python tests/one-offs/thinking/presenter-removable/probe.py
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

# Block APITool.markers at import time, then try each generic entry point.
PROBE = r"""
import sys

# Python 3.12 removed find_module/load_module; only find_spec is consulted.
class Blocked:
    def find_spec(self, name, path=None, target=None):
        if name == "APITool.markers":
            raise ImportError("APITool.markers has been removed (probe)")
        return None

sys.meta_path.insert(0, Blocked())

results = []

# CONTROL ARM: the block must actually block. If this says OK, the instrument
# is broken and every result below is meaningless -- which is exactly what
# happened on the first run of this probe, where the deprecated find_module
# protocol was silently never called.
try:
    import APITool.markers
    results.append(("CONTROL: markers is blocked", "FAIL: it imported anyway"))
except ImportError:
    results.append(("CONTROL: markers is blocked", "OK"))

# 1. The core comparison stack -- must not need the presenter at all.
try:
    import APITool.matcher, APITool.market, APITool.catalog, APITool.journal
    results.append(("core modules import", "OK"))
except Exception as exc:
    results.append(("core modules import", f"FAIL: {exc}"))

# 2. The generic sheet mechanics.
try:
    import APITool.sheets
    results.append(("sheets (generic mechanics) imports", "OK"))
except Exception as exc:
    results.append(("sheets (generic mechanics) imports", f"FAIL: {exc}"))

# 3. The data-emitting surface: CSV / JSON rows and the generated-tab grid.
try:
    from APITool.market import flat_rows, sheet_grid, Market, MarketItem
    m = Market(1, "S", "Sys", None, "journal",
               (MarketItem(1, "X", "Biowaste", stock=5, buy_price=7),))
    assert flat_rows(m) and sheet_grid(m)
    results.append(("flat_rows / sheet_grid produce data", "OK"))
except Exception as exc:
    results.append(("flat_rows / sheet_grid produce data", f"FAIL: {exc}"))

# 4. The application service -- what the CLI and the future HTTP API call.
try:
    import APITool.service
    results.append(("service imports", "OK"))
except Exception as exc:
    results.append(("service imports", f"FAIL: {exc}"))

# 5. The CLI itself, which is how a user reaches any generic path.
try:
    import APITool.cli
    results.append(("cli imports", "OK"))
except Exception as exc:
    results.append(("cli imports", f"FAIL: {exc}"))

for name, outcome in results:
    print(f"{outcome:<8} {name}")
print()
print("VERDICT:", "SEPARABLE" if all(o == "OK" for _, o in results) else "NOT SEPARABLE")
"""


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    print(proc.stdout)
    if proc.stderr.strip():
        print("stderr:", proc.stderr.strip()[:800])
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
