# The observation store

Everything the tool reads from the game and from Frontier is kept, as read, in one SQLite file: `~/edapitool/store.db`, beside `config.json`. `ED_CONFIG_DIR` redirects it with the rest of the tool's files, and `ED_NO_STORE=1` turns the keeping off for a run.

## Why it exists

The game rewrites `Market.json` the next time you open a commodity screen, `Cargo.json` whenever your hold changes, and `Status.json` several times a second. Frontier's API answers are replaced by the next call. The journal is kept, but it is a pile of files on one machine that a reinstall or a cleared disk takes with it, and reading it back for one question means parsing every line of every file. The store keeps the bytes the game destroys, keeps the journal lines worth keeping with a record of where they came from, and indexes what the questions need. That is the whole of the promise, and everything below follows from it.

The store is **additive**. A command's output is the same whether the store is on or off, and a store that cannot be written (a locked file, a full disk, a version it does not understand) prints one line on stderr and the command carries on. Nothing you asked for waits on bookkeeping.

## What is kept, and from where

Every read lands in one table, `observations`, as a row: what kind of thing was read, what it was about, when it was observed (the payload's own timestamp when it has one), when it was recorded, a hash of the bytes, and the bytes. The same bytes read twice are one row, so polling costs nothing; a changed file is a new row and the old one stays.

| Command | What is kept, and as which kind |
|---|---|
| `market` | `Market.json` as `market_json`; Frontier's `/market` answer as `capi_market` when you use it |
| `ship` | `Cargo.json` as `cargo_json` |
| `profile` | Frontier's `/profile` answer as `capi_profile` |
| `carrier` | Frontier's `/fleetcarrier` answer as `capi_fleetcarrier` |
| `serve` | the same kinds, every time it reads them -- and the journal, line by line, as it watches it |
| `store ingest` | the journal: every event the store indexes, under the event's own name (`docked`, `fsdjump`, `colonisationconstructiondepot`, `marketbuy`, ...) |
| `construction`, `plugins`, `store`, `auth`, `version` | nothing; `construction` reads the journal and the store, and writes neither |

A `kind` is a row, not a table: when the tool learns to keep ship loadouts or squadrons, those arrive as new kinds through the same door, and a store made today reads them without a schema change.

A `sources` table records where each row came from: which machine, which file or URL, which commander by name and Frontier id, and -- for a journal file -- how far into it the store has read. A `writes` table is the ledger of what the tool has written into your sheets, which the construction block uses to know when it was last published. Both are **primary**, like `observations`: the tool cannot get them back once they are gone, and nothing regenerates them.

### The journal

```
edapitool store ingest                      # the game's journal directory
edapitool store ingest D:\old-journals --machine laptop
```

`ingest` reads every journal file from the position the store last recorded for it, keeps the events the store indexes, and advances the position, so the second run reads nothing. A file read to its end with nothing worth keeping still gets its source row. The events kept are where you are and where you dock, colonisation depots and your contributions to them, market buys and sells and cargo transfers, who was playing, the markers the game writes when it rewrites a side file, and your carrier's events. The other six hundred thousand lines a long-running journal holds are read past without being parsed; a full ingest of eight years of play takes a few seconds.

The same file under two `--machine` labels is two sources and one set of observations: the bytes are the same, so the row is. A journal copied from another computer is ingested with that computer's name, and `verify` knows not to look for it on this one.

`serve` reads the journal the same way while it runs: it starts where the store left off in the newest file, which is also how a line half-written when it started is delivered once it completes rather than skipped.

### What is derived

Beside the raw rows, the store holds tables **derived** from them, each a projection a question can read in one query. They are built as each raw row is kept and can be rebuilt from the raw rows at any time; losing them costs nothing but a `rebuild`.

| Table | One row per | From |
|---|---|---|
| `market_snapshot`, `market_item` | archived market, and each commodity in it, under the EDDN commodity schema's column names | `Market.json`, the CAPI market |
| `system`, `station` | star system by its address, station by its market id; the name is an attribute and every name seen is kept in order, so a renamed system is one row | `Location`, `FSDJump`, `CarrierJump`, `Docked` |
| `faction_presence`, `conflict` | observation and faction: influence, state, government, allegiance, happiness, your reputation, the active, pending and recovering states, whether it controls the system; conflicts beside them | the same events' `Factions` and `Conflicts` |
| `construction_reading` | depot event and resource: required, provided, payment, with the event's progress, complete and failed | `ColonisationConstructionDepot` |
| `construction_contribution` | resource you handed in | `ColonisationContribution` |
| `construction_delta` | site: how many readings, what was delivered over its life, how much of it you handed in, how much was others' | the two above |
| `trade` | buy, sell or transfer of one commodity, the symbol resolved through the commodity catalog or kept raw and flagged `unknown` | `MarketBuy`, `MarketSell`, `CargoTransfer` |

Every reading is kept, not just the latest. That is what makes the construction delta possible: a site's depot event says what it has now, and the readings over time say what arrived between two moments.

## What reads it

**`edapitool construction --delta [SINCE]`** prints, per commodity, what was delivered to a site between a moment and the store's latest reading, how much of that you handed in, and how much was others'. The moment is `SINCE` (a UTC stamp), else the last time the site's block was published, else the store's first reading; it says which. The construction block a region holds carries the same two numbers in its last two columns, `Delivered since last publish` and `By others`, counted from that region's previous publish; [construction](construction.md) has the block.

**A plugin's step** asks the store through one supplier, `history`: declare `needs = ("history",)` and `ctx.get("history")` answers kept reads by kind and subject, a station's market snapshots, a site's depot readings and its change between two moments. The store is opened on the first pull and never created there, and a machine with no store answers empty. [Writing a plugin](writing-a-plugin.md) has the contract.

## The verbs

```
edapitool store verify
edapitool store backup
edapitool store rebuild
edapitool store ingest [DIR] [--machine NAME]
edapitool store sources
edapitool store retire SOURCE
edapitool store export [FILE]
edapitool store import FILE
```

**`verify`** checks the file is sound: SQLite's own integrity check, every table the tool knows present and no table it does not know, no row pointing at a parent that is gone. Then it re-checks every journal source recorded for this machine against the world -- the file is where the row says, with the first line it was recorded by -- and marks each `present` or `absent`; it prints how many are present, absent, retired, or recorded by another machine. It exits non-zero on problems and writes nothing else. On a fresh install with nothing kept yet it says so and exits 0.

**`backup`** copies the store to `store.db.bak-<stamp>` beside it, using SQLite's online backup so it is safe while `serve` is running. It runs `verify` first and refuses when verify finds anything: the previous backup is a known-good copy, and a broken store must never replace it. It says how many observations are in the **backup set** -- the rows whose source is absent or retired, which this copy is the only other home of. The set shrinks when a source comes back and grows when one goes.

**`rebuild`** drops the derived tables and builds them again from the raw rows, in the order the raw rows were kept, so the result is the same as the ingest produced. It never touches a primary table: `sources`, `observations` and `writes` are byte-identical before and after. It is the answer to a projection that looks wrong, and to a future version that changes what a projection holds.

**`ingest`** is above. It is the one verb that creates the store: an ingest with nothing to write into would be an ingest of nothing.

**`sources`** lists every source: its id, kind, liveness, machine, how many observations it gave, and where it was. **`retire SOURCE`** (an id or a path) marks one gone for good -- the machine is dead, the directory was cleared. No row moves: its observations stay, join the backup set by the flag, and `verify` stops looking for it.

**`export`** writes the primary tables as one JSON document, lossless; a payload that is text (every kind the tool keeps today) is written as that text, so the file is readable. Derived tables do not travel; they are a rebuild away. Exporting the same store twice gives the same bytes. **`import`** brings a document in, creating the store when there is none: an empty store takes the rows as they are, ids included, so export, import and export again are byte-identical; a store with rows merges by source and by content, so importing overlapping backups of one machine does not double-count, and two commanders' rows stay two commanders' rows.

## Versions

The file carries a schema version. A file made by a newer tool is refused by name, with both versions and the path in the message, rather than read by guesswork; a file made by an older tool is brought forward one step at a time on open, and a step the tool does not have is also refused by name. Version 2 added the journal-derived tables; a version-1 store gains them, filled, the first time it is opened.

## What the store never holds

Tokens. `tokens.json` is the only place Frontier credentials live, and nothing in the store references it.
