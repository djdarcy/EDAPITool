"""
Find destination plugins without importing them; import only the enabled ones.

Until v0.7.2 a plugin was chosen by a hardcoded import in ``cli.py``. That line
*was* the selection mechanism: adding ``APITool/plugins/mysheet/`` produced a
directory nothing would ever read. This module is what reads it.

Discovery is two phases, and the split is the design rather than a detail:

    scan   -> names and locations. Imports NOTHING.
    load   -> import only what configuration enables, one plugin at a time,
              catching each failure so a broken plugin is LISTED with its
              reason and never takes the tool down with it.

Importing to discover is itself the hazard -- a broken plugin's side effects
would run before anyone could decide not to load it -- so ``scan`` treats a
directory with an ``__init__.py`` as a candidate and leaves it at that.

Two sources are scanned, shipped plugins under ``APITool/plugins/`` and a user
directory, and a user plugin with a shipped one's name **shadows** it. The
shadowing is recorded on the :class:`Found` and reported, never silent: the
surprising state is the one that must be named.

A plugin's identity is its **name**, not its path. The observation store will
key provenance on it, and a path changes the day a user reorganises a drive.

What this module does not do: it knows nothing about any spreadsheet. No tab
name, column letter or header text appears here, and the leak probe that
enforces that walks this file like any other in the package.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from .guard import PathGuard
from .sheets.a1 import CellRange
from .sheets.guard import WriteGuard

# Where shipped plugins live: the package beside this module. Computed from
# the filesystem, not imported -- ``scan`` must not import what it finds.
SHIPPED_DIR = Path(__file__).resolve().parent / "plugins"
SHIPPED_PACKAGE = "APITool.plugins"
# User plugins are loaded under a package of their own so a user module named
# ``settlement`` never collides in ``sys.modules`` with the shipped one.
USER_PACKAGE = "edapitool_user_plugins"

ORIGIN_SHIPPED = "shipped"
ORIGIN_USER = "user"

#: Words the ``plugins`` verb keeps for itself. A plugin directory carrying
#: one of these names would be unreachable through ``plugins <name>``, so
#: the loader refuses it by name rather than letting the verb shadow it.
#: Three are built today (``list``, ``describe``, ``help``, see
#: :data:`BUILT`); the rest are held back now so that adding one later -- an
#: ``enable`` or an ``install`` -- never breaks somebody's plugin of that name.
#: Compared case-insensitively: ``plugins List`` and ``plugins list`` must
#: not reach two different things on a filesystem that keeps both.
RESERVED = ("list", "describe", "enable", "disable", "check", "config", "help",
            "info", "show", "status", "install", "uninstall", "remove", "update",
            "new", "init")
#: The reserved words the verb actually answers today.
BUILT = ("list", "describe", "help")


def reserved_reason(name: str) -> Optional[str]:
    """
    Why a plugin directory's name cannot be a plugin's, or None when it can.

    A reserved word in any case, or a name that starts with ``-``, which
    ``plugins <name>`` would read as an option rather than a plugin.
    """
    if name.startswith("-"):
        return f"the name {name!r} starts with '-', which `plugins` would read as an option"
    if name.lower() in RESERVED:
        return (f"the name {name!r} is {name.lower()!r}, a word the plugins verb keeps "
                f"reserved ({', '.join(RESERVED)})")
    return None


# ---------------------------------------------------------------------------
# Kinds: what a target IS decides how its writes are bounded
# ---------------------------------------------------------------------------
#
# A plugin DECLARES what it writes, in its target's vocabulary -- a sheet
# declares tab -> A1 ranges, a file would declare a path. The KIND supplies
# the enforcer that understands that vocabulary, and CORE builds it from the
# declaration and hands it to the plugin. The plugin never builds its own:
# measured on 2026-09-16, a plugin trusted to guard itself did not catch its
# own transposed constant, and a guard core built from that plugin's own
# declaration did.
#
# One guard type cannot cover every kind. `WriteGuard.build` raises on a file
# path, because it parses A1 ranges -- so enforcement is per kind, while the
# supplier/subscriber contract above it is not.

GSHEET = "gsheet"


class GSheetKind:
    """A Google sheet. Declarations are ``{tab: [A1 range, ...]}``."""

    name = GSHEET

    @staticmethod
    def build_enforcer(declaration: Mapping[str, Sequence[str]]) -> WriteGuard:
        return WriteGuard.build(dict(declaration))

    @staticmethod
    def overlapping(a: Mapping[str, Sequence[str]],
                    b: Mapping[str, Sequence[str]]) -> list[str]:
        """
        Every pair of declared ranges, on a tab both name, that share a cell.

        Overlap is a question in the kind's own vocabulary -- a sheet asks it
        of A1 ranges, a file would ask it of paths -- which is why it lives
        on the kind and not on the loader.
        """
        found: list[str] = []
        for tab in sorted(set(a) & set(b)):
            for left in a[tab]:
                for right in b[tab]:
                    if CellRange.parse(left).overlaps(CellRange.parse(right)):
                        found.append(f"{tab}!{left} overlaps {right}")
        return found


JSONL = "jsonl"


class JsonlKind:
    """
    A file the tool appends records to. Declarations are ``{FILE: [path, ...]}``.

    The second kind, and the one that proves the contract is not shaped like a
    spreadsheet. What it shares with ``gsheet`` is everything in the plugin
    contract -- supplies, subscribes, a declaration core enforces. What it
    cannot share is the enforcement itself: ``WriteGuard`` speaks A1 and
    raises ``ValueError`` on a path, measured as a control arm before either
    kind was written.
    """

    name = JSONL
    # The one bucket a file declaration uses, where a sheet uses a tab name.
    # A file has no sub-addresses; it is owned whole or not at all.
    FILE = "__file__"

    @staticmethod
    def build_enforcer(declaration: Mapping[str, Sequence[str]]) -> PathGuard:
        return PathGuard.build([p for paths in declaration.values() for p in paths])

    @staticmethod
    def overlapping(a: Mapping[str, Sequence[str]],
                    b: Mapping[str, Sequence[str]]) -> list[str]:
        """
        Every path two file plugins both declare.

        The same question ``gsheet`` asks of cell ranges, asked of files:
        two plugins appending to one file interleave their records, and
        whoever reads it afterwards cannot tell whose is whose. Compared
        after resolution, so two spellings of one file are one overlap.
        """
        left = {PathGuard.resolve(p): p for paths in a.values() for p in paths}
        right = {PathGuard.resolve(p) for paths in b.values() for p in paths}
        return [left[key] for key in sorted(set(left) & right)]


KINDS = {GSHEET: GSheetKind, JSONL: JsonlKind}

# What to do when two enabled plugins declare the same cells. `error` refuses
# to load them until the person resolves it; `warn` loads both, in precedence
# order, and says so; `ignore` loads both silently. The default is `error`
# and is provisional: one plugin exists today, so no overlap has ever been
# anything but a mistake. When a person wants two plugins to cover the same
# region on purpose -- one enabled at a time, the other standing in -- that is
# what `warn` and a declared precedence are for.
SEVERITY_ERROR = "error"
SEVERITY_WARN = "warn"
SEVERITY_IGNORE = "ignore"
SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARN, SEVERITY_IGNORE)


class PluginConflict(ValueError):
    """Two enabled plugins declare overlapping writes and severity is ``error``."""


@dataclass(frozen=True)
class Conflict:
    """One overlap between two plugins' declarations, first-listed first."""

    first: str
    second: str
    kind: str
    where: str

    def describe(self) -> str:
        return f"{self.first} / {self.second}: {self.where} ({self.first} takes precedence)"


