"""
probe_no_config_knowledge.py -- the configuration surface's leak count.

The code probe (probe_no_sheet_knowledge.py) walks APITool/*.py and reported
0 leaks from v0.7.0 on. That number measured CODE. The configuration surface
was never scanned, and #27 named the contamination that lived there:
``construction_regions`` -- one workbook's tab and range -- parsed by core
under a schema core owned. This probe walks that surface. Two questions, one
number:

  1. Which keys does core PARSE from ~/.ed_capi_config.json? Read from
     ``settings.py``'s SOURCE, never from the file itself. Every key literal
     the module reads must be one core owns; a plugin's key read in core is
     a leak, whatever its value.
  2. Where do the docs put a person's sheet strings? Every JSON example in
     ``docs/``, ``README.md`` and ``CLAUDE.md`` is parsed; a key core does
     not own at the top level, or a tab-qualified range or a person-typed
     name anywhere but inside a target's ``config`` block, is a leak. An
     example the probe cannot parse is counted too: an example it cannot
     read is one it cannot vouch for.

Exit code = the count. Red-green: plant ``entry.get("region")`` in
settings.py, or a top-level ``construction_regions`` in a doc example, and
the count is 1.

Run:  python tests/one-offs/thinking/plugin-isolation/probe_no_config_knowledge.py
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SETTINGS = ROOT / "APITool" / "settings.py"
DOCS = [*sorted((ROOT / "docs").glob("*.md")), ROOT / "README.md", ROOT / "CLAUDE.md"]

# The keys core owns at the top level of the file.
TOP_LEVEL = frozenset({"client_id", "sheet_id", "plugin_dir", "targets"})
# The keys core reads inside a target entry. ``id`` is the sheet kind's
# locator, read for the adapter that kind selects; a file kind's ``path``
# will join it when that kind exists. Everything else in an entry is the
# kind's or the plugin's and is never read here.
IN_TARGET = frozenset({"kind", "plugin", "config", "id"})
CORE_READS = TOP_LEVEL | IN_TARGET

# Strings naming something a PERSON maintains in their own spreadsheet --
# the code probe's list, so the two probes disagree about nothing.
PERSON_TYPED = [
    "Totals Tab",
    "Left to buy",
    "At Current Station",
    "ALL SETTLEMENTS",
    "Extra next rnd",
    "In Carrier Now",
    "Left to deliver",
]
# A tab-qualified A1 range: "Agri Lrg. (ex)!R1:AC60", "Totals Tab!L3:L".
TAB_RANGE = re.compile(r"^.+![A-Z]{1,3}\d+(:[A-Z]{1,3}\d*)?$")


# ---------------------------------------------------------------------------
# 1. the keys core reads
# ---------------------------------------------------------------------------


def keys_read(source: str) -> list[tuple[int, str]]:
    """
    Every string literal ``settings.py`` uses as a configuration key, with
    its line: ``x.get("key")``, ``x["key"]``, ``"key" in x`` and the tuples
    on the right of ``in``. Environment lookups (``os.environ.get``, ``ED_*``)
    are not configuration keys and are left out.
    """
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []

    def is_environ(node: ast.AST) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "environ"

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args \
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) \
                and not is_environ(node.func.value):
            found.append((node.lineno, node.args[0].value))
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            found.append((node.lineno, node.slice.value))
        elif isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                found.append((node.lineno, node.left.value))
            for right in node.comparators:
                if isinstance(right, (ast.Tuple, ast.Set, ast.List)):
                    for elt in right.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            found.append((elt.lineno, elt.value))
    return [(n, k) for n, k in found if not k.startswith("ED_")]


def core_leaks(source: str) -> list[tuple[int, str]]:
    """The keys core reads that it does not own."""
    return [(n, k) for n, k in keys_read(source) if k not in CORE_READS]


# ---------------------------------------------------------------------------
# 2. the examples the docs show
# ---------------------------------------------------------------------------


def fenced_json(text: str) -> list[tuple[int, str]]:
    """Every ```json / ```jsonc block, with the line it starts on."""
    blocks, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        if re.match(r"^```(json|jsonc)\s*$", lines[i]):
            start, i = i + 1, i + 1
            body = []
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            blocks.append((start, "\n".join(body)))
        i += 1
    return blocks


def parse_example(body: str):
    """A doc example as an object, tolerating ``//`` comments. None if unreadable."""
    stripped = re.sub(r"//[^\n]*", "", body)
    try:
        return json.loads(stripped)
    except ValueError:
        return None


