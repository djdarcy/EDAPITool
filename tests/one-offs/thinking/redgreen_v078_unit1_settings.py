"""Red-green audit for v0.7.8 unit 1: settings.py header, backup, recovery.

Each arm reverts ONE behaviour in APITool/settings.py, keeps every
signature, runs only the new tests, and restores the file in a finally.
All test writes land in tmp_path (the `config` fixture).

Run from the repo root:  python tests/one-offs/thinking/redgreen_v078_unit1_settings.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / "APITool" / "settings.py"
TESTS = ["tests/test_settings.py", "-k",
         "header or backup or corrupt or once_not or comment_inside"]

ARMS = [
    ("a header not stripped",
     '    return "".join(lines[:count]), "".join(lines[count:])',
     '    return "", text'),
    ("b save drops the header",
     '        tmp.write_text(header + json.dumps(data, indent=2) + "\\n", encoding="utf-8")',
     '        tmp.write_text(json.dumps(data, indent=2) + "\\n", encoding="utf-8")'),
    ("c save skips the backup",
     "        if previous is not None and good:\n            backup_path().write_text(previous, encoding=\"utf-8\")",
     "        if False:\n            backup_path().write_text(previous, encoding=\"utf-8\")"),
    ("d recover ignores the backup",
     "    backup = backup_path()\n    if backup.exists():",
     "    backup = backup_path()\n    if False:"),
    ("e report every time",
     "    if path in _reported:\n        return\n    _reported.add(path)",
     "    _reported.add(path)"),
    ("f corrupt reads {} silently (the old behaviour)",
     "    except json.JSONDecodeError as exc:\n        return _recover(exc)",
     "    except json.JSONDecodeError as exc:\n        return {}"),
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
    original = TARGET.read_bytes()
    text = original.decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    for name, old, new in ARMS:
        old, new = old.replace("\n", nl), new.replace("\n", nl)
        assert text.count(old) == 1, f"{name}: anchor found {text.count(old)}x"
        try:
            TARGET.write_bytes(text.replace(old, new).encode("utf-8"))
            summary, failed = run()
        finally:
            TARGET.write_bytes(original)
        print(f"\n[{name}] {summary}")
        for t in failed:
            print("   red:", t)
    print("\nrestored:", run()[0])


if __name__ == "__main__":
    main()
