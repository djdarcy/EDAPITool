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


def test_the_overlap_check_compares_against_the_tab_the_target_configures(monkeypatch, tmp_path):
    """
    The v0.10.1 checklist's step 3.2, live: a region over `Totals Tab!L3:L10`
    was not reported, because the loaded plugin's declaration named its own
    default tab (`Totals`) while the target configured `Totals Tab`. The
    declaration the overlap check sees must be the configured layout's.
    """
    _config(monkeypatch, tmp_path, {"targets": {
        "totals-workbook": {"kind": "gsheet", "plugin": "totals", "id": "X",
                            "config": {"totals_tab": "Totals Tab"}},
        "my-workbook": {"kind": "gsheet", "id": "X",
                        "regions": [{"region": "Totals Tab!L3:L10", "data": "market"}]},
    }})
    result = loader.discover(severity=loader.SEVERITY_WARN)
    assert result.loaded[0].declaration.get("Totals Tab"), result.loaded[0].declaration
    assert result.conflicts and result.conflicts[0].first == "totals"
    assert result.conflicts[0].second == "my-workbook"


def test_serve_reads_regions_from_a_plugin_less_target(monkeypatch, tmp_path, capsys):
    """
    #34 criterion 2 for serve: a binding on the target reaches the daemon
    with no regions plugin loaded at all. Rule 1b: the daemon builder is
    captured and raises, so nothing runs.
    """
    from test_config_regions import Captured, capture_build

    from APITool.cli import main

    _config(monkeypatch, tmp_path, {"targets": {"my-workbook": {
        "kind": "gsheet", "id": "FAKE_SHEET_ID_NEVER_CONTACTED",
        "regions": [{"region": "Hauling!H1:N200", "data": "market"},
                    {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux"}],
    }}})
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    seen = capture_build(monkeypatch)
    with pytest.raises(Captured):
        main(["serve", "--journal-dir", str(tmp_path)])
    assert [(b.destination.tab, b.data) for b in seen["region_bindings"]] == [
        ("Hauling", "market"), ("Agri Lrg. (ex)", "construction")]
    assert "Traceback" not in capsys.readouterr().out
