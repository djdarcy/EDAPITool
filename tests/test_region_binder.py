"""
A region can hold the market, cargo or carrier, not only a construction block (v0.8.2).

The `regions` plugin's bindings (the `construction` plugin's until v0.8.2) now
name their data. A market or cargo region
places the grid its tab's publisher built in the same pass -- no read and no
request of its own -- so it cannot disagree with the tab. These drive the real
``daemon.build`` with every outward edge replaced: the Google exporter class is
swapped out BEFORE ``build`` runs, so no test here can construct a real one
(rule 1b), and the service and journal watcher are fakes.
"""

from types import SimpleNamespace

import pytest

from APITool import daemon as daemon_mod
from APITool import google as google_mod
from APITool.daemon import CARGO_EVENTS, MARKET_EVENTS, PublishResult
from APITool.journal import LocationState
from APITool.plugins.regions import bindings, check_config
from APITool.service import RefreshResult
from APITool.sheets import Destination, WriteRefused

CARGO = {
    "timestamp": "2026-09-26T00:00:00Z", "event": "Cargo", "Vessel": "Ship", "Count": 12,
    "Inventory": [{"Name": "aluminium", "Name_Localised": "Aluminium", "Count": 12, "Stolen": 0}],
}


class FakeExporter:
    """Records every grid written, and the guard each writer was built with."""

    writes: list = []
    guards: list = []
    cargo_calls: list = []
    failing: set = set()          # region descriptions whose write raises

    def __init__(self, region_guard=None):
        self.region_guard = region_guard
        FakeExporter.guards.append(region_guard)

    def export_grid(self, grid, sheet_id=None, tab_name=None):
        if tab_name is not None and not isinstance(tab_name, str) \
                and tab_name.describe() in FakeExporter.failing:
            raise RuntimeError("the region is too small")
        FakeExporter.writes.append((tab_name, grid))
        return len(grid)

    def export_cargo(self, carrier, sheet_id=None, **kwargs):
        FakeExporter.cargo_calls.append((carrier, kwargs))
        return len(carrier.cargo)

    def worksheet(self, *a, **k):
        raise AssertionError("no test here asks for a worksheet")


@pytest.fixture
def world(monkeypatch):
    """A daemon built by the real build(), with fakes at every edge."""
    FakeExporter.writes, FakeExporter.guards = [], []
    FakeExporter.cargo_calls, FakeExporter.failing = [], set()
    state = {"cargo": CARGO, "station": "Ryman Enterprise"}

    class FakeService:
        def __init__(self, **_):
            self.reader = SimpleNamespace(read_cargo_json=lambda: state["cargo"])

        def refresh(self, **_):
            return RefreshResult(location=LocationState(
                system="Sol", docked=True, station=state["station"]))

    monkeypatch.setattr(google_mod, "GoogleSheetsExporter", FakeExporter)
    monkeypatch.setattr(daemon_mod, "MarketRefreshService", FakeService)
    monkeypatch.setattr(daemon_mod, "JournalWatcher",
                        SimpleNamespace(create=lambda _dir: object()))

    logged: list = []

    def build(*bindings_, carrier=False):
        worker = daemon_mod.build(
            sheet_id="FAKE-SHEET", layout=SimpleNamespace(totals_tab="Totals"),
            region_bindings=list(bindings_), publish_carrier=carrier,
            log=logged.append)
        return worker

    return SimpleNamespace(build=build, state=state, logged=logged)


def fake_cargo(name, quantity, value):
    return SimpleNamespace(commodity=name.lower(), localized_name=name, quantity=quantity,
                           value=value, stolen=False, mission=False)


CARRIER = SimpleNamespace(
    identity=SimpleNamespace(callsign="K7Q-1HT"),
    cargo=[fake_cargo("Steel", 1200, 1200 * 5000), fake_cargo("Aluminium", 800, 800 * 3000)],
)


@pytest.fixture
def frontier(monkeypatch):
    """A logged-in Frontier that answers with CARRIER. No request leaves the machine."""
    from APITool import auth as auth_mod
    from APITool import capi as capi_mod
    from APITool import models as models_mod

    monkeypatch.setattr(daemon_mod, "get_client_id", lambda: "fake-client")
    monkeypatch.setattr(auth_mod, "FrontierAuth",
                        lambda _cid: SimpleNamespace(is_authenticated=True))
    monkeypatch.setattr(capi_mod, "CAPIClient",
                        lambda *a, **k: SimpleNamespace(get_fleet_carrier=lambda: {}))
    monkeypatch.setattr(models_mod.FleetCarrier, "from_capi",
                        classmethod(lambda cls, raw: CARRIER))


