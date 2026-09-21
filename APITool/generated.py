"""
Which tabs this tool builds in full -- declared by the builders themselves.

A generated tab is one this tool writes from nothing every time: it owns the
whole sheet, clears it, and writes a fresh grid. Nothing a person typed can
survive there, which is precisely why clearing it is safe -- and precisely
why clearing anything else is not.

``GoogleSheetsExporter.export_grid`` calls ``worksheet.clear()``, so the set
of tabs it may target is a SAFETY boundary. It used to be a literal:

    WRITABLE_TABS = frozenset({"FreighterData", "MarketData", "ShipCargo"})

A hand-kept safety list fails in one specific, silent way: somebody adds a
generator and does not add its tab. This project has already paid for the
inverse mistake -- the list was once a DENY list of five tab names, three of
which did not exist in the workbook it was written against, while every tab
holding irreplaceable hand-entered work was absent from it and therefore
writable.

So the fact is recorded once, where it is already known: on the function that
builds the grid. ``@generates_tab("MarketData")`` above ``market.sheet_grid``
says what that function is for, and the allow list is read from the
decorations rather than kept in step with them by hand.

What this does NOT do, deliberately: it is not configurable, and a tab does
not become writable by appearing in a config file. A person's own tab is
protected by the tool having no way to be told otherwise.
"""

from __future__ import annotations

import importlib
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)

# Keyed by the builder's qualified name so a module reloaded under a
# different name cannot double-count, and so a wrong entry can be traced back
# to the function that made it.
_BUILDERS: dict[str, str] = {}

# The modules that define grid builders. This is the one place the set of
# generators is named, and it is named as "where the builders live" rather
# than as "which tabs are writable" -- the difference that matters is that
# forgetting to add a MODULE here fails closed (a legitimate write is
# refused, loudly), whereas forgetting to add a TAB to an allow list failed
# open. Imported lazily, because two of them import this one.
_GRID_MODULES = (".market", ".ship", ".google.exporter")


def generates_tab(tab: str) -> Callable[[F], F]:
    """
    Mark a function as building the WHOLE grid for ``tab``.

    The decoration is the declaration: a function carrying it is saying it
    produces every row that tab will hold, which is what makes clearing the
    tab before writing it safe.
    """
    def mark(builder: F) -> F:
        _BUILDERS[f"{builder.__module__}.{builder.__qualname__}"] = tab
        builder.generated_tab = tab  # type: ignore[attr-defined]
        return builder
    return mark


def generated_tabs() -> frozenset[str]:
    """
    Every tab some builder claims to generate in full.

    Evaluated on each call rather than frozen at import, so a builder defined
    after this module loads is still counted -- a test plants one, and so
    would a plugin.
    """
    for module in _GRID_MODULES:
        importlib.import_module(module, __package__)
    return frozenset(_BUILDERS.values())


def builders() -> dict[str, str]:
    """Which builder declared which tab. For diagnostics and tests."""
    generated_tabs()
    return dict(_BUILDERS)


__all__ = ["builders", "generated_tabs", "generates_tab"]
