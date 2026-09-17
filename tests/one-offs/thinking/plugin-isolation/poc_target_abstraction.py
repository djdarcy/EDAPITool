"""
Is "destination" really vendor-neutral, or is it a spreadsheet wearing a coat?

The maintainer's correction, which this exists to test:

    "The sheet obviously needs an id, but a person could have a jsonl, a google
     sheets, a microsoft sheet, etc so we need to make sure the input/output is
     sufficiently abstract not just specific to Google."

He is right that the config shape I proposed -- `"sheets": {"<sheet_id>": ...}`
-- bakes Google in. The replacement sketched in conversation was:

    "targets": {
      "settlement-workbook": {"kind": "gsheet", "id": "1WACbf...", "plugin": ...},
      "nightly-dump":        {"kind": "jsonl",  "path": "~/ed/obs.jsonl"}
    }

That has never been tested. This tests it, by writing a destination that is
NOT a spreadsheet and seeing what breaks.

BUILT TO REFUTE. The claim under test is mine and it should lose if wrong:

    T1  a JSONL target satisfies the same supplier contract        predict: SURVIVES
    T2  a JSONL target satisfies the same subscriber contract      predict: SURVIVES
    T3  a JSONL target needs the WriteGuard                        predict: FAILS  <- control
    T4  one acquisition fans out to a sheet AND a file target      predict: SURVIVES
    T5  `Destination.parse` ("Tab!A1:B2") describes a JSONL target predict: FAILS  <- control

T3 and T5 are the controls. If they SURVIVE, the abstraction is more general
than I think and the design is too cautious. If they fail as predicted, they
tell us precisely WHICH pieces are spreadsheet-shaped, which is the useful
answer either way -- a seam is not proven general by a second example that
happens to be another spreadsheet.

Run:  python tests/one-offs/thinking/plugin-isolation/poc_target_abstraction.py
Writes one temp file, into the system temp directory, and removes it.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from APITool.sheets import Destination, WriteGuard, WriteRefused  # noqa: E402


# ---------------------------------------------------------------------------
# The contract under test, stated once. Nothing here mentions a spreadsheet.
# ---------------------------------------------------------------------------

@dataclass
class Target:
    """What config names. `kind` says what it is; the rest is that kind's."""

    name: str
    kind: str
    locator: str          # a sheet id, a file path, a URL -- the kind decides


class Plugin:
    """
    supplies() -> {name: callable}   pulled once per refresh, memoised
    writes()   -> declaration         core builds enforcement from it
    subscribe(result) -> str          pushed, after suppliers have run
    """


# ---------------------------------------------------------------------------
# Two plugins against two kinds of target.
# ---------------------------------------------------------------------------

@dataclass
class SheetPlugin(Plugin):
    target: Target
    sheet: dict = field(default_factory=dict)
    reads: int = 0

    def supplies(self) -> dict:
        return {"requirements": self._read_requirements}

    def _read_requirements(self):
        self.reads += 1
        return [("Biowaste", 229), ("Steel", 0)]

    def writes(self) -> dict:
        return {"Totals Tab": ["L5:L24"]}

    def subscribe(self, result, guard=None) -> str:
        if guard is not None:
            guard.check("Totals Tab", "L5:L24")
        self.sheet["L5:L24"] = [n for n, q in result["requirements"] if q > 0]
        return f"sheet: {len(self.sheet['L5:L24'])} marked"


@dataclass
class JsonlPlugin(Plugin):
    """A destination that is a FILE. No tabs, no cells, no ranges."""

    target: Target
    lines: int = 0

    def supplies(self) -> dict:
        # A file target can supply too -- the last line is prior state.
        return {"previous": self._read_last_line}

    def _read_last_line(self):
        p = Path(self.target.locator)
        if not p.exists() or not p.read_text(encoding="utf-8").strip():
            return None
        return json.loads(p.read_text(encoding="utf-8").strip().splitlines()[-1])

    def writes(self) -> dict:
        # What does a file DECLARE? It owns the whole file, not a region of it.
        return {"__file__": [self.target.locator]}

    def subscribe(self, result, guard=None) -> str:
        with open(self.target.locator, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"requirements": result["requirements"]}) + "\n")
        self.lines += 1
        return f"jsonl: appended 1 line"


# ---------------------------------------------------------------------------

