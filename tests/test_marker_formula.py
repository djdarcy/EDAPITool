"""
The marker formula must be generated from the scale, not transcribed beside it.

``--show-formula`` prints the formula a spreadsheet uses to render markers from
a generated MarketData tab. Until 2026-09-09 that text was a hand-written
docstring in ``cli.py`` carrying its own copy of the thresholds (0.375, 0.625)
and the glyphs -- while ``markers.py`` held the same values as the definition
the tool itself writes by.

Two sources of truth for one rule, agreeing only because one person typed both.
And the copy was not the harmless one: the 197 formulas now live in the owner's
spreadsheet were pasted from that docstring, so changing ``_PARTIAL_SCALE``
would have left the sheet grading on the old thresholds with every test green.

These tests assert the formula tracks the constants, so the drift cannot
reopen.
"""

import re

import pytest

from APITool.markers import (
    COLOUR_TEXT_COVERED,
    FILL_FOR_MARKER,
    LIGHT_TEXT_MARKERS,
    MARKER_EMPTY,
    MARKER_ENOUGH,
    MARKER_HALF,
    MARKER_QUARTER,
    MARKER_THREE_QUARTER,
    _PARTIAL_SCALE,
    marker_formula,
    marker_formula_help,
)


# --------------------------------------------------------------------------
# The formula tracks the scale
# --------------------------------------------------------------------------

def test_every_threshold_in_the_scale_appears_in_the_formula():
    """
    The band boundaries are the whole content of the scale. All but the last
    become a comparison; the last is the final else and has no number.
    """
    formula = marker_formula()
    *bands, _top = _PARTIAL_SCALE
    for limit, _glyph in bands:
        assert f"stock/need<{limit:g}" in formula, (
            f"threshold {limit} from _PARTIAL_SCALE is missing from the formula"
        )


def test_the_formula_carries_no_threshold_the_scale_does_not_have():
    """The direction the first test cannot see: a stale leftover number."""
    formula = marker_formula()
    in_formula = {float(m) for m in re.findall(r"stock/need<([0-9.]+)", formula)}
    expected = {limit for limit, _ in _PARTIAL_SCALE[:-1]}
    assert in_formula == expected, (
        f"formula compares against {in_formula}, scale defines {expected}"
    )


def test_every_glyph_in_the_scale_appears_in_the_formula():
    formula = marker_formula()
    for _limit, glyph in _PARTIAL_SCALE:
        assert f'"{glyph}"' in formula, f"glyph {glyph!r} missing from the formula"
    for glyph in (MARKER_ENOUGH, MARKER_EMPTY):
        assert f'"{glyph}"' in formula


def test_changing_the_scale_changes_the_formula(monkeypatch):
    """
    The point of the whole unit. If this passes while the others pass, the
    formula is genuinely derived rather than coincidentally matching.
    """
    before = marker_formula()
    monkeypatch.setattr(
        "APITool.markers._PARTIAL_SCALE",
        ((0.5, MARKER_QUARTER), (0.9, MARKER_HALF), (1.0, MARKER_THREE_QUARTER)),
    )
    after = marker_formula()
    assert after != before
    assert "stock/need<0.5" in after and "stock/need<0.9" in after
    assert "0.375" not in after, "the old thresholds survived a scale change"


def test_the_formula_is_syntactically_balanced():
    """
    A Sheets formula that does not balance is rejected on paste, and this one
    is assembled by a loop -- exactly the kind of construction that loses a
    bracket when the scale gains a band.
    """
    formula = marker_formula()
    assert formula.count("(") == formula.count(")")
    assert formula.count('"') % 2 == 0


@pytest.mark.parametrize("bands", [1, 2, 3, 5])
def test_the_formula_stays_balanced_at_any_scale_length(monkeypatch, bands):
    scale = tuple(
        ((i + 1) / (bands + 1), MARKER_HALF) for i in range(bands - 1)
    ) + ((1.0, MARKER_THREE_QUARTER),)
    monkeypatch.setattr("APITool.markers._PARTIAL_SCALE", scale)
    formula = marker_formula()
    assert formula.count("(") == formula.count(")"), formula


def test_an_empty_scale_is_refused_rather_than_emitting_a_broken_formula():
    """Silently producing `IF(...,"")` would be worse than failing."""
    import APITool.markers as markers_mod

    original = markers_mod._PARTIAL_SCALE
    markers_mod._PARTIAL_SCALE = ()
    try:
        with pytest.raises(ValueError, match="scale"):
            marker_formula()
    finally:
        markers_mod._PARTIAL_SCALE = original


# --------------------------------------------------------------------------
# The help text is generated too, not just the formula inside it
# --------------------------------------------------------------------------

def test_the_help_text_embeds_the_generated_formula():
    assert marker_formula() in marker_formula_help()


def test_the_suggested_fills_come_from_the_colour_map():
    """
    The conditional-formatting block used to carry its own copy of every hex
    colour. Same drift, one section further down.
    """
    help_text = marker_formula_help()
    for glyph, colour in FILL_FOR_MARKER.items():
        assert colour in help_text, f"fill {colour} for {glyph!r} missing"
    assert COLOUR_TEXT_COVERED in help_text


def test_the_dark_fill_is_the_one_marked_for_light_text():
    help_text = marker_formula_help()
    (light,) = LIGHT_TEXT_MARKERS
    # Anchor on the colour, not the glyph: the glyph also opens its legend
    # line, and matching that instead would test nothing about the fills.
    line = next(
        ln for ln in help_text.splitlines() if FILL_FOR_MARKER[light] in ln
    )
    assert "white bold text" in line
    others = [
        ln
        for glyph, colour in FILL_FOR_MARKER.items()
        if glyph != light
        for ln in help_text.splitlines()
        if colour in ln
    ]
    assert not any("white bold text" in ln for ln in others), (
        "only the darkest fill should call for light text"
    )


def test_the_help_text_names_the_tab_it_is_asked_about():
    assert "ShipCargo" in marker_formula_help(tab="ShipCargo")


def test_the_help_text_no_longer_promises_that_no_markers_writes_nothing():
    """
    The text tells the reader to run --no-markers. Since that flag now still
    refreshes the location cells, the instruction has to say so -- otherwise
    it describes the old behaviour.
    """
    assert "still refreshes the location cells" in marker_formula_help()
