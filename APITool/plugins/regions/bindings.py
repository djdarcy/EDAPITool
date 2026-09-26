"""
Where this workbook's region bindings come from, and who wins.

A binding -- "keep the construction block in this region of this tab current,
for this site" -- is configuration in the doctrine's sense: it declares what
the tool may WRITE, authored by a person for this plugin. It lives in the
target's ``config`` block, which core hands over without reading; the shape of
that block is this plugin's to know, and this module is where it is known.

Moved verbatim from ``settings.py`` on 2026-09-18 (slice C of the migration),
so that core parses no key of a plugin's. The two rules the settings module
states still hold here and must not drift:

**A flag wins outright over the file, never merging with it.** Merged sources
mean no single place explains what will happen.

**A malformed entry refuses the run and names itself.** An entry silently
skipped is a region that quietly stops being published.

**A binding names its data** (v0.8.2). A region can hold a construction block,
the market, the ship's cargo, or the carrier's hold -- the same grid the tool already publishes as
a tab, placed in a region of a tab you keep. ``site`` chooses a build and means
nothing to the other kinds, so it is refused there rather than ignored. A test
of the plugin system: region binding is meant to move into the tool itself.
"""

from __future__ import annotations

import json
from typing import NamedTuple, Optional

# What a region can hold. Construction first: an entry that names no data is a
# construction block, which is what every binding meant before v0.8.2 -- one
# known configuration relied on it when this was written (2026-09-26), and the
# default goes when region binding moves into the tool.
DATA_KINDS = ("construction", "market", "cargo", "carrier")
DEFAULT_DATA = "construction"


class Binding(NamedTuple):
    """One region, what it holds, and -- for a construction block -- which build."""

    destination: object
    site: Optional[str]
    data: str = DEFAULT_DATA


def parse_region_spec(spec: str) -> Binding:
    """
    Read the command-line form: ``Tab!R1:AC60`` or ``Tab!R1:AC60=Site Name``.

    A command line has to be one string, so the site is appended after '='.
    The config file uses an object instead -- a hand-edited JSON file should
    not make anyone pack two delimiters into one value where a typo surfaces
    only at runtime. One internal shape, two spellings, each suited to where
    it is written. The flag form is always a construction block.
    """
    from ...sheets import Destination

    target, _, site = str(spec).partition("=")
    return Binding(Destination.parse(target), site.strip() or None)


def parse_entry(entry, where: str) -> Binding:
    """
    One config entry, or ValueError naming it.

    The single place the entry's rules live: ``check_config`` reports what this
    raises, and ``region_bindings`` stops on it, so what is accepted when
    the tool starts is exactly what ``serve`` publishes.
    """
    from ...sheets import Destination

    if isinstance(entry, str):
        # Tolerated so a value can be pasted straight from the flag.
        try:
            return parse_region_spec(entry)
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from None
    if not isinstance(entry, dict):
        raise ValueError(f"{where} must be an object or a string, got "
                         f"{type(entry).__name__}")
    if "region" not in entry:
        raise ValueError(f'{where} has no "region"')
    data = entry.get("data", DEFAULT_DATA)
    if data not in DATA_KINDS:
        # Shown as JSON, since that is what the person typed: null, not None.
        raise ValueError(f'{where} has "data": {json.dumps(data)}; a region can hold '
                         + ", ".join(DATA_KINDS))
    site = entry.get("site") or None
    if site is not None and data != "construction":
        raise ValueError(f'{where} names a "site", which only chooses a '
                         f'construction build; a {data} region shows the '
                         f'{data} as its tab does')
    try:
        destination = Destination.parse(entry["region"])
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from None
    return Binding(destination, site, data)


def region_bindings(config: Optional[dict], override: Optional[list] = None) -> list:
    """
    Which construction regions to keep current, and where that was decided.

    Command line wins outright when given -- an explicit flag should never be
    silently merged with saved settings, because then no single place tells
    you what will happen. Otherwise this plugin's ``config`` block, whose
    entries are objects::

        "config": {
          "bindings": [
            {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"}
          ]
        }

    ``site`` may be omitted, meaning "whichever site I am docked at".
    ``data`` may name ``market`` or ``cargo`` instead of a construction block::

        {"region": "Hold!A1:F40", "data": "cargo"}

    Raises ValueError naming the offending entry, because a malformed
    binding that is silently skipped is a region that quietly stops being
    published -- the exact failure this whole surface exists to prevent.
    """
    specs = list(override or [])
    if specs:
        return [parse_region_spec(s) for s in specs]

    return [
        parse_entry(entry, f"bindings[{i}]")
        for i, entry in enumerate((config or {}).get("bindings") or [])
    ]
