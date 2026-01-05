# ED API Tool

Elite Dangerous API Tool for fleet carrier inventory extraction and data exploration.

## Overview

ED API Tool (`edapitool`) is a Python library and CLI for accessing the Elite Dangerous Companion API (CAPI). It allows you to extract data from the game, with a focus on fleet carrier inventory management.

## Features

- OAuth2 authentication with Frontier's auth service
- Fleet carrier data extraction
- Commodity and microresource order tracking
- Carrier locker inventory
- Export to CSV or JSON
- (Planned) Google Sheets integration

## Installation

### From PyPI (when available)

```bash
pip install edapitool
```

### From source

```bash
git clone https://github.com/djdarcy/edapitool.git
cd edapitool
pip install -e .
```

### With Google Sheets support

```bash
pip install edapitool[gsheets]
```

## Setup

Before using ED API Tool, you need to register an application with Frontier:

1. Go to https://auth.frontierstore.net/client/signup
2. Register a new application
3. Note your `client_id`

Then configure the tool:

```bash
# Option 1: Environment variable
export ED_CLIENT_ID="your_client_id"

# Option 2: Config file
echo '{"client_id": "your_client_id"}' > ~/.ed_capi_config.json
```

## Usage

### Authentication

```bash
# First-time setup - opens browser for OAuth
edapitool auth
```

### Fleet Carrier Data

```bash
# View carrier summary
edapitool carrier

# Export to CSV files
edapitool carrier --export csv

# Export to JSON
edapitool carrier --export json

# Include raw CAPI response
edapitool carrier --export json --raw

# Use Legacy galaxy server
edapitool carrier --legacy
```

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

# Export to CSV
exporter = CSVExporter()
exporter.export_all(carrier)
```

## Data Available

### Fleet Carrier (`/fleetcarrier` endpoint)

- **Identity**: Callsign, custom name
- **Location**: Current system, docking access
- **Finances**: Bank balance, weekly upkeep, service costs
- **Capacity**: Ship packs, module packs, cargo usage
- **Orders**: Commodity buy/sell orders, microresource orders
- **Locker**: Stored assets, goods, and data
- **Crew**: Service crew and salaries
- **Travel**: Jump history, total distance

### Rate Limits

- General queries: 1 per minute recommended
- Fleet carrier queries: 15 minute cooldown
- Tokens expire and must be refreshed (~25 days max)

## Development

```bash
# Install dev dependencies
pip install -e .[dev]

# Run tests
pytest

# Format code
black .

# Type checking
mypy APITool
```

## Project Structure

```
APITool/
├── __init__.py    # Package init
├── config.py      # API constants
├── auth.py        # OAuth2 authentication
├── capi.py        # CAPI client
├── models.py      # Data models
├── export.py      # CSV/JSON export
├── cli.py         # Command-line interface
└── version.py     # Version info
```

## License

MIT License - see LICENSE file for details.

## Acknowledgements

- [EDMC](https://github.com/EDCD/EDMarketConnector) - Reference implementation
- [fd-api](https://github.com/Athanasius/fd-api) - CAPI documentation
- [INARA](https://inara.cz/) - Elite Dangerous companion site

## Contributing

Contributions welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

Like the project?

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/djdarcy)
