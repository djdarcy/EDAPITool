"""
Step tokens: the one grammar a configuration lists under
``pipelines[...].steps`` and a person types after ``edapitool pipeline``.

A token means one of three things, tried in this order:

``target``
    A configured target's name. That target's plugin step runs.
``built-in``
    A stage the tool itself runs: ``market``, ``cargo``, ``carrier``,
    ``regions`` -- the four things ``serve`` keeps current.
``command``
    ``<plugin>:<command>[=params]``. A plugin's one-off command, run once,
    with ``params`` as its tail.

Core routes a token and never interprets it. The parameters are split from
the command at the FIRST ``=`` and kept exactly as written, so a ``=`` inside
a value survives; what they mean is the plugin's business. A token that is
none of the three is refused by name, with the meanings it was tried
against, and a target named like a built-in is refused when the
configuration is read (``settings.get_targets``), because a token naming it
would mean two things.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Container, Mapping, Optional

#: The stages the tool runs itself, by the name a step token uses.
BUILTINS = ("market", "cargo", "carrier", "regions")

TARGET = "target"
BUILTIN = "built-in"
COMMAND = "command"


@dataclass(frozen=True)
class Token:
    """One resolved step token."""

    text: str
    kind: str
    # The target's name, the stage's name, or the plugin's name.
    name: str
    command: str = ""
    # Everything after the first "=", unread; None when there was no "=".
    params: Optional[str] = None


class UnknownStep(ValueError):
    """A token that is none of the three things a step can be."""


def refusal(text: str, commands: Mapping[str, Container[str]], where: str) -> str:
    """Why ``text`` is not a step, as one sentence beginning with ``where``."""
    plugin, colon, rest = text.partition(":")
    if colon:
        command = rest.partition("=")[0]
        if plugin not in commands:
            return (f"{where} names the command {text!r}, but no loaded plugin is "
                    f"named {plugin!r}")
        offered = ", ".join(sorted(commands[plugin])) or "none"
        return (f"{where} names the command {text!r}, but plugin {plugin!r} offers "
                f"no command {command!r} (it offers: {offered})")
    return (f"{where} names target {text!r}, which is not configured, and it is not "
            f"a built-in stage ({', '.join(BUILTINS)}) or a plugin command "
            "(<plugin>:<command>)")


def resolve(text: str, *, targets: Container[str],
            commands: Mapping[str, Container[str]],
            where: str = "the step list") -> Token:
    """
    What ``text`` names: a target, a built-in stage, or a plugin command.

    ``targets`` holds the configured target names; ``commands`` maps each
    loaded plugin's name to the command names it offers (empty when it
    offers none). Raises :class:`UnknownStep` with :func:`refusal`'s
    sentence when the token is none of them.
    """
    if text in targets:
        return Token(text, TARGET, text)
    if text in BUILTINS:
        return Token(text, BUILTIN, text)
    plugin, colon, rest = text.partition(":")
    if colon and plugin and rest:
        command, equals, params = rest.partition("=")
        if command and command in commands.get(plugin, ()):
            return Token(text, COMMAND, plugin, command, params if equals else None)
    raise UnknownStep(refusal(text, commands, where))
