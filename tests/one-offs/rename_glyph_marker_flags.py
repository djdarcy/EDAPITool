"""
One-off: #28's four flag renames, for v0.8.0 (slice 3, unit 5).

    --marker-column       -> --glyph-marker-column
    --empty-marker        -> --empty-glyph-marker
    --write-marker-header -> --write-glyph-marker-header
    --no-markers          -> --no-glyph-markers

Spellings only. The dests (`marker_column`, `empty_marker`,
`write_marker_header`, `no_markers`) and every other internal identifier
stay, because #28 wants the identifier rename in a separate commit.

Scope is the live surface: production code, live tests, current docs, and the
vocabulary probe. Historical records -- old checklists and past mutation
reports -- are left as written; they describe the version they were run on.

Run with --dry-run first. Prints each file and its count.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RENAMES = [
    ("--write-marker-header", "--write-glyph-marker-header"),
    ("--marker-column", "--glyph-marker-column"),
    ("--empty-marker", "--empty-glyph-marker"),
    ("--no-markers", "--no-glyph-markers"),
]
# A spelling is replaced only where it is a whole flag: not preceded by a
# word character or '-', and not followed by one.
PATTERNS = [(re.compile(rf"(?<![\w-]){re.escape(old)}(?![\w-])"), new) for old, new in RENAMES]

FILES = [
    "APITool/cli.py",
    "APITool/daemon.py",
    "APITool/plugins/totals/__init__.py",
    "APITool/plugins/totals/layout.py",
    "APITool/plugins/totals/markers.py",
    "docs/market.md",
    "tests/test_help_output.py",
    "tests/test_marker_formula.py",
    "tests/test_marker_skip_occupied.py",
    "tests/test_plugin_loader.py",
    "tests/test_service.py",
    "tests/test_sheets.py",
    "tests/one-offs/thinking/plugin-isolation/probe_flag_vocabulary.py",
]


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    total = 0
    for rel in FILES:
        path = ROOT / rel
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        count = 0
        for pattern, new in PATTERNS:
            text, n = pattern.subn(new, text)
            count += n
        total += count
        print(f"{count:3d}  {rel}")
        if count and not dry:
            # Keep the file's own line endings: write the bytes back as read.
            path.write_bytes(text.encode("utf-8"))
    print(f"{total:3d}  total{' (dry run, nothing written)' if dry else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
