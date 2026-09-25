"""
What `--help` SAYS, not merely that it runs.

`tests/test_destination_seam.py` invokes `edapitool market --help` to prove
the command survives with the destination layer pulled. It never reads the
output. So the two things the help page is carrying -- the warning on
`--force`, and the grouping that makes it findable -- were asserted by
nothing: a refactor could shorten "There is no undo" out of existence and the
suite would stay green.

That gap was found by a person running the v0.7.6 checklist, who reported
the `--force` text as adequate and its PLACEMENT as the problem. Both halves
are pinned here, because both are what makes a destructive flag safe to
ship: the sentence, and where the sentence sits.

From v0.8.0 the placement rule is different in kind: `--force` and every
other word of the settlement workbook's vocabulary sit under a group titled
by the plugin that owns them, and that group exists only when the plugin is
loaded. So the tests below come in two shapes -- what the help shows with
NO plugin configured (core's own words, and none of the plugin's), and what
it shows with the settlement plugin configured (its group, with its words).

This file asserts on WORDS, which is usually a bad idea -- help text should
be free to improve. The substrings chosen are therefore the claims rather
than the phrasing: that the default is to leave a cell alone, that formulas
are why, and that the write cannot be undone. Reword freely; keep the claim.

SAFETY (rule 1b): argparse prints and raises SystemExit. No command function
is reached, so nothing here can open a spreadsheet, read a journal, or make
a network call even if every guard in the tool were broken.
"""

from __future__ import annotations

import pytest

from APITool.cli import main

PLUGIN_GROUP = "the totals plugin:"
CONSTRUCTION_GROUP = "the construction plugin:"


def _help(*argv: str) -> str:
    """
    The help page for a command, as a person would see it, with the usage
    synopsis removed.

    The synopsis lists every flag again at the top -- `[--force]` among
    twenty-three others -- so a naive `page.index("--force")` finds it there,
    above every heading, and any question about WHERE a flag sits answers
    itself wrongly. Dropping it is what makes position meaningful.
    """
    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), pytest.raises(SystemExit) as exit_:
        main([*argv, "--help"])
    assert exit_.value.code == 0
    page = buffer.getvalue()
    return page[page.index("options:"):]


def _flat(*argv: str) -> str:
    """
    The same page with runs of whitespace collapsed.

    argparse wraps help text to the terminal width, so "There is no undo."
    arrives as "There is no\\n                        undo." A substring
    test against the un-flattened page fails on the line break rather than
    on the claim, which is a test that breaks when the window resizes.
    """
    return " ".join(_help(*argv).split())


def _defined_at(page: str, flag: str) -> int:
    """
    Where a flag is DEFINED, not merely mentioned.

    Flags name each other in their help text -- `--dry-run` says "With
    --update-sheet, ...", and `--totals-tab` says "refreshed with
    --write-location". A plain `page.index(flag)` finds whichever comes
    first, which may be a sentence inside a different flag's description
    and in a different group entirely. argparse indents a definition by
    exactly two spaces at the start of its line, and nothing else in the
    page matches that.
    """
    marker = f"\n  {flag}"
    assert marker in page, f"{flag} is not defined on {page[:40]!r}..."
    return page.index(marker)


# ---------------------------------------------------------------------------
# The --force warning: the sentence (needs the plugin that owns the flag)
# ---------------------------------------------------------------------------


def test_force_warns_that_the_default_is_to_leave_a_cell_alone(configured_totals):
    page = _flat("market")
    assert "--force" in page
    assert "left alone" in page, (
        "--force must say what it overrides, not only what it does"
    )


def test_force_says_why_the_default_exists(configured_totals):
    """
    "Because many sheets hold formulas there" is the reason a reader needs;
    without it, skipping looks like timidity rather than the answer to a
    defect that destroyed twenty formulas in one run.

    Read from `--force`'s own paragraph: core's export help also says
    "formulas", and a page-wide search was satisfied with the flag gone.
    """
    page = _help("market")
    start = _defined_at(page, "--force")
    paragraph = " ".join(page[start:start + 500].split())
    assert "formulas" in paragraph


def test_force_says_there_is_no_undo(configured_totals):
    """
    The claim that most needs to survive a rewrite. Remembering what a cell
    held is #29 and is not built, so this sentence is the whole of the
    user's protection against a --force they meant to type as --dry-run.
    """
    assert "no undo" in _flat("market")


def test_write_location_still_says_why_it_is_off_by_default(configured_totals):
    """
    `serve --write-location` is the prior art this project reasoned from --
    the flag named for what it overwrites, off by default, with the reason
    in its help. If that text is ever lost, the precedent goes with it.
    """
    page = _flat("serve")
    assert "Off by default" in page
    assert "formulas" in page and "overwrite" in page