def kind_for(name: Optional[str]):
    """The kind registered under ``name``, or a ValueError naming the known ones."""
    if name is None or name not in KINDS:
        raise ValueError(
            f"unknown target kind {name!r}; known kinds: {', '.join(sorted(KINDS))}"
        )
    return KINDS[name]


def build_enforcer(kind: Optional[str], declaration):
    """
    Core builds the enforcer from a plugin's declaration.

    The one place a guard comes from. Everything that writes on a plugin's
    behalf is handed the result; nothing is allowed to build its own.
    """
    return kind_for(kind).build_enforcer(declaration)


@dataclass(frozen=True)
class Found:
    """A plugin the scan located. Nothing about it has run."""

    name: str
    location: Path
    origin: str
    # The shipped location this user plugin hides, when it hides one.
    shadows: Optional[Path] = None
    # True when the directory's name is one the ``plugins`` verb reserves;
    # the scan still reports it, so the person can see why it never loads.
    reserved: bool = False


@dataclass(frozen=True)
class Loaded:
    """A plugin that imported cleanly."""

    name: str
    module: types.ModuleType
    found: Found
    # What kind of target this plugin serves: the configured target's kind,
    # or the plugin's own ``KIND`` when configuration named none. Selects the
    # enforcer; None means no kind is known and no enforcer can be built.
    kind: Optional[str] = None
    # What the plugin declares it writes, read once at load from the module's
    # ``writes()``. None when the plugin declares nothing -- and a plugin
    # that declares nothing cannot conflict with anything.
    declaration: Optional[Mapping[str, Sequence[str]]] = None
    # The configured target this plugin serves (``settings.Target``): its
    # name, and the ``config`` block the composition root hands the plugin
    # unread. None when configuration named no target for it.
    target: Any = None
    # What this plugin said was wrong with its target's ``config`` block,
    # from its own ``check_config``. Empty when it found nothing wrong or
    # declined to look. Core never inspects a block itself -- it only asks,
    # and repeats the answer.
    complaints: tuple[str, ...] = ()
    # The command-line flags this plugin declares (``registry.Flag`` records,
    # read once at load from ``flags()``). Empty when it declares none. Core
    # registers them into the parser, one group per verb, and never learns
    # what any of them means.
    flags: tuple = ()


