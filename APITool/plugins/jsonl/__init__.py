"""
A destination that is a FILE: one JSON record appended per refresh.

The second plugin, and the reason it exists is to be a different KIND. The
settlement plugin publishes to a Google sheet; this one publishes to a file
on disk, and it satisfies the same contract without a line of that contract
changing. If something here had needed `registry.py` widened, the contract
would have been shaped like a spreadsheet after all.

What the loader asks of a plugin -- the same surface the settlement plugin
answers, in a different vocabulary:

    KIND                  "jsonl"; selects the path enforcer
    layout(**overrides)   where this destination is, with the target's `path`
    writes()              the path it declares, as {FILE: [path]}
    layout.writes()       the same for a layout that knows its target
    supplies()            `previous` -- the last record already in the file,
                          which is prior state a file genuinely has
    subscribes()          `record` -- appends exactly one line per refresh
    default_config()      a starter block
    check_config(config)  what is wrong with a block, or nothing

It writes through the guard core built from its own declaration, before it
opens anything -- so a path it did not declare is refused rather than
written and then regretted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ...guard import PathGuard
from ...loader import JsonlKind
from ...registry import Refresh, Subscription

# A file on disk. Configuration names a kind per target and this is what the
# shipped plugin is when it names none.
KIND = "jsonl"

# What a record carries, unless the target's config narrows it. Named rather
# than inlined because `plugins describe` shows it and `check_config` checks
# against it.
FIELDS = ("checked_at", "system", "station", "market_id", "requirements")


@dataclass(frozen=True)
class FileLayout:
    """
    Where this destination is, and what a record holds.

    The file kind's answer to ``SheetLayout``. A path rather than a tab, and
    no geometry at all -- a file has no rows, columns or header offsets, which
    is exactly why it is worth having as a second kind.
    """

    path: str = ""
    fields: tuple[str, ...] = FIELDS
    # Set from the target's config when one asks for it; empty means every
    # field in FIELDS.
    only: tuple[str, ...] = field(default_factory=tuple)

    def writes(self) -> dict[str, list[str]]:
        """What this plugin DECLARES it writes: one path, owned whole."""
        return {JsonlKind.FILE: [self.path] if self.path else []}

    def selected(self) -> tuple[str, ...]:
        return self.only or self.fields


def layout(**overrides) -> FileLayout:
    """This destination's layout. ``path`` comes from the target, never from here."""
    values = {k: v for k, v in overrides.items() if v is not None}
    only = values.pop("only", None)
    if only is not None:
        values["only"] = tuple(only)
    return FileLayout(**values)


def writes() -> dict[str, list[str]]:
    """
    What this plugin declares as SHIPPED -- which is nothing.

    A file plugin's bound is its target's path, and with no target there is
    no path to declare. Declaring nothing is honest and has a consequence
    the loader already handles: a plugin that declares nothing cannot
    conflict with anything, and core builds it an enforcer that permits
    nothing until a target gives it one.
    """
    return FileLayout().writes()


def default_config() -> dict:
    """A starter block for someone configuring this plugin for the first time."""
    return {"only": list(FIELDS)}


def check_config(config: Optional[dict]) -> list[str]:
    """
    What is wrong with this target's block, as a list of plain sentences.

    Returns an empty list when there is nothing wrong. The tool reports
    whatever comes back, naming the target -- it does not know what any of
    these keys mean, which is the point: the schema lives with the plugin
    that reads it.
    """
    problems: list[str] = []
    if not config:
        return problems
    only = config.get("only")
    if only is not None:
        if not isinstance(only, list) or not all(isinstance(f, str) for f in only):
            problems.append('"only" must be a list of field names')
        else:
            unknown = [f for f in only if f not in FIELDS]
            if unknown:
                problems.append(
                    f'"only" names {", ".join(repr(f) for f in unknown)}, which this '
                    f'plugin does not publish; it knows {", ".join(FIELDS)}'
                )
    return problems


# ---------------------------------------------------------------------------
# The contract: what this plugin supplies, and what it subscribes to
# ---------------------------------------------------------------------------


def _read_previous(ctx: Refresh) -> Any:
    """
    The last record already in the file, or None.

    A file destination has prior state too, and this is it: what was written
    last time. Pulled once per refresh and memoised, exactly as the sheet
    plugin's requirements are -- the registry does not know or care that one
    of them reads a spreadsheet and the other a file.
    """
    from pathlib import Path

    path = getattr(ctx.layout, "path", "")
    if not path:
        return None
    handle = Path(path).expanduser()
    if not handle.is_file():
        return None
    lines = [line for line in handle.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except ValueError:
        # A file somebody else has been writing to, or a truncated last line.
        # Prior state we cannot read is prior state we do not have.
        return None


def _append_record(ctx: Refresh) -> Any:
    """
    Append exactly one JSON record describing this refresh.

    Goes through the guard BEFORE opening anything: the path is checked, then
    the file is opened. A guard consulted after the write would report a
    refusal that had already happened.
    """
    from pathlib import Path

    layout_ = ctx.layout
    path = getattr(layout_, "path", "")
    if not path:
        return "no path configured: nothing written"

    result = ctx.result
    record = {
        "checked_at": ctx.checked_at,
        "system": getattr(result.location, "system", None),
        "station": getattr(result.location, "station_display", None),
        "market_id": getattr(getattr(result, "market", None), "market_id", None),
        "requirements": [
            {"name": m.requirement.name, "need": m.requirement.need,
             "origin": m.origin, "state": getattr(m.state, "name", str(m.state))}
            for m in (result.matches or [])
        ],
    }
    selected = layout_.selected()
    record = {k: v for k, v in record.items() if k in selected}

    if ctx.guard is not None:
        ctx.guard.check(path)
    if not ctx.options.get("write"):
        return f"would append 1 record to {path}"

    handle = Path(path).expanduser()
    handle.parent.mkdir(parents=True, exist_ok=True)
    with handle.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return f"appended 1 record to {path}"


def supplies() -> dict[str, Callable[[Refresh], Any]]:
    """What this plugin can be asked for. Pulled once per refresh, memoised."""
    return {"previous": _read_previous}


def subscribes() -> list[Subscription]:
    """What this plugin publishes, and what must be supplied first."""
    return [Subscription("record", (), _append_record)]


__all__ = [
    "FIELDS", "FileLayout", "KIND", "PathGuard",
    "check_config", "default_config", "layout", "subscribes", "supplies", "writes",
]
