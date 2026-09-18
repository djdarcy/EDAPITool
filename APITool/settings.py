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

# The one place this path is constructed. Tests patch this name, and that
# redirection is only honest because nothing else builds the path for itself.
CONFIG_FILE = Path.home() / ".ed_capi_config.json"
# Where a person's own plugins live. Beside the config file, for the same
# reason the config file is where it is: one dotfile location to remember.
PLUGIN_DIR = Path.home() / ".ed_capi_plugins"


def load() -> dict:
    """The saved settings, or an empty dict if there are none to read."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, IOError):
        return {}
    return data if isinstance(data, dict) else {}


def save(key: str, value) -> bool:
    """
    Set one key, keeping everything else in the file.

    Written to a temporary file in the same directory and moved into place,
    because this is a read-modify-write of a file the user edits BY HAND. It
    holds construction region bindings somebody typed; a write interrupted
    halfway through would take them with it, and there is no copy anywhere.
    ``os.replace`` is atomic on the same filesystem, so a reader sees either
    the old file or the new one and never a truncated one.
    """
    data = load()
    data[key] = value
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2))
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
    target's ``id``, then the bare ``sheet_id`` key every install before
    v0.7.4 wrote.
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


# The keys this module reads at the top level. Everything else in a file
# that predates ``targets`` belongs to the default target's plugin.
CORE_KEYS = frozenset({"client_id", "sheet_id", "plugin_dir", "targets"})


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


def default_target(plugin: str) -> Optional[Target]:
    """
    The target a file written before ``targets`` existed resolves to, or None.

    A bare ``sheet_id`` -- the shape every install before v0.7.4 wrote -- is
    a deprecated alias for one ``gsheet`` target named ``default``, served by
    the shipped plugin the loader names. Every top-level key this module does
    not own travels into that target's ``config`` block, where the plugin
    reads it; nothing here says what those keys are. A file with a
    ``targets`` map is never aliased: the map is the whole configuration.
    A file with neither is not a target at all, and the loader's own rule
    for that case applies.
    """
    data = load()
    if data.get("targets") is not None:
        return None
    extra = {k: v for k, v in data.items() if k not in CORE_KEYS}
    sheet_id = data.get("sheet_id") or os.environ.get("ED_SHEET_ID")
    if not sheet_id and not extra:
        return None
    return Target("default", "gsheet", plugin, extra, {"id": sheet_id} if sheet_id else {})
