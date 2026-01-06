# ED API Tool

ED API Tool (`edapitool`) is a Python library and CLI for accessing the Elite Dangerous Companion API (CAPI). It allows you to extract data from the game, with a focus on fleet carrier inventory management and automated spreadsheet updates to make it easier to track and manage building planetary settlements. An [example Google Spreadsheets template](https://github.com/djdarcy/EDAPITool/tree/main?tab=readme-ov-file#google-sheets-export) is provided that can be copied and used to track your carrier cargo and settlement progress with VLOOKUP formulas.

## Features

- OAuth2 authentication with Frontier's auth service
- Fleet carrier data extraction
- Commodity and microresource order tracking
- Carrier locker inventory
- Export to CSV or JSON
- **Google Sheets integration** - direct API export for VLOOKUP-based tracking
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
| 2 | | Display Name | Quantity | Unit Price | Total Value |
| 3 | | TOTAL | =SUM(C4:C) | | =SUM(E4:E) |
| 4 | | Aluminium | 1751 | 2122 | =C4*D4 |
| 5 | | Meta-Alloys | 6 | 14659 | =C5*D5 |

- Column A empty for margin/formatting
- Row 3 has formula-based totals
- Data sorted alphabetically by commodity name
- Use VLOOKUP to reference by name: `=VLOOKUP("Steel", CargoData!$B:$D, 2, FALSE)`

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

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

See [LICENSE](LICENSE) for details.
