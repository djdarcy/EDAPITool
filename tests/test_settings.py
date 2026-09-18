"""
One module owns the config file, and two structural guards keep it that way.

Both guards here are structural rather than behavioural, and that is the
point. The defect they fence is SILENT: when four modules each rebuilt
``Path.home() / ".ed_capi_config.json"`` for themselves, a test that patched
one module's ``CONFIG_FILE`` looked like it had redirected the config file and
had not. Such a test does not fail -- it reads the developer's real settings
and passes or fails according to whose machine it runs on. No behavioural
assertion can tell "redirected" apart from "read the real file and happened to
find nothing", so the assertion has to be about the shape of the code.
"""

import ast
import json
import os
from pathlib import Path

import pytest

from APITool import settings

PACKAGE = Path(settings.__file__).parent
MODULES = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in str(p))


# --- the two structural guards --------------------------------------------

def test_only_one_module_builds_the_config_path():
    """
    Four modules built this path independently before the extraction. Each
    copy is a place a patched CONFIG_FILE silently fails to reach.
    """
    builders = [p.relative_to(PACKAGE).as_posix() for p in MODULES
                if 'Path.home() / ".ed_capi_config.json"' in
                p.read_text(encoding="utf-8")]
    assert builders == ["settings.py"], (
        f"the config path is constructed in {builders}; it belongs in "
        "settings.py alone, or patching settings.CONFIG_FILE stops meaning "
        "what it appears to mean")


def test_no_production_module_imports_the_cli():
    """
    The CLI may import the package; the package may not import the CLI.

    This is why configuration moved to a third module rather than the daemon
    importing it from `cli`: the daemon needed the client-id resolver, could
    not reach it, and grew its own copy instead.
    """
    offenders = []
    for path in MODULES:
        if path.name == "cli.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "") == "cli":
                offenders.append(path.relative_to(PACKAGE).as_posix())
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith("APITool.cli"):
                        offenders.append(path.relative_to(PACKAGE).as_posix())
    assert offenders == [], f"these modules import the CLI: {offenders}"


# --- saving must not be able to destroy what it did not write -------------

@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    return path


def test_saving_one_key_keeps_the_rest_of_the_file(config):
    config.write_text(json.dumps({
        "sheet_id": "SHEET",
        "construction_regions": [{"region": "Tab!A1:B2", "site": "Somewhere"}],
    }), encoding="utf-8")

    assert settings.save("client_id", "CID") is True

    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["client_id"] == "CID"
    assert data["sheet_id"] == "SHEET"
    assert data["construction_regions"] == [
        {"region": "Tab!A1:B2", "site": "Somewhere"}]


