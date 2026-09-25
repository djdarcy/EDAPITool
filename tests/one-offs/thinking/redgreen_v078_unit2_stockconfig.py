"""Red-green audit for v0.7.8 unit 2: the stock config written on first run.

Each arm reverts ONE behaviour (stockconfig.py or the cli.py hook), keeps
every signature, runs only tests/test_stock_config.py, restores in a finally.
All writes land in the suite's isolated config directory.

Run from the repo root:  python tests/one-offs/thinking/redgreen_v078_unit2_stockconfig.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SC = ROOT / "APITool" / "stockconfig.py"
CLI = ROOT / "APITool" / "cli.py"
TESTS = ["tests/test_stock_config.py"]

ARMS = [
    ("a guard ignored", SC,
     "    if os.environ.get(GUARD_VAR):\n        return None",
     "    if False:\n        return None"),
    ("b overwrites an existing file", SC,
     "    if path.exists():\n        return None",
     "    if False:\n        return None"),
    ("c no default target", SC,
     "    settlement = defaults.get(DEFAULT_PLUGIN)\n    if settlement is not None:",
     "    settlement = defaults.get(DEFAULT_PLUGIN)\n    if False:"),
    ("d literal config instead of the plugin's", SC,
     '            "config": settlement.config,',
     '            "config": {},'),
    ("e header omits the jsonl example", SC,
     "    if jsonl is not None:\n        lines += [",
     "    if False:\n        lines += ["),
    ("f render drops the header", SC,
     "    return header(defaults) + json.dumps(body(defaults), indent=2) + \"\\n\"",
     "    return json.dumps(body(defaults), indent=2) + \"\\n\""),
    ("g main never prints the line", CLI,
     "        wrote = write_if_missing()\n        if wrote:\n            print(wrote)",
     "        wrote = write_if_missing()\n        if False:\n            print(wrote)"),
    ("h user plugins scanned too", SC,
     "    for found in loader.scan(user_dir=None):",
     "    for found in loader.scan(user_dir=settings.get_plugin_dir()):"),
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
    for name, target, old, new in ARMS:
        original = target.read_bytes()
        text = original.decode("utf-8")
        nl = "\r\n" if "\r\n" in text else "\n"
        old, new = old.replace("\n", nl), new.replace("\n", nl)
        assert text.count(old) == 1, f"{name}: anchor found {text.count(old)}x"
        try:
            target.write_bytes(text.replace(old, new).encode("utf-8"))
            summary, failed = run()
        finally:
            target.write_bytes(original)
        print(f"\n[{name}] {summary}")
        for t in failed:
            print("   red:", t)
    print("\nrestored:", run()[0])


if __name__ == "__main__":
    main()
