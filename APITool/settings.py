"""
User settings: the config file, and the precedence rules for reading it.

Distinct from ``config.py``, which holds protocol constants -- endpoints,
cooldowns, token filenames. Those describe how to talk to Frontier and do not
change. These are the preferences a person edits.

This module exists because the resolution logic had accreted inside the
argparse module, and had started duplicating itself: the config file's path
was being rebuilt in four places, and a second copy of the client-id resolver
appeared in the daemon. One place owns the file; one function owns each
precedence rule.

Two rules here are deliberate and must not drift:

**A flag wins outright over the file, never merging with it.** Merged sources
mean no single place explains what will happen.

**A malformed entry refuses the run and names itself.** An entry silently
skipped is a setting that quietly stops taking effect with nothing said.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Where this tool's own files live
# ---------------------------------------------------------------------------
#
# One directory, ``~/edapitool/``, rather than five dotfiles scattered through
# a home directory: the settings, the Frontier tokens, a person's own plugins,
# and the Google credentials. Five places to find is five places to forget
# when backing up, and -- the reason this was built when it was -- there was
# no single thing a test or a script could redirect, so any subprocess read
# the developer's real files however carefully the parent had been isolated.
#
# One rule and no search: ``ED_CONFIG_DIR`` when it is set, otherwise
# ``~/edapitool/``. There was briefly a fallback to the old home-directory
# dotfiles, for installs written before the move. There is exactly one
# install of this tool, its files were moved on 2026-09-19, and a code path
# that can never run is a code path that has to be maintained and cannot be
# tested honestly -- so it is gone rather than kept for a hypothetical user.
CONFIG_DIR_VAR = "ED_CONFIG_DIR"
CONFIG_DIR_NAME = "edapitool"

CONFIG_JSON = "config.json"
TOKENS_JSON = "tokens.json"
PLUGINS_DIR = "plugins"
GSHEET_CREDENTIALS = "gsheet_credentials.json"
GSHEET_TOKEN = "gsheet_token.json"


def config_dir() -> Path:
    """The directory holding everything this tool owns."""
    named = os.environ.get(CONFIG_DIR_VAR)
    if named:
        return Path(named).expanduser()
    return Path.home() / CONFIG_DIR_NAME


def resolve(name: str) -> Path:
    """Where one of this tool's files is. One rule, no search."""
    return config_dir() / name


def config_path() -> Path:
    """The settings file this run reads and writes."""
    return resolve(CONFIG_JSON)


def tokens_path() -> Path:
    """The Frontier OAuth token store."""
    return resolve(TOKENS_JSON)


def plugins_path() -> Path:
    """Where a person's own plugins live, before ``ED_PLUGIN_DIR`` is consulted."""
    return resolve(PLUGINS_DIR)


# Resolved once at import so that a name patched by a test stays patched, and
# so that one run cannot read two different files. Tests patch these names,
# and that redirection is only honest because nothing else builds the paths
# for itself.
CONFIG_FILE = config_path()
PLUGIN_DIR = plugins_path()


# The file is JSON with one concession: a HEADER of comment lines above the
# first brace, each starting with ``#``. It exists so the stock file the tool
# writes on first run can explain its own keys the way a stock Apache config
# does, and it is the only place a comment may go -- a ``#`` inside the body
# is a JSON error and is reported as one. ``load`` strips the header and
# ``save`` puts it back, so a person's commentary survives the tool's own
# writes. Outside JSON tools reject the file; docs/configuration.md says so.
COMMENT_PREFIX = "#"
BACKUP_SUFFIX = ".bak"

# Corrupt-file reports go out once per path per process. ``load`` is called
# by every precedence rule in turn, and one broken file should read as one
# warning, not five.
_reported: set[Path] = set()


def backup_path() -> Path:
    """Where the previous good copy of the settings file is kept."""
    return CONFIG_FILE.with_name(CONFIG_FILE.name + BACKUP_SUFFIX)


def _split_header(text: str) -> tuple[str, str]:
    """The leading comment lines (blank lines included), and the body after them."""
    lines = text.splitlines(keepends=True)
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith(COMMENT_PREFIX):
            break
        count += 1
    return "".join(lines[:count]), "".join(lines[count:])


