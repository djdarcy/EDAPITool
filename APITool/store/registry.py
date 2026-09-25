"""
Which tables exist, and which of them ``rebuild`` may drop.

The registry is the store's equivalent of ``generated.py``'s tab registry:
declared at import, consulted by the verbs, and closed -- a table the
registry does not know is a ``verify`` failure, never something to work
around. That is what lets ``rebuild`` be safe to run: it drops exactly the
tables registered ``derived``, in reverse order of registration (so a
child goes before its parent), recreates them, and runs each projector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

PRIMARY = "primary"
DERIVED = "derived"


@dataclass(frozen=True)
class Table:
    name: str
    tier: str
    ddl: str
    #: For a derived table: rebuilds its rows from primary ones. Registered
    #: on the parent of a group (the snapshot fills its items too).
    projector: Optional[Callable] = None


_TABLES: dict[str, Table] = {}


def register(name: str, tier: str, ddl: str, projector: Optional[Callable] = None) -> Table:
    if tier not in (PRIMARY, DERIVED):
        raise ValueError(f"table {name!r}: tier must be primary or derived, not {tier!r}")
    if name in _TABLES:
        raise ValueError(f"table {name!r} registered twice")
    table = Table(name, tier, ddl.strip(), projector)
    _TABLES[name] = table
    return table


def tables() -> tuple[Table, ...]:
    """Every registered table, in registration order (parents first)."""
    return tuple(_TABLES.values())


def names() -> frozenset[str]:
    return frozenset(_TABLES)


def derived() -> tuple[Table, ...]:
    return tuple(t for t in _TABLES.values() if t.tier == DERIVED)


def primary() -> tuple[Table, ...]:
    return tuple(t for t in _TABLES.values() if t.tier == PRIMARY)
