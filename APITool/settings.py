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
from dataclasses import dataclass
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
    """Resolve the spreadsheet id from args, environment, or saved config."""
    if getattr(args, "sheet_id", None):
        return args.sheet_id
    env = os.environ.get("ED_SHEET_ID")
    if env:
        return env
    return load().get("sheet_id")


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


def get_targets() -> dict[str, Target]:
    """
    The configured targets, keyed by the name the person gave each one::

        "targets": {
          "settlement-workbook": {"kind": "gsheet", "plugin": "settlement"}
        }

    Keyed by a name rather than a sheet id or a path because a name survives
    a person moving to a different workbook or reorganising a drive, and it
    is what the observation store will key provenance on. Order is kept: the
    first entry is the one single-destination commands talk to.

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
        out[str(name)] = Target(str(name), kind, plugin)
    return out


def parse_region_spec(spec: str):
    """
    Read the command-line form: ``Tab!R1:AC60`` or ``Tab!R1:AC60=Site Name``.

    A command line has to be one string, so the site is appended after '='.
    The config file uses an object instead -- a hand-edited JSON file should
    not make anyone pack two delimiters into one value where a typo surfaces
    only at runtime. One internal shape, two spellings, each suited to where
    it is written.
    """
    from .sheets import Destination

    target, _, site = str(spec).partition("=")
    return Destination.parse(target), (site.strip() or None)


def get_construction_regions(args: argparse.Namespace) -> list:
    """
    Which construction regions to keep current, and where that was decided.

    Command line wins outright when given -- an explicit flag should never be
    silently merged with saved settings, because then no single place tells
    you what will happen. Otherwise the config file, whose entries are
    objects::

        "construction_regions": [
          {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"}
        ]

    ``site`` may be omitted, meaning "whichever site I am docked at".

    Raises ValueError naming the offending entry, because a malformed
    binding that is silently skipped is a region that quietly stops being
    published -- the exact failure this whole surface exists to prevent.
    """
    from .sheets import Destination

    specs = list(getattr(args, "construction_region", None) or [])
    if specs:
        return [parse_region_spec(s) for s in specs]

    out = []
    for i, entry in enumerate(load().get("construction_regions") or []):
        where = f"construction_regions[{i}]"
        if isinstance(entry, str):
            # Tolerated so a value can be pasted straight from the flag.
            out.append(parse_region_spec(entry))
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be an object or a string, got "
                             f"{type(entry).__name__}")
        if "region" not in entry:
            raise ValueError(f'{where} has no "region"')
        out.append((Destination.parse(entry["region"]),
                    (entry.get("site") or None)))
    return out
