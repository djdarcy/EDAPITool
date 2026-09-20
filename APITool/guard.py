"""
What every kind of destination shares about refusing a write.

The refusal itself is kind-neutral -- "this write is outside what you
declared" means the same thing whether what was declared is a range of cells
or a path on disk -- so it lives here rather than inside the spreadsheet
toolkit, where it began. ``APITool.sheets`` still exports it, so nothing that
caught it before has to change.

The guards themselves are NOT shared, and deliberately: a spreadsheet's bounds
are A1 ranges and a file's are paths, and one class cannot answer both
questions. Each kind supplies its own enforcer (``APITool.loader.KINDS``);
core builds it from the plugin's declaration and applies it. The plugin never
builds its own -- measured 2026-09-16, when a plugin trusted to guard itself
did not catch its own transposed constant and a guard built by core from that
same declaration did.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class WriteRefused(Exception):
    """A write was attempted outside the allowlist."""


@dataclass(frozen=True)
class PathGuard:
    """
    Deny-by-default gate on every write to a file destination.

    The file kind's answer to ``WriteGuard``. A declaration is a list of
    paths; a write is permitted only to a path that resolves to one of them.
    Resolution happens on both sides, so ``~/x.jsonl``, ``./x.jsonl`` and an
    absolute spelling of the same file are one path rather than three -- the
    comparison is about which file is written, not how it was spelled.
    """

    allowed: frozenset[str] = frozenset()

    @classmethod
    def build(cls, paths: Sequence[str]) -> "PathGuard":
        return cls(allowed=frozenset(cls.resolve(p) for p in paths))

    @staticmethod
    def resolve(path) -> str:
        """One spelling per file: user-expanded, absolute, case-folded on Windows."""
        resolved = str(Path(str(path)).expanduser().resolve())
        return resolved.casefold() if Path().resolve().drive else resolved

    def allows(self, path) -> bool:
        return self.resolve(path) in self.allowed

    def check(self, path) -> None:
        """Raise :class:`WriteRefused` unless this exact file was declared."""
        if not self.allows(path):
            permitted = ", ".join(sorted(self.allowed)) or "(nothing)"
            raise WriteRefused(
                f"refusing to write {path}: outside the allowlist. Permitted: {permitted}"
            )
