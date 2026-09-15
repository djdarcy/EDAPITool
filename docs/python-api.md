# Using it as a Python library

Everything the command line does is available as importable code.

## Python API

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

---

[< Back to the README](../README.md)
