"""
Where this workbook's construction-region bindings come from, and who wins.

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
"""

from __future__ import annotations

from typing import Optional


def parse_region_spec(spec: str):
    """
    Read the command-line form: ``Tab!R1:AC60`` or ``Tab!R1:AC60=Site Name``.

    A command line has to be one string, so the site is appended after '='.
    The config file uses an object instead -- a hand-edited JSON file should
    not make anyone pack two delimiters into one value where a typo surfaces
    only at runtime. One internal shape, two spellings, each suited to where
    it is written.
    """
    from ...sheets import Destination

    target, _, site = str(spec).partition("=")
    return Destination.parse(target), (site.strip() or None)


def construction_regions(config: Optional[dict], override: Optional[list] = None) -> list:
    """
    Which construction regions to keep current, and where that was decided.

    Command line wins outright when given -- an explicit flag should never be
    silently merged with saved settings, because then no single place tells
    you what will happen. Otherwise this plugin's ``config`` block, whose
    entries are objects::

        "config": {
          "construction_regions": [
            {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"}
          ]
        }

    ``site`` may be omitted, meaning "whichever site I am docked at".

    Raises ValueError naming the offending entry, because a malformed
    binding that is silently skipped is a region that quietly stops being
    published -- the exact failure this whole surface exists to prevent.
    """
    from ...sheets import Destination

    specs = list(override or [])
    if specs:
        return [parse_region_spec(s) for s in specs]

    out = []
    for i, entry in enumerate((config or {}).get("construction_regions") or []):
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
