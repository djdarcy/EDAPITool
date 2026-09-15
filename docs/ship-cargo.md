# Your ship's cargo

What is in your hold right now, read from the game's own `Cargo.json`. No Frontier login, no network.

## Current Ship Cargo

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

### Letting your spreadsheet read it

> **Column layout:** see [Writing your own formulas](writing-your-own-formulas.md) for what lands in which column of every published tab, and what the tool overwrites.


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

### Which vessel

The game writes `Cargo.json` for whichever vessel you are currently in, including the SRV. `edapitool ship` checks that field and refuses rather than reporting an SRV's hold as your ship's.

---

[< Back to the README](../README.md)
