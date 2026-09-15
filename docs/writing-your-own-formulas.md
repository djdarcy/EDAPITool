# Writing your own formulas

A reference for the tabs `edapitool` publishes: what lands in which column, and the handful of rules about what it will overwrite.

The tool does not compute anything meaningful for you on purpose. It publishes facts; your spreadsheet decides what they mean. This page is what you need to write that formula.

## The idiom

Every published tab is laid out the same way, and that is deliberate:

- **Column A is an empty margin.** Nothing is ever written there.
- **Column B is the key** — the commodity name, in the game's own spelling.
- Everything else is a value you can look up.

So one idiom works against all of them:

```
=VLOOKUP($B5, FreighterData!$B:$D, 2, FALSE)
```

`$B5` is the commodity name in *your* sheet, `$B:$D` is the range on the published tab, and `2` counts from B — so 2 is the second column of that range, `Quantity`.

**Why you can rely on those indices.** They are asserted by the test suite (`tests/test_cargo_contract.py`), specifically so that inserting a column can never silently shift what your formula addresses. A change that moved `Unit Price` would fail the build rather than quietly break your sheet.

---

## `FreighterData` — your fleet carrier

Written by `carrier --export google`, and kept current by `serve`.

| Row | Contents |
|---|---|
| 1 | blank |
| 2 | headers |
| 3 | `TOTAL` row — B is the label, C the total tonnage, E the total value |
| 4+ | one row per commodity |

| Column | Header | Contents |
|---|---|---|
| A | — | empty margin |
| **B** | `Commodity` | the key |
| C | `Quantity` | tonnes on the carrier |
| D | `Unit Price` | what you paid, per tonne |
| E | `Total Value` | quantity x unit price |

```
=VLOOKUP($B5, FreighterData!$B:$D, 2, FALSE)     tonnes on the carrier
=VLOOKUP($B5, FreighterData!$B:$D, 3, FALSE)     what a tonne cost you
```

## `ShipCargo` — your ship's hold

Written by `ship --export ship-tab`, and kept current by `serve`. No Frontier login needed.

| Row | Contents |
|---|---|
| 1 | `Vessel` / value / `Updated (UTC)` / timestamp |
| 2 | `Total Tonnage` / value / `Items` / count |
| 3 | headers |
| 4+ | one row per commodity |

| Column | Header | Contents |
|---|---|---|
| A | — | empty margin |
| **B** | `Commodity` | the key |
| C | `Quantity` | tonnes in the hold |
| D | `Unit Price` | blank unless known |
| E | `Symbol` | the game's internal name |
| F | `Stolen` | whether the cargo is stolen |

```
=IFNA(VLOOKUP($B5, ShipCargo!$B:$C, 2, FALSE), "")     tonnes in your hold
=ShipCargo!$C$2                                         total tonnage
```

## `MarketData` — the station you are docked at

Written by `market --export market-tab`, and kept current by `serve`.

| Row | Contents |
|---|---|
| 1 | `Station` / name / `System` / name / `MarketID` / id |
| 2 | `Updated (UTC)` / timestamp / `Source` / where it came from / `Items` / count |
| 3 | headers |
| 4+ | one row per commodity the station trades |

| Column | Header | Contents |
|---|---|---|
| A | — | empty margin |
| **B** | `Commodity` | the key |
| C | `Stock` | how many tonnes are available to buy |
| D | `Buy Price` | 0 means the station does not sell it |
| E | `Sell Price` | |
| F | `Demand` | |
| G | `Source` | |

```
=VLOOKUP($B5, MarketData!$B:$G, 2, FALSE)     stock here
=VLOOKUP($B5, MarketData!$B:$G, 3, FALSE)     price here
=MarketData!$C$1                               which station this is
```

**A station with no commodity market** — a construction site, say — still reports where you are. `C1` and `E1` carry the station and system from the game's journal; `Items` is 0 and no commodity rows follow. That is what says "no prices here", not a blank header.

## A construction block — what a build still needs

Written by `construction --publish-to TAB --region RANGE`, into a rectangle of a tab **you** own. Positions below are relative to the region's top-left corner.

| Row | Contents |
|---|---|
| 1 | headers: `Site`, `System`, `MarketID`, `Updated (UTC)`, `State`, `Progress`, `Required`, `Provided`, `Remaining` |
| 2 | the matching values |
| 3 | blank |
| 4 | table headers |
| **5+** | one row per commodity |

| Offset | Header | Contents |
|---|---|---|
| +0 | `Symbol` | the game's internal name |
| **+1** | `Commodity` | the key |
| +2 | `Required` | total the build needs |
| +3 | `Provided` | delivered so far |
| +4 | `Remaining` | still outstanding |
| +5 | `Payment` | credits per tonne |

**Row 5 is not arbitrary.** The settlement tabs in the example sheet start their own commodities on row 5, so a commodity in your column B lands on the same screen line as its counterpart in the block, and the two can be read across by eye.

`Updated (UTC)` is the **game's** timestamp for the event, not the time the tool ran.

---

## What the tool will overwrite

Four rules. The first two have bitten people.

**1. A tab the tool owns is cleared wholesale, every publish.** `FreighterData`, `ShipCargo` and `MarketData` are rewritten from the top left each time. **Do not put your own formulas or notes in them** — they will be gone on the next run. Put your formulas in your own tabs and look *into* these.

**2. A declared region is cleared to its bounds, every publish.** When you publish a construction block into `Agri!R1:AC60`, the whole of `R1:AC60` is emptied first and then written. That is what stops a shrinking build leaving stale rows behind — and it means **anything of yours inside that rectangle is destroyed**. Reserve more room than you need; growing inside the reserve costs nothing.

**3. Everything outside a declared region is never touched.** That is the point of declaring it. A region is the only thing the tool may write on a tab it does not own outright, and a write one row outside is refused rather than performed.

**4. Nothing is painted.** No colours, no formatting, no cell comments. If you want a stale reading greyed out or a shortfall in red, that is a conditional format rule in your sheet reading the data the tool published.

## Gotchas worth knowing

**`UNIQUE()` is case-sensitive; `VLOOKUP` is not.** This one is nastier than it sounds. The game writes `Liquid oxygen`; if you have typed `Liquid Oxygen` by hand elsewhere, a `UNIQUE()` roll-up treats them as two commodities and splits the row, while every `VLOOKUP` continues to work. Normalise with `PROPER()` or `LOWER()` before deduplicating.

**Commodity names come from the game, not from us.** That means `Fruit and Vegetables`, not `Fruit And Vegetables`, and it means casing is inconsistent across commodities because the game is inconsistent. Match on the value in column B rather than on something you typed.

**Inserting a column in your own tab shifts your formulas but not the published block.** A construction block goes to the region you *configured*. Insert a column to the left of it and your formulas follow the insert while the block does not — so update the configured region at the same time.

**A missing commodity is `#N/A`, not zero.** Wrap lookups in `IFNA(...)` or `IFERROR(...)` if a commodity might legitimately be absent, which it will be whenever a station does not trade it.

## When the data you want is not there

If you find yourself wishing the tool understood your spreadsheet, that is the signal to ask a different question: **what fact is my column derived from, and is that fact published?**

- If it is, write the formula.
- If it is not, that is a request for a new **data** output, not for the tool to compute your column. Open an issue naming the data, and what you would do with it.

The difference matters. "Publish the payment per tonne" is something the tool can do for everyone. "Add a left-to-buy column" is something only your sheet can mean.

---

[< Back to the README](../README.md)