def t1_t2_jsonl_fits_contract(tmp: Path) -> tuple[bool, bool, str]:
    target = Target("nightly-dump", "jsonl", str(tmp / "obs.jsonl"))
    plugin = JsonlPlugin(target)

    supplies_ok = set(plugin.supplies()) == {"previous"} and \
        plugin.supplies()["previous"]() is None       # empty file -> None

    context = {"requirements": [("Biowaste", 229)]}
    msg = plugin.subscribe(context)
    subscribe_ok = plugin.lines == 1 and "appended" in msg
    return supplies_ok, subscribe_ok, f"supplies()={list(plugin.supplies())}, {msg}"


def t3_jsonl_needs_the_guard(tmp: Path) -> tuple[bool, str]:
    """
    CONTROL. `WriteGuard.build` parses its ranges as A1 cell ranges. A file
    path is not one. If this survives, the guard is more general than believed.
    """
    target = Target("nightly-dump", "jsonl", str(tmp / "obs2.jsonl"))
    plugin = JsonlPlugin(target)
    try:
        WriteGuard.build(plugin.writes())
        return True, "WriteGuard accepted a file path as a range"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:58]}"


def t4_fanout_across_kinds(tmp: Path) -> tuple[bool, str]:
    sheet_t = Target("settlement", "gsheet", "1WACbf...")
    file_t = Target("nightly-dump", "jsonl", str(tmp / "obs3.jsonl"))
    sheet_p, file_p = SheetPlugin(sheet_t), JsonlPlugin(file_t)

    # ONE acquisition, fanned out to both kinds.
    suppliers = {}
    for p in (sheet_p, file_p):
        suppliers.update(p.supplies())
    context = {name: supply() for name, supply in suppliers.items()}

    guard = WriteGuard.build(sheet_p.writes())
    out = [sheet_p.subscribe(context, guard), file_p.subscribe(context)]

    ok = sheet_p.reads == 1 and file_p.lines == 1 and len(out) == 2
    return ok, f"one refresh -> {out[0]} | {out[1]}; sheet reads={sheet_p.reads}"


def t5_destination_describes_a_file(tmp: Path) -> tuple[bool, str]:
    """CONTROL. `Destination` is (tab, anchor, bounds). Can it name a file?"""
    try:
        Destination.parse(str(tmp / "obs.jsonl"))
        return True, "Destination.parse accepted a file path"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:58]}"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="edapi-target-poc-"))
    try:
        rows = []

        s_ok, sub_ok, d12 = t1_t2_jsonl_fits_contract(tmp)
        rows.append(("T1", "JSONL satisfies supplies()", "SURVIVES", s_ok, d12))
        rows.append(("T2", "JSONL satisfies subscribe()", "SURVIVES", sub_ok, d12))

        g_ok, d3 = t3_jsonl_needs_the_guard(tmp)
        rows.append(("T3", "WriteGuard covers a file target (CONTROL)", "FAILS", g_ok, d3))

        f_ok, d4 = t4_fanout_across_kinds(tmp)
        rows.append(("T4", "one acquisition fans out across KINDS", "SURVIVES", f_ok, d4))

        d_ok, d5 = t5_destination_describes_a_file(tmp)
        rows.append(("T5", "Destination names a file target (CONTROL)", "FAILS", d_ok, d5))

        print("=" * 76)
        print("Is the destination seam vendor-neutral, or spreadsheet-shaped?")
        print("=" * 76)
        print()
        wrong = 0
        for tag, claim, predicted, survived, detail in rows:
            actual = "SURVIVES" if survived else "FAILS"
            verdict = "as predicted" if actual == predicted else "*** PREDICTION WRONG ***"
            if actual != predicted:
                wrong += 1
            print(f"  {tag}  {claim}")
            print(f"      predicted {predicted:<9} actual {actual:<9} {verdict}")
            print(f"      {detail}")
            print()

        print("-" * 76)
        print(f"  {len(rows) - wrong}/{len(rows)} predictions held")
        print("-" * 76)
        print()
        print("  WHAT THIS SAYS, if the controls fired: the SUPPLIER/SUBSCRIBER")
        print("  contract is genuinely kind-neutral -- a file target satisfies it")
        print("  unchanged. What is NOT neutral is the ENFORCEMENT: `WriteGuard`")
        print("  and `Destination` both speak A1 ranges, which a file has none of.")
        print()
        print("  So a target's 'what may I write' is per-KIND, not universal.")
        print("  A sheet declares cell ranges; a file declares a path it owns.")
        print("  Core cannot hold one guard type for all kinds -- it must ask the")
        print("  KIND for its enforcer, then apply it the same way everywhere.")
        return wrong
    finally:
        for f in tmp.glob("*"):
            f.unlink()
        tmp.rmdir()


if __name__ == "__main__":
    sys.exit(main())
