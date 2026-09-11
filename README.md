# ED API Tool

ED API Tool (`edapitool`) is a Python library and CLI for accessing the Elite Dangerous Companion API (CAPI). It allows you to extract data from the game, with a focus on fleet carrier inventory management and automated spreadsheet updates to make it easier to track and manage building planetary settlements. An [example Google Spreadsheets template](https://github.com/djdarcy/EDAPITool/tree/main?tab=readme-ov-file#google-sheets-export) is provided that can be copied and used to track your carrier cargo and settlement progress with VLOOKUP formulas.

## Features

- OAuth2 authentication with Frontier's auth service
- Fleet carrier data extraction
- Commodity and microresource order tracking
- Carrier locker inventory
- Export to CSV or JSON
- **Google Sheets integration** - direct API export for VLOOKUP-based tracking
- **Current-station market comparison** - marks which commodities you still need are buyable at the station you are docked at
- **Current ship cargo** - reads your ship's hold from the game journal, with no Frontier login required
- **Live sheet updates** - `edapitool serve` watches the game journal and republishes the generated tabs as you play, so the spreadsheet stays current without running anything by hand
- **Scheduled sync** - cron/Task Scheduler support for automated updates
- Cargo filtering (exclude stolen/mission cargo)

## Installation

### From source

```bash
git clone https://github.com/djdarcy/EDAPITool.git
cd edapitool
pip install -e .
```

### With Google Sheets support

```bash
pip install .[gsheets]
```

## Setup

Before using ED API Tool, you need to register an application with Frontier:

1. Go to https://auth.frontierstore.net/client/signup
2. Register a new application (use `https://localhost/callback` as redirect URI)
3. Note your `client_id`

See [docs/frontier-oauth-setup.md](docs/frontier-oauth-setup.md) for detailed instructions.

### First-time authentication

```bash
# Authenticate and save client ID for future use
edapitool auth --client-id YOUR_CLIENT_ID
```

This saves your client ID to `~/.ed_capi_config.json` so you don't need to provide it again.

## Usage

### Fleet Carrier Data

```bash
# View carrier summary
edapitool carrier

# Export to CSV files
edapitool carrier --export csv

# Export to JSON
edapitool carrier --export json

# Use Legacy galaxy server
edapitool carrier --legacy
```

### Google Sheets Export

**Template spreadsheet**: [Carrier Cargo Tracker Template](https://docs.google.com/spreadsheets/d/1WACbf6u81fLIWsJVXsxUqYyIGZ0OCckN-Qb1FBgHAy0/edit?usp=sharing) - Make a copy to track your own settlements and carrier cargo.

```bash
# Export Google Sheets-formatted CSV (import manually)
edapitool carrier --export gsheet

# Export directly to Google Sheets (requires setup)
edapitool carrier --export google --sheet-id YOUR_SHEET_ID --client-id YOUR_CLIENT_ID

# Multiple formats at once
edapitool carrier --export csv,gsheet,google --sheet-id YOUR_SHEET_ID --client-id YOUR_CLIENT_ID

# Include stolen/mission cargo (excluded by default)
edapitool carrier --export gsheet --include stolen,mission
```

See [docs/google-sheets-setup.md](docs/google-sheets-setup.md) for Google API setup.

### Scheduled Sync

For automated updates, use the sync script:

```bash
# One-time sync
python scripts/sync-cargo-to-sheets.py

# Preview without executing
python scripts/sync-cargo-to-sheets.py --dry-run

# Also save CSV locally
python scripts/sync-cargo-to-sheets.py --also-csv
```

**Windows Task Scheduler**: Run every 15+ minutes (respects CAPI rate limit)
- Program: `python`
- Arguments: `C:\path\to\scripts\sync-cargo-to-sheets.py`

**Linux/Mac cron**:
```bash
*/15 * * * * /path/to/python /path/to/sync-cargo-to-sheets.py >> /path/to/sync.log 2>&1
```

### Google Sheets Output Format

The export creates a VLOOKUP-friendly layout:

| Row | A | B | C | D | E |
|-----|---|---|---|---|---|
| 1 | | | | | |
| 2 | | Commodity | Quantity | Unit Price | Total Value |
| 3 | | TOTAL | =SUM(C4:C) | | =SUM(E4:E) |
| 4 | | Aluminium | 1751 | 2122 | =C4*D4 |
| 5 | | Meta-Alloys | 6 | 14659 | =C5*D5 |

- Column A empty for margin/formatting
- Row 3 has formula-based totals
- Data sorted alphabetically by commodity name
- Use VLOOKUP to reference by name: `=VLOOKUP("Steel", FreighterData!$B:$D, 2, FALSE)`

### Current Station Market

`edapitool market` answers one question: **of the commodities I still need, which can I buy right here?**

It reads your current system and docked station from the Elite Dangerous journal, reads the station's commodity market, reads the outstanding quantities from your tracking spreadsheet, and marks the ones worth buying.

```bash
# Just look -- reads the market and the sheet, writes nothing
edapitool market --sheet-id YOUR_SHEET_ID

# See exactly which cells would change, without changing them
edapitool market --sheet-id YOUR_SHEET_ID --update-sheet --dry-run

# Write the markers
edapitool market --sheet-id YOUR_SHEET_ID --update-sheet

# Inspect location and market with no spreadsheet involved
edapitool market --no-sheet

# Also query the Frontier API for live stock (needs authentication)
edapitool market --sheet-id YOUR_SHEET_ID --use-capi
```

Set `ED_SHEET_ID`, or add `"sheet_id"` to `~/.ed_capi_config.json`, to omit `--sheet-id` every time.

**A spreadsheet is required for the comparison, not for the market.** Where you are, whether you are docked, what the station sells and how fresh that data is all come from the game's own files — only "what do I still need" lives in the sheet. So with no spreadsheet configured, `market` reports everything else and says plainly that the comparison was skipped:

```
No comparison: no spreadsheet configured
```

The skip is announced rather than silent, so nobody who *meant* to get a comparison mistakes an empty one for "nothing outstanding here". `--json` carries the same fact as `comparison_skipped`, which is `null` when a comparison actually ran. A spreadsheet that **is** configured and cannot be opened is still an error — a broken setup is not an absent one, and degrading it would hide a mistyped id or an expired credential behind a quietly missing comparison.

#### What gets written

Only three things, and nothing else on the sheet is touched:

| Cell | Contents |
|------|----------|
| `C2` | Current star system |
| `G2` | Current station, or `Not docked` |
| `L5:L…` | One marker per commodity row |

#### Reading the markers

The marker is a circle, filled by how much of what you still need this station can supply:

| Marker | Background | Meaning |
|--------|-----------|---------|
| ● | dark green | Buy the whole outstanding quantity here |
| ◕ | green | Covers most of what you need |
| ◑ | light green | Covers about half |
| ◔ | pale green | Covers a little |
| ○ | near-white | Sold here, but out of stock right now |
| ● ○ | none, grey text | Available here, but you need none of it |
| *(blank)* | none | Not sold at this station |

Hovering a marker shows stock, how many to buy, unit price, estimated cost, and when the market data was read.

#### Sheet layout

Columns are found by their **header text**, so you can move them without changing any code. Defaults match the template:

```bash
edapitool market --totals-tab "Totals Tab" \
                 --need-header "Left to buy" \
                 --marker-column L
```

If you combine "Left to buy" and "Extra next rnd" into one signed column, tell it which sign means "still to buy":

```bash
edapitool market --need-header "What's left" --need-sign negative
```

Other options: `--show-covered`/`--no-show-covered` (mark commodities you already have enough of), `--no-colour` (glyphs only), `--write-marker-header` (label the column; off by default so your own header is left alone), `--empty-marker small|dotted`, `--journal-dir`, and `--json`.

#### Using the market data without our formatting

The markers above are one presentation. The underlying data is available on its own, and needs no spreadsheet and no Google credentials:

```bash
# Files you can use anywhere
edapitool market --no-sheet --export csv
edapitool market --no-sheet --export json

# Machine-readable comparison on stdout
edapitool market --no-sheet --json
```

The CSV has one self-contained row per commodity — station, system and timestamp repeat on every row, so snapshots from different stations concatenate into a usable dataset:

```
station,system,market_id,timestamp,commodity,commodity_id,symbol,category,stock,buy_price,sell_price,demand,source
Ryman Enterprise,Lhou Mans,3226578176,2026-09-08T05:48:18+00:00,Biowaste,128049244,Biowaste,Waste,70192,54,32,1,journal
```

#### Letting your spreadsheet do the rendering

`--export market-tab` writes the station's market to a generated `MarketData` tab — the exact peer of `FreighterData`. Your sheet then looks it up with its own formulas, which means you own the symbols and the colours:

```bash
edapitool market --sheet-id YOUR_SHEET_ID --export market-tab --no-markers
```

`--no-markers` is the flag that makes this safe. Once your marker column holds formulas, the tool must not rewrite it — the marker write replaces the whole column wholesale (deliberately, so a stale marker cannot survive a row shift), and that would replace your formulas with plain values. The glyphs would look identical afterwards, which is what makes the mistake hard to spot.

What `--no-markers` does **not** do is stop the tool writing at all. It still refreshes the current-system and current-station cells, which is what the `MarketData` lookup formulas need in order to know where you are. Combine it with `--update-sheet` when you want both:

```bash
edapitool market --sheet-id YOUR_SHEET_ID --update-sheet --export market-tab --no-markers
```

| Row | A | B | C | D | E | F | G |
|-----|---|---|---|---|---|---|---|
| 1 | | Station | Ryman Enterprise | System | Lhou Mans | MarketID | 3226578176 |
| 2 | | Updated (UTC) | 2026-09-08T05:48:18+00:00 | Source | journal | Items | 366 |
| 3 | | Commodity | Stock | Buy Price | Sell Price | Demand | Source |
| 4 | | Biowaste | 70192 | 54 | 32 | 1 | journal |

Consume it exactly as the carrier's cargo is already consumed:

```
=VLOOKUP($B5, MarketData!$B:$G, 2, FALSE)   stock
=VLOOKUP($B5, MarketData!$B:$G, 3, FALSE)   buy price
```

Run `edapitool market --show-formula` for a ready-made formula that reproduces the marker column from that tab, plus the conditional-formatting colours to pair with it. The tool keeps writing markers directly by default, so nothing changes until you choose to switch.

#### Safety

- Writes are restricted to the cells listed above. Anything else is refused before a request is sent.
- Formulas, hand-entered values, and the settlement tabs are never written to.
- If the market data on disk belongs to a different station than the one you are docked at, the comparison is refused rather than showing the previous station's prices as current. Open the station's Commodity Market screen once so the game refreshes it.

### Current Ship Cargo

What your ship is carrying right now, read from the game's own `Cargo.json`. No Frontier login and no spreadsheet are involved.

```bash
# Just look
edapitool ship
```

```
Ship cargo as of 2026-09-08T06:46:29+00:00
  227 t across 4 commodities

  Biowaste                    62
  Building Fabricators        40
  Power Generators             9
  Structural Regulators      116
```

Every output below works with no Google credentials and no spreadsheet configured:

```bash
# Machine-readable, on stdout
edapitool ship --json

# Files you can use anywhere
edapitool ship --export csv
edapitool ship --export json
```

The CSV has one self-contained row per commodity, with the vessel and timestamp repeated on each row so snapshots taken across a trading run concatenate into a usable file:

```
vessel,timestamp,commodity,commodity_id,symbol,count,stolen
Ship,2026-09-08T06:46:29+00:00,Biowaste,128049244,biowaste,62,0
```

#### Letting your spreadsheet read it

`--export ship-tab` writes a generated `ShipCargo` tab, the peer of `FreighterData` and `MarketData`. This is the only ship output that needs a spreadsheet id.

```bash
edapitool ship --sheet-id YOUR_SHEET_ID --export ship-tab
edapitool ship --sheet-id YOUR_SHEET_ID --export ship-tab --dry-run   # preview, writes nothing
```

| Row | A | B | C | D | E |
|-----|---|---|---|---|---|
| 1 | | Vessel | Ship | Updated (UTC) | 2026-09-08T06:46:29+00:00 |
| 2 | | Total Tonnage | 227 | Items | 4 |
| 3 | | Commodity | Quantity | Symbol | Stolen |
| 4 | | Biowaste | 62 | biowaste | 0 |

Your sheet then looks it up with its own formula, so how it is displayed stays yours:

```
=IFNA(VLOOKUP($B5, ShipCargo!$B:$C, 2, FALSE), "")
```

`IFNA` rather than `IFERROR` on purpose: `IFNA` blanks a commodity you are not carrying, but still surfaces a genuine `#REF!` if the tab is renamed or removed. `IFERROR` would hide that too, leaving a silently empty column.

Use `--ship-tab NAME` if you want a different tab name.

#### Which vessel

The game writes `Cargo.json` for whichever vessel you are currently in, including the SRV. `edapitool ship` checks that field and refuses rather than reporting an SRV's hold as your ship's.

### Keeping the sheet current while you play

The generated tabs are only as fresh as the last time you published them. `edapitool serve` watches the game's journal and republishes them for you:

```bash
# Watch the journal and keep MarketData and ShipCargo current
edapitool serve --sheet-id YOUR_SHEET_ID

# Publish both tabs once and exit -- useful for checking it works
edapitool serve --sheet-id YOUR_SHEET_ID --once
```

It republishes when you dock, undock, jump, open a commodity screen, or change your hold. Any spreadsheet column that reads those tabs — a `VLOOKUP` into `MarketData` or `ShipCargo` — then updates on its own, because the formula recalculates when its source does. Nothing needs to write into your own columns.

**It only ever writes tabs this tool generates.** Ranges you maintain by hand are never touched.

That includes the cells naming where you are. Rather than having the tool paint them, point them at the generated tab, which already carries both:

```
=MarketData!$C$1     the station
=MarketData!$E$1     the system
```

The tool publishes the data; the sheet decides what to show. (`--write-location` makes it paint those cells instead, for a sheet that has not been set up this way — but it overwrites whatever is in them, formulas included.)

Two settings control how eagerly it reacts:

| Flag | Default | What it does |
|---|---|---|
| `--interval` | 2s | how often the journal is checked |
| `--debounce` | 5s | how long the game must be quiet before publishing |

The debounce matters more than it looks. The game emits events in bursts — one real session produced 19 `Market` events — and publishing per event would be pointless writes against a quota. Each new event pushes the deadline out, so a burst results in one publish once it settles. Publishing is also skipped entirely when the data is unchanged, so sitting at a station does not rewrite the same values.

No Frontier login is involved: `serve` reads the journal and `Cargo.json` from your own disk, so there is nothing to rate-limit on the game's side.

Stop it with Ctrl+C; it reports what it did.

### Commander Profile

```bash
edapitool profile
```

### Python API

```python
from APITool import FrontierAuth, CAPIClient
from APITool.models import FleetCarrier
from APITool.export import CSVExporter

# Authenticate
auth = FrontierAuth(client_id="your_client_id")
if not auth.is_authenticated:
    auth.authorize()

# Create client
client = CAPIClient(auth)

# Get fleet carrier data
raw_data = client.get_fleet_carrier()
carrier = FleetCarrier.from_capi(raw_data)

# Access data
print(f"Carrier: {carrier.identity.display_name}")
print(f"Location: {carrier.location.system}")
print(f"Fuel: {carrier.fuel} t")
print(f"Cargo items: {len(carrier.cargo)}")

# Export to CSV
exporter = CSVExporter()
exporter.export_all(carrier)

# Export Google Sheets format
exporter.export_cargo_gsheet(carrier)
```

## Data Available

### Fleet Carrier (`/fleetcarrier` endpoint)

- **Identity**: Callsign, custom name
- **Location**: Current system, docking access
- **Finances**: Bank balance, weekly upkeep, service costs
- **Capacity**: Ship packs, module packs, cargo usage
- **Cargo**: Commodity storage with quantities and values
- **Orders**: Commodity buy/sell orders, microresource orders
- **Locker**: Stored assets, goods, and data
- **Crew**: Service crew and salaries
- **Travel**: Jump history, total distance

### Rate Limits

- General queries: 1 per minute recommended
- Fleet carrier queries: 15 minute cooldown
- Tokens expire and must be refreshed (~25 days max)

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.ed_capi_config.json` | Frontier client ID |
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

See [APITool/README.md](APITool/README.md) for module documentation.

## Contributing

Contributions welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

Like the project?

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/djdarcy)

## Acknowledgements

- [EDMC](https://github.com/EDCD/EDMarketConnector) - Reference implementation
- [fd-api](https://github.com/Athanasius/fd-api) - CAPI documentation
- [INARA](https://inara.cz/) - Elite Dangerous companion site

## License

Copyright (C) 2025-2026 Dustin Darcy

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

See [LICENSE](LICENSE) for details.
