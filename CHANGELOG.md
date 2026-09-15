# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.2] - 2026-09-15

### Added
- `edapitool serve --construction-region "Tab!R1:AC60=Site Name"` keeps a construction block current while you play, the same way the generated tabs already are. The block refreshes when you dock, when you deliver, or when the game reports on the build - so a settlement tracker stops needing a command run by hand. Repeat the flag for more than one region.
- The site can be named, named by a name it *used* to have, or given as a market id. Leave the name off and the block follows whichever site you are docked at.
- **`serve` now keeps `FreighterData` current too.** It refreshes after you move cargo to or from your carrier, or trade at its market, and at least once every fifteen minutes regardless - because another commander filling a buy order changes your carrier's hold without anything reaching your journal. It never asks Frontier more than once a minute, so shifting a full hold costs one request rather than dozens.
- Construction regions can be set once in `~/.ed_capi_config.json` under `construction_regions` and then left alone, instead of being typed on every run. The command-line flag still works and takes precedence over the file when both are present.
- `serve` now says what it is keeping current, by name, at startup - and says plainly what it is *not* keeping current, and why. A background publisher covering part of a sheet used to look exactly like one covering all of it.
- `serve --once` publishes every declared target rather than only the two tabs.

### Changed
- The published construction block now labels itself. It was a bare row of nine values, and the first question anyone asked of it was what the numbers after `active` meant. It now carries a header row above the values, a blank row, and then the commodity table's own headers - with the commodities starting on the fifth row, so they line up beside a settlement tab's own commodity column and the two can be read across by eye.
- The publish loop holds a list of targets rather than two named ones. Adding a target is now an entry rather than an edit to the loop, which is the reason the daemon could quietly cover a subset before.
- A publish that fails no longer ends the session. The carrier refresh is the only one that leaves your machine, and a network blip should not stop the tabs that read local files.

### Fixed
- Docking somewhere with no commodity market - a construction site, say - used to replace the station name on `MarketData` with a sentence explaining why there were no prices, and blank the system beside it. Where you are and what a station sells are different facts, and only the second one was missing. The tab now keeps reporting your station, system and market id from the game's own journal, and the explanation moves to the `Source` field. A sheet pointing its "current system" cell at this tab no longer loses that value - which, in one workbook, was what every commodity link on the page was built from.
- `FreighterData` could keep showing cargo you had already moved into your ship. Frontier's own carrier data lags behind the game - it was still reporting 840 t of Biowaste on the carrier fourteen minutes after that same 840 t had been transferred off it - so the refresh that a transfer triggers routinely reads the *old* contents. That read was being taken as "nothing has changed", and the tab kept the wrong number until the next quarter-hourly refresh happened to catch up. It now keeps asking, once a minute, until the carrier's contents actually change.
- The fifteen-minute gap the tool keeps between fleet-carrier queries was never being applied while `serve` ran. A new connection was being made for each refresh, which started the timer again from zero every time. `serve` now holds one connection and sets that gap to the once-a-minute figure it actually intends, so the limit is a stated choice rather than one skipped by accident.
- The summary printed when `serve` stops counts refreshes that were actually written, rather than every time a target was checked.
- A construction block republished on *every* delivery event rather than only when something changed - five writes from six events, against a quota of sixty a minute. The check for "has anything changed" was reading the block's rendered layout, and labelling the block moved the timestamp into the rows it was reading. It now compares the build's actual numbers, so the block can be laid out differently without the check quietly breaking again.
- Restarting `serve` left every tab holding whatever it held before, until the game happened to emit an event - which could be a long wait, and a restart is exactly when a sheet is most likely to be wrong. It now publishes once at startup.
- A published target now clears its own deadline. Without that it stayed permanently due and republished on every poll - roughly thirty writes a minute against a sixty-per-minute quota, from a single docking. No test covered it; a mutation run found it.
- A region whose site cannot be found is left untouched rather than blanked. A name that matches nothing is far more likely to be a typo in the setting than a build that vanished, and wiping a tracker over a typo is not recoverable.
- A malformed `construction_regions` entry in the config file refuses the run and says which entry is wrong, rather than being skipped. A region silently dropped is one that stops being published with nothing said.

### Notes
- `FreighterData` still carries no timestamp of its own, so a tab written an hour ago looks exactly like one written a minute ago. Publishing it more often makes that matter more, not less.

