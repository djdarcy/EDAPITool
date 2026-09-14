"""
AC-2 for the cargo tab contract (#11): capture, then compare.

Snapshots the VALUES every cross-tab formula currently resolves to, so a
reshape of the generated tabs can be proved not to have changed meaning.

Values, not formulas, on purpose. A formula that still looks right while
returning a different number is exactly the failure this guards against --
and it is the shape Google Sheets produces when a column is inserted left
of a VLOOKUP index, since the range auto-widens and the index literal does
not.

  capture:  python baseline.py <sheet-id> capture
  compare:  python baseline.py <sheet-id> compare

Read-only in both modes. Writes one JSON file next to this script.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

SNAPSHOT = Path(__file__).with_name("baseline.json")

# Bumped when the snapshot's shape changes. A reader that does not recognise
# the version refuses rather than guessing.
SNAPSHOT_FORMAT = 2


def head_sha() -> str:
    """The commit this working tree is on, or '' if git cannot say."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def check_snapshot_fresh(snapshot: dict, current_sha: str) -> tuple[bool, str]:
    """
    Would comparing against this snapshot mean anything?

    Pure: no network, no disk, no git. Everything it needs is an argument, so
    the guard itself is testable without a spreadsheet -- which matters,
    because an instrument nobody can test is the thing it exists to prevent.

    The snapshot this replaced carried no provenance at all. It sat in the
    tree for four releases and would have compared a post-refactor build
    against a v0.4.1-era capture, reporting either a false green or a false
    red with equal confidence. A stale instrument that silently compares is
    worse than no instrument, so this refuses instead.
    """
    meta = snapshot.get("meta")
    if not isinstance(meta, dict):
        return False, (
            "This baseline carries no provenance -- it predates the staleness "
            "guard and there is no way to know what it was captured against. "
            "Recapture it."
        )

    version = meta.get("format")
    if version != SNAPSHOT_FORMAT:
        return False, (
            f"Baseline is format {version!r}; this reader speaks "
            f"{SNAPSHOT_FORMAT}. Recapture it."
        )

    captured_at_sha = meta.get("sha") or ""
    if not captured_at_sha:
        return False, "Baseline records no commit. Recapture it."

    if not current_sha:
        return False, (
            "Cannot determine HEAD, so the baseline's freshness cannot be "
            "established. Refusing to compare rather than guess."
        )

    if captured_at_sha != current_sha:
        return False, (
            f"Baseline was captured at {captured_at_sha[:12]} but HEAD is "
            f"{current_sha[:12]}. It describes a different build, so a "
            f"comparison would be meaningless in either direction. "
            f"Recapture it."
        )

    return True, f"Baseline is current ({current_sha[:12]})."

# Every column that reads a generated tab, per the measured reference survey.
TARGETS = [
    ("Totals Tab",     "B5:B201",  {"D": "D5:D201", "I": "I5:I201",
                                    "M": "M5:M201", "G": "G5:G201"}),
    ("Agri Lrg. (ex)", "B4:B60",   {"D": "D4:D60",  "H": "H4:H60"}),
    ("Sat. (ex)",      "B4:B60",   {"D": "D4:D60",  "H": "H4:H60"}),
    ("Extr. (ex)",     "B4:B60",   {"D": "D4:D60",  "H": "H4:H60"}),
]


def grab(book) -> dict:
    out = {}
    for tab, key_range, cols in TARGETS:
        ws = book.worksheet(tab)
        keys = [r[0] if r else "" for r in ws.get(key_range)]
        cells = {}
        for label, rng in cols.items():
            vals = ws.get(rng, value_render_option="UNFORMATTED_VALUE")
            cells[label] = [
                (v[0] if v else "") for v in vals
            ] + [""] * (len(keys) - len(vals))
        for i, name in enumerate(keys):
            if not str(name).strip():
                continue
            for label in cols:
                raw = cells[label][i] if i < len(cells[label]) else ""
                out[f"{tab}!{label}{i}|{name}"] = "" if raw is None else str(raw)
    return out


def main(sheet_id: str, mode: str) -> int:
    # The freshness gate runs BEFORE the network call, on purpose: a stale
    # baseline is knowable from disk alone, and failing fast keeps the guard
    # testable without a spreadsheet.
    before = {}
    if mode == "compare":
        if not SNAPSHOT.is_file():
            print("No baseline captured. Run 'capture' first.")
            return 2
        snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        fresh, message = check_snapshot_fresh(snapshot, head_sha())
        print(message)
        if not fresh:
            return 2
        before = snapshot["values"]

    from APITool.google import GoogleSheetsExporter

    book = GoogleSheetsExporter().open_spreadsheet(sheet_id)
    now = grab(book)

    if mode == "capture":
        sha = head_sha()
        payload = {
            "meta": {
                "format": SNAPSHOT_FORMAT,
                "sha": sha,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "cells": len(now),
            },
            "values": now,
        }
        SNAPSHOT.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"captured {len(now)} cell values at {sha[:12]} -> {SNAPSHOT.name}")
        return 0

    added = set(now) - set(before)
    removed = set(before) - set(now)
    changed = {k: (before[k], now[k]) for k in set(before) & set(now)
               if before[k] != now[k]}

    print(f"  baseline cells : {len(before)}")
    print(f"  current cells  : {len(now)}")
    print(f"  changed values : {len(changed)}")
    print(f"  disappeared    : {len(removed)}")
    print(f"  appeared       : {len(added)}")
    for k, (a, b) in list(changed.items())[:20]:
        print(f"    {k}\n        was {a!r}  now {b!r}")
    for k in list(removed)[:10]:
        print(f"    GONE: {k}  (was {before[k]!r})")
    print()
    ok = not changed and not removed
    print("AC-2", "PASSES -- every cross-tab value is unchanged" if ok
          else "FAILS -- the reshape changed what the sheet computes")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[2] not in ("capture", "compare"):
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
