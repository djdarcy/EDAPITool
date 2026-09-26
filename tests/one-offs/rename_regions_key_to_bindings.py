"""
2026-09-26, second pass of the rename: the plugin's config key becomes `bindings`.

After rename_plugin_to_regions.py the key was `regions`, the same word as the
plugin's name -- `{"plugin": "regions", "config": {"regions": [...]}}` -- and
test_the_composing_modules_hold_no_plugin_schema_literal could no longer tell
core naming the plugin (allowed) from core knowing its schema (not allowed).
`bindings` reads as "the regions plugin's bindings" and matches the function
core asks for, `region_bindings`.

Only the KEY shapes change: a dict/JSON key `"regions":`, a `.get("regions")`,
the `regions[N]` / `regions[{i}]` position in messages, and the quoted
`"regions" must be a list`. The plugin NAME `"regions"` is left alone.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

LIVE = [
    "APITool/plugins/regions/__init__.py", "APITool/plugins/regions/bindings.py",
    "APITool/daemon.py", "APITool/cli.py",
    "tests/conftest.py", "tests/test_config_regions.py", "tests/test_region_binder.py",
    "tests/test_plugin_loader.py", "tests/test_plugin_flags.py", "tests/test_settings.py",
    "tests/test_config_surface.py", "tests/test_stock_config.py",
    "tests/one-offs/thinking/plugin-isolation/probe_no_config_knowledge.py",
    "docs/configuration.md", "docs/construction.md", "docs/serve.md",
    "docs/writing-a-plugin.md",
    "tests/checklists/v0.8.2__Feature__a-region-can-hold-any-data.md",
]

RULES = [
    (r'"regions"(\s*):', r'"bindings"\1:'),
    (r'\.get\("regions"\)', '.get("bindings")'),
    (r"\bregions\[(\d+|\{i\})\]", r"bindings[\1]"),
    (r'"regions" must be a list', '"bindings" must be a list'),
]

total = 0
for rel in LIVE:
    path = ROOT / rel
    raw = path.read_bytes().decode("utf-8")
    text = raw
    counts = []
    for pattern, new in RULES:
        text, n = re.subn(pattern, new, text)
        if n:
            counts.append(f"{n}x {pattern}")
    if text != raw:
        path.write_bytes(text.encode("utf-8"))
        total += 1
        print(f"{rel}: " + "; ".join(counts))
print(f"{total} files changed")