def _parse(text: str) -> dict:
    """The settings in ``text``: the header dropped, an empty body read as nothing."""
    _, body = _split_header(text)
    if not body.strip():
        return {}
    data = json.loads(body)
    return data if isinstance(data, dict) else {}


def report_once(path: Path, message: str) -> None:
    """Say ``message`` once per process for ``path``; the store reuses this."""
    if path in _reported:
        return
    _reported.add(path)
    print(message, file=sys.stderr)


def _recover(exc: Exception) -> dict:
    """
    The settings file did not parse. Say so, and use the backup if it does.

    Returning ``{}`` silently was the old behaviour, and it is the wrong one:
    a person whose file has a stray comma sees the tool forget every setting
    with nothing said, and reports it as the tool losing their config. The
    backup is the previous good copy ``save`` keeps, so recovering from it
    is honest -- it is what the file held before the last write.
    """
    backup = backup_path()
    if backup.exists():
        try:
            data = _parse(backup.read_text(encoding="utf-8"))
            report_once(CONFIG_FILE,
                         f"Warning: {CONFIG_FILE} is not valid JSON ({exc}); "
                         f"using {backup.name} instead")
            return data
        except (json.JSONDecodeError, IOError):
            pass
    report_once(CONFIG_FILE,
                 f"Warning: {CONFIG_FILE} is not valid JSON ({exc}); "
                 f"no usable {backup.name}, running with no settings")
    return {}


