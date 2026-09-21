"""
POC: does "who declared the rectangle" fully answer it, or is there a second axis?

The question, in the maintainer's words (2026-09-20):

    The only real special case is that columns R:W are truly never going to
    collide with human input as it's reserved for the edapitool whereas the
    column L is in the USER's section of the sheet where they expect to be
    able to write themselves. Then again letting the tool write and the user
    write may be desireable in some situations (so long as the human knows).
    But at the same time it could also clobber work.

An earlier measurement in this directory
(`measure_who_declares_the_range.py`) showed one axis: the construction
region is declared by the PERSON and deny-by-default, while the marker
column is declared by the PLUGIN and permit-by-default. That axis is real
but it is about CONSENT -- may the tool write here at all.

This one tests whether consent is sufficient. It is not obviously so: a
person can consent to a rectangle inside their own working area and still
lose work, because consent says nothing about what the tool does to cells
it has no value for.

So: two axes, tested as a grid.

    TERRITORY   owned  -- a reserved block; nothing of the person's is ever here
                shared -- inside the person's working area; they edit it too

    POLICY      clear  -- write the whole rectangle, blanking cells with no value
                sparse -- write only the cells there is a value for; touch nothing else

Four combinations, plus the hazard each policy exists to prevent. A policy
that is safe in one territory and destructive in the other is evidence that
the cases do NOT homogenize.

SAFETY: pure computation on in-memory grids. No worksheet, no network, no
file outside this repository is opened, and nothing is written anywhere.

Run:  python tests/one-offs/thinking/plugin-isolation/poc_owned_vs_shared_ranges.py
"""

from __future__ import annotations

import sys

LINE = "=" * 78
FORMULA = "=IF(...LET...)"   # abbreviated; the real one is quoted in #25

# An ASCII stand-in for the filled marker glyph. The real one is U+25CF, and a
# cp1252 console cannot encode it -- the same defect already recorded against
# `market --show-formula`, hit twice while writing this probe. Platform rule:
# emit ASCII from anything whose output reaches a Windows terminal.
MARKER = "[filled]"


def rule(title: str) -> None:
    print()
    print(LINE)
    print(f"  {title}")
    print(LINE)


def apply_clear(before: list[str], values: dict[int, str]) -> list[str]:
    """Write the whole rectangle. Cells with no value are blanked."""
    return [values.get(i, "") for i in range(len(before))]


def apply_sparse(before: list[str], values: dict[int, str]) -> list[str]:
    """Write only the cells there is a value for. Everything else is untouched."""
    return [values.get(i, before[i]) for i in range(len(before))]


def survivors(before: list[str], after: list[str]) -> int:
    """How many of the person's own cells are still there."""
    return sum(1 for b, a in zip(before, after) if b and b.startswith("=") and a == b)


def destroyed(before: list[str], after: list[str]) -> int:
    return sum(1 for b, a in zip(before, after) if b and b.startswith("=") and a != b)


def report(name: str, before: list[str], after: list[str]) -> None:
    print(f"    {name:<8} before: {before}")
    print(f"    {'':<8} after : {after}")
    theirs = sum(1 for b in before if b and b.startswith("="))
    if theirs:
        print(f"    {'':<8} of {theirs} formulas the person owns: "
              f"{survivors(before, after)} survive, {destroyed(before, after)} destroyed")


def owned_territory() -> None:
    rule("TERRITORY: OWNED -- a reserved block (the Agri Lrg. (ex)!R1:AC60 case)")
    print("  Nothing of the person's is ever in here. Last run wrote 4 commodities;")
    print("  the site shrank and this run has 2.")
    before = ["Gold", "Silver", "Tritium", "Water"]
    values = {0: "Gold", 1: "Silver"}

    print()
    report("clear", before, apply_clear(before, values))
    print("           -> correct. The tail is gone.")
    print()
    report("sparse", before, apply_sparse(before, values))
    print("           -> WRONG. 'Tritium' and 'Water' are last run's, still")
    print("              sitting there looking current. This is the exact hazard")
    print("              the clear-to-bounds rule was built for: a site that")
    print("              shrinks leaves a stale tail.")


