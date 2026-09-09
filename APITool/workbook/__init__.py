"""
This settlement workbook's own conventions -- DEMOTED, deliberately.

Everything here encodes one particular spreadsheet: a Totals Tab, a marker
column, harvey-ball glyphs, a green colour ramp. The tool's supported path is
to publish generated data tabs and let the sheet's formulas decide what they
mean, which is what both computed columns now do.

This package is kept because it is how sheet writes get tested, and it is a
package rather than loose modules so that depending on it is visible in an
import line. Nothing on the generic path may import from here.
"""
