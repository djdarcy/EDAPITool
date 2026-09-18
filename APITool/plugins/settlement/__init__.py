"""
This settlement workbook's own conventions -- DEMOTED, deliberately.

Everything here encodes one particular spreadsheet: a Totals Tab, a marker
column, harvey-ball glyphs, a green colour ramp. The tool's supported path is
to publish generated data tabs and let the sheet's formulas decide what they
mean, which is what both computed columns now do.

This package is kept because it is how sheet writes get tested, and it is a
package rather than loose modules so that depending on it is visible in an
import line. Nothing on the generic path may import from here.

What the loader asks of a plugin -- the surface below is the whole of it:

    KIND                  what kind of target this is; selects the enforcer
    layout(**overrides)   this sheet's shape, with any command-line overrides
    writes()              what it declares it writes, as shipped; the loader
                          checks these against every other plugin's at load
    layout.writes()       the same declaration for a layout with overrides;
                          core builds the guard from this one
"""

from .layout import SheetLayout

# A Google sheet. Configuration may name a kind per target and overrides this;
# with no targets configured, this is what the shipped plugin is.
KIND = "gsheet"


def layout(**overrides) -> SheetLayout:
    """This workbook's layout. Overrides are the command line's, when given."""
    return SheetLayout(**{k: v for k, v in overrides.items() if v is not None})


def writes() -> dict[str, list[str]]:
    """What this plugin declares it writes, as shipped. One definition: the layout's."""
    return SheetLayout().writes()
