"""
The supplier/subscriber registry: one acquisition, every consumer (check C8).

Promoted from tests/one-offs/thinking/plugin-isolation/poc_subscriber_model.py,
where H4 (two registries, one read), H5 (the carrier cooldown) and the
settlement plugin's declarations ran 8/8 with the control arms firing. The
control arm is kept here on purpose: the flat registry that gets REFUSED by
the cooldown is what makes the memoised one mean something.

SAFETY (rule 1b): every "sheet" is an in-memory fake, every "CAPI" a counter;
the service-level tests build a journal in tmp_path. Nothing is written.
"""

from __future__ import annotations

import types
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from APITool.registry import Refresh, Subscription, merge_suppliers


# ---------------------------------------------------------------------------
# One supplier, many consumers (H4)
# ---------------------------------------------------------------------------


def test_a_supplier_is_pulled_once_for_two_subscribers():
    calls: list[int] = []

    def requirements(ctx):
        calls.append(1)
        return [("Biowaste", 229), ("Steel", 0)]

    published: list[tuple[str, int]] = []
    subscriptions = [
        Subscription("markers", ("requirements",),
                     lambda ctx: published.append(("markers", len(ctx.get("requirements"))))),
        Subscription("summary", ("requirements",),
                     lambda ctx: published.append(("summary", sum(q for _, q in ctx.get("requirements"))))),
    ]
    ctx = Refresh({"requirements": requirements})
    statuses = ctx.run(subscriptions)

    assert len(calls) == 1
    assert ctx.calls == {"requirements": 1}
    assert published == [("markers", 2), ("summary", 229)]
    assert list(statuses) == ["markers", "summary"]


def test_supplied_lists_pulls_in_first_ask_order_and_never_twice():
    ctx = Refresh({"a": lambda c: 1, "b": lambda c: 2})
    ctx.get("b")
    ctx.get("a")
    ctx.get("b")
    assert ctx.supplied() == ["b", "a"]
    assert ctx.calls == {"b": 1, "a": 1}


# ---------------------------------------------------------------------------
# The carrier cooldown (H5): a flat registry is refused, one acquisition is not
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


def test_the_control_arm_a_flat_registry_is_refused_by_the_cooldown():
    """Each consumer fetching for itself: the second gets nothing, for 900 s."""
    capi = CountingCAPI()
    published, errors = [], []
    for consumer in (capi.get_fleet_carrier, capi.get_fleet_carrier):
        try:
            published.append(consumer())
        except CooldownError as exc:
            errors.append(str(exc))
    assert (capi.fetches, capi.refusals, len(published)) == (1, 1, 1)
    assert "Wait 900 seconds" in errors[0]


def test_one_acquisition_feeds_every_consumer_of_the_carrier():
    capi = CountingCAPI()
    published: list[int] = []
    ctx = Refresh({"carrier": lambda c: capi.get_fleet_carrier()})
    ctx.run([
        Subscription("freighter", ("carrier",), lambda c: published.append(len(c.get("carrier")["cargo"]))),
        Subscription("summary", ("carrier",), lambda c: published.append(len(c.get("carrier")["cargo"]))),
    ])
    assert (capi.fetches, capi.refusals, len(published)) == (1, 0, 2)


# ---------------------------------------------------------------------------
# Errors are named
# ---------------------------------------------------------------------------


def test_an_unknown_supplier_is_named_with_the_known_ones():
    ctx = Refresh({"location": lambda c: "here"})
    with pytest.raises(KeyError, match="no supplier named 'carrier'; known suppliers: location"):
        ctx.get("carrier")


def test_a_subscription_needing_an_unknown_supplier_fails_before_publishing():
    published: list[int] = []
    with pytest.raises(KeyError, match="nothere"):
        Refresh({}).run([Subscription("x", ("nothere",), lambda c: published.append(1))])
    assert published == []


