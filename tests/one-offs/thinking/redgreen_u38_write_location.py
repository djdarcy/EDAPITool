"""Red-green audit for U38 (v0.7.7): the location cells are opt-in.

Each arm reverts ONE behaviour while keeping every signature, runs only the
audited tests, and restores the file in a finally block. Rule 1b: the serve
test uses capture-and-abort stand-ins, so no arm can reach a real sheet.

Run from the repo root:  python tests/one-offs/thinking/redgreen_u38_write_location.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TESTS = [
    "tests/test_location_opt_in.py",
    "tests/test_marker_formula.py::test_the_help_text_no_longer_promises_that_no_markers_writes_nothing",
]

ARMS = [
    ("a writer: location unconditional", "APITool/sheets/writer.py",
     "        if write_location:\n            plan.updates.append({\"range\": layout.system_cell",
     "        if True:\n            plan.updates.append({\"range\": layout.system_cell"),
    ("b plugin: missing option means yes", "APITool/plugins/settlement/__init__.py",
     'options.get("write_location", False)', 'options.get("write_location", True)'),
    ("c daemon: serve stops asking", "APITool/daemon.py",
     "write_location=totals_ws is not None,", "write_location=False,"),
    ("d cli: market ignores the flag", "APITool/cli.py",
     "force=args.force,\n            write_location=args.write_location,",
     "force=args.force,\n            write_location=False,"),
    ("e help: the old promise", "APITool/plugins/settlement/markers.py",
     "   --no-markers leaves your marker column alone. The location cells are\n"
     "   yours as well: they are written only with --write-location, and are\n"
     "   better as formulas reading the same generated tab -- the system in\n"
     "   MarketData!$E$1, the station in MarketData!$C$1.",
     "   --no-markers still refreshes the location cells; it only leaves your marker\n"
     "   column alone."),
]


def run():
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    ).stdout
    failed = [line.split("::")[-1].split(" ")[0] for line in out.splitlines()
              if line.startswith("FAILED")]
    return out.strip().splitlines()[-1], failed


def main():
    print("baseline:", run()[0])
    for name, rel, old, new in ARMS:
        path = ROOT / rel
        original = path.read_bytes()
        text = original.decode("utf-8")
        if "\r\n" in text:          # some sources are CRLF; match their endings
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        assert text.count(old) == 1, f"{name}: anchor found {text.count(old)}x"
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            summary, failed = run()
        finally:
            path.write_bytes(original)
        print(f"\n[{name}] {summary}")
        for test in failed:
            print("   red:", test)
    print("\nrestored:", run()[0])


if __name__ == "__main__":
    main()
