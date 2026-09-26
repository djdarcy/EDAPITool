"""
2026-09-26: the `construction` plugin becomes `regions` (v0.8.2, before commit).

The maintainer's call: once a region could hold the market, cargo or carrier,
the plugin's name no longer said what it was. The data kind "construction",
the `construction` command and the `--construction-region` flag keep the name;
the plugin, its config key and the core lookup do not.

Run after `git mv APITool/plugins/construction APITool/plugins/regions`.
Ordered, whole-token replacements over an explicit list of LIVE files; the
checklists, CHANGELOG entries and one-off scripts of earlier versions are a
record of what was true then and are not touched. Prints every change count.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

LIVE = [
    "APITool/cli.py", "APITool/daemon.py", "APITool/stockconfig.py",
    "APITool/plugins/regions/__init__.py", "APITool/plugins/regions/bindings.py",
    "tests/conftest.py", "tests/test_config_regions.py", "tests/test_region_binder.py",
    "tests/test_plugin_loader.py", "tests/test_plugin_flags.py", "tests/test_settings.py",
    "tests/test_config_surface.py", "tests/test_stock_config.py",
    "tests/test_destination_seam.py", "tests/test_supplier_registry.py",
    "tests/one-offs/thinking/plugin-isolation/poc_pull_the_plug.py",
    "tests/one-offs/thinking/plugin-isolation/probe_no_config_knowledge.py",
    "docs/configuration.md", "docs/construction.md", "docs/serve.md",
    "docs/writing-a-plugin.md",
    "tests/checklists/v0.8.2__Feature__a-region-can-hold-any-data.md",
]

# Order matters: the specific call sites first, then the config key everywhere.
RULES = [
    (r"\bbindings\.construction_regions\(", "bindings.region_bindings("),
    (r'offering\("construction_regions"\)', 'offering("region_bindings")'),
    (r'getattr\(binder\.module, "construction_regions"', 'getattr(binder.module, "region_bindings"'),
    (r'seen\["construction_regions"\]', 'seen["region_bindings"]'),
    (r"\bdef construction_regions\(", "def region_bindings("),
    (r"import construction_regions, ", "import region_bindings, "),
    (r"\bconstruction_regions=", "region_bindings="),
    (r"\bconstruction_regions: Optional", "region_bindings: Optional"),
    (r"in construction_regions or \[\]", "in region_bindings or []"),
    (r"\bconstruction_regions\b", "regions"),
    (r"\bAPITool\.plugins\.construction\b", "APITool.plugins.regions"),
    (r"\bplugins\.construction\b", "plugins.regions"),
    (r'"plugin": "construction"', '"plugin": "regions"'),
    (r'\bCONSTRUCTION_TARGET = "construction-workbook"', 'REGIONS_TARGET = "regions-workbook"'),
    (r'\bCONSTRUCTION_PLUGIN = "construction"', 'REGIONS_PLUGIN = "regions"'),
    (r"\bCONSTRUCTION_TARGET\b", "REGIONS_TARGET"),
    (r"\bCONSTRUCTION_PLUGIN\b", "REGIONS_PLUGIN"),
    (r'"construction-workbook"', '"regions-workbook"'),
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
        print(f"{rel}:")
        for c in counts:
            print(f"    {c}")
print(f"{total} files changed")
