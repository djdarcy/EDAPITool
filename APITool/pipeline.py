"""
The pipeline: an ordered list of steps, each handed the data and passing it on.

A STEP is one plugin's ``process(data, ctx) -> data``, bound to that plugin's
own target through ``ctx`` (``registry.Bound``). The runner pulls every
step's ``needs`` first, so a step asking for a supplier nobody offers is
refused before any step has acted; then it calls the steps in the order the
configuration listed them, handing each the data the previous one returned.
A step that returns ``None`` is refused by name: a later step would otherwise
receive nothing and fail somewhere confusing.

Status -- a plan, a message, a count -- goes through ``ctx.report`` and is
read by the tool, never by another step. What a later step needs from an
earlier one travels in the data.

Nothing here knows what the data is. In 0.9.0 the one pipeline is ``market``
and its data is the refresh result; the shape is the same for any kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

#: The data kinds a pipeline may read in this release. A ``pipelines`` entry
#: naming another kind is refused by name rather than ignored.
PIPELINE_KINDS = ("market",)


@dataclass(frozen=True)
class Step:
    """One plugin's step: its target's name, its ``process``, what it needs first, its bound context."""

    target: str
    process: Callable[[Any, Any], Any]
    ctx: Any
    needs: tuple[str, ...] = ()


def run(steps: Sequence[Step], data: Any) -> Any:
    """
    Run the steps in order and return the last one's data.

    Every ``needs`` is pulled before the first step acts, each through its own
    step's context, so an unknown supplier is refused with nothing done.
    """
    for step in steps:
        for need in step.needs:
            step.ctx.get(need)
    for step in steps:
        out = step.process(data, step.ctx)
        if out is None:
            raise ValueError(
                f"step {step.target!r} returned None; a step hands its data on "
                "(status goes through ctx.report)"
            )
        data = out
    return data
