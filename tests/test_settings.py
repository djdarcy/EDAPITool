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
import subprocess
import sys
from pathlib import Path

import pytest

from APITool import settings

PACKAGE = Path(settings.__file__).parent
ROOT = PACKAGE.parent
MODULES = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in str(p))


# --- the two structural guards --------------------------------------------

def test_only_one_module_builds_the_config_path():
    """
    Four modules built this path independently before the extraction. Each
    copy is a place a patched CONFIG_FILE silently fails to reach.

    Checked by the two things a path is actually built FROM -- the directory
    name and the environment variable that overrides it -- rather than by
    the word "edapitool", which also spells the program's own name.
    """
    builders = [p.relative_to(PACKAGE).as_posix() for p in MODULES
                if "CONFIG_DIR_NAME" in p.read_text(encoding="utf-8")
                or "ED_CONFIG_DIR" in p.read_text(encoding="utf-8")]
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


# --- a broken file is reported and recovered, never silently forgotten ----

HEADER = "# The tool wrote this file.\n# Edit the JSON below the comments.\n\n"


def test_a_comment_header_is_ignored_by_load_and_kept_by_save(config):
    """
    The stock file explains its keys in `#` lines above the first brace.
    They must be invisible to the parser and survive the tool's own writes,
    or the first `auth` would erase the commentary the first run wrote.
    """
    config.write_text(HEADER + json.dumps({"sheet_id": "SHEET"}), encoding="utf-8")

    assert settings.load() == {"sheet_id": "SHEET"}
    assert settings.save("client_id", "CID") is True

    text = config.read_text(encoding="utf-8")
    assert text.startswith(HEADER), text
    assert settings.load() == {"sheet_id": "SHEET", "client_id": "CID"}
    assert json.loads(text[len(HEADER):]) == settings.load()


def test_every_save_keeps_the_previous_file_as_a_backup(config):
    config.write_text(json.dumps({"client_id": "FIRST"}), encoding="utf-8")
    settings.save("sheet_id", "S1")
    backup = settings.backup_path()
    assert json.loads(backup.read_text(encoding="utf-8")) == {"client_id": "FIRST"}

    settings.save("sheet_id", "S2")
    assert json.loads(backup.read_text(encoding="utf-8")) == {
        "client_id": "FIRST", "sheet_id": "S1"}


def test_a_corrupt_file_is_reported_and_the_backup_is_used(config, capsys):
    """
    A stray comma used to read as "no settings at all", silently. The person
    then saw the tool forget their sheet and their client id with nothing
    said. Now the file is named, the error is named, and the last good copy
    is what the run uses.
    """
    settings.backup_path().write_text(json.dumps({"sheet_id": "GOOD"}), encoding="utf-8")
    config.write_text('{"sheet_id": "BROKEN",}', encoding="utf-8")

    assert settings.load() == {"sheet_id": "GOOD"}
    err = capsys.readouterr().err
    assert str(config) in err and "not valid JSON" in err and ".bak" in err, err


def test_a_corrupt_file_with_no_backup_is_reported_and_reads_as_empty(config, capsys):
    config.write_text("not json at all", encoding="utf-8")

    assert settings.load() == {}
    err = capsys.readouterr().err
    assert "not valid JSON" in err and "no usable" in err, err


def test_a_corrupt_file_is_reported_once_not_once_per_lookup(config, capsys):
    """Every precedence rule calls load(); one broken file is one warning."""
    config.write_text("{", encoding="utf-8")
    settings.load()
    settings.load()
    settings.get_client_id()
    assert capsys.readouterr().err.count("not valid JSON") == 1


def test_saving_over_a_corrupt_file_does_not_overwrite_the_good_backup(config, capsys):
    """
    The backup is what recovery reads. Copying a broken file over it on the
    way to fixing it would destroy the one good copy at the moment it
    mattered.
    """
    settings.backup_path().write_text(json.dumps({"sheet_id": "GOOD"}), encoding="utf-8")
    config.write_text("{ broken", encoding="utf-8")

    assert settings.save("client_id", "CID") is True
    assert json.loads(settings.backup_path().read_text(encoding="utf-8")) == {"sheet_id": "GOOD"}
    assert settings.load() == {"sheet_id": "GOOD", "client_id": "CID"}


def test_a_body_that_is_valid_json_but_not_an_object_reads_as_nothing(config):
    """
    A file holding `[]` or `"text"` is JSON and is not settings. Pinned from
    mutation survivor M03 (v0.7.8): the guard existed before the header work
    and nothing had ever exercised it.
    """
    config.write_text(HEADER + "[1, 2, 3]", encoding="utf-8")
    assert settings.load() == {}
    config.write_text('"just a string"', encoding="utf-8")
    assert settings.load() == {}


