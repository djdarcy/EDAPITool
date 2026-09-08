# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.2] - 2026-09-08

### Changed
- The marker rendering is now a separate, replaceable component. The code that decides which cells may be written, finds columns by their header text and parses quantities no longer knows anything about the filled-circle glyphs or the green colour ramp, so a spreadsheet for something else entirely - a ship build, a weapon upgrade path - can supply its own symbols without touching any of that machinery. Nothing about how the existing markers look or behave has changed

### Fixed
- The data-only paths no longer require the marker rendering to be installed. The module that drives every comparison loaded the glyph and colour definitions on import, so removing them broke the CSV, JSON and generated-tab exports too - the opposite of the separation those paths were meant to have

## [0.3.1] - 2026-09-08

### Added
- `edapitool market --export csv,json` - writes the station's market as plain data files. Needs no spreadsheet and no Google credentials; one self-contained row per commodity, so snapshots from different stations concatenate
- `edapitool market --export market-tab` - writes the station's market to a generated `MarketData` tab, the exact peer of the existing `CargoData` tab. Your spreadsheet reads it with its own `VLOOKUP` formulas, which means the symbols and colours become yours to change without touching any code
- `edapitool market --show-formula` - prints a ready-made spreadsheet formula that reproduces the marker column from a `MarketData` tab, with the conditional-formatting colours to pair with it
- `edapitool market --no-markers` - writes data only, leaving the marker column alone

### Changed
- The tool now emits the market as data rather than only as a rendering. Previously the only way the market reached a spreadsheet was as symbols and cell colours written directly into specific cells, which nobody else could consume and which could not be re-styled without a code change. Writing markers directly is still the default, so existing behaviour is unchanged until you opt in

## [0.3.0] - 2026-09-08

### Added
- `edapitool market` - compares the market at the station you are docked at against the outstanding commodities in your tracking spreadsheet, and marks what to buy
- Marker column showing how much of each requirement the station covers, as a filled-circle scale: solid for the full quantity, through three-quarter, half and quarter, to a hollow ring for "sells it but currently out of stock". Commodities the station stocks that you no longer need are shown greyed out, so a blank cell means "not sold here" and nothing else
- Cell notes on each marker with stock, quantity to buy, unit price, estimated cost, and when the market data was read
- Bundled commodity catalog mapping Frontier IDs, symbols and display names, so names that differ between the game and the reference data still match. Works offline; regenerate with `scripts/update-commodity-catalog.py`
- User-editable name aliases (`APITool/data/name_aliases.json`) for commodity spellings the catalog does not cover
- Reads the Elite Dangerous journal directly for current system, docked station and market data, falling back to the Frontier API
- Refuses to compare when the market data on disk belongs to a different station than the one you are docked at, rather than reporting the previous station's prices as current
- `--dry-run` to preview exactly which cells would change, and `--no-sheet` to inspect the market without touching the spreadsheet
- Support for a combined signed requirement column, where a negative value means "still to buy" and a positive value means surplus

### Changed
- Spreadsheet writes are now restricted to an explicit list of permitted cells. Previously a list of tabs to avoid was used, which did not cover the tabs holding hand-entered settlement data. Anything outside the permitted cells is refused before any request is sent
- Columns are located by their header text rather than by position, so moving a column no longer requires a code change
- Existing `carrier --export google` behaviour is unchanged, but the tab it rewrites must now be named explicitly rather than merely not being on an avoid-list

### Fixed
- Google Sheets credentials are now refreshed automatically. Previously an expired token triggered a full browser sign-in every hour
- Frontier credentials are now refreshed automatically. Previously an expired access token was treated as no authorization at all, prompting a browser sign-in several times a day
- Journal files are ordered by the date inside the filename. Elite Dangerous has used two filename formats, and comparing them as plain text could select a years-old log and report the wrong star system
- The pre-commit private-content check no longer rejects ordinary filenames. Its extension patterns used an unescaped `.`, so `*.log` also matched any name containing "log" -- including "catalog"

## [0.2.0] - 2026-01-04

### Added
- Google Sheets direct API export (`--export google --sheet-id ID`)
- Google Sheets CSV format (`--export gsheet`) - VLOOKUP-optimized layout
- Multiple export formats in single command (`--export csv,gsheet,google`)
- Cargo filtering flags (`--include stolen,mission`)
- Automated sync script (`scripts/sync-cargo-to-sheets.py`)
- Setup documentation for Google Sheets integration (`docs/google-sheets-setup.md`)
- GPL-3.0 license file
- This CHANGELOG

### Changed
- Switched from google-api-python-client to gspread for simpler Sheets API
- Client ID now auto-saves to config after successful authentication

### Dependencies
- Added: gspread>=5.0.0 (in `[gsheets]` extra)

## [0.1.0] - 2026-01-04

### Added
- Initial release
- Frontier CAPI OAuth2 authentication flow
- Fleet carrier data retrieval (cargo, services, crew)
- CSV export for carrier inventory data
- Command-line interface with `edapitool` command
- Support for multiple export formats (summary, commodities, microresources)
- Token persistence and automatic refresh
- Setup documentation for Frontier OAuth (`docs/frontier-oauth-setup.md`)

[0.3.2]: https://github.com/djdarcy/EDAPITool/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/djdarcy/EDAPITool/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/djdarcy/EDAPITool/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/djdarcy/EDAPITool/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/djdarcy/EDAPITool/releases/tag/v0.1.0