@dataclass(frozen=True)
class Broken:
    """A plugin that was enabled and did not load. It stopped nothing else."""

    name: str
    reason: str
    found: Optional[Found] = None


@dataclass
class LoadResult:
    """
    What loaded, what did not, and what was found but never asked for.

    ``loaded`` is in enablement order, which is the precedence order every
    later decision uses: the first-listed plugin is the one the single-
    destination commands talk to, and the one that goes first when several
    publish.
    """

    loaded: list[Loaded] = field(default_factory=list)
    broken: list[Broken] = field(default_factory=list)
    # Discovered, not enabled. Present-but-off is the default for anything
    # the user has not spoken about: loading code nobody asked for is the
    # thing a scanned directory makes too easy.
    available: list[Found] = field(default_factory=list)
    # Overlapping declarations found at load, recorded under `warn`. Under
    # `error` they raise instead; under `ignore` they are not looked for.
    conflicts: list[Conflict] = field(default_factory=list)

    def first(self) -> Optional[Loaded]:
        """The plugin a single-destination command talks to, or None."""
        return self.loaded[0] if self.loaded else None

    def publisher(self) -> Optional[Loaded]:
        """
        The loaded plugin a single-destination command talks to: the first
        that has a ``layout()`` -- a place of its own to read from and write to.

        Since v0.8.0 two shipped plugins can be loaded on one workbook: the
        roll-up tab (a layout, a comparison, markers) and the construction
        bindings (no tab of its own, only "where the blocks go"). A command
        that wants "the destination" wants the one with a layout; a command
        that wants a capability asks :meth:`offering`. The file plugin has
        a layout too, which is what makes it a destination for `market`.
        """
        return self.offering("layout")

    def offering(self, capability: str) -> Optional[Loaded]:
        """The first loaded plugin whose module exposes a callable ``capability``."""
        for entry in self.loaded:
            if callable(getattr(entry.module, capability, None)):
                return entry
        return None

    def plugin(self, name: str) -> Optional[types.ModuleType]:
        for entry in self.loaded:
            if entry.name == name:
                return entry.module
        return None

    def describe(self) -> list[str]:
        """
        One line per plugin, in the tone ``describe_gaps`` set: the surprising
        state is named, the expected one is brief.
        """
        lines = []
        for entry in self.loaded:
            lines.append(f"loaded    {entry.name} ({entry.found.origin})")
            if entry.found.shadows is not None:
                lines.append(f"          shadows the shipped plugin at {entry.found.shadows}")
            for complaint in entry.complaints:
                where = entry.target.name if entry.target is not None else entry.name
                lines.append(f"CONFIG    {where}: {complaint}")
        for entry in self.broken:
            lines.append(f"BROKEN    {entry.name}: {entry.reason}")
        for found in self.available:
            if found.reserved:
                lines.append(f"available {found.name} ({found.origin}) -- RESERVED name, "
                             "cannot be enabled; rename the directory")
            else:
                lines.append(f"available {found.name} ({found.origin}) -- not enabled")
        for conflict in self.conflicts:
            lines.append(f"CONFLICT  {conflict.describe()}")
        return lines


