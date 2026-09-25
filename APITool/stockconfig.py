"""
The stock configuration the tool writes the first time it runs (#30).

A fresh install has no ``config.json``. Before v0.7.5 a bare ``sheet_id``
was enough and the tool filled in the rest; removing that fallback was
right -- the core ships no destination -- but it left a new person
hand-writing nested JSON with nothing to copy from. So, like a freshly
installed web server, the tool writes itself a commented starting file the
first time any command runs and finds none, and says so in one line.

Two rules shape what is written:

**The plugin blocks are asked for, never restated.** Each shipped plugin's
``default_config()`` supplies its own block, so the stock file cannot drift
from what ``check_config()`` will accept. Only SHIPPED plugins are asked
(``APITool/plugins/*``), never a plugin from the person's own directory: on
a first run nothing has been enabled, and running a stranger's code to
write defaults would break the consent rule ``plugins`` keeps.

**The commentary is a header, not inline.** JSON has no comments, and the
tool rewrites the file whenever ``auth`` stores a client id, so the guidance
lives in ``#`` lines above the first brace, which ``settings.load`` strips and
``settings.save`` preserves. The design and its rejected alternatives are in
the vault (``how-the-stock-config-carries-its-comments``).

The write is skipped when :data:`GUARD_VAR` is set. The test suite sets it,
so no test writes a file it did not ask for; a script that wants a run
without side effects can set it too.
"""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from typing import Optional

from . import settings

# The maintainer's public template workbook (README, docs/google-sheets-setup.md).
# Reading it works for anyone; writing to it is expected to fail at the API
# with a permission error, which is the right failure and needs no code.
TEMPLATE_SHEET_ID = "1WACbf6u81fLIWsJVXsxUqYyIGZ0OCckN-Qb1FBgHAy0"
TEMPLATE_URL = f"https://docs.google.com/spreadsheets/d/{TEMPLATE_SHEET_ID}/edit"

GUARD_VAR = "ED_NO_STOCK_CONFIG"
# Two targets on the one template workbook: the roll-up tab and the
# construction blocks are two plugins from v0.8.0, each with its own block.
DEFAULT_TARGET = "totals-workbook"
DEFAULT_PLUGIN = "totals"
CONSTRUCTION_TARGET = "construction-workbook"
CONSTRUCTION_PLUGIN = "construction"
EXAMPLE_FILE_TARGET = "nightly-dump"
EXAMPLE_FILE_PLUGIN = "jsonl"


@dataclass(frozen=True)
class ShippedDefault:
    """One shipped plugin's own answer to "how would you like to be configured"."""

    name: str
    kind: str
    config: dict


def shipped_defaults() -> dict[str, ShippedDefault]:
    """
    Every shipped plugin's kind and ``default_config()``, by name.

    Imports the shipped plugins, and only them, for this one purpose. A
    plugin without ``default_config`` contributes nothing rather than a
    guess.
    """
    from . import loader

    out: dict[str, ShippedDefault] = {}
    for found in loader.scan(user_dir=None):
        if found.origin != loader.ORIGIN_SHIPPED:
            continue
        module = importlib.import_module(f"{loader.SHIPPED_PACKAGE}.{found.name}")
        default = getattr(module, "default_config", None)
        kind = getattr(module, "KIND", None)
        if default is None or kind is None:
            continue
        out[found.name] = ShippedDefault(found.name, kind, default())
    return out


def body(defaults: Optional[dict[str, ShippedDefault]] = None) -> dict:
    """The JSON the stock file holds: one working target, pointed at the template."""
    defaults = shipped_defaults() if defaults is None else defaults
    targets: dict = {}
    for target_name, plugin_name in ((DEFAULT_TARGET, DEFAULT_PLUGIN),
                                     (CONSTRUCTION_TARGET, CONSTRUCTION_PLUGIN)):
        shipped = defaults.get(plugin_name)
        if shipped is not None:
            targets[target_name] = {
                "kind": shipped.kind,
                "plugin": shipped.name,
                "id": TEMPLATE_SHEET_ID,
                "config": shipped.config,
            }
    return {"targets": targets}


