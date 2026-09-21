# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.6] - 2026-09-21

### Fixed
- **`market --update-sheet` no longer overwrites what is already in the marker column** (#25). A cell holding anything — a formula, a note, a value you typed — is left alone; only empty cells are filled. The tool reports which cells it skipped, on the dry run and on the real write alike. `--force` overwrites them anyway, and there is no undo. This was measured live: twenty `LET` formulas in `Totals Tab!L5:L24` were destroyed by a single run, and the command reported success because it had done exactly what it intended.
  - The check reads the column as **formulas**, not as what they display, and that distinction is the whole of it. A marker formula shows nothing at a station that does not sell the commodity, so a cell that looks empty is very often a live formula; a displayed-value read would call it empty and overwrite it.
  - A cell that is skipped is not coloured either. Painting a cell the tool has just decided not to touch would be an unasked-for edit to a cell that is not the tool's.
  - If the column cannot be read at all, nothing in it is written and every cell is reported as skipped. Not knowing what is there is not a reason to write over it.
  - **The trade, stated rather than hidden:** on a workbook the tool *paints*, a glyph from a previous station now persists in a row the tool has nothing to say about, because the tool cannot tell its own leftover from something a person typed. Remembering what it wrote is #29.

### Changed
- **The list of tabs the tool may rewrite wholesale is now derived from the tabs it generates**, rather than being three names kept in step by hand with the functions that build them (#18). Each grid builder declares the tab it produces; the allow list asks. A hand-kept safety list has one silent failure mode — somebody adds a generator and does not add its tab — and this removes it. Behaviour is unchanged: the same three tabs, `FreighterData`, `MarketData` and `ShipCargo`.
- **The settlement plugin declares what it writes more narrowly.** It used to declare the marker column from the header row down, which permitted the TOTAL row in between — a row the tool has never written, and one whose every other cell is a `=SUM(...)`. It now declares the header cell and the data block separately, so a write to the TOTAL row, or a block spanning it, is refused.
- `GoogleSheetsExporter(writable_tabs=[])` now means *permit nothing*, which is what it says. It used to be read as *not specified* and fall back to permitting every generated tab.
- **`market`'s flags are grouped in `--help`** under five headings, and `serve`'s under three, each with a line saying what the group is for. Twenty-four flags printed as one flat run is not a reference — six of them concern the glyph column alone, so finding the three that answer "stop writing there" meant reading all of them. No flag was renamed; the `marker` → `glyph-marker` rename is still to come and lands as one break.

### Removed
- **`--no-colour` — use `--no-color`.** Both spellings have worked since 0.3.0, which left no answer to "which is the real one". One is enough.

## [0.7.5] - 2026-09-19

### Added
- **A second destination that is not a spreadsheet at all.** The `jsonl` plugin appends one JSON record per refresh to a file you name, and it satisfies the same plugin contract as the settlement workbook without a line of that contract changing. It is shipped but not enabled; point a target at it to use it. This is the plugin that proves the contract is not secretly shaped like a spreadsheet — if a file destination had needed the contract widened, the isolation would have been cosmetic.
- **`edapitool plugins`** lists what is installed, where each one came from, and whether it is loaded, available, broken, or shadowing a shipped plugin — each with a reason and what to do next. `edapitool plugins describe <name>` imports that one plugin and shows its kind, what it writes, what it supplies, what it subscribes to, and a starter block for its settings. The split is deliberate: listing imports nothing, because showing an unloaded plugin's capabilities would mean running code you declined.
- **A plugin can check its own settings.** A plugin that offers `check_config` is asked what is wrong with its block, and the tool repeats the answer naming the target. One target's malformed block no longer affects any other target. The tool does not inspect the block itself — it cannot, and does not try.
- **Everything this tool owns now lives in one directory, `~/edapitool/`** — the settings, the Frontier tokens, your own plugins, and the Google credentials, instead of five dotfiles scattered through a home directory. `ED_CONFIG_DIR` redirects the whole directory, which also means a script or a test can be isolated from your real files in one step.
- [docs/writing-a-plugin.md](docs/writing-a-plugin.md) — what a plugin must offer, in enough detail to write a second one from.

### Changed
- **The tool no longer chooses a destination for you, and this reverses what 0.7.4 said.** That release promised a settings file with a `sheet_id` and no `targets` would keep working as it always had, read as one target named `default`. It no longer is. With no `targets` entry, no plugin is enabled: the tool reads your journal, prints the station, and exports CSV and JSON, and publishes nowhere. **If you have a settings file with a bare `sheet_id`, add a `targets` entry naming the plugin you want** — `edapitool plugins` names what is installed and `edapitool plugins describe <name>` shows a starter block. Choosing which code runs against your spreadsheet should be something you said, not something the tool assumed because only one plugin happened to be lying around.
- `sheet_id` still names a spreadsheet, and the commands that publish a generated tab without any plugin still read it. What it no longer does is select a destination plugin.
- **`market` works with no destination configured.** Where you are, what the station sells, how fresh the reading is, and the CSV and JSON of it all come from your journal and never needed a plugin. Only `--update-sheet` and `--show-formula` refuse without one, and they name the flag that needed it. The missing comparison is reported as missing rather than rendered as an empty table, which would read as "you need nothing here".
- **A plugin is handed only the options you actually typed**, plus whatever its target carries that its own layout understands. Previously every plugin received the settlement workbook's vocabulary whether it spoke it or not, so a file destination was refused for not understanding `--need-sign`, which nobody had asked for. Defaults now come from the plugin rather than from the tool.
- Publishing is no longer gated on there being a spreadsheet handle. A plugin whose destination is a file gets its subscriptions run; a plugin that needs a worksheet and has not been given one says so itself. The settlement workbook behaves exactly as before.

### Removed
- The deprecated `sheet_id`-to-`default`-target alias introduced in 0.7.4, and with it the last path by which the tool enabled a plugin nobody had configured.

### Notes
- `--show-formula` is byte-identical, and the settlement workbook's plan is the same plan.
- `market --update-sheet` still clears the marker column (#25). Use `--dry-run` against a workbook whose marker column holds formulas.

## [0.7.4] - 2026-09-18

### Added
- **Your settings file now names the places you publish to.** A `targets` map, keyed by a name you choose, replaces the single `sheet_id`: each entry says what kind of place it is (`gsheet` today), which plugin knows its shape, where it is, and carries a `config` block that belongs to that plugin. The tool hands that block over without reading it, so a plugin's settings are the plugin's — the settlement plugin's construction-region bindings moved there, and the tool no longer parses a single key of theirs. [docs/configuration.md](docs/configuration.md) is the whole shape.
- `market --json` rows say which target a requirement came from: `origin` now reads `settlement-workbook!Totals Tab!B12` where it read `Totals Tab!B12`. Nothing was removed.

### Changed
- **Nothing changes for an existing install.** A settings file with a `sheet_id` and no `targets` — every file written before this release — keeps working exactly as it did; the tool reads it as one target named `default`, and anything else in the file goes into that target's `config` block for the plugin to read. `"sheet_id"` is deprecated rather than removed, and `ED_SHEET_ID` and `--sheet-id` are unaffected. There is nothing you need to do; the migration table in the configuration page is there for when you want a second destination.
- `serve` asks the loaded plugin where its construction blocks go, rather than reading them itself. A plugin that has no such bindings publishes no regions. Malformed bindings are still refused by name, in the same words, before anything is published.

### Notes
- Nothing that produces output changed: `--show-formula` is byte-identical, and a dry-run plan is the same plan.
- `market --update-sheet` still clears the marker column (#25). Use `--dry-run` against a workbook whose marker column holds formulas.

## [0.7.3] - 2026-09-18

### Added
- **A plugin declares what it supplies and what it subscribes to.** A supplier is something the tool pulls once per refresh and hands, unchanged, to every consumer that asks; a subscriber is something the tool pushes to once its inputs are ready. The settlement plugin supplies the requirements it reads from its tab and subscribes to publish the marker column beside them. Pulling once matters more than it sounds: the fleet-carrier endpoint refuses a second query for fifteen minutes, so two consumers each fetching for themselves would leave one of them with nothing.
- `market --json` rows carry an `origin` — where the requirement was read from, such as `Totals Tab!B12` — beside the `row` they always had. Nothing was removed from the JSON.

### Changed
- The requirements reader and the marker writer are now part of the shared spreadsheet toolkit, as `APITool.sheets.RequirementsReader` and `APITool.sheets.MarkerWriter`, because a second plugin would have had to rewrite them. `APITool.plugins.settlement.totals.TotalsTabReader` and `TotalsTabWriter` still exist and still work; they are now thin wrappers that supply the settlement workbook's layout.
- The command layer imports nothing from a plugin any more. `--empty-marker` reaches the plugin as the word you typed, and the plugin chooses the glyphs; `--show-formula` asks whichever plugin is loaded for its formula text, and a plugin that has none says `The 'name' plugin has no formula help.` instead of showing another plugin's.

### Notes
- **Nothing changes for an existing install.** Every command behaves as it did in 0.7.2; the `--show-formula` output is byte-identical.
- `market --update-sheet` still clears the marker column (#25). Use `--dry-run` against a workbook whose marker column holds formulas.

## [0.7.2] - 2026-09-18

### Added
- **A second plugin can be loaded.** Plugins are discovered from the tool's own `APITool/plugins/` directory and from a directory of yours — `ED_PLUGIN_DIR`, or `"plugin_dir"` in `~/.ed_capi_config.json`, or `~/.ed_capi_plugins/` by default — without importing any of them, and only the ones your configuration enables are imported at all. Enabling is a `"targets"` map keyed by a name you choose: `"targets": {"settlement-workbook": {"kind": "gsheet", "plugin": "settlement"}}`. A plugin of yours with the same name as a shipped one takes its place, and the tool says so.
- A plugin that fails to import is listed with the reason and stops nothing else. `edapitool --version` runs with a broken plugin enabled, and a command that needs a destination prints which plugins were found, which were enabled and which broke, instead of a traceback.
- Two enabled plugins that declare the same cells are refused before either writes, naming both plugins and both ranges. The default is to refuse; the loader also knows how to warn and load both in a declared order, and how to ignore, for the day a configuration asks for that.

### Changed
- The guard that bounds what the tool may write to a spreadsheet is now built by the tool from what a plugin *declares* it writes, never by the plugin itself. A plugin trusted to build its own guard could build a permissive one; this one cannot. The settlement workbook's declared ranges are exactly the ranges its old guard allowed, so nothing it writes has changed.
- `SheetLayout.guard()` is gone; `SheetLayout.writes()` returns the declaration it was built from. If you have a script calling `guard()`, build one with `WriteGuard.build(layout.writes())`.

### Notes
- **Nothing changes for an existing install.** With no `"targets"` in your configuration, the shipped settlement plugin is used exactly as before, and every command behaves as it did in 0.7.1.
- A `"targets"` entry's other keys are not read yet — per-plugin configuration is the next step — and `docs/` does not yet describe the map; the checklist that ships with this version does.
- `market --update-sheet` still clears the marker column (#25). Use `--dry-run` against a workbook whose marker column holds formulas.

## [0.7.1] - 2026-09-16

### Fixed
- The tool needed its bundled settlement-workbook code in order to start at all — even `edapitool --version` would not run without it. That was a mistake introduced by 0.7.0, the release whose whole point was that the tool should survive losing that code, and it went unnoticed because the test guarding it checked that the code could be *loaded* rather than that a command could be *run*. Nothing changes for anyone who has not removed or replaced that part, which today is everybody.

## [0.7.0] - 2026-09-16

### Changed
- **Two import paths moved, and this is the only thing you will notice.** `APITool.sheets.SheetLayout` and everything under `APITool.workbook` now live in `APITool.plugins.settlement`. If you have a script of your own importing either, change it to `from APITool.plugins.settlement.layout import SheetLayout`; if you only use the command line, nothing changes for you at all.
- Everything describing one particular spreadsheet — which tab, which headers, which row the commodities start on, which column the markers go in — now lives in a plugin directory of its own. The rest of the tool no longer knows any of it. The settlement workbook keeps exactly the values it always had; they simply moved to the one place that means them.
- A second spreadsheet, laid out differently, becomes a second directory beside the first rather than a set of edits scattered through the tool.

### Notes
- This is one half of that work. The tool can now survive losing a plugin, and a plugin can hold whatever conventions its sheet needs — but there is still no way to **select** one: which plugin is used is decided by an import in the source, so adding a second directory today would leave it unused. That half is open.
- Every command behaves identically to 0.6.7. This was verified against a real spreadsheet in both directions, which the automated tests cannot do.

## [0.6.7] - 2026-09-16

### Removed
- `SheetLayout` no longer carries a `name_header` setting. It defaulted to `ALL SETTLEMENTS` — a heading from one particular spreadsheet, shipped in the tool's own source — and nothing had ever read it. Passing it did nothing, so removing it changes nothing except that the tool no longer ships someone else's column heading as a default.

## [0.6.6] - 2026-09-16

### Changed
- Nothing you can see, which is the whole point. The tool no longer needs the settlement-workbook code in order to start. Until now that code was loaded the moment the tool ran, whether or not you were going anywhere near a workbook — so removing or replacing it stopped `serve` and `market` from starting at all, even though neither has anything to do with any one spreadsheet. It is now loaded only when something actually reads or writes that workbook's tabs. If you want to point this tool at a sheet laid out differently from ours, that is the part that had to move first.

### Notes
- This is one half of that work, not all of it. The tool can now survive losing the settlement-workbook code; it still cannot be *told* to use a different one without editing source. That half is still open.

## [0.6.5] - 2026-09-16

### Fixed
- `serve` printed a redundant line every time it checked your fleet carrier. `Exported 49 cargo items to 'FreighterData' tab` appeared directly above `FreighterData unchanged -- stamp refreshed`, and the two said opposite things. Both were accurate — the tab really was rewritten, and its contents really had not changed — but the first was being printed from deep inside the code that does the writing, where it had no business deciding what you see. The commands now report their own work, and the carrier refresh is one line again.

## [0.6.4] - 2026-09-16

### Added
- `FreighterData` now says when it was last looked at. The tab carries two stamps above its header: **Last checked**, the moment the tool last asked Frontier, and **Last changed**, the moment the answer last differed. It was the only generated tab with no timestamp at all, so a figure written half an hour ago looked exactly like one written a second ago - which is how it once sat several thousand tonnes out of date with nothing on the sheet to show it. Nothing moves: the header is still on row 2 and your commodities still start on row 4, so every formula pointing at this tab keeps working untouched.
- Both stamps are **your tool's clock, not Frontier's**, and they are named that way on purpose. The other two tabs say `Updated (UTC)` because they read files the game wrote, so that data can state its own age. Frontier's carrier response carries no such timestamp anywhere - and the endpoint runs 14 to 31 minutes behind the game - so the moment we asked is emphatically not the moment the data describes. Calling it `Updated (UTC)` would claim something nothing supports.

### Fixed
- `serve` no longer floods the console with cooldown errors at startup. Starting it printed thirty lines of `carrier publish failed: Fleet carrier query cooldown` - one every two seconds, counting down for a solid minute - because the initial catch-up published your carrier and then nothing recorded that it had. The loop concluded no carrier refresh had ever happened and asked again on every single poll. More generally: **any** failed refresh used to retry at the poll interval instead of waiting its own limit, so a passing network problem produced the same flood. A failed attempt now counts as an attempt.
- A fleet carrier jump no longer makes the tool think you have left the carrier. Arriving somewhere aboard your own carrier was being read as an undocking, so for the whole stretch after every jump the tool reported you as flying in open space - which is exactly the stretch in which people move cargo around.
- `edapitool carrier --export google` writes the new timestamps too. They were wired into `serve` and not into the command you run by hand, so that command wrote the cells empty.

### Changed
- The carrier tab is now rewritten on every successful check rather than only when its contents differ. That is what lets **Last checked** mean "when the tool last asked" instead of "when the data last moved" - which are very different facts when the source is half an hour behind. The extra writes are capped at one a minute and were measured well inside Google's limits.
- Internally, the publish loop now distinguishes "we wrote something" from "the source actually changed". They used to be one flag, and keeping them separate is what stops the new timestamp from undoing the previous release's fix for a stale carrier - the first stamp refresh would otherwise have been read as "Frontier has caught up" and stopped it waiting.

### Notes
- If you keep `serve` running while reading the sheet, you will now see `FreighterData unchanged -- stamp refreshed` where it previously said nothing was written. That line means the tool asked, Frontier's answer had not moved yet, and the "last checked" time was brought up to date. It is the tool waiting, not failing.

## [0.6.3] - 2026-09-15

### Added
- Installable from PyPI: `pip install edapitool`, or `pip install "edapitool[gsheets]"` for anything that writes to a spreadsheet. Cloning the repository still works and is still the right thing if you intend to change the code.

### Fixed
- `carrier --export google` now finds your spreadsheet id the same way every other command does. It was the only one that looked at the `--sheet-id` flag and nothing else, so if you had `sheet_id` saved in your config file - or `ED_SHEET_ID` set - it told you the flag was required anyway. Nobody chose that; it is what happens when several parts of a program each decide for themselves where a setting comes from, which is also why the rest of this release exists. The message when it genuinely cannot find one now names all three places you could put it.
- Saving your Frontier client id can no longer damage the rest of your config file. It rewrote the whole file in place, which was harmless while the file held one setting - but since the previous release it also holds construction region bindings you typed by hand and that exist nowhere else. An interrupted or failed write could have taken them. The new contents are now written to a temporary file first and moved into place, so an interrupted save leaves the original exactly as it was.

### Changed
- Settings handling moved into a module of its own. The file's location, how it is read and written, and the rules deciding whether a value comes from a flag, the environment or the file, all now live in one place instead of four. None of it changes what the tool does; it changes how easily the next setting can be added without the rules drifting apart again.
- The module holding fixed protocol values - server addresses, timeouts, the fleet-carrier cooldown - is now named `constants` rather than `config`, because it never held anything a user configures. If you import this package as a library rather than using the command line, that import path changed.

### Notes
- Neither fix is visible unless you were affected by it. The first one you would have seen as a command refusing to run; the second you would most likely never have seen at all, which is the point.

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
