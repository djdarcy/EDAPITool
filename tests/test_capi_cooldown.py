"""
The fleet-carrier cooldown is ours, and it has to be said out loud.

Frontier does not enforce a 15-minute gap between fleet-carrier queries --
measured 2026-09-14: two calls one second apart both succeeded in about a
second and returned byte-identical cached data. `FLEETCARRIER_COOLDOWN` is
therefore politeness, not a limit anyone imposes.

That makes it something a long-running publisher may legitimately lower. The
defect these fence is how it was lowered before: the daemon built a fresh
CAPIClient inside every publish, so the guard's counter restarted from zero
each time and the 15 minutes never once applied. The limit was being skipped
by accident, in a way nothing named and no test would have noticed.
"""

import pytest

from APITool.capi import CAPIClient, CAPIRateLimitError
from APITool.config import FLEETCARRIER_COOLDOWN


class StubAuth:
    """Enough of FrontierAuth to construct a client. Never used: no request
    is made by any test here."""

    access_token = "not-a-real-token"
    is_authenticated = True


def test_the_default_cooldown_is_still_the_polite_fifteen_minutes():
    """Lowering it must be a decision, never the default."""
    assert CAPIClient(StubAuth()).fleet_carrier_cooldown == FLEETCARRIER_COOLDOWN
    assert FLEETCARRIER_COOLDOWN == 900


def test_a_second_carrier_query_inside_the_cooldown_is_refused():
    client = CAPIClient(StubAuth())
    client._last_fc_query_time = client._last_query_time = 1e12
    with pytest.raises(CAPIRateLimitError):
        client._check_rate_limit(is_fleet_carrier=True)


def test_a_caller_can_lower_the_cooldown_deliberately():
    """
    What the daemon does, and the point of the parameter: one client for the
    process's life, with the floor it actually intends.
    """
    client = CAPIClient(StubAuth(), fleet_carrier_cooldown=60)
    assert client.fleet_carrier_cooldown == 60
    # Nothing queried yet, so nothing to wait for.
    client._check_rate_limit(is_fleet_carrier=True)


def test_the_lowered_cooldown_is_enforced_rather_than_merely_recorded():
    """
    The failure mode being fenced is a limit that exists as an attribute and
    is never consulted -- which is what the per-call client amounted to.
    """
    import time

    client = CAPIClient(StubAuth(), fleet_carrier_cooldown=60)
    client._last_fc_query_time = time.time()
    with pytest.raises(CAPIRateLimitError):
        client._check_rate_limit(is_fleet_carrier=True)

    client._last_fc_query_time = time.time() - 61
    client._check_rate_limit(is_fleet_carrier=True)


def test_the_daemon_builds_one_client_and_lowers_it_to_its_own_floor():
    """
    Structural: the carrier publisher must not construct a client per call.
    Doing so restarts the cooldown counter every time, which is how the guard
    came to be inert -- a bug invisible from either side on its own.
    """
    import inspect

    from APITool import daemon as mod

    whole = inspect.getsource(mod.build)
    source = whole[whole.index("def _make_carrier_publisher("):]
    where_publish = source.index("def publish() -> PublishResult:")
    before = source[:where_publish]
    assert "CAPIClient(auth, fleet_carrier_cooldown=" in before, (
        "the client must be built once, outside publish(), with an explicit "
        "cooldown -- a per-call client silently disables the guard")
    assert "CAPIClient(" not in source[where_publish:], (
        "a client is still being constructed inside publish()")
