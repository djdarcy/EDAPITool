"""
Can plugins register READS the way they already register WRITES?

The maintainer's proposal, verbatim:

    "It sounds like we just need a subscriber model where plugins give their
     'read' and 'write' functionality to the main loop so data can be fetched
     during a refresh?"

Half of it already exists. `daemon.Publisher` is a subscriber model for the
write half, and its docstring says why it was built:

    "The loop used to hold exactly two of these as named fields, which made a
     third a question of editing the loop rather than adding an entry -- and it
     is why the daemon could publish two of the three generated tabs without
     anything being obviously missing."

So the question is not "should we have a subscriber model" -- we have one. It
is whether READS can join the same registry, or whether they need a different
one.

BUILT TO REFUTE. The claim under test is mine, and it is the one that should
lose if it is wrong:

    H1  a plugin's WRITE half fits `Publisher` unchanged        predict: SURVIVES
    H2  a plugin's READ half also fits `Publisher` unchanged    predict: FAILS  <- control
    H3  one flat registry orders reads before writes by itself  predict: FAILS
    H4  two registries (suppliers + subscribers) order correctly predict: SURVIVES

H2 is the control arm. If H2 SURVIVES, my read/write asymmetry claim is wrong,
one registry is enough, and this file should be read as evidence against its
own author. That is the point of writing it this way.

The cost H3 is measured on is SHEET READS, because that is the currency that
actually matters here: Google's API is quota-limited, the requirements read is
the tool's only production sheet read, and duplicating it per subscriber is
the kind of regression nobody notices until the quota bites.

Run:  python tests/one-offs/thinking/plugin-isolation/poc_subscriber_model.py
No game, no network, no spreadsheet. Everything is counted in-process.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from APITool.daemon import Publisher, PublishResult  # noqa: E402


# ---------------------------------------------------------------------------
# A fake sheet that counts what is asked of it.
# ---------------------------------------------------------------------------

@dataclass
class CountingSheet:
    """Stands in for a worksheet, and counts reads and writes separately."""

    reads: int = 0
    writes: int = 0
    read_log: list = field(default_factory=list)

    def get_values(self, rng: str):
        self.reads += 1
        self.read_log.append(rng)
        # Two commodities outstanding, as if from a Totals Tab.
        return [["Biowaste", "229"], ["Steel", "0"]]

    def batch_update(self, data):
        self.writes += 1
        return {"replies": []}


# ---------------------------------------------------------------------------
# Two plugins. One reads AND writes; one only writes.
# ---------------------------------------------------------------------------

@dataclass
class SettlementPlugin:
    """Reads requirements from its sheet, then writes markers derived from them."""

    sheet: CountingSheet
    name: str = "settlement"

    def read_requirements(self) -> list:
        grid = self.sheet.get_values("A1:AZ400")
        return [(row[0], int(row[1])) for row in grid]

    def write_markers(self, requirements) -> str:
        outstanding = [n for n, q in requirements if q > 0]
        self.sheet.batch_update([{"range": "L5:L24", "values": [outstanding]}])
        return f"markers for {len(outstanding)} outstanding"


@dataclass
class SummaryPlugin:
    """A second sheet that ALSO needs the requirements, but writes elsewhere."""

    sheet: CountingSheet
    name: str = "summary"

    def write_summary(self, requirements) -> str:
        total = sum(q for _, q in requirements)
        self.sheet.batch_update([{"range": "B2", "values": [[total]]}])
        return f"summary total {total}"


# ---------------------------------------------------------------------------
# H1 / H2 -- does a Publisher carry each half?
# ---------------------------------------------------------------------------

def h1_write_fits_publisher() -> tuple[bool, str]:
    """A write is self-contained: closes over its inputs, returns a status."""
    sheet = CountingSheet()
    plugin = SettlementPlugin(sheet)
    reqs = plugin.read_requirements()

    pub = Publisher(
        name="settlement-markers",
        triggers=frozenset({"Market"}),
        publish=lambda: PublishResult(True, plugin.write_markers(reqs)),
    )
    result = PublishResult.of(pub.publish())
    ok = result.wrote and sheet.writes == 1
    return ok, f"publish() returned {result.message!r}; writes={sheet.writes}"


def h2_read_fits_publisher() -> tuple[bool, str]:
    """
    THE CONTROL ARM. Can a read be a Publisher?

    `Publisher.publish` is `Callable[[], PublishResult]` -- zero arguments in,
    a STATUS out. A read has to hand DATA to whoever needs it next. Wrapping it
    still "works" in the sense that it runs; the question is whether the value
    survives the interface.
    """
    sheet = CountingSheet()
    plugin = SettlementPlugin(sheet)

    captured = {}

    def publish_shaped_read() -> PublishResult:
        captured["requirements"] = plugin.read_requirements()
        return PublishResult(False, "read 2 requirements")

    pub = Publisher(
        name="settlement-requirements",
        triggers=frozenset({"Market"}),
        publish=publish_shaped_read,
    )
    result = PublishResult.of(pub.publish())

    # The interface hands back a status. The DATA only survives because this
    # test closed over a dict from the outside -- which is the loop reaching
    # into the subscriber, not the subscriber returning to the loop.
    reachable_through_interface = not isinstance(result, (list, tuple)) and \
        not hasattr(result, "requirements")
    survives = not reachable_through_interface
    detail = (f"publish() returned {type(result).__name__}"
              f"(wrote={result.wrote}); the requirements reached the caller "
              f"only via an out-of-band dict, not through the return value")
    return survives, detail


# ---------------------------------------------------------------------------
# H3 / H4 -- ordering and duplicated reads
# ---------------------------------------------------------------------------

def h3_flat_registry() -> tuple[bool, str, int]:
    """
    One flat registry. Every subscriber is zero-arg and self-contained, so
    each one that needs requirements must read them ITSELF.
    """
    sheet = CountingSheet()
    settlement = SettlementPlugin(sheet)
    summary = SummaryPlugin(sheet)

    registry = [
        Publisher("settlement-markers", frozenset({"Market"}),
                  lambda: PublishResult(
                      True, settlement.write_markers(settlement.read_requirements()))),
        Publisher("summary", frozenset({"Market"}),
                  lambda: PublishResult(
                      True, summary.write_summary(settlement.read_requirements()))),
    ]
    for pub in registry:
        PublishResult.of(pub.publish())

    # Correct output, but the read happened once PER SUBSCRIBER.
    ordered_correctly = sheet.writes == 2
    return ordered_correctly, f"writes={sheet.writes}, sheet reads={sheet.reads}", sheet.reads


def h4_two_registries() -> tuple[bool, str, int]:
    """
    Suppliers pulled first, subscribers pushed after. One read, two writes.
    """
    sheet = CountingSheet()
    settlement = SettlementPlugin(sheet)
    summary = SummaryPlugin(sheet)

    suppliers = {"requirements": settlement.read_requirements}
    subscribers = [
        ("settlement-markers", settlement.write_markers),
        ("summary", summary.write_summary),
    ]

    context = {name: supply() for name, supply in suppliers.items()}
    for _name, consume in subscribers:
        consume(context["requirements"])

    ordered_correctly = sheet.writes == 2
    return ordered_correctly, f"writes={sheet.writes}, sheet reads={sheet.reads}", sheet.reads


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# H5 -- the case the maintainer actually named: ONE acquisition, MANY plugins.
#
#   "when we do a read from say the Elite Dangerous Freighter we update all our
#    plugins without doing multiple calls needlessly"
#
# For a sheet read, duplication is waste. For the FLEET CARRIER it is failure:
# `capi.py:121-127` raises CAPIRateLimitError when a second fleet-carrier query
# arrives inside FLEETCARRIER_COOLDOWN, which `constants.py:30` sets to 900
# seconds. So a flat registry does not cost an extra call -- the second plugin
# gets an exception and publishes nothing, for fifteen minutes.
# ---------------------------------------------------------------------------

class CooldownError(Exception):
    """Stands in for CAPIRateLimitError, with the same trigger condition."""


@dataclass
class CountingCAPI:
    """A fleet-carrier endpoint with the real 900-second cooldown rule."""

    fetches: int = 0
    refusals: int = 0
    _last: Optional[float] = None
    cooldown: float = 900.0
    clock: float = 0.0

    def get_fleet_carrier(self) -> dict:
        if self._last is not None and (self.clock - self._last) < self.cooldown:
            self.refusals += 1
            wait = self.cooldown - (self.clock - self._last)
            raise CooldownError(f"Fleet carrier query cooldown. Wait {wait:.0f} seconds.")
        self._last = self.clock
        self.fetches += 1
        return {"cargo": [{"commodity": "Biowaste", "qty": 840}]}


def h5_carrier_fanout() -> tuple[bool, bool, str]:
    """
    Two plugins both want carrier cargo. Flat registry vs one acquisition.

    Returns (flat_ok, fanout_ok, detail).
    """
    # --- flat registry: each subscriber fetches for itself ---
    capi_flat = CountingCAPI()
    sheet_flat = CountingSheet()
    errors = []

    def freighter_tab():
        data = capi_flat.get_fleet_carrier()
        sheet_flat.batch_update([{"range": "A1", "values": [[len(data["cargo"])]]}])
        return "FreighterData published"

    def carrier_summary():
        data = capi_flat.get_fleet_carrier()      # second fetch, same refresh
        sheet_flat.batch_update([{"range": "B1", "values": [[len(data["cargo"])]]}])
        return "carrier summary published"

    for fn in (freighter_tab, carrier_summary):
        try:
            fn()
        except CooldownError as exc:
            errors.append(str(exc))

    flat_ok = sheet_flat.writes == 2 and not errors

    # --- one acquisition, fanned out ---
    capi_fan = CountingCAPI()
    sheet_fan = CountingSheet()
    carrier = capi_fan.get_fleet_carrier()        # acquired ONCE
    for rng in ("A1", "B1"):
        sheet_fan.batch_update([{"range": rng, "values": [[len(carrier["cargo"])]]}])
    fanout_ok = sheet_fan.writes == 2

    detail = (f"flat: {capi_flat.fetches} fetch(es), {capi_flat.refusals} refused, "
              f"{sheet_flat.writes}/2 published"
              + (f" -- {errors[0]}" if errors else "")
              + f"  |  fan-out: {capi_fan.fetches} fetch, "
              f"{sheet_fan.writes}/2 published")
    return flat_ok, fanout_ok, detail


# ---------------------------------------------------------------------------
# H6 -- who holds the write guard?
#
# If a plugin owns its layout AND does its own writing, it also builds its own
# guard: today `TotalsTabWriter` does `guard or self.layout.guard()`. That makes
# the plugin its own safety boundary. `sheets/guard.py` is deny-by-default and
# exists because the previous design was a deny-LIST that failed open and left
# every hand-entered tab writable.
#
# The alternative: the plugin DECLARES the regions it writes, core BUILDS the
# guard from that declaration, and the subscriber is handed a pre-guarded
# writer. The plugin says where; core decides whether.
#
# SAFETY (rule 1b): nothing here can perform a real write. The only "sheet" is
# CountingSheet, and the guarded path raises before reaching it.
# ---------------------------------------------------------------------------

from APITool.sheets import WriteGuard, WriteRefused  # noqa: E402


@dataclass
class HonestPlugin:
    """Declares the marker range, writes inside it."""

    def declares(self) -> dict:
        return {"Totals Tab": ["L5:L24"]}

    def write(self, guard: WriteGuard, sheet: CountingSheet) -> str:
        guard.check("Totals Tab", "L5:L24")
        sheet.batch_update([{"range": "L5:L24", "values": [["*"]]}])
        return "wrote its own range"


@dataclass
class BuggyPlugin:
    """
    Declares the marker range, then writes over the commodity column.

    Not malice -- a transposed constant. `B5:B24` is the column of formulas
    that must never be touched; the project has a test named for exactly that
    cell range.
    """

    def declares(self) -> dict:
        return {"Totals Tab": ["L5:L24"]}

    def write(self, guard: Optional[WriteGuard], sheet: CountingSheet) -> str:
        if guard is not None:
            guard.check("Totals Tab", "B5:B24")
        sheet.batch_update([{"range": "B5:B24", "values": [[""]]}])
        return "wrote OUTSIDE its declaration"


def h6_guard_authority() -> tuple[bool, bool, str]:
    """
    Returns (self_policed_blocked, core_built_blocked, detail).

    The first is the control: a plugin trusted to guard itself is predicted NOT
    to stop the buggy write, because nothing checks its declaration against
    what it actually does.
    """
    # --- plugin self-polices: it builds whatever guard it likes ---
    sheet_a = CountingSheet()
    buggy = BuggyPlugin()
    # A plugin that builds its own guard can simply build a permissive one --
    # or, as here, pass none at all. Nothing outside it notices.
    try:
        buggy.write(None, sheet_a)
        self_policed_blocked = False
    except WriteRefused:
        self_policed_blocked = True

    # --- core builds the guard from the DECLARATION ---
    sheet_b = CountingSheet()
    core_guard = WriteGuard.build(buggy.declares())
    try:
        buggy.write(core_guard, sheet_b)
        core_built_blocked = False
    except WriteRefused:
        core_built_blocked = True

    # and the honest plugin is unaffected by the guard being core's
    sheet_c = CountingSheet()
    honest = HonestPlugin()
    honest_guard = WriteGuard.build(honest.declares())
    honest.write(honest_guard, sheet_c)

    detail = (f"self-policed: B5:B24 write {'refused' if self_policed_blocked else 'WENT THROUGH'}"
              f" (sheet writes={sheet_a.writes})  |  "
              f"core-built: {'refused' if core_built_blocked else 'went through'}"
              f" (sheet writes={sheet_b.writes})  |  "
              f"honest plugin still works (writes={sheet_c.writes})")
    return self_policed_blocked, core_built_blocked, detail


def main() -> int:
    print("=" * 76)
    print("Can plugins register READS the way they register WRITES?")
    print("=" * 76)
    print()

    rows = []

    ok, detail = h1_write_fits_publisher()
    rows.append(("H1", "write fits Publisher unchanged", "SURVIVES", ok, detail))

    ok, detail = h2_read_fits_publisher()
    rows.append(("H2", "read fits Publisher unchanged (CONTROL)", "FAILS", ok, detail))

    ok3, d3, reads3 = h3_flat_registry()
    rows.append(("H3", "flat registry, one read shared", "FAILS", reads3 == 1, d3))

    ok4, d4, reads4 = h4_two_registries()
    rows.append(("H4", "two registries, one read shared", "SURVIVES", reads4 == 1, d4))

    self_ok, core_ok, d6 = h6_guard_authority()
    rows.append(("H6a", "a self-policing plugin stops its own bad write", "FAILS",
                 self_ok, d6))
    rows.append(("H6b", "a core-built guard stops it", "SURVIVES", core_ok, d6))

    flat_ok, fanout_ok, d5 = h5_carrier_fanout()
    rows.append(("H5a", "flat registry survives the carrier cooldown", "FAILS",
                 flat_ok, d5))
    rows.append(("H5b", "one acquisition fanned out to both plugins", "SURVIVES",
                 fanout_ok, d5))

    for tag, claim, predicted, survived, detail in rows:
        actual = "SURVIVES" if survived else "FAILS"
        verdict = "as predicted" if actual == predicted else "*** PREDICTION WRONG ***"
        print(f"  {tag}  {claim}")
        print(f"      predicted {predicted:<9} actual {actual:<9} {verdict}")
        print(f"      {detail}")
        print()

    print("-" * 76)
    print(f"  sheet reads, flat registry : {reads3}")
    print(f"  sheet reads, two registries: {reads4}")
    if reads3 > reads4:
        print(f"  -> the flat registry costs {reads3 - reads4} extra sheet read(s)")
        print("     per refresh, and the cost grows with each subscriber that")
        print("     needs the same input. Google's API is quota-limited.")
    print("-" * 76)
    print()

    control = rows[1]
    if control[3]:
        print("  THE CONTROL ARM SURVIVED. A read DOES fit Publisher, the")
        print("  read/write asymmetry claim is wrong, and one registry suffices.")
        print("  Read this file as evidence against its author.")
    else:
        print("  The control fired: a read does not survive the Publisher")
        print("  interface, because `publish` returns a STATUS and a read must")
        print("  return DATA. Two registries, not one.")

    wrong = [r for r in rows if ("SURVIVES" if r[3] else "FAILS") != r[2]]
    print()
    print("=" * 76)
    print(f"{len(rows) - len(wrong)}/{len(rows)} predictions held")
    print("=" * 76)
    return len(wrong)


if __name__ == "__main__":
    sys.exit(main())