# ---------------------------------------------------------------------------
# Where the words sit: core's groups, and the plugin's own
# ---------------------------------------------------------------------------


CORE_MARKET_GROUPS = [
    "signing in to Frontier:",
    "finding the market:",
    "the spreadsheet:",
    "writing to it:",
    "exporting data:",
]


@pytest.mark.parametrize("heading", CORE_MARKET_GROUPS)
def test_the_market_help_is_grouped(heading):
    """
    Twenty-four flags in one undifferentiated run is not a reference. A
    refactor that flattens this back is a regression in the same sense a
    lost warning is: the text survives and nobody finds it.
    """
    assert heading in _help("market"), CORE_MARKET_GROUPS


@pytest.mark.parametrize("command", ["market", "carrier", "serve", "profile"])
def test_nothing_but_help_itself_sits_under_the_catch_all_heading(command):
    """
    #28 criterion 1: every flag under a heading that says what it is for.
    argparse's unnamed `options:` keeps only `-h`; the sign-in flags, which
    every verb inherits, have a group of their own.
    """
    page = _help(command)
    catch_all = page.split("options:\n", 1)[1].split("\n\n", 1)[0]
    assert "--help" in catch_all
    assert "--client-id" not in catch_all and "--manual-auth" not in catch_all
    assert "signing in to Frontier:" in page


def test_with_no_plugin_the_help_shows_none_of_its_words():
    """An install without the settlement workbook never sees its vocabulary."""
    page = _help("market")
    assert PLUGIN_GROUP not in page
    for flag in ("--force", "--totals-tab", "--glyph-marker-column", "--empty-glyph-marker",
                 "--no-glyph-markers", "--show-formula", "--write-location"):
        assert f"\n  {flag}" not in page, f"{flag} is core's business now?"


def test_with_the_plugin_its_words_sit_under_its_own_name(configured_totals):
    """
    One group per loaded plugin, titled by the plugin, holding every word it
    declares and nothing of core's. That is #28's grouping, made structural.
    """
    page = _help("market")
    assert PLUGIN_GROUP in page
    group = page.index(PLUGIN_GROUP)
    for flag in ("--force", "--write-location", "--totals-tab", "--need-header",
                 "--need-sign", "--glyph-marker-column", "--empty-glyph-marker", "--no-glyph-markers",
                 "--no-show-covered", "--no-color", "--show-formula",
                 "--write-glyph-marker-header"):
        assert _defined_at(page, flag) > group, f"{flag} is defined above the plugin's group"
    for flag in ("--update-sheet", "--dry-run", "--sheet-id", "--journal-dir"):
        assert _defined_at(page, flag) < group, f"{flag} is core's and sits in the plugin's group"


def test_the_plugin_group_names_glyph_markers(configured_totals):
    """#28: the term is `glyph marker`, said where the glyphs live."""
    assert "glyph" in _flat("market")


def test_the_serve_help_puts_each_plugins_words_under_its_own_name(configured_totals, configured_construction):
    """
    `--write-location` is serve's only write into someone else's cell and is
    the roll-up plugin's word; `--construction-region` is the construction
    plugin's. Two plugins on one workbook, two groups, each honest.
    """
    page = _help("serve")
    assert PLUGIN_GROUP in page and CONSTRUCTION_GROUP in page
    assert page.index(PLUGIN_GROUP) < _defined_at(page, "--write-location")
    assert page.index(CONSTRUCTION_GROUP) < _defined_at(page, "--construction-region")


# ---------------------------------------------------------------------------
# What grouping must NOT have changed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command, flag", [
    ("market", "--update-sheet"), ("market", "--dry-run"),
    ("market", "--export"), ("market", "--json"), ("market", "--sheet-id"),
    ("serve", "--once"), ("serve", "--interval"), ("serve", "--ship-tab"),
])
def test_every_core_flag_still_appears(command, flag):
    """A core flag silently dropped while being regrouped would be a breaking change in disguise."""
    assert flag in _flat(command)


@pytest.mark.parametrize("command, flag", [
    ("market", "--no-glyph-markers"), ("market", "--show-formula"),
    ("market", "--no-color"), ("market", "--empty-glyph-marker"),
    ("serve", "--construction-region"),
])
def test_every_plugin_flag_still_appears_when_the_plugin_is_loaded(
        command, flag, configured_totals, configured_construction):
    """Moved, not dropped: every word the plugin took with it is still typed the same way."""
    assert flag in _flat(command)
