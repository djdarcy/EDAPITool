#!/usr/bin/env python
"""
Red-green audit: prove the test suite can actually detect wrong behaviour.

A test that has only ever been seen green has not demonstrated it detects
anything. This injects known-wrong behaviour into the source, runs the suite,
and reports which mutants SURVIVED. Every survivor is a test gap.

Always restores the originals, including on Ctrl-C.

    python tests/one-offs/mutate.py            # all modules
    python tests/one-offs/mutate.py matcher    # one module
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "APITool"

# module -> (test file, [(description, find, replace), ...])
MUTANTS: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "catalog": (
        "tests/test_catalog.py",
        [
            ("aliases never loaded",
             "        catalog.load_aliases(alias_source)",
             "        pass  # MUTANT"),
            ("by_symbol stops stripping the $..._name; wrapper",
             "        return self._by_symbol.get(normalize(strip_symbol(symbol)))",
             "        return self._by_symbol.get(normalize(symbol))  # MUTANT"),
            ("add_alias overwrites an existing canonical name",
             "        if not key or key in self._by_name:\n            return False",
             "        if not key:\n            return False  # MUTANT"),
            ("resolve() checks name before id (wrong precedence)",
             "            (self.by_id, commodity_id),\n            (self.by_symbol, symbol),\n            (self.by_name, name),",
             "            (self.by_name, name),\n            (self.by_symbol, symbol),\n            (self.by_id, commodity_id),  # MUTANT"),
            ("normalize keeps punctuation",
             '    return re.sub(r"[^a-z0-9]", "", str(text).lower())',
             "    return str(text).lower()  # MUTANT"),
        ],
    ),
    "market": (
        "tests/test_matcher.py",
        [
            ("merge lets the supplement win over the primary",
             "    combined = {item.id: item for item in supplement.items}\n    combined.update({item.id: item for item in primary.items})",
             "    combined = {item.id: item for item in primary.items}\n    combined.update({item.id: item for item in supplement.items})  # MUTANT"),
            ("merge stops refusing two different stations",
             "        raise ValueError(\n            f\"refusing to merge different markets: \"",
             "        pass\n    if False:\n        raise ValueError(  # MUTANT\n            f\"refusing to merge different markets: \""),
            ("is_purchasable ignores the buy price",
             "        return self.stock > 0 and self.buy_price > 0",
             "        return self.stock > 0  # MUTANT"),
            ("journal parser drops the localised name",
             '    name = raw.get("Name_Localised") or symbol',
             "    name = symbol  # MUTANT"),
            ("timestamps parsed as naive local time",
             "    if parsed.tzinfo is None:\n        parsed = parsed.replace(tzinfo=timezone.utc)",
             "    if parsed.tzinfo is not None:\n        parsed = parsed.replace(tzinfo=None)  # MUTANT"),
        ],
    ),
    "matcher": (
        "tests/test_matcher.py",
        [
            ("EMPTY collapsed into NONE (loses 'sold here but out')",
             "    if item.is_stocked_when_available:\n        # The station sells this and is simply out right now.\n        return MatchState.EMPTY",
             "    if item.is_stocked_when_available:\n        return MatchState.NONE  # MUTANT"),
            ("PARTIAL boundary off by one (exactly-enough becomes partial)",
             "    return MatchState.ENOUGH if item.stock >= need else MatchState.PARTIAL",
             "    return MatchState.ENOUGH if item.stock > need else MatchState.PARTIAL  # MUTANT"),
            ("zero buy price no longer means 'not traded here'",
             "    if not item.is_purchasable:",
             "    if False:  # MUTANT"),
            ("buyable quantity not capped at need",
             "    buyable = min(item.stock, requirement.need)",
             "    buyable = item.stock  # MUTANT"),
            ("satisfied rows no longer skipped",
             "        if not include_satisfied and not requirement.is_outstanding:\n            continue",
             "        if False:\n            continue  # MUTANT"),
            ("unresolvable names reported as NONE instead of UNKNOWN",
             "        return Match(requirement=requirement, state=MatchState.UNKNOWN)",
             "        return Match(requirement=requirement, state=MatchState.NONE)  # MUTANT"),
            ("UNKNOWN rows become markable",
             "        return self.state in (MatchState.ENOUGH, MatchState.PARTIAL, MatchState.EMPTY)",
             "        return self.state is not MatchState.NONE  # MUTANT"),
            ("is_outstanding accepts zero",
             "        return self.need > 0",
             "        return self.need >= 0  # MUTANT"),
        ],
    ),
    "journal": (
        "tests/test_journal.py",
        [
            ("journal files sorted by raw filename (mixes the two formats)",
             "        return sorted(self.journal_dir.glob(\"Journal.*.log\"), key=journal_sort_key)",
             "        return sorted(self.journal_dir.glob(\"Journal.*.log\"), key=lambda p: p.name)  # MUTANT"),
            ("legacy YYMMDD filenames no longer decoded",
             "    legacy = _LEGACY_NAME.match(name)\n    if legacy:",
             "    legacy = None  # MUTANT\n    if legacy:"),
            ("market freshness gate always passes",
             "        if not self.docked or self.market_id is None or market_id in (None, \"\"):\n            return False",
             "        if False:\n            return False  # MUTANT"),
            ("undocking leaves the old market id in place",
             "            self.market_id = None\n            self.has_commodity_market = False\n            return before",
             "            self.has_commodity_market = False\n            return before  # MUTANT"),
            ("partial final journal line consumed anyway",
             "                    if not line.endswith(\"\\n\"):\n                        # Partial final line -- leave it for the next poll.\n                        break",
             "                    if False:\n                        break  # MUTANT"),
            ("watcher never rolls onto a new journal file",
             "        if self._path is None or latest != self._path:",
             "        if self._path is None:  # MUTANT"),
            ("station_display reports the stale station when undocked",
             "        return self.station if (self.docked and self.station) else NOT_DOCKED",
             "        return self.station or NOT_DOCKED  # MUTANT"),
        ],
    ),
    "sheets": (
        "tests/test_sheets.py",
        [
            ("write guard allows everything",
             "        return any(allowed.contains(target) for allowed in ranges)",
             "        return True  # MUTANT"),
            ("guard stops rejecting unknown tabs",
             "        ranges = self.allowed.get(tab)\n        if not ranges:\n            return False",
             "        ranges = self.allowed.get(tab)\n        if not ranges:\n            return True  # MUTANT"),
            ("range containment ignores the lower bound",
             "        if lo is not None:\n            if other_lo is None or other_lo < lo:\n                return False",
             "        if False:\n            return False  # MUTANT"),
            ("duplicate headers no longer rejected",
             "        if len(hits) > 1:",
             "        if False:  # MUTANT"),
            ("missing header silently returns column A",
             "        if not hits:\n            present = [str(v).strip() for v in header_row_values if str(v).strip()]\n            raise SheetLayoutError(",
             "        if not hits:\n            return 0  # MUTANT\n        if False:\n            present = []\n            raise SheetLayoutError("),
            ("signed need column no longer inverted",
             "        if self.layout.need_sign == SIGN_NEGATIVE:\n            return -quantity",
             "        if False:\n            return -quantity  # MUTANT"),
            # NOTE: mutating away the startswith("#") fast path is an EQUIVALENT
            # mutant -- float("#N/A") raises anyway, so behaviour is unchanged.
            # The behavioural question is what happens on a parse failure.
            ("unparseable quantities silently become zero",
             "    try:\n        return int(round(float(text)))\n    except ValueError:\n        return None",
             "    try:\n        return int(round(float(text)))\n    except ValueError:\n        return 0  # MUTANT"),
            ("marker column patched instead of fully rewritten",
             "            column.append([glyph])",
             "            column.append([glyph] if glyph else [None])  # MUTANT"),
            ("plan skips the guard check on values",
             "        for update in plan.updates:\n            self.guard.check(layout.totals_tab, update[\"range\"])",
             "        for update in []:  # MUTANT\n            self.guard.check(layout.totals_tab, update[\"range\"])"),
            # NOTE: no mutant for the FORMATTING guard loop. Removing it is an
            # EQUIVALENT mutation by construction -- format ranges are always a
            # subset of the value ranges, so the values loop already rejects
            # anything the formats loop would. The loop stays as defence in
            # depth for a future change that breaks that containment, and the
            # containment itself is pinned by
            # test_format_ranges_never_reach_outside_the_value_ranges.
            ("thousands separators not stripped",
             '    text = text.replace(",", "")',
             '    text = text  # MUTANT'),
        ],
    ),
}


def run(test_file: str) -> tuple[int, str]:
    # The suite prints the marker glyphs (● ◕ ◑ ◔ ○ ✓) in assertion diffs, and
    # the default Windows console encoding (cp1252) cannot represent them --
    # decoding then fails and stdout comes back as None. Force UTF-8 on both
    # sides and replace anything still undecodable rather than crashing the
    # audit over a character in a diff.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", test_file, "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln for ln in output.strip().splitlines() if ln.strip()]
    return proc.returncode, lines[-1] if lines else "(no output)"


def main() -> int:
    wanted = sys.argv[1:] or list(MUTANTS)
    targets = {m: MUTANTS[m] for m in wanted if m in MUTANTS}
    if not targets:
        print(f"Unknown module(s). Known: {', '.join(MUTANTS)}")
        return 2

    originals = {m: (PKG / f"{m}.py").read_text(encoding="utf-8") for m in targets}
    survivors: list[str] = []
    skipped: list[str] = []

    try:
        for module, (test_file, mutants) in targets.items():
            path = PKG / f"{module}.py"
            source = originals[module]

            code, line = run(test_file)
            print(f"\n=== {module}.py  ({test_file}) ===")
            print(f"BASELINE: {'PASS' if code == 0 else 'FAIL'}  {line}")
            if code != 0:
                print("  Baseline is not green; fix that before auditing.")
                return 1

            for name, find, replace in mutants:
                if find not in source:
                    print(f"  SKIP     {name}  (anchor not found)")
                    skipped.append(f"{module}: {name}")
                    continue
                path.write_text(source.replace(find, replace, 1), encoding="utf-8")
                code, line = run(test_file)
                if code != 0:
                    print(f"  KILLED   {name}")
                else:
                    print(f"  SURVIVED {name}")
                    survivors.append(f"{module}: {name}")
                path.write_text(source, encoding="utf-8")
    finally:
        for module, source in originals.items():
            (PKG / f"{module}.py").write_text(source, encoding="utf-8")
        print("\nRestored all originals.")

    total = sum(len(m[1]) for m in targets.values())
    print()
    if skipped:
        print(f"{len(skipped)} mutant(s) skipped -- stale anchors:")
        for s in skipped:
            print(f"  - {s}")
    if survivors:
        print(f"{len(survivors)} of {total} mutants SURVIVED -- test gaps:")
        for s in survivors:
            print(f"  - {s}")
        return 1
    print(f"All {total - len(skipped)} applied mutants killed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