# ---------------------------------------------------------------------------
# Phase one: scan
# ---------------------------------------------------------------------------


def _candidates(directory: Optional[Path]) -> list[Path]:
    """Subdirectories that look like packages. Nothing is imported."""
    if directory is None or not directory.is_dir():
        return []
    return sorted(
        child for child in directory.iterdir()
        if child.is_dir()
        and not child.name.startswith(("_", "."))
        and (child / "__init__.py").is_file()
    )


def scan(shipped_dir: Optional[Path] = SHIPPED_DIR,
         user_dir: Optional[Path] = None) -> list[Found]:
    """
    Every plugin that exists, shipped first, then the user's.

    A user plugin whose name matches a shipped one replaces it in the result
    and records what it replaced. Order within each source is by name, so
    the listing is stable from run to run.
    """
    by_name: dict[str, Found] = {}
    for child in _candidates(shipped_dir):
        by_name[child.name] = Found(child.name, child, ORIGIN_SHIPPED,
                                    reserved=reserved_reason(child.name) is not None)
    for child in _candidates(user_dir):
        hidden = by_name.get(child.name)
        by_name[child.name] = Found(
            child.name, child, ORIGIN_USER,
            shadows=hidden.location if hidden is not None else None,
            reserved=reserved_reason(child.name) is not None,
        )
    return list(by_name.values())


# ---------------------------------------------------------------------------
# Phase two: load
# ---------------------------------------------------------------------------


def _import_shipped(found: Found) -> types.ModuleType:
    return importlib.import_module(f"{SHIPPED_PACKAGE}.{found.name}")


