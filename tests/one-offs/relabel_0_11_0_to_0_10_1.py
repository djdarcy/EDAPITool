"""
One-off, 2026-10-09: the sequencing release was labelled 0.11.0 and the
version-bump check judged it a PATCH of the pipeline line (the line's own
goal finishing, not a new capability area; the config-file break has the
0.8.2 precedent as a patch). Relabel every reference in the tree to 0.10.1.

`APITool/version.py` is left alone: MINOR/PATCH were edited by hand and the
hook restamps `__version__` at commit. Run from the repository root.
"""

from pathlib import Path

FILES = [
    "APITool/regions.py",
    "APITool/settings.py",
    "APITool/stockconfig.py",
    "CHANGELOG.md",
    "docs/configuration.md",
    "docs/construction.md",
    "docs/serve.md",
    "tests/checklists/v0.10.1__Feature__sequencing-from-the-cli.md",
    "tests/conftest.py",
    "tests/one-offs/thinking/plugin-isolation/probe_no_config_knowledge.py",
    "tests/test_changelog_break.py",
    "tests/test_config_regions.py",
    "tests/test_config_surface.py",
    "tests/test_destination_seam.py",
    "tests/test_help_output.py",
    "tests/test_plugin_flags.py",
    "tests/test_plugin_loader.py",
    "tests/test_region_binder.py",
    "tests/test_stock_config.py",
]


def main() -> int:
    changed = 0
    for name in FILES:
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        new = text.replace("0.11.0", "0.10.1")
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
            print(f"relabelled {name}: {text.count('0.11.0')} occurrence(s)")
    print(f"{changed} file(s) changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