def _commented(obj) -> str:
    """A JSON value as `#`-prefixed lines, for an example the file does not enable."""
    return "\n".join(f"#   {line}" for line in json.dumps(obj, indent=2).splitlines())


def header(defaults: Optional[dict[str, ShippedDefault]] = None) -> str:
    """The commentary above the first brace. Every key the body may hold, explained."""
    defaults = shipped_defaults() if defaults is None else defaults
    jsonl = defaults.get(EXAMPLE_FILE_PLUGIN)
    lines = [
        "# edapitool settings -- written by the tool on its first run.",
        "#",
        "# Everything below the comments is ordinary JSON. Comments are allowed",
        "# ONLY in this header, above the first brace; a '#' inside the JSON is",
        "# an error. The tool keeps this header when it rewrites the file, and",
        "# keeps the previous copy as config.json.bak. Outside JSON tools will",
        "# not accept the header; the JSON below it is what they want.",
        "#",
        "# Reference: docs/configuration.md. For any plugin's own settings:",
        "#   edapitool plugins describe <name>",
        "#",
        "# client_id   Your Frontier developer client id, saved by `edapitool auth`.",
        "#             The ED_CLIENT_ID environment variable overrides it.",
        "# sheet_id    A Google Sheet id for commands that publish a generated tab",
        "#             without any plugin. ED_SHEET_ID overrides it. It does not",
        "#             select a destination; targets do.",
        "# targets     The places the tool publishes to, keyed by a name YOU choose.",
        "#             Each target names its kind, its plugin, where it is, and the",
        "#             plugin's own config block:",
        "#   kind      \"gsheet\" (a Google Sheet, located by \"id\") or",
        "#             \"jsonl\" (a file on disk, located by \"path\").",
        "#   plugin    The plugin that serves it; `edapitool plugins` lists them.",
        "#   config    That plugin's own settings. The tool never reads inside it;",
        "#             the plugin checks it and reports what is wrong, naming the target.",
        "#",
        f"# The two targets below point at the PUBLIC TEMPLATE workbook: one for",
        "# the roll-up tab (plugin \"totals\", whose block names the template's",
        "# tab), one for the construction blocks (plugin \"construction\",",
        "# whose block lists the regions they go in):",
        f"#   {TEMPLATE_URL}",
        "# Reading it works for anyone, so the first run shows something real.",
        "# Writing to it (--update-sheet, serve) is EXPECTED TO FAIL with a",
        "# permission error: it is not yours. Make your own copy of it",
        "# (in Google Sheets: File > Make a copy) and put its id in \"id\" of both.",
    ]
    if jsonl is not None:
        lines += [
            "#",
            "# A second kind of target, kept as an example. Remove the '#' marks and",
            "# add it inside \"targets\" to append one JSON record per refresh to a file:",
            _commented({
                EXAMPLE_FILE_TARGET: {
                    "kind": jsonl.kind,
                    "plugin": jsonl.name,
                    "path": "~/edapitool/market.jsonl",
                    "config": jsonl.config,
                }
            }),
        ]
    lines.append("#")
    return "\n".join(lines) + "\n"


def render(defaults: Optional[dict[str, ShippedDefault]] = None) -> str:
    """The whole stock file: the header, then the body as strict JSON."""
    defaults = shipped_defaults() if defaults is None else defaults
    return header(defaults) + json.dumps(body(defaults), indent=2) + "\n"


def write_if_missing() -> Optional[str]:
    """
    Write the stock file when there is none, and say where it went.

    Returns the one line to print, or ``None`` when nothing was written:
    the file already exists, or :data:`GUARD_VAR` is set. Never overwrites.
    """
    if os.environ.get(GUARD_VAR):
        return None
    path = settings.CONFIG_FILE
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")
    return f"Wrote a starting configuration to {path} -- edit it, or keep the defaults."