def _import_user(found: Found) -> types.ModuleType:
    """
    Import a user plugin from its directory, under :data:`USER_PACKAGE`.

    The parent package is a namespace created on demand so that relative
    imports inside the plugin -- ``from .layout import ...`` -- resolve the
    way they would for a shipped one.
    """
    parent = sys.modules.get(USER_PACKAGE)
    if parent is None:
        parent = types.ModuleType(USER_PACKAGE)
        parent.__path__ = []  # type: ignore[attr-defined]
        sys.modules[USER_PACKAGE] = parent

    qualified = f"{USER_PACKAGE}.{found.name}"
    spec = importlib.util.spec_from_file_location(
        qualified, found.location / "__init__.py",
        submodule_search_locations=[str(found.location)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"no importable package at {found.location}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # A half-imported module left in sys.modules would make the NEXT
        # attempt look like a success. Take it back out.
        sys.modules.pop(qualified, None)
        raise
    return module


def _unique(names: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def load(found: Sequence[Found], enabled: Sequence[str],
         kinds: Optional[Mapping[str, str]] = None, *,
         severity: str = SEVERITY_ERROR,
         precedence: Optional[Sequence[str]] = None,
         targets: Optional[Mapping[str, Any]] = None) -> LoadResult:
    """
    Import the enabled plugins, in the order given, isolating each failure.

    ``enabled`` is a sequence rather than a set on purpose: its order is the
    precedence order (see :class:`LoadResult`). A name that was enabled but
    never found is reported as broken with that reason, because a target
    naming a plugin that does not exist is a setting that quietly does
    nothing -- exactly the failure the settings module refuses elsewhere.

    ``kinds`` maps a plugin name to the kind configuration gave its target;
    a plugin configuration did not describe falls back to its own ``KIND``.
    ``targets`` maps a plugin name to the target itself, carried on the
    loaded entry for the composition root to hand over.

    Two knobs govern overlapping declarations, and they answer different
    questions. ``severity`` answers "did you mean this?" -- refuse, warn, or
    say nothing. ``precedence`` answers "who wins when you did?" -- an
    explicit ordering of names that, when given, reorders what loaded; the
    enabled order otherwise. Neither alone is enough: ``ignore`` must not be
    the only way to get a deterministic winner.
    """
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}, got {severity!r}")
    by_name = {f.name: f for f in found}
    result = LoadResult()
    wanted = _unique(enabled)
    kinds = kinds or {}
    targets = targets or {}

    for name in wanted:
        entry = by_name.get(name)
        if entry is None:
            result.broken.append(Broken(name, "not found by the scan"))
            continue
        if entry.reserved:
            # Never imported: the name collides with a word the `plugins`
            # verb keeps, so `plugins <name>` could never reach it. Said by
            # name, not shadowed in silence.
            result.broken.append(Broken(
                name,
                f"{reserved_reason(name)}; rename the plugin's directory",
                entry,
            ))
            continue
        importer = _import_user if entry.origin == ORIGIN_USER else _import_shipped
        try:
            module = importer(entry)
        except Exception as exc:  # noqa: BLE001 -- isolation is the point
            result.broken.append(Broken(name, f"{type(exc).__name__}: {exc}", entry))
            continue
        kind = kinds.get(name) or getattr(module, "KIND", None)
        declares = getattr(module, "writes", None)
        declaration = declares() if callable(declares) else None
        target = targets.get(name)
        result.loaded.append(
            Loaded(name, module, entry, kind, declaration, target,
                   check_config(module, target), _declared_flags(module))
        )

    result.available = [f for f in found if f.name not in wanted]

    if precedence:
        rank = {name: i for i, name in enumerate(_unique(precedence))}
        result.loaded.sort(key=lambda e: rank.get(e.name, len(rank)))

    if severity != SEVERITY_IGNORE:
        found_conflicts = conflicts(result.loaded)
        if found_conflicts and severity == SEVERITY_ERROR:
            raise PluginConflict(
                "refusing to load plugins whose declared writes overlap; "
                "resolve the overlap, or set severity to 'warn' with a precedence:\n  "
                + "\n  ".join(c.describe() for c in found_conflicts)
            )
        result.conflicts = found_conflicts

    # Two plugins claiming one spelling on one verb is always an error: a
    # parser cannot hold both, and "the later one wins" would make the flag
    # mean something different depending on load order.
    clashes = flag_collisions(result.loaded)
    if clashes:
        raise PluginConflict(
            "refusing to load plugins that declare the same flag:\n  "
            + "\n  ".join(clashes)
        )
    return result


def _declared_flags(module) -> tuple:
    """The ``Flag`` records a module declares, or none. Never raises past load."""
    declares = getattr(module, "flags", None)
    if not callable(declares):
        return ()
    return tuple(declares())


def flag_collisions(loaded: Sequence[Loaded]) -> list[str]:
    """Every (verb, flag) two loaded plugins both declare, as one line each."""
    seen: dict[tuple[str, str], str] = {}
    out: list[str] = []
    for entry in loaded:
        for flag in entry.flags:
            key = (flag.verb, flag.name)
            other = seen.get(key)
            if other is not None and other != entry.name:
                out.append(f"{flag.name} on `{flag.verb}`: declared by both {other!r} and {entry.name!r}")
            seen.setdefault(key, entry.name)
    return out


def check_config(module, target) -> tuple[str, ...]:
    """
    Ask a plugin what is wrong with its target's ``config`` block.

    Core does not know what any key in that block means -- that is the whole
    point of the block -- so it cannot validate it and does not try. It asks
    the plugin, which owns the schema, and repeats whatever comes back.

    A plugin with no ``check_config`` is not failing a duty: validation is
    optional, and a plugin that does not offer it simply reports nothing. A
    ``check_config`` that itself raises is the plugin's defect and is
    reported as one, rather than taking down the load of every other target.
    """
    ask = getattr(module, "check_config", None)
    if not callable(ask):
        return ()
    block = getattr(target, "config", None) or {}
    try:
        found = ask(block)
    except Exception as exc:  # noqa: BLE001 -- the plugin's defect, isolated
        return (f"{type(exc).__name__} while checking its configuration: {exc}",)
    if not found:
        return ()
    if isinstance(found, str):
        return (found,)
    return tuple(str(item) for item in found)


def conflicts(loaded: Sequence[Loaded]) -> list[Conflict]:
    """
    Every overlap between two loaded plugins' declarations, in load order.

    Only plugins of the SAME kind can overlap -- a sheet range and a file
    path have no cell in common -- and only plugins that declared anything.
    The kind answers the overlap question in its own vocabulary.
    """
    out: list[Conflict] = []
    for i, left in enumerate(loaded):
        for right in loaded[i + 1:]:
            if left.kind is None or left.kind != right.kind:
                continue
            if left.declaration is None or right.declaration is None:
                continue
            kind = KINDS.get(left.kind)
            if kind is None:
                continue
            for where in kind.overlapping(left.declaration, right.declaration):
                out.append(Conflict(left.name, right.name, left.kind, where))
    return out


# ---------------------------------------------------------------------------
# The whole thing, from configuration
# ---------------------------------------------------------------------------


def enabled_from(targets, found: Sequence[Found]) -> list[str]:
    """
    Which plugins configuration turns on, in precedence order.

    Configuration is the whole answer, and an empty configuration answers
    "none". Nothing is enabled by being present -- not a user plugin, and
    not the plugin this repository happens to ship. That is #18's sixth
    criterion, *the core ships no destination*, and it is a one-line rule
    here because the alternative is a rule nobody can state: "the shipped
    ones, unless the person configured something, in which case only what
    they named" is two selection mechanisms, and the implicit one wins
    exactly when a person has said the least.

    ``found`` is still taken, and still unused, because the caller has it
    and the day a kind needs to answer this question it will be asked here.
    """
    return _unique(t.plugin for t in targets.values()) if targets else []


def kinds_from(targets) -> dict[str, str]:
    """Each enabled plugin's kind, from the first target that names it."""
    kinds: dict[str, str] = {}
    for target in targets.values():
        kinds.setdefault(target.plugin, target.kind)
    return kinds


def targets_by_plugin(targets) -> dict[str, Any]:
    """Each enabled plugin's target, the first that names it."""
    by_plugin: dict[str, Any] = {}
    for target in targets.values():
        by_plugin.setdefault(target.plugin, target)
    return by_plugin


def discover(user_dir: Optional[Path] = None, *,
             severity: str = SEVERITY_ERROR) -> LoadResult:
    """
    Scan both sources, read the configuration, load what it enables.

    The one composition root: every command that asks "which destination am
    I talking to" arrives here, so there is one answer and no command can
    drift into computing its own. A configuration naming no target loads
    nothing, and the scan's findings are reported as *available* -- present,
    offered, off until somebody says otherwise.
    """
    from . import settings

    if user_dir is None:
        user_dir = settings.get_plugin_dir()
    found = scan(SHIPPED_DIR, user_dir)
    targets = settings.get_targets()
    return load(found, enabled_from(targets, found), kinds_from(targets),
                severity=severity, targets=targets_by_plugin(targets))
