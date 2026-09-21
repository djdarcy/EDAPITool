"""
Prove that grouping the help output changed no parsing.

Grouping flags under `add_argument_group` is meant to be pure presentation:
the same flags, the same dests, the same defaults, in a different order on
the page. "Meant to be" is not evidence. This captures what every flag
parses to, so the claim becomes a diff.

Run it BEFORE the change with `--save`, then AFTER with `--check`:

    python tests/one-offs/thinking/help-grouping/capture_namespaces.py --save
    # ... apply the grouping ...
    python tests/one-offs/thinking/help-grouping/capture_namespaces.py --check

`--check` exits non-zero and prints every difference if any namespace moved.

The baseline is re-taken whenever a change to parsing is DELIBERATE -- it
was re-saved on 2026-09-21 after `--no-colour` was dropped, leaving one
spelling of the colour flag. Re-saving is not cheating as long as it is
the deliberate change being recorded and not the surprise being buried,
which is why every re-save gets a line here saying what it absorbed.

SAFETY (rule 1b): this must not be able to do what `market` does. Both
command functions are replaced with a recorder before `main()` is called, so
argument parsing is all that runs -- no journal is read, no spreadsheet is
opened, no network call is possible, and the real `cmd_market` and
`cmd_serve` are never reached. The capture file is written beside this
script and nowhere else.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CAPTURE = HERE / "namespaces.json"

sys.path.insert(0, str(ROOT))

# Every flag of both commands, spread over argv lines that can coexist.
# A flag absent from every line here is a flag this probe does not cover --
# the coverage check below fails if one is missed.
ARGV = {
    "market/bare": ["market"],
    "market/no-sheet": ["market", "--no-sheet", "--use-capi"],
    "market/journal": ["market", "--journal-dir", "D:/journals"],
    "market/write": ["market", "--update-sheet", "--dry-run", "--force",
                     "--write-marker-header"],
    "market/sheet": ["market", "--sheet-id", "ABC123", "--totals-tab", "T",
                     "--need-header", "Left to buy", "--need-sign", "negative"],
    "market/glyphs": ["market", "--marker-column", "Q", "--no-markers",
                      "--empty-marker", "dotted", "--no-show-covered",
                      "--no-color", "--show-formula"],
    "market/data": ["market", "--export", "csv,json", "--output", "out",
                    "--json"],
    "market/short": ["market", "-e", "market-tab", "-o", "out"],
    "market/auth": ["market", "--client-id", "cid", "--redirect-uri",
                    "http://localhost/x", "--manual-auth"],
    "serve/bare": ["serve"],
    "serve/watch": ["serve", "--journal-dir", "D:/journals", "--interval",
                    "3.5", "--debounce", "9", "--once"],
    "serve/publish": ["serve", "--sheet-id", "ABC123", "--ship-tab", "S",
                      "--totals-tab", "T",
                      "--construction-region", "Agri!R1:AC60=Site"],
    "serve/regions": ["serve", "--construction-region", "A!R1:S2",
                      "--construction-region", "B!R1:S2"],
    "serve/own": ["serve", "--write-location"],
    "serve/auth": ["serve", "--client-id", "cid", "--manual-auth"],
}

# Flags this probe must touch. Anything here that never appears in ARGV is a
# gap, and a gap is how "nothing changed" gets claimed about a flag nobody
# exercised.
MUST_COVER = [
    "--journal-dir", "--use-capi", "--sheet-id", "--no-sheet", "--totals-tab",
    "--need-header", "--need-sign", "--update-sheet", "--dry-run", "--force",
    "--write-marker-header", "--marker-column", "--no-markers",
    "--empty-marker", "--no-show-covered", "--no-color",
    "--show-formula", "--export", "--output", "--json", "--client-id",
    "--redirect-uri", "--manual-auth", "--interval", "--debounce", "--once",
    "--ship-tab", "--construction-region", "--write-location",
]


def capture() -> dict:
    """Parse every argv line and record the resulting namespace."""
    import APITool.cli as cli

    seen: dict[str, dict] = {}

    def recorder(args):
        seen["last"] = {
            k: v for k, v in sorted(vars(args).items()) if k != "func"
        }
        return 0

    # Replace BOTH commands before anything is parsed. Neither real command
    # may run: one opens a spreadsheet, the other starts a watch loop.
    original = (cli.cmd_market, cli.cmd_serve)
    cli.cmd_market, cli.cmd_serve = recorder, recorder
    try:
        out = {}
        for label, argv in ARGV.items():
            seen.clear()
            code = cli.main(list(argv))
            out[label] = {"exit": code, "args": seen.get("last")}
        return out
    finally:
        cli.cmd_market, cli.cmd_serve = original


def coverage_gaps() -> list[str]:
    flat = " ".join(tok for argv in ARGV.values() for tok in argv)
    return [flag for flag in MUST_COVER if flag not in flat.split()]


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"

    gaps = coverage_gaps()
    if gaps:
        print(f"COVERAGE GAP -- never exercised: {', '.join(gaps)}")
        return 1

    now = capture()

    if mode == "--save":
        CAPTURE.write_text(json.dumps(now, indent=1, sort_keys=True), encoding="utf-8")
        print(f"saved {len(now)} namespaces -> {CAPTURE.name}")
        print(f"covered {len(MUST_COVER)} flags")
        return 0

    if not CAPTURE.exists():
        print(f"no baseline at {CAPTURE}; run with --save first")
        return 1

    before = json.loads(CAPTURE.read_text(encoding="utf-8"))
    problems = 0
    for label in sorted(set(before) | set(now)):
        was, is_ = before.get(label), now.get(label)
        if was == is_:
            continue
        problems += 1
        print(f"\nCHANGED: {label}")
        keys = sorted(set(was.get("args") or {}) | set(is_.get("args") or {}))
        for key in keys:
            a = (was.get("args") or {}).get(key, "<absent>")
            b = (is_.get("args") or {}).get(key, "<absent>")
            if a != b:
                print(f"    {key}: {a!r} -> {b!r}")
        if was.get("exit") != is_.get("exit"):
            print(f"    exit: {was.get('exit')} -> {is_.get('exit')}")

    if problems:
        print(f"\n{problems} namespace(s) changed. Grouping was not neutral.")
        return problems
    print(f"{len(now)} namespaces unchanged across {len(MUST_COVER)} flags.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