def run_once(worker):
    """What `serve --once` does: every publisher, in the daemon's own order."""
    return [PublishResult.of(p.publish()) for p in worker.publishers()]


def region_writes(dest):
    return [grid for where, grid in FakeExporter.writes if where == dest]


def tab_writes(name):
    return [grid for where, grid in FakeExporter.writes if where == name]


# --- the daemon: a region places its tab's grid ----------------------------


def test_a_cargo_region_holds_exactly_the_cargo_tabs_grid(world):
    hold = Destination.parse("Hold!A1:F40")
    run_once(world.build(bindings.Binding(hold, None, "cargo")))
    tab, = tab_writes("ShipCargo")
    region, = region_writes(hold)
    assert region == tab
    assert any("Aluminium" in str(row) for row in region)


def test_a_market_region_holds_exactly_the_market_tabs_grid(world):
    corner = Destination.parse("Prices!H1:N200")
    run_once(world.build(bindings.Binding(corner, None, "market")))
    tab, = [grid for where, grid in FakeExporter.writes if where is None]
    region, = region_writes(corner)
    assert region == tab


def test_an_unchanged_region_is_not_rewritten_and_a_change_is(world):
    corner = Destination.parse("Prices!H1:N200")
    worker = world.build(bindings.Binding(corner, None, "market"))
    run_once(worker)
    run_once(worker)
    assert len(region_writes(corner)) == 1          # same market, one write
    world.state["station"] = "Somewhere Else"
    run_once(worker)
    assert len(region_writes(corner)) == 2          # moved: rewritten


def test_a_region_waits_for_its_tabs_first_read(world):
    """Asked before its tab has run, it writes nothing and says why."""
    hold = Destination.parse("Hold!A1:F40")
    worker = world.build(bindings.Binding(hold, None, "cargo"))
    region = worker.publishers()[-1]
    result = PublishResult.of(region.publish())
    assert region_writes(hold) == []
    assert "waiting for the first cargo read" in result.message


def test_a_region_runs_on_its_tabs_events_and_after_its_tab(world):
    market = bindings.Binding(Destination.parse("P!H1:N200"), None, "market")
    cargo = bindings.Binding(Destination.parse("H!A1:F40"), None, "cargo")
    worker = world.build(market, cargo)
    names = [p.name for p in worker.publishers()]
    by_name = {p.name: p for p in worker.publishers()}
    assert by_name["P!H1:N200"].triggers == MARKET_EVENTS
    assert by_name["H!A1:F40"].triggers == CARGO_EVENTS
    # Both tabs come before every region, which is what lets a region reuse
    # the grid its tab built in the same pass.
    assert names.index("market") < names.index("P!H1:N200")
    assert names.index("cargo") < names.index("H!A1:F40")


def test_each_region_writes_under_a_guard_of_its_own_bounds(world):
    hold = Destination.parse("Hold!A1:F40")
    world.build(bindings.Binding(hold, None, "cargo"))
    guard, = [g for g in FakeExporter.guards if g is not None]
    guard.check("Hold", "A1:F40")                   # its own rectangle: allowed
    with pytest.raises(WriteRefused):
        guard.check("Hold", "A1:G40")               # one column wider: refused


# --- the carrier: its regions follow its own publisher ----------------------


def test_a_carrier_region_holds_the_freighterdata_grid_with_the_tabs_stamps(world, frontier):
    """Same two functions export_cargo uses, same arguments, same stamps."""
    from APITool.google.exporter import carrier_grid, carrier_rows

    hold = Destination.parse("Carrier!A1:E300")
    worker = world.build(bindings.Binding(hold, None, "carrier"), carrier=True)
    carrier = next(p for p in worker.publishers() if p.name == "carrier")
    result = PublishResult.of(carrier.publish())

    (sent, kwargs), = FakeExporter.cargo_calls            # the tab was written
    region, = region_writes(hold)
    assert region == carrier_grid(carrier_rows(sent), checked_at=kwargs["checked_at"],
                                  changed_at=kwargs["changed_at"])
    assert any("Steel" in str(row) for row in region)
    assert "Carrier!A1:E300 <- " in result.message


def test_a_carrier_region_is_not_a_publisher_of_its_own(world, frontier):
    """It rides the carrier's floor, heartbeat and retries, so it cannot drift."""
    hold = Destination.parse("Carrier!A1:E300")
    worker = world.build(bindings.Binding(hold, None, "carrier"), carrier=True)
    assert [p.name for p in worker.publishers()] == ["market", "cargo", "carrier"]


