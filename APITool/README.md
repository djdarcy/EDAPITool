# APITool Module Reference

Core library modules for Elite Dangerous Companion API access.

| Module | Description |
|--------|-------------|
| `__init__.py` | Package exports (`FrontierAuth`, `CAPIClient`) |
| `auth.py` | OAuth2 + PKCE authentication with Frontier |
| `capi.py` | Companion API client for profile, market, fleetcarrier endpoints |
| `cli.py` | Command-line interface (`edapitool` entry point) |
| `config.py` | API URLs, endpoints, and constants |
| `export.py` | CSV/JSON export functionality |
| `gsheet.py` | Google Sheets direct API export |
| `models.py` | Data models for fleet carrier, cargo, orders, etc. |
| `version.py` | Version info (auto-updated by git hooks) |

## Quick Start

```python
from APITool import FrontierAuth, CAPIClient
from APITool.models import FleetCarrier

# Authenticate
auth = FrontierAuth(client_id="your_client_id")
if not auth.is_authenticated:
    auth.authorize()

# Get fleet carrier data
client = CAPIClient(auth)
carrier = FleetCarrier.from_capi(client.get_fleet_carrier())

print(f"Carrier: {carrier.identity.display_name}")
print(f"Cargo items: {len(carrier.cargo)}")
```

See the main [README](../README.md) for full documentation.