def test_a_failed_save_leaves_the_existing_file_untouched(config, monkeypatch):
    """
    The file holds region bindings typed by hand and copied nowhere. A
    read-modify-write that fails partway through would take them with it,
    which is why the write lands on a temporary file and is moved into place.
    """
    original = {
        "client_id": "OLD",
        "construction_regions": [{"region": "Tab!A1:B2", "site": "Somewhere"}],
    }
    config.write_text(json.dumps(original), encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    assert settings.save("client_id", "NEW") is False

    # Still parseable, still the old contents, and the binding survived.
    assert json.loads(config.read_text(encoding="utf-8")) == original


def test_a_failed_save_leaves_no_temporary_file_behind(config, monkeypatch):
    config.write_text(json.dumps({"client_id": "OLD"}), encoding="utf-8")
    monkeypatch.setattr(os, "replace",
                        lambda src, dst: (_ for _ in ()).throw(OSError("no")))

    settings.save("client_id", "NEW")

    strays = [p.name for p in config.parent.iterdir() if p.name.endswith(".tmp")]
    assert strays == [], f"left behind: {strays}"


def test_saving_into_a_directory_with_no_file_yet_works(config):
    assert not config.exists()
    assert settings.save("client_id", "CID") is True
    assert json.loads(config.read_text(encoding="utf-8")) == {"client_id": "CID"}


# --- every verb resolves the sheet id the same way ------------------------
#
# `carrier --export google` used to check `args.sheet_id` RAW, so it ignored
# both ED_SHEET_ID and the config file while market, construction, serve and
# ship all honoured them. Nobody chose that; it is what four independent call
# sites drift into, and it is the concrete argument for one resolver.
#
# These drive the real CLI. `setup_auth` is stubbed to raise, which is not
# tidiness: reaching it means a Frontier login attempt over the network. The
# assertion "we got past the sheet-id check" must not be able to perform the
# thing it is asserting we got to.


class ReachedAuth(Exception):
    """Raised by the stub to prove the sheet-id gate let us through."""


@pytest.fixture
def carrier_cli(config, monkeypatch):
    """Run `carrier --export google` with no network and no real settings."""
    from APITool import cli

    def no_network(*a, **k):
        raise ReachedAuth()

    monkeypatch.setattr(cli, "setup_auth", no_network)
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    monkeypatch.setenv("ED_CLIENT_ID", "CID-FOR-TEST")

    def run():
        return cli.main(["carrier", "--export", "google"])
    return run


def test_carrier_refuses_when_no_sheet_id_exists_anywhere(carrier_cli, capsys):
    assert carrier_cli() == 1
    out = capsys.readouterr().out
    assert "--sheet-id" in out
    assert "ED_SHEET_ID" in out, "the message must name the environment variable"
    assert "sheet_id" in out, "and the config key"


def test_carrier_honours_a_sheet_id_from_the_config_file(carrier_cli, config,
                                                         capsys):
    config.write_text(json.dumps({"sheet_id": "FROM-CONFIG"}), encoding="utf-8")
    with pytest.raises(ReachedAuth):
        carrier_cli()
    assert "needs a spreadsheet" not in capsys.readouterr().out


def test_carrier_honours_ED_SHEET_ID(carrier_cli, monkeypatch, capsys):
    monkeypatch.setenv("ED_SHEET_ID", "FROM-ENV")
    with pytest.raises(ReachedAuth):
        carrier_cli()
    assert "needs a spreadsheet" not in capsys.readouterr().out


def test_carrier_honours_the_first_sheet_targets_id(carrier_cli, config, capsys):
    """Since v0.7.4 a target's ``id`` is where a sheet id lives; the bare key is the alias."""
    config.write_text(json.dumps({"targets": {
        "mine": {"kind": "gsheet", "plugin": "settlement", "id": "FROM-TARGET"},
    }}), encoding="utf-8")
    with pytest.raises(ReachedAuth):
        carrier_cli()
    assert "needs a spreadsheet" not in capsys.readouterr().out


def test_the_first_sheet_targets_id_wins_over_the_bare_key(config, monkeypatch):
    """A file target in front of it is not a sheet and is passed over."""
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    config.write_text(json.dumps({"sheet_id": "BARE", "targets": {
        "file": {"kind": "jsonl", "plugin": "dump", "path": "out.jsonl"},
        "mine": {"kind": "gsheet", "plugin": "settlement", "id": "FROM-TARGET"},
    }}), encoding="utf-8")
    assert settings.get_sheet_id() == "FROM-TARGET"


def test_a_malformed_targets_map_does_not_turn_a_sheet_id_lookup_into_a_traceback(
        config, monkeypatch):
    """
    The destination resolver reports the malformed map by name; a command
    that only wants a sheet id reads it as no targets and falls through to
    the bare key rather than crashing on somebody else's entry.
    """
    monkeypatch.delenv("ED_SHEET_ID", raising=False)
    config.write_text(json.dumps({"sheet_id": "BARE",
                                  "targets": {"mine": {"kind": "gsheet"}}}), encoding="utf-8")
    assert settings.get_sheet_id() == "BARE"