def test_a_carrier_region_is_rewritten_with_every_carrier_check(world, frontier):
    """Like the tab: "Last checked" means when the tool last asked."""
    hold = Destination.parse("Carrier!A1:E300")
    worker = world.build(bindings.Binding(hold, None, "carrier"), carrier=True)
    carrier = next(p for p in worker.publishers() if p.name == "carrier")
    carrier.publish()
    carrier.publish()
    assert len(region_writes(hold)) == 2


def test_a_failing_carrier_region_is_reported_and_undoes_nothing(world, frontier):
    small = Destination.parse("Carrier!A1:E5")
    fine = Destination.parse("Other!A1:E300")
    FakeExporter.failing = {small.describe()}
    worker = world.build(bindings.Binding(small, None, "carrier"),
                         bindings.Binding(fine, None, "carrier"), carrier=True)
    carrier = next(p for p in worker.publishers() if p.name == "carrier")
    result = PublishResult.of(carrier.publish())
    assert len(FakeExporter.cargo_calls) == 1              # the tab still written
    assert len(region_writes(fine)) == 1                   # the other region too
    assert "! Carrier!A1:E5 failed" in result.message


def test_a_carrier_region_without_a_login_says_so_at_start(world, monkeypatch):
    monkeypatch.setattr(daemon_mod, "get_client_id", lambda: None)
    hold = Destination.parse("Carrier!A1:E300")
    worker = world.build(bindings.Binding(hold, None, "carrier"), carrier=True)
    assert "carrier" not in [p.name for p in worker.publishers()]
    assert any("NOT published: Carrier!A1:E300" in line and "Frontier login" in line
               for line in world.logged)


# --- the bindings: what a region may hold ---------------------------------


def test_a_binding_may_name_market_cargo_or_carrier():
    got = bindings.region_bindings({"bindings": [
        {"region": "P!H1:N200", "data": "market"},
        {"region": "H!A1:F40", "data": "cargo"},
        {"region": "C!A1:E300", "data": "carrier"},
    ]})
    assert [b.data for b in got] == ["market", "cargo", "carrier"]
    assert [b.site for b in got] == [None, None, None]


def test_an_unknown_data_kind_is_refused_and_names_the_kinds():
    with pytest.raises(ValueError) as excinfo:
        bindings.region_bindings({"bindings": [
            {"region": "P!H1:N200", "data": "journal"}]})
    message = str(excinfo.value)
    assert "bindings[0]" in message
    assert "construction, market, cargo, carrier" in message


def test_a_refused_data_value_is_quoted_as_the_json_the_person_typed():
    """Found by the v0.8.2 checklist sweep: a null showed as Python's None."""
    with pytest.raises(ValueError) as excinfo:
        bindings.region_bindings({"bindings": [
            {"region": "P!H1:N200", "data": None}]})
    assert '"data": null;' in str(excinfo.value)


def test_a_site_on_a_market_or_cargo_region_is_refused_not_ignored():
    with pytest.raises(ValueError) as excinfo:
        bindings.region_bindings({"bindings": [
            {"region": "H!A1:F40", "data": "cargo", "site": "Badeaux"}]})
    assert '"site"' in str(excinfo.value)


@pytest.mark.parametrize("entry", [
    {"region": "P!H1:N200", "data": "journal"},
    {"region": "H!A1:F40", "data": "cargo", "site": "Badeaux"},
    {"site": "no region"},
    {"region": "Just A Tab Name"},
    42,
])
def test_check_config_refuses_exactly_what_serve_refuses(entry):
    """One parser: a problem reported at load is the error serve would raise."""
    config = {"bindings": [entry]}
    with pytest.raises(ValueError) as excinfo:
        bindings.region_bindings(config)
    assert check_config(config) == [str(excinfo.value)]


def test_the_changelog_says_how_to_move_a_construction_target():
    """
    The rename is a break for a config file: a target naming the old plugin
    publishes nothing. The 0.8.2 entry must name both spellings of both words,
    so a person holding the old file can find the fix by searching for it.
    """
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    entry = re.search(r"## \[0\.8\.2\].*?(?=\n## \[)", text, re.S)
    assert entry, "CHANGELOG.md has no [0.8.2] entry"
    for needed in ('"plugin": "construction"', '"plugin": "regions"',
                   '"construction_regions"', '"bindings"'):
        assert needed in entry.group(0), needed


def test_check_config_accepts_what_serve_accepts():
    config = {"bindings": [
        {"region": "P!H1:N200", "data": "market"},
        {"region": "Agri!R1:AC60", "site": "Badeaux Nutrition Centre"},
        "Other!R1:AC60=Somewhere",
    ]}
    assert check_config(config) == []
    assert len(bindings.region_bindings(config)) == 3
