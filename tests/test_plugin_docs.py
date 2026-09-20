"""
The plugin-authoring page describes the contract that actually exists.

#26's ninth criterion asks for documentation good enough to write a second
plugin from. A page that drifts from the code is worse than no page, because
someone follows it and gets a plugin that does not load -- so these tests
check the page against the real contract rather than against a memory of it.

They are deliberately shallow: they assert that every name the contract uses
appears, that the worked example is real Python, and that the example does
not reach for anything the tool does not export. Whether the prose is any
good is a human's judgement, and the checklist asks for it.
"""

import ast
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
PAGE = DOCS / "writing-a-plugin.md"


def python_blocks(text: str) -> list[str]:
    return re.findall(r"^```python\n(.*?)^```", text, re.MULTILINE | re.DOTALL)


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_page_exists_and_is_linked_from_the_readme():
    readme = (DOCS.parent / "README.md").read_text(encoding="utf-8")
    assert PAGE.is_file()
    assert "writing-a-plugin.md" in readme


def test_every_name_the_contract_uses_is_documented(page):
    """
    The surface a plugin implements, taken from the shipped plugin's own
    docstring. A name the tool asks for and the page never mentions is a
    plugin somebody writes without.
    """
    for name in ("KIND", "layout", "writes", "supplies", "subscribes",
                 "default_config", "check_config", "Subscription"):
        assert name in page, f"the page never mentions {name}"


def test_every_kind_the_tool_registers_is_described(page):
    from APITool import loader

    for kind in loader.KINDS:
        assert f"`{kind}`" in page, f"the page does not describe the {kind!r} kind"


def test_the_refresh_attributes_the_page_promises_are_real(page):
    """Each `ctx.x` the page names must exist on a real Refresh."""
    from APITool.registry import Refresh

    ctx = Refresh({}, worksheet=None, layout=None, guard=None, target="t",
                  result=None, checked_at="", options={})
    for attribute in sorted(set(re.findall(r"`ctx\.([a-z_]+)", page))):
        assert hasattr(ctx, attribute) or attribute in ctx.env, \
            f"the page promises ctx.{attribute}, which a refresh does not carry"


def test_the_worked_example_is_real_python(page):
    blocks = python_blocks(page)
    assert blocks, "the page has no example to follow"
    for block in blocks:
        ast.parse(block)


def test_the_worked_example_imports_only_what_the_tool_exports(page):
    """
    Someone copies this block. Every import in it has to resolve, or the
    page teaches a plugin that cannot load.
    """
    import importlib

    for block in python_blocks(page):
        for node in ast.walk(ast.parse(block)):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("APITool"):
                module = importlib.import_module(node.module)
                for alias in node.names:
                    assert hasattr(module, alias.name), \
                        f"the example imports {alias.name} from {node.module}, which is not there"


def test_the_examples_plugin_would_actually_load(tmp_path, monkeypatch, page):
    """
    The strongest thing this file does: plant the page's own worked example
    as a plugin, point configuration at it, and require that the loader
    loads it, reads its declaration, and builds it an enforcer.
    """
    from APITool import loader, settings

    # The COMPLETE example, not the snippets illustrating one function each:
    # a whole plugin is the one that declares its kind and subscribes.
    blocks = [b for b in python_blocks(page)
              if "KIND = " in b and "def subscribes" in b and "def layout" in b]
    assert len(blocks) == 1, "the page must carry exactly one complete worked example"

    plugins = tmp_path / "plugins"
    (plugins / "myfileplugin").mkdir(parents=True)
    (plugins / "myfileplugin" / "__init__.py").write_text(blocks[0], encoding="utf-8")
    monkeypatch.setenv("ED_PLUGIN_DIR", str(plugins))
    monkeypatch.delenv("ED_CONFIG_DIR", raising=False)

    path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", path)
    path.write_text(
        '{"targets": {"nightly-dump": {"kind": "jsonl", "plugin": "myfileplugin",'
        ' "config": {"path": "' + str(tmp_path / "out.jsonl").replace("\\", "/") + '"}}}}',
        encoding="utf-8")

    result = loader.discover()
    entry = result.first()

    assert entry is not None, f"the example did not load: {result.describe()}"
    assert entry.name == "myfileplugin"
    assert entry.kind == "jsonl"
    assert entry.complaints == ()
    # And the tool can build it an enforcer from what it declared -- which is
    # the whole point of the declaration being in the page at all.
    enforcer = loader.build_enforcer(entry.kind, entry.module.layout(
        path=str(tmp_path / "out.jsonl")).writes())
    assert enforcer.allows(str(tmp_path / "out.jsonl"))
    assert not enforcer.allows(str(tmp_path / "elsewhere.jsonl"))