def test_two_offerers_of_one_supplier_are_refused_by_name():
    with pytest.raises(ValueError, match="supplier 'requirements' is offered by both 'a' and 'b'"):
        merge_suppliers([("a", {"requirements": lambda c: 1}), ("b", {"requirements": lambda c: 2})])


def test_the_environment_reads_as_attributes_and_nothing_else_does():
    ctx = Refresh({}, worksheet="ws", guard=None)
    assert ctx.worksheet == "ws"
    assert ctx.guard is None
    with pytest.raises(AttributeError):
        ctx.nothere  # noqa: B018 -- the access is the assertion


# ---------------------------------------------------------------------------
# The settlement plugin declares both halves
# ---------------------------------------------------------------------------


def test_the_settlement_plugin_supplies_requirements_and_subscribes_markers():
    from APITool.plugins import settlement

    assert set(settlement.supplies()) == {"requirements"}
    subscriptions = settlement.subscribes()
    assert [s.name for s in subscriptions] == ["markers"]
    assert "requirements" in subscriptions[0].needs


# ---------------------------------------------------------------------------
# The service pulls once, and names no plugin
# ---------------------------------------------------------------------------


def _counting_sheet(grid):
    from test_service import FakeWorksheet

    class Counting(FakeWorksheet):
        def __init__(self, grid):
            super().__init__(grid)
            self.reads = 0
            # Which ranges, not just how many. The plan now probes the marker
            # column for occupancy before writing it, so a bare count can no
            # longer say whether the REQUIREMENTS were read twice -- which is
            # the duplication these tests exist to catch.
            self.ranges: list[str] = []

        def get_values(self, range_name, **kwargs):
            self.reads += 1
            self.ranges.append(range_name)
            return super().get_values(range_name, **kwargs)

    return Counting(grid)


def _service(tmp_path, plugin, **kwargs):
    from test_service import docked_event, make_journal, ryman_market_json

    from APITool.catalog import load_catalog
    from APITool.plugins.settlement.layout import SheetLayout
    from APITool.service import MarketRefreshService

    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    return MarketRefreshService(journal_dir=directory, catalog=load_catalog(),
                                layout=SheetLayout(), plugin=plugin, **kwargs)


def test_refresh_reads_the_worksheet_once_for_the_comparison_and_the_writer(tmp_path):
    """
    Both the comparison and the marker writer need the requirements. Before
    the registry, _finish read the sheet again whenever the snapshot was not
    already on the result; now the supplier is pulled once and both consume
    the same read.

    Counted by RANGE rather than by call, because the plan makes a second,
    different read of its own: the marker column's occupancy, which must be
    fetched as formulas and so cannot come from the requirements read. The
    claim here is about the requirements block -- `A1:AZ<n>` -- being read
    once, and that is what is asserted.
    """
    from test_service import ROWS, totals_grid

    from APITool.plugins import settlement

    sheet = _counting_sheet(totals_grid(ROWS))
    result = _service(tmp_path, settlement).refresh(worksheet=sheet, write=True)

    assert [r for r in sheet.ranges if r.startswith("A1:")] == sheet.ranges[:1]
    assert sum(r.startswith("A1:") for r in sheet.ranges) == 1
    assert result.ok and result.matches
    assert result.plan is not None and result.written
    assert len(sheet.batches) == 1


def test_a_plugin_that_supplies_nothing_publishes_nothing_and_breaks_nothing(tmp_path):
    from test_service import ROWS, totals_grid

    quiet = types.SimpleNamespace(supplies=lambda: {}, subscribes=lambda: [])
    sheet = _counting_sheet(totals_grid(ROWS))
    result = _service(tmp_path, quiet).refresh(worksheet=sheet, write=True)

    assert result.ok and result.market is not None
    assert result.matches == [] and result.plan is None and not result.written
    assert sheet.reads == 0 and sheet.batches == []


