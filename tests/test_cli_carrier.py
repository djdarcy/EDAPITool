"""
CLI tests for `edapitool carrier --export google`.

This file exists because of a gap an acceptance check found, not because
somebody planned it. `carrier --export google` is the command issue #19 names
by name -- "writes an Updated (UTC) stamp into FreighterData" -- and it was
the one carrier path with no test at all.

The metadata row (#19) was wired into the daemon's publisher and NOT into this
command, so the CLI wrote an empty stamp. Nothing noticed, for a reason worth
recording: the live verification ran `export_cargo(...)` DIRECTLY with the
argument filled in, which proved the grid builder and never touched
`cmd_carrier`. A green result that could not have been red.

So these tests drive `main(["carrier", ...])` through the real parser and the
real command, with only the network edges stubbed.
"""

import argparse

import pytest

from APITool import settings
from APITool.cli import main

CALLSIGN = "Q9G-6HX"


# ---------------------------------------------------------------------------
# Doubles. Only the three edges that leave the machine are replaced: Frontier
# auth, the Frontier client, and the Sheets writer. Everything between them --
# argument parsing, flag handling, sheet-id resolution, grid construction --
# is the real code, which is the whole point of testing here rather than at
# the exporter.
# ---------------------------------------------------------------------------

CARRIER_PAYLOAD = {
    "name": {"callsign": CALLSIGN, "vanityName": "", "filteredVanityName": ""},
    "currentStarSystem": "Col 285 Sector ZG-T c4-10",
    "state": "normalOperation",
    "dockingAccess": "all",
    "notoriousAccess": False,
    "finance": {},
    "cargo": [
        {"commodity": "Aluminium", "locName": "Aluminium", "qty": 1751,
         "value": 3715622, "stolen": False, "mission": False},
        {"commodity": "Biowaste", "locName": "Biowaste", "qty": 840,
         "value": 84000, "stolen": False, "mission": False},
    ],
}


class FakeExporter:
    """Records exactly what `export_cargo` was called with."""

    seen: dict = {}

    def export_cargo(self, carrier, sheet_id, tab_name="FreighterData",
                     include_stolen=False, include_mission=False,
                     checked_at="", changed_at=""):
        FakeExporter.seen = {
            "sheet_id": sheet_id,
            "tab_name": tab_name,
            "checked_at": checked_at,
            "changed_at": changed_at,
            "callsign": carrier.identity.callsign,
        }


@pytest.fixture
def carrier_cli(monkeypatch, tmp_path):
    """The carrier command with its three network edges stubbed."""
    import APITool.cli as cli_mod
    import APITool.google as google_mod

    # No real config, no real credentials, no real home directory.
    monkeypatch.setattr(settings, "CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    monkeypatch.setenv("ED_CLIENT_ID", "test-client-id")

    monkeypatch.setattr(cli_mod, "setup_auth", lambda *a, **k: object())

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def get_fleet_carrier(self):
            return CARRIER_PAYLOAD

    monkeypatch.setattr(cli_mod, "CAPIClient", FakeClient)
    monkeypatch.setattr(
        google_mod, "GoogleSheetsExporter", lambda *a, **k: FakeExporter()
    )
    FakeExporter.seen = {}
    return FakeExporter


# ---------------------------------------------------------------------------
# The gap itself
# ---------------------------------------------------------------------------

def test_carrier_export_google_sends_a_last_checked_stamp(carrier_cli):
    """
    #19's first criterion, driven through the command it actually names.

    Before this, `cmd_carrier` called `export_cargo` without `checked_at`, so
    the tab's `Last checked` cell was written EMPTY by the one command a user
    runs by hand -- while the daemon filled it correctly. The tab said nothing
    about its own age precisely when somebody had gone looking.
    """
    assert main(["carrier", "--export", "google", "--sheet-id", "S1"]) == 0

    seen = carrier_cli.seen
    assert seen["checked_at"], (
        "carrier --export google wrote an empty Last checked stamp"
    )
    # ISO-8601 to the second, with an explicit offset: the offset is what
    # keeps the UTC anchor readable after Sheets stores it as text.
    assert seen["checked_at"].endswith("+00:00")
    assert "T" in seen["checked_at"]


def test_a_one_shot_export_leaves_last_changed_blank(carrier_cli):
    """
    It has no memory of a previous reading, so it cannot know when the hold
    last changed -- and must say "not known" rather than guess. Only `serve`,
    which sees successive readings, can fill this.
    """
    main(["carrier", "--export", "google", "--sheet-id", "S1"])
    assert carrier_cli.seen["changed_at"] == ""


def test_the_stamp_is_taken_at_fetch_time_not_write_time(carrier_cli,
                                                         monkeypatch):
    """
    #19's second criterion: "the time the data was fetched, not the time the
    sheet was written, if those differ."

    The two are milliseconds apart in a normal run, so asserting on them
    directly would pass whichever line took the stamp -- the test would prove
    nothing. This forces a gap instead: parsing the payload is made to take
    50ms, and the gap lands between the fetch and the write. A stamp taken at
    fetch time is measurably OLDER than the write; one taken just before the
    export is not.
    """
    import time
    from datetime import datetime, timezone

    from APITool.models import FleetCarrier

    real_from_capi = FleetCarrier.from_capi

    def slow_parse(data):
        time.sleep(0.05)
        return real_from_capi(data)

    monkeypatch.setattr(FleetCarrier, "from_capi", staticmethod(slow_parse))

    main(["carrier", "--export", "google", "--sheet-id", "S1"])
    wrote_at = datetime.now(timezone.utc)

    checked_at = datetime.fromisoformat(carrier_cli.seen["checked_at"])
    gap = (wrote_at - checked_at).total_seconds()
    assert gap >= 0.04, (
        f"stamp is only {gap:.3f}s older than the write -- it was taken at "
        f"write time, not when Frontier answered"
    )


# ---------------------------------------------------------------------------
# Guards: things that were already true and must stay true
# ---------------------------------------------------------------------------

def test_the_destination_tab_is_not_user_selectable(carrier_cli):
    """
    The write allowlist is a second line of defence; this is the first. There
    is no flag aiming this command at another tab, so a user cannot reach the
    refusal by typo. Asserted so a future flag addition has to be deliberate.
    """
    parser = argparse.ArgumentParser()
    main(["carrier", "--export", "google", "--sheet-id", "S1"])
    assert carrier_cli.seen["tab_name"] == "FreighterData"
    del parser


def test_the_configured_sheet_id_is_honoured_without_a_flag(carrier_cli,
                                                            monkeypatch):
    """v0.6.3's fix, still holding: ED_SHEET_ID is enough on its own."""
    monkeypatch.setenv("ED_SHEET_ID", "FROM-ENV")
    assert main(["carrier", "--export", "google"]) == 0
    assert carrier_cli.seen["sheet_id"] == "FROM-ENV"
