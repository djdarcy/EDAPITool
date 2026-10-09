"""
The settlement plugin: a settlement tab from a template, seeded from the matrix.

A command, not a step. It runs when a person asks, through
``edapitool plugins settlement new``, and never during a refresh. What the
loader asks of a plugin, and what this one answers:

    KIND                  "gsheet" -- the tabs it makes are on a Google sheet
    layout(**overrides)   the five names in the target's config: the matrix
                          tab, the source tab the template is made from, the
                          template tab, the block's range, the title cell
    writes()              nothing as shipped: the tab it writes to does not
                          exist until the command runs, so the bound is built
                          then, for that tab alone
    commands()            `new` -- make a tab for a settlement that does not
                          exist in the game yet
    default_config()      the five names, with the template workbook's values
    check_config(config)  what is wrong with a block, or nothing

It offers no step and no suppliers, so the market pipeline leaves it out.
The workbook's formulas live in the workbook: the template is a copy of a
real settlement tab, and the only thing this plugin writes is the block
those formulas read, in the shape the live site will later overwrite.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any, Optional

from ...registry import Command
from ...sheets import CellRange
from . import base as base_mod
from . import tabs as tabs_mod

# A Google sheet: the tabs this plugin makes are on one.
KIND = "gsheet"

KEYS = ("base_tab", "source_tab", "template_tab", "region", "title_cell")


@dataclass(frozen=True)
class SettlementLayout:
    """Where things are in the workbook this plugin serves. Every value is the workbook's own word."""

    base_tab: str = "Base"
    source_tab: str = "Agri Lrg. (ex)"
    template_tab: str = "_settlement template"
    region: str = "R1:AC60"
    title_cell: str = "C3"

    def writes(self) -> dict[str, list[str]]:
        """Nothing at load: the tab this plugin writes is named when the command runs."""
        return {}


def layout(**overrides) -> SettlementLayout:
    values = {k: v for k, v in overrides.items() if k in KEYS and v is not None}
    return SettlementLayout(**values)


def writes() -> dict[str, list[str]]:
    return {}


def default_config() -> dict:
    """A starter block: the template workbook's own names."""
    defaults = SettlementLayout()
    return {key: getattr(defaults, key) for key in KEYS}


def check_config(config: Optional[dict]) -> list[str]:
    """What is wrong with a target's block, as plain sentences; nothing when nothing is."""
    problems: list[str] = []
    if not config:
        return problems
    for key in KEYS:
        if key in config and (not isinstance(config[key], str) or not config[key].strip()):
            problems.append(f'"{key}" must be a non-empty string')
    for key in ("region", "title_cell"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            try:
                CellRange.parse(value)
            except Exception as exc:  # noqa: BLE001 -- the parser's own wording is the complaint
                problems.append(f'"{key}" is not a range: {exc}')
    return problems


# -- the command --------------------------------------------------------------

def _open(sheet_id: str) -> Any:
    """The workbook, through the tool's own client. Tests replace this; nothing else does."""
    from ...google import GoogleSheetsExporter

    return GoogleSheetsExporter()._get_client().open_by_key(sheet_id)


def _exporter(guard) -> Any:
    """A writer bound to one run's guard. Tests replace this; nothing else does."""
    from ...google import GoogleSheetsExporter

    return GoogleSheetsExporter(region_guard=guard)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edapitool plugins settlement new",
        description="Make a tab for a settlement that does not exist in the game yet: a copy "
                    "of the template, titled, with its block seeded from the requirements matrix.",
    )
    parser.add_argument("--type", required=True, metavar="TYPE",
                        help='a settlement type as the matrix names it, e.g. "industrial large"')
    parser.add_argument("--name", required=True, metavar="TAB", help="the new tab's name")
    parser.add_argument("--site", default="", help="the site's name, for the block's header (default: the tab's name)")
    parser.add_argument("--system", default="", help="the star system, for the block's header")
    parser.add_argument("--dry-run", action="store_true", help="say what would be made and make nothing")
    parser.add_argument("--refresh-template", action="store_true",
                        help="remake the hidden template from the source tab first")
    return parser


def _new(tail: list[str], target: Any) -> int:
    args = _parser().parse_args(tail)
    config = getattr(target, "config", None) or {}
    the_layout = layout(**config)
    sheet_id = (getattr(target, "params", None) or {}).get("id")
    if not sheet_id:
        print(f"Error: target {getattr(target, 'name', '?')!r} names no spreadsheet (\"id\").")
        return 1

    spreadsheet = _open(sheet_id)
    try:
        grid = spreadsheet.worksheet(the_layout.base_tab).get_values()
    except Exception as exc:  # noqa: BLE001 -- the workbook's state, reported by name
        print(f"Error: could not read the {the_layout.base_tab!r} tab: {exc}")
        return 1
    try:
        matrix = base_mod.parse_matrix(grid)
        requirements = matrix.requirements(args.type)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    if not requirements:
        print(f"Error: the matrix lists nothing for {args.type!r}; nothing to seed.")
        return 1

    # The plan and its bound first, the tab last: a refused range or a taken
    # name creates nothing.
    the_plan = tabs_mod.plan(the_layout, args.name, args.type, requirements,
                             site=args.site, system=args.system)
    try:
        guard = tabs_mod.guard_for(the_plan)
    except Exception as exc:  # noqa: BLE001 -- a bad range in the block, reported
        print(f"Error: the target's ranges cannot be guarded: {exc}")
        return 1
    if tabs_mod.find_tab(spreadsheet, args.name) is not None:
        print(f"Error: a tab named {args.name!r} already exists; nothing created.")
        return 1

    print(f"{args.type}: {the_plan.commodities} commodities from {the_layout.base_tab!r}")
    for line in the_plan.describe():
        print(f"  {line}")
    if args.dry_run:
        print("Dry run: nothing created.")
        return 0

    try:
        if args.refresh_template and tabs_mod.drop_template(spreadsheet, the_layout):
            print(f"  removed the old template {the_layout.template_tab!r}")
        before = tabs_mod.find_tab(spreadsheet, the_layout.template_tab) is not None
        tabs_mod.ensure_template(spreadsheet, the_layout)
        if not before:
            print(f"  made the hidden template {the_layout.template_tab!r} from {the_layout.source_tab!r}")
        tabs_mod.new_tab(spreadsheet, the_layout, args.name)
        tabs_mod.write(the_plan, _exporter(guard), sheet_id)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    binding = {"region": f"{args.name}!{the_layout.region}", "site": args.site or args.name}
    print(f"Created {args.name!r}.")
    print("To keep its block current once the site exists, add to your workbook target's \"regions\" list:")
    print(f"  {json.dumps(binding)}")
    print("Then add the tab to the Totals Tab's source list so the roll-up sees it.")
    return 0


def commands() -> dict[str, Command]:
    return {
        "new": Command("new", _new, "make a settlement tab from the template, seeded from the matrix",
                       safe_unconfigured=False),
    }


__all__ = [
    "KIND", "KEYS", "SettlementLayout",
    "check_config", "commands", "default_config", "layout", "writes",
]
