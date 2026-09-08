#!/usr/bin/env python
"""
Run the writer-seam POC.

    cd tests/one-offs/thinking/writer-seam && python run.py

Three checks, in this order:

  CONTROL   -- both structures must produce IDENTICAL output for both domains.
               If they do not, the two arms are not comparable and no line
               count means anything. Predicted: identical. If this fails, the
               instrument is broken and NO result is reported.

  ARM A     -- writer moved into the presentation module. Count the lines of
               non-presentation logic the SECOND presenter is forced to write.
               Predicted: >= 40.

  ARM B     -- writer kept generic, taking a renderer. Same count.
               Predicted: <= 10.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import FakeWorksheet, Guard, market_rows, outfitting_rows  # noqa: E402
import structure_a as A  # noqa: E402
import structure_b as B  # noqa: E402

MARKET_GUARD = Guard(allowed=(("Totals Tab", "L"),))
OUTFIT_GUARD = Guard(allowed=(("ShipBuild", "F"),))


def run_a():
    ws1 = FakeWorksheet()
    a_market = A.MarketMarkerWriter(ws1, MARKET_GUARD)
    a_market.apply(a_market.build_plan(market_rows()))

    ws2 = FakeWorksheet()
    a_outfit = A.OutfittingWriter(ws2, OUTFIT_GUARD)
    a_outfit.apply(a_outfit.build_plan(outfitting_rows()))
    return (ws1.batches, ws1.format_batches), (ws2.batches, ws2.format_batches)


def run_b():
    ws1 = FakeWorksheet()
    b_market = B.SheetWriter(ws1, MARKET_GUARD, "Totals Tab", "L", B.MarketRenderer())
    b_market.apply(b_market.build_plan(market_rows()))

    ws2 = FakeWorksheet()
    b_outfit = B.SheetWriter(ws2, OUTFIT_GUARD, "ShipBuild", "F", B.OutfittingRenderer())
    b_outfit.apply(b_outfit.build_plan(outfitting_rows()))
    return (ws1.batches, ws1.format_batches), (ws2.batches, ws2.format_batches)


def second_presenter_lines(path: Path, marker_class: str):
    """
    Count lines inside the SECOND presenter, split by whether they are
    generic machinery (tagged `# GENERIC`) or presentation.
    """
    src = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(src) if l.startswith(f"class {marker_class}"))
    body = src[start:]
    generic = sum(1 for l in body if "# GENERIC" in l)
    code = sum(1 for l in body
               if l.strip() and not l.strip().startswith("#")
               and not l.strip().startswith('"""') )
    return generic, code


def main() -> int:
    here = Path(__file__).parent

    # ---- CONTROL -------------------------------------------------------
    a_market, a_outfit = run_a()
    b_market, b_outfit = run_b()

    print("CONTROL -- do both structures produce identical output?")
    market_same = a_market == b_market
    outfit_same = a_outfit == b_outfit
    print(f"  market domain    identical: {market_same}")
    print(f"  outfitting domain identical: {outfit_same}")
    if not (market_same and outfit_same):
        print()
        print("  METHOD-BROKEN: the structures are not behaviourally equivalent,")
        print("  so any line-count comparison between them is meaningless.")
        print(f"  A market: {a_market}")
        print(f"  B market: {b_market}")
        return 2
    print("  -> the arms are comparable; line counts are meaningful.")
    print()

    # ---- ARMS ----------------------------------------------------------
    a_gen, a_code = second_presenter_lines(here / "structure_a.py", "OutfittingWriter")
    b_gen, b_code = second_presenter_lines(here / "structure_b.py", "OutfittingRenderer")

    print("Lines the SECOND presenter must write, by structure:")
    print(f"  {'':32} {'generic':>8} {'total':>7}")
    print(f"  {'A: writer inside markers.py':32} {a_gen:>8} {a_code:>7}")
    print(f"  {'B: generic writer + renderer':32} {b_gen:>8} {b_code:>7}")
    print()

    print(f"ARM A  predicted generic-lines >= 40   observed {a_gen}   "
          f"{'PASS' if a_gen >= 40 else 'FAIL'}")
    print(f"ARM B  predicted generic-lines <= 10   observed {b_gen}   "
          f"{'PASS' if b_gen <= 10 else 'FAIL'}")
    print()

    survived = a_gen >= 40 and b_gen <= 10
    print(f"VERDICT: {'SURVIVED' if survived else 'REFUTED'}")
    if survived:
        print(f"  Keeping the writer generic removes {a_gen} lines of duplicated")
        print(f"  machinery per additional presenter, at the cost of one Protocol")
        print(f"  and two methods.")
    else:
        print("  The generic writer does not buy the predicted reuse.")
        print("  Fallback: move the writer into markers.py (simpler, no indirection).")
    return 0 if survived else 1


if __name__ == "__main__":
    sys.exit(main())
