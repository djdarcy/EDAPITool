# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-09-10

### Added
- `edapitool serve` keeps the generated tabs current while you play. It watches the game's journal and republishes `MarketData` and `ShipCargo` when you dock, jump, open a commodity screen or change your hold, so the spreadsheet columns that read those tabs update without running anything by hand. It never writes to a range you maintain - only to tabs this tool generates. `--once` publishes both and exits; `--interval` and `--debounce` tune how eagerly it reacts.
- Publishing is skipped entirely when the data has not changed, so sitting at one station does not repeatedly rewrite the same values.
- `serve --write-location` will paint the current system and station into the roll-up tab's location cells, for a spreadsheet that expects the tool to supply them. It is off by default: those cells are better written as formulas reading the generated tab (`=MarketData!$C$1` for the station, `=MarketData!$E$1` for the system), which keeps the tool publishing data rather than deciding what a cell should say.

### Fixed
- `edapitool market` no longer demands a spreadsheet in order to run. Where you are, whether you are docked, what the station sells and how fresh that data is all come from the game's own files; only "what do I still need" requires the sheet. Asking for `--json`, `--export csv` or a plain report now works with no spreadsheet configured, and the command says plainly that the comparison was skipped rather than exiting with an error.
- With no comparison to show, the terminal output no longer prints "(nothing outstanding)" and a summary of zeroes. Those are the renderings of an empty comparison and read as "you need nothing at this station" - a false answer when nothing had been asked. It now states why no comparison happened.
- A spreadsheet that is configured but cannot be opened is still an error. A broken setup is not an absent one, and degrading it would hide a mistyped id or an expired credential behind a quietly missing comparison.

### Changed
- `--json` output carries `comparison_skipped`, naming why no comparison ran, or `null` when one did.

## [0.4.3] - 2026-09-09

Internal restructuring. Nothing a user of the command line can observe has changed; every command, option and output is identical to 0.4.2. The entry exists because the module layout moved, which matters to anyone reading or importing the code.

### Changed
- The spreadsheet code is now three packages rather than three modules, split by who each part is for. `APITool/sheets/` holds generic spreadsheet mechanics - A1 ranges, the write allowlist, header-driven layout - and knows nothing about any vendor or any particular workbook. `APITool/google/` holds the Google Sheets exporter. `APITool/workbook/` holds this settlement workbook's own conventions: its Totals Tab, its marker column, its glyphs and colours
- The name `sheets` now means "any spreadsheet". It previously held the generic name while being entangled with Google-specific and workbook-specific code, which left a future Excel or ODS writer nowhere honest to live. That was the point of the move
- `APITool/workbook/` is deliberately marked as demoted, and says so in its own docstring. The tool's supported path is to publish a generated data tab and let the spreadsheet's formulas decide what it means; the direct cell-writing code is kept because it is how sheet writes get tested, not because it is the way forward. What would retire each piece is recorded rather than left to be guessed at
- A test now enforces the direction of these dependencies, so the separation cannot quietly erode: the generic mechanics may never reach up into the workbook's opinions, and the extraction code may never reach into either

### Fixed
- The mutation-testing harness located its targets by hardcoded file path, so it broke outright when modules moved. It now finds each check by the code it is aimed at, and survives future moves
- The same harness could leave a stale bytecode cache behind after a run, which made the *next* run report failures against code that was correct on disk

## [0.4.2] - 2026-09-09

### Fixed
- `--no-markers` now still updates the current-system and current-station cells. Previously it suppressed the entire write, so the one option intended for a spreadsheet that renders its own markers was also the one option that stopped the tool telling that spreadsheet where you are. Those cells and the marker column travel in a single write, and the option now removes the marker column from that write rather than cancelling it
- `market --update-sheet --no-markers` no longer prints `DRY RUN - would write:` on a run you asked to be real. It was a consequence of the same defect: with the write cancelled there was nothing to report as written, so the output fell through to the dry-run wording and listed changes it was not going to make
- `--show-formula` now generates the marker formula from the same thresholds and symbols the tool itself marks with, instead of a separate hand-written copy. The two had no mechanism keeping them in step, so adjusting the coverage thresholds would have left the printed formula - and any spreadsheet built from it - grading against the old ones

### Changed
- Continuous integration now runs the test suite on every push and pull request, across Python 3.10, 3.11 and 3.12. It previously ran only a syntax check and a build, and the syntax check was configured so that it could not fail. The package is no longer built from a tree with failing tests
- The `--show-formula` output notes that `--no-markers` still refreshes the location cells, and the README now explains what the option does and why a formula-driven sheet needs it

### Added
- `pyyaml` to the `dev` extra, for the tests that check the CI workflow still gates

## [0.4.1] - 2026-09-08

### Changed
- The tab holding fleet carrier cargo is now called `FreighterData`. It was `CargoData`, which stopped saying which cargo it meant once a second cargo tab existed. Renaming the tab in your spreadsheet updates every formula that references it automatically; if you have an existing workbook, rename the tab and nothing else needs changing
- Both cargo tabs now use the same three columns in the same three places - commodity, quantity, and unit price - so one formula shape works against either of them. On the ship's tab the symbol and stolen columns moved one place right to make room for the price column, which stays empty because the game does not record what your ship's cargo cost
- The carrier tab's first column header reads `Commodity` rather than `Display Name`, matching the ship's tab. No formula reads the header text, so nothing needs updating

### Fixed
- A spreadsheet formula that looks a commodity up in a cargo tab now means the same thing on both tabs. Previously the third column held a unit price on one and an internal symbol on the other, so the same formula pointed at different things depending on which tab it was aimed at

## [0.4.0] - 2026-09-08

### Added
- `edapitool ship` - reports what your current ship is carrying, read from the game's own `Cargo.json`. Prints a summary, or emits the hold as JSON with `--json`, as files with `--export csv,json`, or as a generated `ShipCargo` tab with `--export ship-tab`
- The `ShipCargo` tab is a peer of the existing `CargoData` and `MarketData` tabs: your spreadsheet reads it with its own `VLOOKUP` formulas, so a column that tracks "how much of this am I already carrying" no longer has to be typed by hand
- Ship cargo is refused when the game's cargo file describes your SRV rather than your ship, rather than reporting one vessel's hold as the other's

### Changed
- Every `edapitool ship` output except the generated tab works with no spreadsheet and no Google credentials configured. Only `--export ship-tab` asks for a sheet id, because only that one writes to a spreadsheet

### Fixed
- Commodity names in ship cargo resolve by the game's internal symbol as well as its display name. The game omits the display name when it matches the internal one, so a display-name-only lookup silently dropped whichever commodities were affected

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

[0.4.3]: https://github.com/djdarcy/EDAPITool/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/djdarcy/EDAPITool/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/djdarcy/EDAPITool/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/djdarcy/EDAPITool/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/djdarcy/EDAPITool/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/djdarcy/EDAPITool/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/djdarcy/EDAPITool/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/djdarcy/EDAPITool/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/djdarcy/EDAPITool/releases/tag/v0.1.0
