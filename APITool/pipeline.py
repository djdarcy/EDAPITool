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

#: The data kinds a pipeline may read in this release, each the name of its
#: pipeline: ``market`` (the station market, with the sheet comparison),
#: ``cargo`` (the ship's hold) and ``carrier`` (the fleet carrier). A
#: ``pipelines`` entry naming another kind is refused by name rather than
#: ignored. Only the market pipeline derives a default step list when the
#: file names none; a cargo or carrier pipeline runs only the steps listed.
PIPELINE_KINDS = ("market", "cargo", "carrier")


@dataclass(frozen=True)
class Step:
    """One plugin's step: its target's name, its ``process``, what it needs first, its bound context."""

    target: str
    process: Callable[[Any, Any], Any]
    ctx: Any
    needs: tuple[str, ...] = ()


def run_specs(specs: Sequence[Any], data: Any, *, options: Any = None) -> tuple:
    """
    Run plugin steps on one reading of a kind that has no refresh service.

    The cargo and carrier pipelines hand their record -- a ``ShipCargo``, a
    ``FleetCarrier`` -- through the configured steps the way the market
    pipeline hands its result through ``service._finish``: one context,
    one bound view per step (its own layout, guard and target), the steps
    in the listed order. No suppliers are offered on these kinds yet, so a
    step whose ``needs`` names one is refused before anything runs.
    Returns ``(data, reported)``. Core's ``history`` is the one supplier
    offered on these kinds, lazily, so a step may read the store here too.
    """
    from .registry import Refresh
    from .store import history

    ctx = Refresh(history.offered(), options=dict(options or {}), result=None, checked_at="")
    steps = []
    for spec in specs:
        ctx.bind(spec.offerer, worksheet=spec.worksheet, layout=spec.layout,
                 guard=spec.guard, ledger=None, target=spec.target)
        if callable(getattr(spec.module, "process", None)):
            steps.append(Step(target=spec.offerer, process=spec.module.process,
                              needs=tuple(getattr(spec.module, "needs", ())),
                              ctx=ctx.view(spec.offerer)))
    return run(steps, data), ctx.reported


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
