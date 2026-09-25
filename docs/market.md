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

# Write the glyph markers
edapitool market --sheet-id YOUR_SHEET_ID --update-sheet

# Inspect location and market with no spreadsheet involved
edapitool market --no-sheet

# Also query the Frontier API for live stock (needs authentication)
edapitool market --sheet-id YOUR_SHEET_ID --use-capi
```

Set `ED_SHEET_ID`, or add `"sheet_id"` to `~/edapitool/config.json`, to omit `--sheet-id` every time.

**A spreadsheet is required for the comparison, not for the market.** Where you are, whether you are docked, what the station sells and how fresh that data is all come from the game's own files — only "what do I still need" lives in the sheet. So with no spreadsheet configured, `market` reports everything else and says plainly that the comparison was skipped:

```
No comparison: no spreadsheet configured
```

The skip is announced rather than silent, so nobody who *meant* to get a comparison mistakes an empty one for "nothing outstanding here". `--json` carries the same fact as `comparison_skipped`, which is `null` when a comparison actually ran. A spreadsheet that **is** configured and cannot be opened is still an error — a broken setup is not an absent one, and degrading it would hide a mistyped id or an expired credential behind a quietly missing comparison.

### What gets written

The glyph-marker column, and the two location cells only if you ask. Nothing else on the sheet is touched:

| Cell | Contents | Written |
|------|----------|---------|
| `L5:L…` | One glyph marker per commodity row | with `--update-sheet`: an empty cell, or one still holding what the tool last wrote there |
| `C2` | Current star system | only with `--write-location`, by the same rule |
| `G2` | Current station, or `Not docked` | only with `--write-location`, by the same rule |

The location cells are off by default because they work better as formulas reading the generated `MarketData` tab (`=MarketData!$E$1` for the system, `=MarketData!$C$1` for the station), which follow wherever you dock without the tool writing anything. Before 0.7.7, every `--update-sheet` wrote them and replaced those formulas with fixed text. Pass `--write-location` only if your sheet still expects the tool to fill them. It is deprecated and may be removed in a release after 2027-01-01.

### Reading the glyph markers

The glyph marker is a circle, filled by how much of what you still need this station can supply. The two channels answer different questions: **the symbol says what is here, the background says whether it is worth your time.**

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


Columns are found by their **header text**, so you can move them without changing any code. These options, and every option below that concerns the roll-up tab or its glyph markers, belong to the `totals` plugin: `market --help` lists them under "the totals plugin" when a target enables it, and without one they do not exist. The plugin's own default tab is `Totals`; the template workbook's tab is `Totals Tab`, which the stock configuration names in the target's `"totals_tab"`. Spelled out on the command line:

```bash
edapitool market --totals-tab "Totals Tab" \
                 --need-header "Left to buy" \
                 --glyph-marker-column L
```

If you combine "Left to buy" and "Extra next rnd" into one signed column, tell it which sign means "still to buy":

```bash
edapitool market --need-header "What's left" --need-sign negative
```

Other options: `--no-show-covered` (leave blank the commodities you already have enough of, which are otherwise shown greyed), `--no-color` (glyphs only), `--write-glyph-marker-header` (label the column; off by default so your own header is left alone), `--empty-glyph-marker small|dotted`, `--journal-dir`, and `--json`.

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
edapitool market --sheet-id YOUR_SHEET_ID --export market-tab --no-glyph-markers
```

`--no-glyph-markers` says it outright: build a plan with no glyph-marker column in it at all. You no longer need it to stay safe, though it is still the clearest way to say what you mean.

**The tool only overwrites what it can prove it wrote.** It remembers, per target and per cell, what each cell held right after its last write (the writes ledger, in `store.db`). On the next run every cell it would write is one of three things:

| The cell holds | The tool |
|---|---|
| nothing | fills it |
| exactly what the tool last wrote there | refreshes it: it is the tool's own glyph from the last station |
| anything else: a formula, a note, something you typed, a glyph of ours you edited | leaves it alone, and says so |

The dry run and the real write both list the three, plus anything `--force` wrote. `--force` writes every cell regardless, and there is no undo — but what a forced write leaves is recorded, so the tool treats those cells as its own from then on.

The check reads cells as *formulas* rather than as what they display. A marker formula shows nothing at a station that does not sell the commodity, so a cell that looks empty is very often a live formula; reading the displayed value would call it empty and overwrite it.

**After upgrading to 0.8.1**, the ledger starts empty, so glyphs painted by an earlier version are "something the tool did not write" and are left alone — the same as 0.7.6 did. One run with `--force` adopts them; after that they refresh on their own. With the store switched off (`ED_NO_STORE=1`) nothing is remembered and every occupied cell is left alone, never overwritten.

Knowing what it wrote costs one extra read of the sheet on each real write: `market --update-sheet` makes five calls where it made four (the requirements read, the cells read, the write, the formatting, and the read-back that records what landed). A dry run makes the same two reads as before and writes nothing.

The location cells are yours in the same way: point them at `MarketData`'s own header (`=MarketData!$E$1`, `=MarketData!$C$1`) and the lookup formulas always know where you are, with nothing written into the roll-up tab at all. For a sheet that still wants the tool to fill them, alongside the export:

```bash
edapitool market --sheet-id YOUR_SHEET_ID --update-sheet --export market-tab --no-glyph-markers --write-location
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
