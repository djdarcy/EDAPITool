"""
Step tokens (slice 2 of the pipeline redesign, unit 1): one grammar for
`pipelines[...].steps` and the `pipeline` verb. A token is a target, a
built-in stage, or `<plugin>:<command>[=params]`, tried in that order. Smokes.
"""

import json
from types import SimpleNamespace

import pytest

from APITool import loader, settings, steps

TARGETS = {"totals-workbook", "market-log"}
COMMANDS = {"settlement": frozenset({"new"}), "totals": frozenset()}


def _resolve(text):
    return steps.resolve(text, targets=TARGETS, commands=COMMANDS)


def test_a_target_name_is_a_target():
    token = _resolve("totals-workbook")
    assert (token.kind, token.name) == (steps.TARGET, "totals-workbook")


@pytest.mark.parametrize("name", steps.BUILTINS)
def test_each_built_in_stage_is_a_built_in(name):
    assert _resolve(name).kind == steps.BUILTIN


def test_a_command_keeps_its_parameters_unread_from_the_first_equals():
    token = _resolve('settlement:new=--type "industrial large" --name a=b')
    assert (token.kind, token.name, token.command) == (steps.COMMAND, "settlement", "new")
    assert token.params == '--type "industrial large" --name a=b'


def test_a_command_without_parameters_has_none():
    assert _resolve("settlement:new").params is None
    assert _resolve("settlement:new=").params == ""


def test_a_target_wins_over_a_command_shaped_name():
    token = steps.resolve("settlement:new", targets={"settlement:new"}, commands=COMMANDS)
    assert token.kind == steps.TARGET


@pytest.mark.parametrize("text, said", [
    ("nothere", "names target 'nothere', which is not configured, and it is not a "
                "built-in stage (market, cargo, carrier, regions) or a plugin command"),
    ("nobody:new", "no loaded plugin is named 'nobody'"),
    ("settlement:old", "plugin 'settlement' offers no command 'old' (it offers: new)"),
    ("totals:setup", "plugin 'totals' offers no command 'setup' (it offers: none)"),
])
def test_an_unknown_token_is_refused_by_name(text, said):
    with pytest.raises(steps.UnknownStep, match="the step list") as caught:
        _resolve(text)
    assert said in str(caught.value)


def _config(monkeypatch, tmp_path, body):
    directory = tmp_path / "cfg"
    directory.mkdir()
    (directory / "config.json").write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setenv("ED_CONFIG_DIR", str(directory))
    monkeypatch.setattr(settings, "CONFIG_FILE", directory / "config.json")


@pytest.mark.parametrize("name", steps.BUILTINS)
def test_a_target_named_like_a_built_in_is_refused_at_load(monkeypatch, tmp_path, name):
    _config(monkeypatch, tmp_path, {"targets": {name: {"kind": "jsonl", "plugin": "jsonl"}}})
    with pytest.raises(ValueError, match=rf"targets\['{name}'\] has the name of the built-in stage"):
        settings.get_targets()


def _result(pipeline_steps):
    module = SimpleNamespace(process=lambda data, ctx: data,
                             commands=lambda: {"new": object()})
    target = SimpleNamespace(name="totals-workbook", plugin="totals")
    entry = loader.Loaded(name="totals", module=module, found=None, kind="gsheet",
                          declaration={}, target=target)
    return loader.LoadResult(
        loaded=[entry],
        pipelines={"market": settings.Pipeline("market", "market", tuple(pipeline_steps))},
        configured={"totals-workbook": target},
    )


def test_the_loader_resolves_steps_through_the_grammar():
    result = _result(["totals-workbook"])
    assert [e.name for e in result.steps("market")] == ["totals"]
    assert result.commands() == {"totals": frozenset({"new"})}


@pytest.mark.parametrize("token, said", [
    ("cargo", "lists the built-in stage 'cargo'"),
    ("totals:new", "lists the plugin command 'totals:new'"),
    ("totals:nope", "plugin 'totals' offers no command 'nope'"),
])
def test_a_refresh_refuses_what_it_cannot_run_inside_itself(token, said):
    result = _result(["totals-workbook", token])
    assert result.steps("market") == []
    assert any(said in refusal for refusal in result.refusals), result.refusals
