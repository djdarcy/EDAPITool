# ED API Tool

ED API Tool (`edapitool`) is a Python library and CLI for accessing the Elite Dangerous Companion API (CAPI). It allows you to extract data from the game, with a focus on fleet carrier inventory management and automated spreadsheet updates to make it easier to track/manage building planetary settlements, to track the BGS simulation, upgrade your ship, and more. An [example Google Spreadsheets template](https://github.com/djdarcy/EDAPITool/blob/main/docs/frontier-data.md#google-sheets-export) is provided that can be copied and used to track your carrier cargo and settlement progress with VLOOKUP formulas.

## Features

- OAuth2 authentication with Frontier's auth service
- Fleet carrier data extraction
- Commodity and microresource order tracking
- Carrier locker inventory
- Export to CSV, JSON, spreadsheets
- **Google Sheets integration** - direct API export for VLOOKUP-based tracking
- **Current-station market comparison** - marks which commodities you still need are buyable at the station you are docked at
- **Current ship cargo** - reads your ship's hold from the game journal, with no Frontier login required
- **Colony construction tracking** - what a build still needs, read from the game journal: a shopping list ordered by what you are shortest of, with what each commodity pays
- **Publishing into a corner of your own sheet** - a generated block can go into a declared region of a tab you already maintain, beside your own columns, instead of onto a tab of its own. The region is cleared to its own bounds on every publish, so data that shrinks leaves nothing stale behind
- **Live sheet updates** - `edapitool serve` watches the game journal and republishes the generated tabs as you play, and any construction regions you name, so the spreadsheet stays current without running anything by hand. It lists what it is covering at startup, so a partial setup does not look like a complete one
- **Your fleet carrier, kept current too** - `serve` refreshes the carrier's hold when you move cargo to or from it, and every fifteen minutes regardless, because another commander filling a buy order changes it without anything reaching your journal
- Cargo filtering (exclude stolen/mission cargo)

## Installation

```bash
pip install edapitool
```

Anything that writes to a spreadsheet needs the `gsheets` extra:

```bash
pip install "edapitool[gsheets]"
```

The quotes are necessary on zsh and some shells, which otherwise would try to expand the brackets.

### From source

```bash
git clone https://github.com/djdarcy/EDAPITool.git
cd EDAPITool
pip install -e ".[gsheets]"
```

## Setup

Before using ED API Tool, you need to register an application with Frontier:

1. Go to https://auth.frontierstore.net/client/signup
2. Register a new application (use `https://localhost/callback` as redirect URI)
3. Note your `client_id`

See [docs/frontier-oauth-setup.md](https://github.com/djdarcy/EDAPITool/blob/main/docs/frontier-oauth-setup.md) for detailed instructions.

### First-time authentication

```bash
# Authenticate and save client ID for future use
edapitool auth --client-id YOUR_CLIENT_ID
```

This saves your client ID to `~/.ed_capi_config.json` so you don't need to provide it again.

## An example: tracking settlement construction

**[Example spreadsheet](https://docs.google.com/spreadsheets/d/1WACbf6u81fLIWsJVXsxUqYyIGZ0OCckN-Qb1FBgHAy0/edit?usp=sharing)** -- feel free to make a copy and point the tool at it.

To clarify what the example sheet is, because it is the quickest way to misunderstand what the `edapitool` does. **The sheet above is an example, not the goal of the project.** The `edapitool` tool knows nothing about the sheet. What the tool does is publish plain data tabs, which can be referenced by whoever authored the sheet, to *automate what the sheet calculates*.

### How it works, in one picture...

The tool *currently* writes three or four tabs and never touches anything else:

| Tab | What lands in it |
|---|---|
| `FreighterData` | every commodity on your fleet carrier, and what it cost |
| `ShipCargo` | what is in your ship's hold right now |
| `MarketData` | what the station you are docked at sells, and for how much |
| a region you name | what a construction site still needs — into a corner of a tab you already maintain |

Nothing in that list is interpreted. `FreighterData` is a list of commodities and numbers; it does not know you are building a settlement.

The meaning is added by the sheet, with ordinary formulas:

```
=VLOOKUP($B5, FreighterData!$B:$D, 2, FALSE)     how much is on the carrier
=VLOOKUP($B5, ShipCargo!$B:$C, 2, FALSE)         how much is in the ship
= required - delivered - on_carrier - in_ship    how much is still to buy
```

That is the whole trick of making the Elite Dangerous in-game data available to a spreadsheet, and it is why the tool stays small. A column like "left to buy" exists only in the spreadsheet. Change your mind about what it should mean and you edit a formula -- the tool does not need to know and will not break.

### What the example sheet does with that...

- **Several settlements at once**, one tab each, each bound to its own construction site. A totals tab rolls them up into a summary, so you can see what to buy for *all* of your builds in one place.
- **A marker column** that says, at a glance, whether the station you are standing in sells something you still need -- and how much of the shortfall it covers.
- **Round-trip planning** from your ship's capacity against what is still outstanding.
- **Cost tracking**, because the carrier data carries what you paid.

None of these extrapolations are in the tool. All of it is formulas you can read, change, or throw away.

### Why this is handy if you want something completely different...

Getting at this data normally means somebody builds an entire website around it. That is an absurd amount of machinery between a player and numbers already sitting in a file they own on their computer.

So the same tabs serve any purpose you like:

- a **trading sheet** that ignores construction entirely and watches prices at stations you visit
- **CSV or JSON** instead of a spreadsheet, `--export csv,json` needs no Google account at all
- **a Python script**, importing the same readers directly ([Python API](https://github.com/djdarcy/EDAPITool/blob/main/docs/python-api.md))
- **your own tooling**, since the journal data is on your disk and this just reads it

If you find yourself wanting the tool to understand your spreadsheet, that is usually an indicator to publish the data your column is derived from and let a formula do the rest.

**[Writing your own formulas](https://github.com/djdarcy/EDAPITool/blob/main/docs/writing-your-own-formulas.md)** is the way to do exactly that: what goes in which column of every published tab, what the tool clears and when, and the gotchas that are easier to read about than to discover.

## Documentation

The commands, each on its own page:

| Page | What it covers |
|---|---|
| **[Your fleet carrier and commander](https://github.com/djdarcy/EDAPITool/blob/main/docs/frontier-data.md)** | `carrier`, `profile`, exporting the hold to CSV / JSON / Google Sheets, what the API makes available, and its rate limits |
| **[The current station's market](https://github.com/djdarcy/EDAPITool/blob/main/docs/market.md)** | `market` -- compare what a station sells against what your sheet still needs, and the marker column |
| **[Your ship's cargo](https://github.com/djdarcy/EDAPITool/blob/main/docs/ship-cargo.md)** | `ship` -- what is in your hold right now, with no Frontier login |
| **[Colony construction](https://github.com/djdarcy/EDAPITool/blob/main/docs/construction.md)** | `construction` -- what a build still needs, and publishing it into a corner of a sheet you already maintain |
| **[Keeping the sheet current](https://github.com/djdarcy/EDAPITool/blob/main/docs/serve.md)** | `serve` -- watch the journal and republish as you play |
| **[Using it as a Python library](https://github.com/djdarcy/EDAPITool/blob/main/docs/python-api.md)** | the same data, importable |
| **[Writing your own formulas](https://github.com/djdarcy/EDAPITool/blob/main/docs/writing-your-own-formulas.md)** | what lands in which column of every published tab, what the tool overwrites, and the gotchas |

Setting up the two logins:

| Page | What it covers |
|---|---|
| **[Frontier OAuth setup](https://github.com/djdarcy/EDAPITool/blob/main/docs/frontier-oauth-setup.md)** | getting a client id, for anything that reads your carrier |
| **[Google Sheets setup](https://github.com/djdarcy/EDAPITool/blob/main/docs/google-sheets-setup.md)** | credentials, for anything that writes to a spreadsheet |

### The shortest useful thing

```bash
edapitool ship                 # what is in your hold, no login needed
edapitool construction         # what your build still needs
edapitool serve                # keep the spreadsheet current while you play
```

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.ed_capi_config.json` | Your settings: Frontier client ID, `sheet_id`, and any `construction_regions` you declare. Edited by hand, and the only copy of anything you type into it |
| `~/.ed_capi_tokens.json` | Frontier OAuth tokens |
| `~/.ed_gsheet_credentials.json` | Google API credentials |
| `~/.ed_gsheet_token.json` | Google OAuth tokens |

## Development

```bash
# Install in development mode
pip install -e .

# With Google Sheets support
pip install -e .[gsheets]

# Lint code
flake8 APITool/
```

See [APITool/README.md](https://github.com/djdarcy/EDAPITool/blob/main/APITool/README.md) for module documentation.

## Contributing

Contributions welcome! Please read [CONTRIBUTING.md](https://github.com/djdarcy/EDAPITool/blob/main/CONTRIBUTING.md) first.

Like the project?

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/djdarcy)

## Acknowledgements

- [EDMC](https://github.com/EDCD/EDMarketConnector) - Reference implementation
- [fd-api](https://github.com/Athanasius/fd-api) - CAPI documentation
- [INARA](https://inara.cz/) - Elite Dangerous companion site

## License

Copyright (C) 2025-2026 Dustin Darcy

This project is licensed under the GNU General Public License v3.0 -- see the [LICENSE](LICENSE) file for details.