def shared_territory() -> None:
    rule("TERRITORY: SHARED -- inside the person's own area (the Totals Tab!L5:L24 case)")
    print("  The person put formulas here. They recalculate from the generated")
    print("  MarketData tab. The tool has a marker for row 2 only.")
    before = [FORMULA, FORMULA, FORMULA, FORMULA]
    values = {1: MARKER}

    print()
    report("clear", before, apply_clear(before, values))
    print("           -> the #25 defect, exactly. Measured live 2026-09-16.")
    print()
    report("sparse", before, apply_sparse(before, values))
    print("           -> the person's formulas survive. But note what it costs:")
    print("              row 2's formula is replaced by a painted glyph, so that")
    print("              ONE cell stops recalculating. Sparse is not free here")
    print("              either -- it is merely bounded to the cells the tool has")
    print("              an opinion about.")


def the_stale_hazard_in_shared() -> None:
    rule("Does sparse reintroduce the stale-marker hazard in SHARED territory?")
    print("  The hazard: a painted glyph from a previous station sits there")
    print("  looking current, because nothing repaints it. This project has the")
    print("  worked example -- column L's fossilised fills were wrong for three")
    print("  releases.")
    print()
    print("  Round 1 at station A: the tool paints row 2.")
    before = [FORMULA, FORMULA, FORMULA, FORMULA]
    after1 = apply_sparse(before, {1: MARKER})
    print(f"    {after1}")
    print()
    print("  Round 2 at station B: the tool has nothing for row 2 any more.")
    after2 = apply_sparse(after1, {})
    print(f"    {after2}")
    print("           -> row 2 still reads the marker. STALE. Sparse alone does")
    print("              not solve it: a cell the tool painted once must be cleared")
    print("              when the tool stops having a value for it.")
    print()
    print("  The fix that works in BOTH territories: clear to bounds, but only")
    print("  over the cells THIS TOOL WROTE LAST TIME -- not the whole rectangle.")
    print("  That needs the tool to remember what it wrote, which is state it")
    print("  does not currently keep.")
    after3 = apply_sparse(after1, {1: ""})   # tool clears what it previously painted
    print(f"    with that memory: {after3}")
    print("           -> row 2 blank, rows 1/3/4 formulas intact. Correct in")
    print("              shared territory, and identical to clear-to-bounds in")
    print("              owned territory, where the tool wrote every cell anyway.")


def verdict() -> int:
    rule("VERDICT -- do the cases homogenize?")
    print("  NO, not on one axis. The measurement is:")
    print()
    print("    policy   OWNED territory          SHARED territory")
    print("    ------   ---------------------    ----------------------------")
    print("    clear    correct                  DESTROYS the person's work (#25)")
    print("    sparse   leaves a stale tail      preserves, but goes stale itself")
    print()
    print("  No single policy is right in both. So 'who declared the rectangle'")
    print("  -- the consent axis -- is necessary and NOT sufficient. A person")
    print("  can consent to a rectangle inside their own working area, and the")
    print("  clear policy will still eat their formulas.")
    print()
    print("  What that implies for the design:")
    print("    ONE mechanism (the person names the rectangle, deny-by-default)")
    print("    plus ONE declared property on that binding: is this block MINE")
    print("    to own, or SHARED with you? The property selects the policy.")
    print()
    print("  And a third finding that neither option A nor option D reaches:")
    print("  in shared territory, correctness needs the tool to remember what")
    print("  it wrote last time. Without that, sparse goes stale and clear")
    print("  destroys. That is a real cost and belongs in the decision.")
    print(LINE)
    return 0


def main() -> int:
    owned_territory()
    shared_territory()
    the_stale_hazard_in_shared()
    return verdict()


if __name__ == "__main__":
    sys.exit(main())
