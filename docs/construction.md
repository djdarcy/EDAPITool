# Colony construction

What a build still needs, read from the game's journal -- and how to publish it into a corner of a spreadsheet you already maintain.

## Colony Construction

What a build still needs, read from the game's own journal. No Frontier login, no spreadsheet, no waiting on an API.

```bash
# What does the site I'm docked at still want?
edapitool construction

# Every build the journal knows about
edapitool construction --list

# A particular one, by the name you see in game
edapitool construction --site "Badeaux Nutrition Centre"
```

The report is a shopping list, ordered by what you are shortest of:

```
Site      : Badeaux Nutrition Centre (in progress)
System    : Col 285 Sector ZG-T c4-10
Progress  : 60.7%  (5,168 of 8,517 t)

  commodity                still need   delivered      pays
  ---------------------------------------------------------
  Biowaste                        840           0       667
  Crop Harvesters                 630           0     2,916
  Aluminium                       529       1,148     3,239
```

`pays` is the per-tonne payment the site offers — useful when deciding which run to do first.

**The game states what has been delivered**, so nothing here is calculated or guessed: the delivered column is the figure the in-game construction panel shows.

### Choosing a build

`--list` shows active builds; completed and long-abandoned ones are hidden until you ask:

```bash
edapitool construction --list --all
```

A build can be named however you know it — the name in game, the name it had before it was renamed, or its market id. The game prefixes these names (`Planetary Construction Site: …`) and a new colonisation ship names itself with an internal token; you never need to type either.

When two builds share a station name, `--system` separates them.

### On builds that lapsed

A build nobody has touched for a long time is reported as *not seen for N days* — never as expired or failed. Elite Dangerous does not mark a lapsed build as failed, so elapsed time is the only signal there is, and the tool says no more than it knows. `--stale-after DAYS` changes where that line falls.

### As data

```bash
edapitool construction --json                    # to stdout
edapitool construction --export csv,json         # to files
```

Both work with nothing configured.

### Into a corner of a sheet you already have

> **Column layout:** see [Writing your own formulas](writing-your-own-formulas.md) for what lands in which column of every published tab, and what the tool overwrites.


Most generated data goes to a tab of its own. A construction block usually should not: you already have a tracking sheet, with your own columns, and you want the game's numbers to appear beside them rather than on a tab you have to cross-reference.

```bash
edapitool construction --publish-to "Agri Lrg. (ex)" --region R1:AC60 --sheet-id YOUR_SHEET_ID
```

That writes the build into columns R onward — a row naming the site, its system, its market id and when the reading was taken, then headers, then one row per commodity with required, provided, remaining, and the payment per tonne. Your visible columns stay yours; point a `VLOOKUP` at the block and the sheet decides what the numbers mean.

**The region is declared, not guessed, and that matters.** Everything inside it is cleared on every publish, so when a build shrinks — commodities get completed — nothing of the previous report is left sitting there looking current. Everything outside it is never touched. Reserve more room than you need; growing inside the reserve costs nothing, and a block that outgrows its reserve is refused rather than spilling into the columns beside it.

Two things to know before pointing one at a sheet you care about:

- **Duplicate the tab first.** Right-click → Duplicate, aim at the copy, and look at the result before you trust it with real work.
- **A region cannot reach past the tab's last column.** A 29-column tab ends at `AC`, not `AD`. Declaring one column too far used to succeed while silently clearing less than it claimed; it is now refused with the tab's real size in the message.

---

[< Back to the README](../README.md)