## [0.6.1] - 2026-09-14

### Added
- A generated data block can now be published into a **region** of a spreadsheet tab, instead of only into a tab the tool owns outright. That means construction data can sit in the hidden columns of a settlement tracker, beside the columns you maintain yourself, and your own formulas decide what it means.
- `edapitool construction --publish-to TAB --region R1:AC60 --sheet-id ID` publishes a build as a data block: a row naming the site, its system, its market id and when the reading was taken, then a header row, then one row per commodity with required, provided, remaining and the payment per tonne.
- The region is declared, never guessed. Everything inside it is cleared on every publish, so a build that shrinks leaves nothing of its previous report behind; everything outside it is never touched. Reserve more room than you need - growing inside the reserve costs nothing.

### Changed
- The write allowlist now covers regions as well as whole tabs. Without an explicit entry naming it, no region of a tab the tool does not own is writable at all, so a sheet holding hand-entered work is opted in deliberately or not at all.
- The three generated tabs (`MarketData`, `ShipCargo`, `FreighterData`) are unchanged in every observable way. Publishing them still clears the tab and writes from the top left.

### Fixed
- A region reaching past the edge of a tab's grid is now refused, naming the column the tab actually ends at. Google Sheets silently shrinks such a range and reports success, which meant the area cleared could be smaller than the area declared - and stale cells left by that gap are indistinguishable from current data.
- A grid too large for the region it is published into is refused, with both shapes named, rather than being quietly cut off at the boundary.
- The contract snapshot used to prove a change did not alter what the spreadsheet computes now records which commit it was taken at, and refuses to compare against a snapshot from a different one. The snapshot in the tree had been four releases out of date, so a comparison could have reported either a false pass or a false failure with equal confidence.

### Notes
- The background service does not yet refresh these blocks; a construction region is republished when you run the command. Keeping it current while you play is the next piece of work.

## [0.6.0] - 2026-09-14

### Added
- `edapitool construction` reports what a colony build still needs. It reads the game's own journal, so it works with no spreadsheet, no Frontier login and no waiting on an API - the same class of source as the market and ship data. The game states how much of each commodity has been delivered, so nothing is inferred or calculated: what you see is what the construction panel says.
- The report is a shopping list, ordered by what you are shortest of, with what each commodity pays per tonne - a figure the tool did not previously have access to.
- `--list` shows every build the journal knows about, with its progress, system, and how long since the game last mentioned it. Completed and long-abandoned builds are hidden unless you ask for them with `--all`.
- A build can be selected by name, by the name it used to have, or by its market id. Sites are renamed during construction and the game prefixes their names in ways nobody types; all of that is handled, so the name you see in game is the name that works.
- `--export csv,json` writes the same data as files, and `--json` prints it, both without a spreadsheet.

### Notes
- A build that has lapsed is reported as not having been seen for so many days, never as expired or failed. Elite Dangerous does not mark a lapsed build failed - a site abandoned for ten months still reports as unfailed - so elapsed time is the only signal available, and the wording says no more than that.
- Nothing is written to a spreadsheet by this release. Publishing a build's requirements into a tracking sheet is the next piece of work.

## [0.5.2] - 2026-09-11

### Changed
- A coloured background in the marker column now means one thing only: there is something here worth acting on. Green says you still need this commodity and this station has some of it, shaded by how much of the outstanding amount it covers. Everything else has no fill, so the column can be read on its own without cross-checking the quantity beside it.
- The "sold here, out of stock right now" state is no longer shaded green. It had been near-white green, on the reasoning that an empty ring and a full ring are two ends of one coverage scale - true of the symbol, which keeps its place on that scale, but not of the colour, because green reads as "act" and there is nothing to act on at an empty shelf. It is now greyed, like a commodity you need none of: both are rows to skip, and the symbol still tells them apart.
- `--show-formula` describes the new rules automatically; it generates its suggested formatting from the same table the writer marks with, so a spreadsheet built from its instructions matches what the tool would have painted.

## [0.5.1] - 2026-09-11

### Fixed
- `edapitool market --export market-tab` raised `NameError` for anyone with a spreadsheet id configured. A helper moved into another module and the call site was updated without its import. No test reached the line - the only test covering that option supplies no sheet id, so it stops at the check that refuses one - and the linter in continuous integration is what caught it.

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
