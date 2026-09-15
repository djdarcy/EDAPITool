# The current station's market

Compare what the station in front of you sells against what your spreadsheet still needs.

## Current Station Market

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

### What gets written

Only three things, and nothing else on the sheet is touched:

| Cell | Contents |
|------|----------|
| `C2` | Current star system |
| `G2` | Current station, or `Not docked` |
| `L5:L…` | One marker per commodity row |

### Reading the markers

The marker is a circle, filled by how much of what you still need this station can supply. The two channels answer different questions: **the symbol says what is here, the background says whether it is worth your time.**

A coloured background means there is something to act on — you still need this commodity and the station has some of it. Nothing else is ever coloured, so the column can be read on its own without checking the quantity beside it.

| Marker | Background | Meaning |
|--------|-----------|---------|
| ● | dark green | Buy the whole outstanding quantity here |
| ◕ | green | Covers most of what you need |
| ◑ | light green | Covers about half |
| ◔ | pale green | Covers a little |
| ○ | none, grey text | Sold here, but out of stock right now |
| ● ○ | none, grey text | Available here, but you need none of it |
| *(blank)* | none | Not sold at this station |

The last three are all "nothing to do here", which is why they share a treatment; the symbol still tells them apart when you want the detail.

Hovering a marker shows stock, how many to buy, unit price, estimated cost, and when the market data was read.

### Sheet layout

> **Column layout:** see [Writing your own formulas](writing-your-own-formulas.md) for what lands in which column of every published tab, and what the tool overwrites.


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

### Using the market data without our formatting

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

### Letting your spreadsheet do the rendering

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

### Safety

- Writes are restricted to the cells listed above. Anything else is refused before a request is sent.
- Formulas, hand-entered values, and the settlement tabs are never written to.
- If the market data on disk belongs to a different station than the one you are docked at, the comparison is refused rather than showing the previous station's prices as current. Open the station's Commodity Market screen once so the game refreshes it.

---

[< Back to the README](../README.md)