def load() -> dict:
    """The saved settings, or an empty dict if there are none to read."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        text = CONFIG_FILE.read_text(encoding="utf-8")
    except IOError as exc:
        report_once(CONFIG_FILE, f"Warning: could not read {CONFIG_FILE}: {exc}")
        return {}
    try:
        return _parse(text)
    except json.JSONDecodeError as exc:
        return _recover(exc)


def save(key: str, value) -> bool:
    """
    Set one key, keeping everything else in the file -- and its header.

    Written to a temporary file in the same directory and moved into place,
    because this is a read-modify-write of a file the user edits BY HAND. It
    holds construction region bindings somebody typed; a write interrupted
    halfway through would take them with it, and there is no copy anywhere.
    ``os.replace`` is atomic on the same filesystem, so a reader sees either
    the old file or the new one and never a truncated one.

    The previous file is kept as ``config.json.bak`` first -- but only when
    it parsed. A corrupt file must not overwrite the good backup that
    ``load`` has just recovered from.
    """
    header, previous, good = "", None, False
    if CONFIG_FILE.exists():
        try:
            previous = CONFIG_FILE.read_text(encoding="utf-8")
            header, _ = _split_header(previous)
            _parse(previous)
            good = True
        except json.JSONDecodeError:
            good = False
        except IOError:
            previous = None
    data = load()
    data[key] = value
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    try:
        tmp.write_text(header + json.dumps(data, indent=2) + "\n", encoding="utf-8")
        if previous is not None and good:
            backup_path().write_text(previous, encoding="utf-8")
        os.replace(tmp, CONFIG_FILE)
        return True
    except (IOError, OSError) as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        print(f"Warning: Could not save {key} to config: {exc}",
              file=sys.stderr)
        return False


def get_client_id() -> Optional[str]:
    """The Frontier OAuth client id, from the environment or the file."""
    client_id = os.environ.get("ED_CLIENT_ID")
    if client_id:
        return client_id
    return load().get("client_id")


def get_sheet_id(args: Optional[argparse.Namespace] = None) -> Optional[str]:
    """
    Resolve the spreadsheet id: a flag, the environment, the first sheet
    target's ``id``, then the bare ``sheet_id`` key.

    The last step is not a leftover. ``sheet_id`` says WHERE, and a target
    says WHO -- the commands that publish a generated tab without any plugin
    at all need the first and have no use for the second, so a person who
    has never installed a destination still has a way to name a workbook.
    A configured target's ``id`` wins because it is the more specific
    statement of the same fact.
    """
    if getattr(args, "sheet_id", None):
        return args.sheet_id
    env = os.environ.get("ED_SHEET_ID")
    if env:
        return env
    for target in _targets_or_empty().values():
        if target.kind == "gsheet" and target.params.get("id"):
            return target.params["id"]
    return load().get("sheet_id")


def _targets_or_empty() -> dict:
    """
    The targets map for a caller that only wants one value out of it.

    A malformed map is reported, by name, by the destination resolver that
    every publishing command goes through. Here it would turn a command that
    merely wants a sheet id into a traceback, so it reads as no targets.
    """
    try:
        return get_targets()
    except ValueError:
        return {}


def get_plugin_dir() -> Path:
    """The user plugin directory: the environment, the file, or the default."""
    env = os.environ.get("ED_PLUGIN_DIR")
    if env:
        return Path(env).expanduser()
    saved = load().get("plugin_dir")
    if saved is not None:
        # Refused rather than coerced: a number or an empty string here is a
        # setting that would quietly point at the wrong place.
        if not isinstance(saved, str) or not saved:
            raise ValueError(f'"plugin_dir" must be a non-empty string, got {saved!r}')
        return Path(saved).expanduser()
    return PLUGIN_DIR


@dataclass(frozen=True)
class Target:
    """
    One named place the tool publishes to, as configuration describes it.

    ``kind`` says what it is -- a Google sheet, a file -- and selects both the
    adapter that talks to it and the enforcer that bounds what may be written.
    ``plugin`` names the code that knows its shape. Everything else in the
    entry belongs to that plugin and is not read here.
    """

    name: str
    kind: str
    plugin: str
    # The plugin's own block, handed over unread. Its shape is the plugin's
    # to know; nothing in this module names a key inside it.
    config: dict = field(default_factory=dict)
    # The kind's own keys -- ``id`` for a sheet, ``path`` for a file -- kept
    # for the adapter that kind selects. Not interpreted here.
    params: dict = field(default_factory=dict)


def get_targets() -> dict[str, Target]:
    """
    The configured targets, keyed by the name the person gave each one::

        "targets": {
          "settlement-workbook": {
            "kind": "gsheet", "id": "1WACbf...", "plugin": "settlement",
            "config": { ... whatever that plugin reads ... }
          }
        }

    Keyed by a name rather than a sheet id or a path because a name survives
    a person moving to a different workbook or reorganising a drive, and it
    is what the observation store will key provenance on. Order is kept: the
    first entry is the one single-destination commands talk to.

    Three keys are read: ``kind``, ``plugin`` and ``config``. ``config`` must
    be an object when present and is carried over whole; every other key is
    the kind's and is carried in ``params``.

    Raises ValueError naming the offending entry, for the reason the module
    docstring gives: a target that is silently skipped is a destination that
    quietly stops being published.
    """
    raw = load().get("targets")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f'"targets" must be an object, got {type(raw).__name__}')

    out: dict[str, Target] = {}
    for name, entry in raw.items():
        where = f"targets[{name!r}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be an object, got {type(entry).__name__}")
        kind = entry.get("kind")
        plugin = entry.get("plugin")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f'{where} has no "kind"')
        if not isinstance(plugin, str) or not plugin:
            raise ValueError(f'{where} has no "plugin"')
        config = entry.get("config", {})
        if not isinstance(config, dict):
            raise ValueError(f"{where}.config must be an object, got {type(config).__name__}")
        params = {k: v for k, v in entry.items() if k not in ("kind", "plugin", "config")}
        out[str(name)] = Target(str(name), kind, plugin, dict(config), params)
    return out


# There was, briefly, a ``default_target()`` here: a bare ``sheet_id`` was
# aliased to one ``gsheet`` target named ``default``, served by whichever
# plugin the loader happened to find first, so that a file written before
# ``targets`` existed kept its destination. It is gone, and the reason is
# worth keeping. It existed for installs that predate v0.7.4; there is
# exactly one install of this tool, its configuration was rewritten into the
# ``targets`` shape on 2026-09-19, and nobody else has a file to migrate. A
# code path that can never run again is one that still has to be maintained,
# still has to be reasoned about at every change, and can never be tested
# against the thing it claims to serve.
#
# Removing it is also what makes #18's sixth criterion true rather than
# nearly true: with the alias in place, a configuration that named no target
# still got one, so "the core ships no destination" was a sentence the code
# contradicted.
