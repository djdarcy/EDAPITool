"""
The configuration surface carries no spreadsheet knowledge -- check C4.

The code probe measured 0 leaks in code from v0.7.0; the configuration
surface was never measured, and #27 named what lived there. The probe
``probe_no_config_knowledge.py`` counts two things: keys core parses that it
does not own, and sheet strings the documented examples put anywhere but
inside a target's ``config`` block. The tree-level test asserts 0; the unit
tests plant one of each and assert the probe sees it, so a green tree is
known to be a measured zero and not a probe that cannot see.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests" / "one-offs" / "thinking" / "plugin-isolation" / "probe_no_config_knowledge.py"


def _probe():
    spec = importlib.util.spec_from_file_location("probe_no_config_knowledge", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_configuration_surface_measures_zero():
    proc = subprocess.run([sys.executable, str(PROBE)], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stdout


def test_settings_reads_only_the_keys_core_owns():
    probe = _probe()
    source = (ROOT / "APITool" / "settings.py").read_text(encoding="utf-8")
    assert probe.core_leaks(source) == []
    assert {k for _, k in probe.keys_read(source)} <= probe.CORE_READS


def test_a_plugin_key_read_in_core_is_seen():
    """Red-green for the first half: plant one read and the count is 1."""
    probe = _probe()
    source = (ROOT / "APITool" / "settings.py").read_text(encoding="utf-8")
    planted = source + '\n\ndef _planted(entry):\n    return entry.get("region")\n'
    assert [k for _, k in probe.core_leaks(planted)] == ["region"]


def test_a_sheet_string_outside_a_config_block_is_seen():
    """Red-green for the second half, in every position it could hide."""
    probe = _probe()
    top_level = {"sheet_id": "X", "construction_regions": [{"region": "Agri Lrg. (ex)!R1:AC60"}]}
    whys = [why for _, why in probe.example_leaks(top_level)]
    assert any("does not own" in why for why in whys)
    assert any("sheet string" in why for why in whys)

    in_entry = {"targets": {"mine": {"kind": "gsheet", "plugin": "p", "regions": ["Totals Tab!L3:L"]}}}
    assert [path for path, _ in probe.example_leaks(in_entry)] == ["targets.mine.regions.[0]"]

    inside_config = {"targets": {"mine": {"kind": "gsheet", "plugin": "p", "id": "X",
                                          "config": {"construction_regions": [
                                              {"region": "Agri Lrg. (ex)!R1:AC60"}]}}}}
    assert probe.example_leaks(inside_config) == []


def test_an_example_the_probe_cannot_parse_counts():
    probe = _probe()
    assert probe.parse_example('{"sheet_id": "X", // a comment\n "targets": {}}') == {"sheet_id": "X", "targets": {}}
    assert probe.parse_example('{"sheet_id": ...}') is None


def test_the_deprecated_exemption_is_explicit_and_never_silent():
    """
    Documenting the shape we moved away from is legitimate, and the exemption
    must be spelled in the example a reader sees -- not held in the probe,
    where it would be an allowlist nobody reviews. Every use is printed.
    """
    probe = _probe()
    assert probe.marked_deprecated("// deprecated: the old shape\n{}")
    assert not probe.marked_deprecated("// the old shape\n{}")
    assert not probe.marked_deprecated('{"sheet_id": "X"}')

    proc = subprocess.run([sys.executable, str(PROBE)], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8")
    exempt = [ln for ln in proc.stdout.splitlines() if "docs/configuration.md" in ln]
    assert exempt, "an exemption that is taken must be reported"
    assert "exempt" in proc.stdout


def test_only_examples_of_the_config_file_are_judged():
    """The tokens file and Frontier's payloads are documented too; they are not this surface."""
    probe = _probe()
    tokens = {"access_token": "a", "refresh_token": "b", "expires_at": 1}
    assert probe.example_leaks(tokens) == []
    # A block made only of a plugin's keys is still judged when it shows a sheet.
    plugin_only = {"construction_regions": [{"region": "Agri Lrg. (ex)!R1:AC60"}]}
    assert len(probe.example_leaks(plugin_only)) == 2