def test_a_comment_inside_the_body_is_a_json_error(config, capsys):
    """Comments live above the first brace and nowhere else; the docs say so."""
    config.write_text('{\n  # not allowed here\n  "sheet_id": "S"\n}', encoding="utf-8")
    assert settings.load() == {}
    assert "not valid JSON" in capsys.readouterr().err


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


# ---------------------------------------------------------------------------
# where the tool's own files live
# ---------------------------------------------------------------------------
#
# Nothing here touches a real home directory: every test points `Path.home`
# at a tmp_path, so a resolver that ignored its inputs would reach a
# directory that does not exist rather than the developer's own files.


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    # Both spellings of "home": `Path.home()` reads these env vars on the
    # platforms we run on, and so does `expanduser`. Patching only the
    # method would leave `~` expanding to the developer's real directory --
    # which is the exact failure this whole change exists to prevent.
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(settings.Path, "home", staticmethod(lambda: home))
    monkeypatch.delenv("ED_CONFIG_DIR", raising=False)
    return home


def test_everything_this_tool_owns_is_in_one_directory(fake_home):
    """
    Five dotfiles scattered through a home directory is five things to find
    and five things to back up. One rule, no search: they are all here.
    """
    assert settings.config_path() == fake_home / "edapitool" / "config.json"
    assert settings.tokens_path() == fake_home / "edapitool" / "tokens.json"
    assert settings.plugins_path() == fake_home / "edapitool" / "plugins"


def test_a_file_in_the_old_home_location_is_not_looked_for(fake_home):
    """
    There was briefly a fallback to the pre-2026-09-19 dotfiles. It is gone:
    a path that can never be taken cannot be tested honestly, and there is
    no install left that needs it. A stray dotfile is simply ignored.
    """
    stray = fake_home / ".ed_capi_config.json"
    stray.write_text("{}", encoding="utf-8")
    assert settings.config_path() == fake_home / "edapitool" / "config.json"


def test_an_explicit_directory_wins_outright_and_never_falls_back(fake_home, monkeypatch, tmp_path):
    """
    The same rule the flags follow: an explicit setting is the complete
    answer, not one merged with the file. A redirect that quietly fell back
    to the real home is exactly how a test subprocess reads the developer's
    own configuration -- which is the gap this closes.
    """
    (fake_home / ".ed_capi_config.json").write_text("{}", encoding="utf-8")
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("ED_CONFIG_DIR", str(scratch))

    assert settings.config_path() == scratch / "config.json"
    assert settings.tokens_path() == scratch / "tokens.json"
    assert settings.plugins_path() == scratch / "plugins"


def test_the_explicit_directory_expands_a_home_relative_path(fake_home, monkeypatch):
    monkeypatch.setenv("ED_CONFIG_DIR", "~/elsewhere")
    assert settings.config_path() == fake_home / "elsewhere" / "config.json"


def test_a_subprocess_can_be_isolated_by_the_environment_alone(tmp_path):
    """
    The incident this closes, 2026-09-18: a checklist step ran the CLI as a
    subprocess, and the in-process redirect every other test relies on does
    not cross a process boundary, so it read the developer's own settings.
    One environment variable now redirects every file this tool owns.

    Structurally safe (rule 1b): the child's HOME and USERPROFILE point at a
    scratch directory too, so a resolver that ignored ED_CONFIG_DIR entirely
    would reach an empty scratch home rather than anyone's real files -- the
    assertion can fail, but it cannot read what it is asserting is unread.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "config.json").write_text(json.dumps({"client_id": "FROM-SCRATCH"}),
                                         encoding="utf-8")
    decoy_home = tmp_path / "not-a-real-home"
    decoy_home.mkdir()

    env = {**os.environ, "ED_CONFIG_DIR": str(scratch),
           "HOME": str(decoy_home), "USERPROFILE": str(decoy_home)}
    env.pop("ED_CLIENT_ID", None)
    proc = subprocess.run(
        [sys.executable, "-c",
         "from APITool import settings;"
         "print(settings.config_path());print(settings.get_client_id())"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")

    assert proc.returncode == 0, proc.stderr
    reported, client_id = proc.stdout.splitlines()[:2]
    assert Path(reported) == scratch / "config.json"
    assert client_id == "FROM-SCRATCH", "the child read the directory it was pointed at"


def test_the_plugin_directorys_own_override_still_wins(fake_home, monkeypatch, tmp_path):
    """`ED_PLUGIN_DIR` predates this and keeps working, over both locations."""
    monkeypatch.setenv("ED_PLUGIN_DIR", str(tmp_path / "plugs"))
    assert settings.get_plugin_dir() == tmp_path / "plugs"


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
