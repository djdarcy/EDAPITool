"""
What `--help` SAYS, not merely that it runs.

`tests/test_destination_seam.py` invokes `edapitool market --help` to prove
the command survives with the destination layer pulled. It never reads the
output. So the two things the help page is carrying for this release --
the warning on `--force`, and the grouping that makes it findable -- were
asserted by nothing: a refactor could shorten "There is no undo" out of
existence and the suite would stay green.

That gap was found by a person running the v0.7.6 checklist, who reported
the `--force` text as adequate and its PLACEMENT as the problem. Both halves
are pinned here, because both are what makes a destructive flag safe to
ship: the sentence, and where the sentence sits.

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
# The warning on the one flag that destroys work
# ---------------------------------------------------------------------------


def test_force_warns_that_the_default_is_to_leave_a_cell_alone():
    page = _flat("market")
    assert "--force" in page
    assert "left alone" in page, (
        "--force must say what it overrides, not only what it does"
    )


def test_force_says_why_the_default_exists():
    """
    "Because many sheets hold formulas there" is the reason a reader needs;
    without it, skipping looks like timidity rather than the answer to a
    defect that destroyed twenty formulas in one run.
    """
    assert "formulas" in _flat("market")


def test_force_says_there_is_no_undo():
    """
    The claim that most needs to survive a rewrite. Remembering what a cell
    held is #29 and is not built, so this sentence is the whole of the
    user's protection against a --force they meant to type as --dry-run.
    """
    assert "no undo" in _flat("market")


def test_write_location_still_says_why_it_is_off_by_default():
    """
    `serve --write-location` is the prior art this project reasoned from --
    the flag named for what it overwrites, off by default, with the reason
    in its help. If that text is ever lost, the precedent goes with it.
    """
    page = _flat("serve")
    assert "Off by default" in page
    assert "formulas" in page and "overwrite" in page


# ---------------------------------------------------------------------------
# Where the warning sits, which is the other half of whether it works
# ---------------------------------------------------------------------------


MARKET_GROUPS = [
    "finding the market:",
    "the spreadsheet:",
    "writing to it:",
    "the marker column:",
    "exporting data:",
]


@pytest.mark.parametrize("heading", MARKET_GROUPS)
def test_the_market_help_is_grouped(heading):
    """
    Twenty-four flags in one undifferentiated run is not a reference. A
    refactor that flattens this back is a regression in the same sense a
    lost warning is: the text survives and nobody finds it.
    """
    assert heading in _help("market"), MARKET_GROUPS


def test_force_sits_with_the_other_writing_flags():
    """
    Placement, asserted rather than assumed. `--force` belongs beside
    --update-sheet and --dry-run, under a heading that says nothing here
    happens unless you ask -- not next to --no-color, which is where it
    was when a reader called it hard to find.
    """
    page = _help("market")
    writing = page.index("writing to it:")
    glyphs = page.index("the marker column:")

    assert writing < _defined_at(page, "--force") < glyphs
    assert writing < _defined_at(page, "--update-sheet") < glyphs
    assert writing < _defined_at(page, "--dry-run") < glyphs


def test_the_serve_help_separates_cells_the_tool_does_not_own():
    """`--write-location` is serve's only write into someone else's cell."""
    page = _help("serve")
    heading = "writing to cells the tool does not own:"

    assert heading in page
    assert page.index(heading) < _defined_at(page, "--write-location")


# ---------------------------------------------------------------------------
# What grouping must NOT have changed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command, flag", [
    ("market", "--update-sheet"), ("market", "--dry-run"),
    ("market", "--no-markers"), ("market", "--show-formula"),
    ("market", "--no-color"),
    ("market", "--empty-marker"), ("market", "--export"),
    ("market", "--json"), ("market", "--sheet-id"),
    ("serve", "--once"), ("serve", "--construction-region"),
    ("serve", "--interval"), ("serve", "--ship-tab"),
])
def test_every_flag_still_appears(command, flag):
    """
    A flag silently dropped while being moved under a heading would be a
    breaking change wearing a presentation change's clothes.
    """
    assert flag in _flat(command)
