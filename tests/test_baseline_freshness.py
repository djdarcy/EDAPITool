"""The cargo-contract baseline must refuse to compare against a stale capture.

Why this test is in tests/ while the harness it guards is in one-offs
--------------------------------------------------------------------
``tests/one-offs/thinking/cargo-contract/baseline.py`` needs a live
spreadsheet and credentials, so it can never be an ordinary pytest. But its
*freshness guard* is pure -- it decides from a dict and a sha string whether a
comparison would mean anything -- and that half runs every build.

The guard exists because the instrument had already failed silently. The
snapshot sat in the tree from 2026-09-08 through v0.5.0, v0.5.1, v0.5.2 and
v0.6.0 carrying no provenance whatsoever, so a comparison would have measured
a post-refactor build against a v0.4.1-era capture and reported either a false
green or a false red with equal confidence. An instrument that cannot be wrong
out loud is worse than no instrument.
"""

import importlib.util
from pathlib import Path

import pytest

HARNESS = (
    Path(__file__).resolve().parent
    / "one-offs" / "thinking" / "cargo-contract" / "baseline.py"
)


def _load_harness():
    spec = importlib.util.spec_from_file_location("_cargo_baseline", HARNESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    if not HARNESS.is_file():
        pytest.skip(f"harness not present at {HARNESS}")
    return _load_harness()


SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"


def _snapshot(harness, **meta_overrides):
    meta = {
        "format": harness.SNAPSHOT_FORMAT,
        "sha": SHA,
        "captured_at": "2026-09-14T00:00:00+00:00",
        "cells": 1,
    }
    meta.update(meta_overrides)
    return {"meta": meta, "values": {"Totals Tab!D0|Aluminium": "1"}}


def test_a_matching_sha_is_fresh(harness):
    fresh, message = harness.check_snapshot_fresh(_snapshot(harness), SHA)
    assert fresh is True
    assert SHA[:12] in message


def test_a_different_sha_is_refused_and_names_both(harness):
    fresh, message = harness.check_snapshot_fresh(_snapshot(harness), OTHER)
    assert fresh is False
    assert SHA[:12] in message
    assert OTHER[:12] in message


def test_the_legacy_shape_with_no_meta_is_refused(harness):
    """The exact shape of the file this guard replaced: a flat value map."""
    legacy = {"Totals Tab!D0|Aluminium": "1", "Totals Tab!I0|Aluminium": "2"}
    fresh, message = harness.check_snapshot_fresh(legacy, SHA)
    assert fresh is False
    assert "provenance" in message.lower()


def test_an_unknown_format_version_is_refused(harness):
    fresh, message = harness.check_snapshot_fresh(
        _snapshot(harness, format=harness.SNAPSHOT_FORMAT + 1), SHA
    )
    assert fresh is False
    assert "format" in message.lower()


def test_a_snapshot_with_no_sha_is_refused(harness):
    fresh, message = harness.check_snapshot_fresh(_snapshot(harness, sha=""), SHA)
    assert fresh is False
    assert "commit" in message.lower()


def test_an_unknown_head_refuses_rather_than_guessing(harness):
    """git unavailable must not be read as 'probably fine'."""
    fresh, message = harness.check_snapshot_fresh(_snapshot(harness), "")
    assert fresh is False
    assert "refusing" in message.lower()