def test_a_plugin_that_supplies_nothing_survives_the_not_docked_path(tmp_path):
    """
    Mutation survivor, pinned. The docked path returns before _finish when
    nothing supplies requirements; the NOT-docked path reaches _finish, and
    an `or` where an `and` belongs would ask for a supplier nobody offers.
    """
    from test_service import ROWS, docked_event, ev, make_journal, ryman_market_json, totals_grid

    from APITool.catalog import load_catalog
    from APITool.plugins.settlement.layout import SheetLayout
    from APITool.service import REASON_NOT_DOCKED, MarketRefreshService

    directory = make_journal(
        tmp_path,
        [docked_event(), ev("Undocked", StationName="Ryman Enterprise", MarketID=3226578176)],
        ryman_market_json(),
    )
    quiet = types.SimpleNamespace(supplies=lambda: {}, subscribes=lambda: [])
    service = MarketRefreshService(journal_dir=directory, catalog=load_catalog(),
                                   layout=SheetLayout(), plugin=quiet)
    sheet = _counting_sheet(totals_grid(ROWS))
    result = service.refresh(worksheet=sheet, write=True)

    assert result.reason == REASON_NOT_DOCKED
    assert result.snapshot is None and result.plan is None and not result.written
    assert sheet.reads == 0


def test_checked_at_is_now_when_the_refresh_succeeded_without_a_market_timestamp(tmp_path, monkeypatch):
    """
    Mutation survivor, pinned. The note stamp falls back to "now" only when
    the refresh SUCCEEDED and the market carries no timestamp; a flipped
    condition stamped failures and left successes blank, and no test had a
    successful refresh whose market lacked a timestamp.
    """
    from test_service import ROWS, totals_grid

    from APITool.market import Market
    from APITool.plugins.settlement.totals import TotalsTabReader
    from APITool.service import REASON_NO_MARKET_DATA, REASON_OK

    seen: list[str] = []
    probe = types.SimpleNamespace(
        supplies=lambda: {"requirements": lambda c: TotalsTabReader(c.worksheet, c.layout, c.catalog).read()},
        subscribes=lambda: [Subscription("probe", ("requirements",), lambda c: seen.append(c.checked_at))],
    )
    service = _service(tmp_path, probe)
    sheet = _counting_sheet(totals_grid(ROWS))

    monkeypatch.setattr(
        service, "current_market",
        lambda location: (Market(location.market_id, "Ryman Enterprise", "Lhou Mans", None, "journal", ()),
                          REASON_OK),
    )
    assert service.refresh(worksheet=sheet).ok
    assert seen and seen[0].endswith("UTC")

    seen.clear()
    monkeypatch.setattr(service, "current_market", lambda location: (None, REASON_NO_MARKET_DATA))
    assert not service.refresh(worksheet=sheet).ok
    assert seen == [""]


def test_no_plugin_at_all_still_reports_location_and_market(tmp_path):
    from test_service import ROWS, totals_grid

    sheet = _counting_sheet(totals_grid(ROWS))
    result = _service(tmp_path, None).refresh(worksheet=sheet)
    assert result.ok and result.market is not None and result.plan is None


def test_the_service_imports_no_plugin():
    import APITool.service as service

    source = Path(service.__file__).read_text(encoding="utf-8")
    assert "plugins.settlement" not in source


# ---------------------------------------------------------------------------
# R5: where a requirement came from
# ---------------------------------------------------------------------------


def test_a_requirement_read_from_a_sheet_says_where_it_came_from():
    from test_service import ROWS, FakeWorksheet, totals_grid

    from APITool.catalog import load_catalog
    from APITool.plugins.settlement.layout import SheetLayout
    from APITool.plugins.settlement.totals import TotalsTabReader

    layout = SheetLayout()
    snapshot = TotalsTabReader(FakeWorksheet(totals_grid(ROWS)), catalog=load_catalog()).read()
    first = snapshot.requirements[0]
    assert first.origin == f"{layout.totals_tab}!{layout.name_column}{first.row}"
    assert all(r.origin.endswith(str(r.row)) for r in snapshot.requirements)


