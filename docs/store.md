# The observation store

Everything the tool reads from the game and from Frontier is kept, as read, in one SQLite file: `~/edapitool/store.db`, beside `config.json`. `ED_CONFIG_DIR` redirects it with the rest of the tool's files, and `ED_NO_STORE=1` turns the keeping off for a run.

## Why it exists

The game rewrites `Market.json` the next time you open a commodity screen, `Cargo.json` whenever your hold changes, and `Status.json` several times a second. Frontier's API answers are replaced by the next call. Every one of those is the only copy there will ever be of what was true at that moment, and until v0.7.9 the tool read it, used it, and let it go. The store keeps the bytes. That is the whole of the promise, and everything below follows from it.

The store is **additive**. A command's output is the same whether the store is on or off, and a store that cannot be written (a locked file, a full disk, a version it does not understand) prints one line on stderr and the command carries on. Nothing you asked for waits on bookkeeping.

## What is kept

Every read lands in one table, `observations`, as a row: what kind of thing was read, what it was about, when it was observed (the payload's own timestamp when it has one), when it was recorded, a hash of the bytes, and the bytes. The same bytes read twice are one row, so polling costs nothing; a changed file is a new row and the old one stays.

| Command | What is archived, and as which kind |
|---|---|
| `market` | `Market.json` as `market_json`; Frontier's `/market` answer as `capi_market` when you use it |
| `ship` | `Cargo.json` as `cargo_json` |
| `profile` | Frontier's `/profile` answer as `capi_profile` |
| `carrier` | Frontier's `/fleetcarrier` answer as `capi_fleetcarrier` |
| `serve` | the same kinds, every time it reads them |
| `construction` | nothing yet. It reads journal *events* rather than a file, and events join the store when journal ingest lands (#22). Until then this is the one command whose data the store does not hold. |
| `plugins`, `store`, `auth`, `version` | nothing; they read no game data |

A `kind` is a row, not a table: when the tool learns to keep star systems, factions, ship loadouts or squadrons, those arrive as new kinds through the same door, and a store made today reads them without a schema change.

Beside the raw rows, two tables hold the market re-read as columns: `market_snapshot` (one row per archived market: the market id, station, system, station type, when, and how many items) and `market_item` (one row per commodity, under the column names of the EDDN commodity schema: `name`, `meanPrice`, `buyPrice`, `stock`, `stockBracket`, `sellPrice`, `demand`, `demandBracket`, `statusFlags`, with the game's own token kept in `symbol`). These two are **derived**: they are built from the raw rows and can be rebuilt from them at any time.

A `sources` table records where each row came from (which machine, which file or URL, which commander by name and Frontier id) and a `writes` table is reserved for the ledger of what the tool has written into your sheets, which a later version fills. Both are **primary**, like `observations`: the tool cannot get them back once they are gone, and nothing regenerates them.

## The three verbs

```
edapitool store verify
edapitool store backup
edapitool store rebuild
```

**`verify`** checks the file is sound: SQLite's own integrity check, every table the tool knows present and no table it does not know, no row pointing at a parent that is gone. It prints `Store OK` or the list of problems, exits non-zero on problems, and writes nothing. On a fresh install with nothing archived yet it says so and exits 0.

**`backup`** copies the store to `store.db.bak-<stamp>` beside it, using SQLite's online backup so it is safe while `serve` is running. It runs `verify` first and refuses when verify finds anything: the previous backup is a known-good copy, and a broken store must never replace it.

**`rebuild`** drops the derived tables and builds them again from the raw rows. It never touches a primary table: `sources`, `observations` and `writes` are byte-identical before and after. It is the answer to a projection that looks wrong, and to a future version that changes what a projection holds.

None of the three creates a store. A verb that checks a file must not make one to have something to check.

## Versions

The file carries a schema version. A file made by a newer tool is refused by name, with both versions and the path in the message, rather than read by guesswork; a file made by an older tool is brought forward one step at a time, and a step the tool does not have is also refused by name.

## What the store never holds

Tokens. `tokens.json` is the only place Frontier credentials live, and nothing in the store references it.
