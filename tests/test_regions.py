"""
Native regions (#34, slice 2's unit 0): a `regions` key the tool owns on a
target, read by settings, bound by APITool.regions, and seen by the overlap
check. Smokes; the regions plugin's own parser tests still run through its
shim (tests/test_region_binder.py).
"""

import json

import pytest

from APITool import loader, regions, settings


def _config(monkeypatch, tmp_path, body):
    directory = tmp_path / "cfg"
    directory.mkdir()
    (directory / "config.json").write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setenv("ED_CONFIG_DIR", str(directory))
    monkeypatch.setattr(settings, "CONFIG_FILE", directory / "config.json")


def test_a_target_may_bind_regions_with_no_plugin(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, {"targets": {"my-workbook": {
        "kind": "gsheet", "id": "FAKE_SHEET_ID_NEVER_CONTACTED",
        "regions": [{"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux"},
                    {"region": "Hauling!H1:N200", "data": "market"}],
    }}})
    targets = settings.get_targets()
    target = targets["my-workbook"]
    assert target.plugin == "" and len(target.regions) == 2
    bound = regions.bindings_for(target)
    assert [(b.destination.tab, b.data, b.site) for b in bound] == [
        ("Agri Lrg. (ex)", "construction", "Badeaux"), ("Hauling", "market", None)]
    assert regions.declarations_for(target) == {"Agri Lrg. (ex)": ["R1:AC60"], "Hauling": ["H1:N200"]}
    # Nothing is enabled by a plugin-less target; the loader does not trip on it.
    assert loader.enabled_from(targets, []) == []


def test_a_malformed_region_refuses_the_run_by_name(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, {"targets": {"my-workbook": {
        "kind": "gsheet", "id": "X", "regions": [{"region": "Hauling!H1:N200", "data": "weather"}],
    }}})
    with pytest.raises(ValueError, match=r"targets\['my-workbook'\]\.regions\[0\]"):
        settings.get_targets()


def test_a_target_with_neither_plugin_nor_regions_is_refused(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, {"targets": {"empty": {"kind": "gsheet", "id": "X"}}})
    with pytest.raises(ValueError, match="names nothing to do"):
        settings.get_targets()


def test_the_overlap_check_sees_a_region_over_a_plugins_declared_range():
    """The finding local_2026.09.26_02: the check was blind to regions. Now it is not."""
    from types import SimpleNamespace

    plugin = loader.Loaded(name="totals", module=None, found=None, kind="gsheet",
                           declaration={"Totals Tab": ["L3", "L5:L"]})
    target = SimpleNamespace(name="my-workbook", kind="gsheet",
                             regions=[{"region": "Totals Tab!L4:M10", "data": "market"}])
    found = loader.conflicts([plugin], {"my-workbook": target})
    assert found and found[0].first == "totals" and found[0].second == "my-workbook"