def marked_deprecated(body: str) -> bool:
    """
    Whether a block declares itself the OLD shape, in a comment a reader sees.

    Documenting the shape we moved away from is not contamination -- somebody
    upgrading has to recognise their own file. The exemption is deliberate,
    it is spelled in the example itself rather than kept in this probe, and
    every use of it is printed in the report: a silent exemption is how a
    leak becomes permanent.
    """
    return any("deprecated" in line.lower()
               for line in re.findall(r"//[^\n]*", body))


def person_typed(value: str) -> bool:
    return bool(TAB_RANGE.match(value)) or any(name in value for name in PERSON_TYPED)


def strings_in(node) -> list[str]:
    if isinstance(node, dict):
        return [s for v in node.values() for s in strings_in(v)]
    if isinstance(node, list):
        return [s for v in node for s in strings_in(v)]
    return [node] if isinstance(node, str) else []


def is_config_example(obj) -> bool:
    """
    Whether a JSON block documents ``~/.ed_capi_config.json`` at all.

    The docs also show the tokens file and Frontier's own payloads, which
    are not this surface. A block is judged when it names a key core owns,
    or when it carries a sheet string anywhere -- so an example made only of
    a plugin's keys is still judged if it shows a person's sheet.
    """
    if not isinstance(obj, dict):
        return False
    return bool(TOP_LEVEL & set(obj)) or any(person_typed(s) for s in strings_in(obj))


def example_leaks(obj) -> list[tuple[str, str]]:
    """
    Where an example puts a person's sheet strings, as (path, why).

    A key core does not own at the top level is a leak: it is a plugin's key
    shown where core would have to parse it. Inside ``targets.<name>``, the
    entry's own keys are the kind's and free; anything under ``config`` is
    the plugin's and never looked at. Everywhere else, a tab-qualified range
    or a person-typed name is a leak.
    """
    out: list[tuple[str, str]] = []
    if not is_config_example(obj):
        return out

    def walk(node, path: list[str], inside_config: bool) -> None:
        if inside_config:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + [str(key)], key == "config")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, path + [f"[{i}]"], False)
        elif isinstance(node, str) and person_typed(node):
            out.append((".".join(path), f"sheet string outside a config block: {node!r}"))

    for key in obj:
        if key not in TOP_LEVEL:
            out.append((str(key), "a key core does not own, at the top level"))
    walk(obj, [], False)
    return out


def scan_docs() -> tuple[list[tuple[str, int, str, str]], list[tuple[str, int]]]:
    """Every leak in every example, and every block exempted as deprecated."""
    rows: list[tuple[str, int, str, str]] = []
    exempt: list[tuple[str, int]] = []
    for doc in DOCS:
        if not doc.is_file():
            continue
        rel = doc.relative_to(ROOT).as_posix()
        for start, body in fenced_json(doc.read_text(encoding="utf-8")):
            obj = parse_example(body)
            if obj is not None and not is_config_example(obj):
                continue
            if marked_deprecated(body):
                exempt.append((rel, start))
                continue
            if obj is None:
                if re.search(r'"(client_id|sheet_id|plugin_dir|targets|config)"', body) \
                        or any(person_typed(s) for s in re.findall(r'"([^"]*)"', body)):
                    rows.append((rel, start, "-", "config example the probe cannot parse"))
                continue
            for path, why in example_leaks(obj):
                rows.append((rel, start, path, why))
    return rows, exempt


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def main() -> int:
    core = core_leaks(SETTINGS.read_text(encoding="utf-8"))
    docs, exempt = scan_docs()

    print("=" * 78)
    print("Person-typed spreadsheet knowledge on the CONFIGURATION surface")
    print("=" * 78)

    print("\n  -- keys core parses that it does not own --")
    if core:
        for n, key in core:
            print(f"    APITool/settings.py:{n:<5} {key!r}")
    else:
        print(f"    none -- core reads only: {', '.join(sorted(CORE_READS))}")

    print("\n  -- sheet strings in the documented examples --")
    if docs:
        for rel, n, path, why in docs:
            print(f"    {rel}:{n:<5} {path:<40} {why}")
    else:
        print("    none -- every sheet string sits inside a target's config block")

    if exempt:
        print("\n  -- exempt: blocks marked `// deprecated`, documenting the old shape --")
        for rel, n in exempt:
            print(f"    {rel}:{n}")

    total = len(core) + len(docs)
    print()
    print("=" * 78)
    print(f"{total} leaks   ({len(core)} parsed by core, {len(docs)} in examples)")
    if total:
        print()
        print("A key must move under its plugin's config block, and the example")
        print("that shows it must show it there.")
    print("=" * 78)
    return total


if __name__ == "__main__":
    sys.exit(min(main(), 125))
