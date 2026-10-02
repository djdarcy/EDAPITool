"""
Making a settlement tab: the template, the copy, the seed.

A settlement tab in the workbook this plugin serves has no hand-entered
input but one block -- the construction data the ``regions`` plugin writes
into it once the site exists in the game. Every other cell is a formula over
that block. So a tab for a site that does not exist yet needs exactly one
thing: that block, seeded from the requirements matrix in the shape the
live site will later overwrite. The grid comes from the same builder the
live publisher uses, so the tab's formulas cannot tell the two apart.

The template is a hidden copy of an existing settlement tab with its block
and title cleared, made once; each new tab is a copy of the template. The
workbook's own formulas travel in the copy and never through this code.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Sequence

from ...construction import ConstructionResource, ConstructionSite, normalize
from ...export import construction_region_rows
from ...sheets import Destination, WriteGuard
from .base import normalise_type

#: The State cell of a seeded block. A planned site is neither active nor
#: complete, and the builder has no word for it; this one is written after.
PLANNED = "planned"
_STATE_COLUMN = 4   # row 2 of the block: name, system, market id, stamp, STATE, ...
_MARKET_ID_COLUMN = 2


@dataclass(frozen=True)
class Plan:
    """What one ``new`` would do: the tab, the two ranges, and what goes in them."""

    tab: str
    region: str
    title_cell: str
    title: str
    grid: list
    commodities: int

    def describe(self) -> list[str]:
        return [
            f"tab        {self.tab!r} (a copy of the template)",
            f"title      {self.title_cell} = {self.title!r}",
            f"block      {self.region}: {self.commodities} commodities, seeded as a planned site",
        ]


def seed_grid(type_name: str, requirements: Sequence[tuple[str, int]], *,
              site: str = "", system: str = "") -> list[list]:
    """
    The block for a site that does not exist yet, in the live block's shape.

    Built through ``construction_region_rows`` from a synthetic site whose
    every commodity is required and none provided, then marked planned.
    """
    resources = tuple(
        ConstructionResource(symbol=normalize(name), name=name, required=count, provided=0, payment=0)
        for name, count in requirements
    )
    planned = ConstructionSite(market_id=None, timestamp=None, progress=0.0, resources=resources)
    where = SimpleNamespace(short_station=site, system=system)
    rows = construction_region_rows(planned, where)
    rows[1][_STATE_COLUMN] = PLANNED
    if rows[1][_MARKET_ID_COLUMN] is None:
        rows[1][_MARKET_ID_COLUMN] = ""
    return rows


def plan(layout: Any, name: str, type_name: str, requirements: Sequence[tuple[str, int]], *,
         site: str = "", system: str = "") -> Plan:
    return Plan(
        tab=name,
        region=layout.region,
        title_cell=layout.title_cell,
        title=f"Settlement {normalise_type(type_name)}",
        grid=seed_grid(type_name, requirements, site=site or name, system=system),
        commodities=len(requirements),
    )


def guard_for(the_plan: Plan) -> WriteGuard:
    """The bound core builds for this run: the new tab's two ranges, nothing else."""
    return WriteGuard.build({the_plan.tab: [the_plan.region, the_plan.title_cell]})


def find_tab(spreadsheet: Any, title: str) -> Any:
    for worksheet in spreadsheet.worksheets():
        if worksheet.title == title:
            return worksheet
    return None


def ensure_template(spreadsheet: Any, layout: Any) -> Any:
    """
    The hidden template, made from the source tab the first time it is needed.

    The copy keeps every formula and format of the source; its block and its
    title are cleared so no settlement's data travels into the next tab.
    """
    existing = find_tab(spreadsheet, layout.template_tab)
    if existing is not None:
        return existing
    source = find_tab(spreadsheet, layout.source_tab)
    if source is None:
        raise ValueError(
            f"no tab named {layout.source_tab!r} to make the template from; "
            "name an existing settlement tab in the target's \"source_tab\""
        )
    template = spreadsheet.duplicate_sheet(source.id, new_sheet_name=layout.template_tab)
    template.batch_clear([layout.region, layout.title_cell])
    template.hide()
    return template


def drop_template(spreadsheet: Any, layout: Any) -> bool:
    """Remove the template so the next ``ensure_template`` remakes it; says whether one was there."""
    existing = find_tab(spreadsheet, layout.template_tab)
    if existing is None:
        return False
    spreadsheet.del_worksheet(existing)
    return True


def new_tab(spreadsheet: Any, layout: Any, name: str) -> Any:
    """A visible copy of the template under ``name``; refuses a name that is taken."""
    if find_tab(spreadsheet, name) is not None:
        raise ValueError(f"a tab named {name!r} already exists")
    template = find_tab(spreadsheet, layout.template_tab)
    if template is None:
        raise ValueError(f"no template tab {layout.template_tab!r}; ensure_template first")
    created = spreadsheet.duplicate_sheet(template.id, new_sheet_name=name)
    # A copy of a hidden sheet is hidden. gspread has hide() and no unhide();
    # the API's own request shows it.
    spreadsheet.batch_update({"requests": [{
        "updateSheetProperties": {
            "properties": {"sheetId": created.id, "hidden": False},
            "fields": "hidden",
        }
    }]})
    return created


def write(the_plan: Plan, exporter: Any, sheet_id: str) -> None:
    """The seed, then the title, each through the exporter's guard."""
    exporter.export_grid(the_plan.grid, sheet_id=sheet_id,
                         tab_name=Destination.region(the_plan.tab, the_plan.region))
    exporter.export_grid([[the_plan.title]], sheet_id=sheet_id,
                         tab_name=Destination.region(the_plan.tab, the_plan.title_cell))
