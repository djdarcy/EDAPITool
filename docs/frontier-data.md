# Data from Frontier's API

Your fleet carrier, your commander profile, and what the Companion API makes available. These are the only commands that need a Frontier login -- everything else reads files the game already wrote to your own disk.

See [Frontier OAuth setup](frontier-oauth-setup.md) to get a client id.

## Fleet Carrier Data

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

## Google Sheets Export

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

See [docs/google-sheets-setup.md](google-sheets-setup.md) for Google API setup.

## Google Sheets Output Format

> **Column layout:** see [Writing your own formulas](writing-your-own-formulas.md) for what lands in which column of every published tab, and what the tool overwrites.


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

## Commander Profile

```bash
edapitool profile
```

## Data Available

## Fleet Carrier (`/fleetcarrier` endpoint)

- **Identity**: Callsign, custom name
- **Location**: Current system, docking access
- **Finances**: Bank balance, weekly upkeep, service costs
- **Capacity**: Ship packs, module packs, cargo usage
- **Cargo**: Commodity storage with quantities and values
- **Orders**: Commodity buy/sell orders, microresource orders
- **Locker**: Stored assets, goods, and data
- **Crew**: Service crew and salaries
- **Travel**: Jump history, total distance

## Rate Limits

- General queries: 1 per minute recommended
- Fleet carrier queries: 15 minute cooldown
- Tokens expire and must be refreshed (~25 days max)

---

[< Back to the README](../README.md)