def test_market_json_carries_origin_and_still_carries_row():
    from APITool.cli import _market_result_json
    from APITool.journal import LocationState
    from APITool.matcher import Match, MatchState, Requirement
    from APITool.service import RefreshResult

    requirement = Requirement(row=7, name="Biowaste", need=3, origin="Tab!B7")
    result = RefreshResult(location=LocationState(),
                           matches=[Match(requirement=requirement, state=MatchState.EMPTY)])
    row = _market_result_json(result)["matches"][0]
    assert row["row"] == 7
    assert row["origin"] == "Tab!B7"


def test_a_requirement_built_without_a_source_has_an_empty_origin():
    from APITool.matcher import build_requirements

    assert build_requirements([(1, "Steel", 2)])[0].origin == ""


def test_a_configured_targets_name_prefixes_the_origin():
    """
    Slice C's half of R5: with configuration keyed by target, the locator
    names the target before the tab -- "settlement-workbook!Totals Tab!B12"
    -- and a reader given no target name writes the shorter form unchanged.
    """
    from test_service import ROWS, FakeWorksheet, totals_grid

    from APITool.catalog import load_catalog
    from APITool.plugins.settlement.layout import SheetLayout
    from APITool.plugins.settlement.totals import TotalsTabReader

    layout = SheetLayout()
    snapshot = TotalsTabReader(FakeWorksheet(totals_grid(ROWS)), catalog=load_catalog(),
                               target="settlement-workbook").read()
    first = snapshot.requirements[0]
    assert first.origin == f"settlement-workbook!{layout.totals_tab}!{layout.name_column}{first.row}"


def test_a_plugin_with_no_worksheet_still_has_its_subscriptions_pushed(tmp_path):
    """
    Core must not decide, on one kind's behalf, that there is nothing to
    publish. ``worksheet`` is the ``gsheet`` kind's handle; a plugin whose
    destination is a file has none, and used to have its subscriptions
    skipped entirely because ``refresh`` and ``_finish`` both returned early
    on it. The comparison still needs requirements -- that gate is right --
    but whether a subscription can run is the subscriber's question.
    """
    from test_service import docked_event, make_journal, ryman_market_json

    from APITool.catalog import load_catalog
    from APITool.plugins.settlement.layout import SheetLayout
    from APITool.registry import Subscription
    from APITool.service import MarketRefreshService

    pushed = []

    class FilePlugin:
        __name__ = "fileplugin"

        @staticmethod
        def supplies():
            return {}

        @staticmethod
        def subscribes():
            return [Subscription("appended", (), lambda ctx: pushed.append(ctx.env["result"]))]

    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    service = MarketRefreshService(journal_dir=directory, catalog=load_catalog(),
                                   layout=SheetLayout(), plugin=FilePlugin)
    result = service.refresh(worksheet=None)

    assert len(pushed) == 1, "a file destination's subscription must run without a worksheet"
    assert pushed[0] is result


def test_the_target_name_rides_the_refresh_to_the_reader(tmp_path):
    """The composition root names the target once; the refresh carries it to whoever reads."""
    from test_service import (ROWS, FakeWorksheet, docked_event, make_journal,
                              ryman_market_json, totals_grid)

    from APITool.catalog import load_catalog
    from APITool.plugins import settlement
    from APITool.plugins.settlement.layout import SheetLayout
    from APITool.service import MarketRefreshService

    directory = make_journal(tmp_path, [docked_event()], ryman_market_json())
    service = MarketRefreshService(journal_dir=directory, catalog=load_catalog(),
                                   layout=SheetLayout(), plugin=settlement, target="mine")
    result = service.refresh(worksheet=FakeWorksheet(totals_grid(ROWS)), show_covered=False)
    assert result.matches, "the fixture market must produce a comparison to look at"
    assert all(m.origin.startswith("mine!") for m in result.matches)
