# Keeping the sheet current while you play

`edapitool serve` watches the journal and republishes as you play, so nothing has to be run by hand.

## Keeping the sheet current while you play

The generated tabs are only as fresh as the last time you published them. `edapitool serve` watches the game's journal and republishes them for you:

```bash
# Watch the journal and keep MarketData and ShipCargo current
edapitool serve --sheet-id YOUR_SHEET_ID

# Publish both tabs once and exit -- useful for checking it works
edapitool serve --sheet-id YOUR_SHEET_ID --once
```

It republishes when you dock, undock, jump, open a commodity screen, or change your hold. Any spreadsheet column that reads those tabs — a `VLOOKUP` into `MarketData` or `ShipCargo` — then updates on its own, because the formula recalculates when its source does. Nothing needs to write into your own columns.

**By default it only ever writes tabs this tool generates.** Ranges you maintain by hand are never touched unless you name one.

### Keeping a construction block current too

A construction block published into a region of your own tab goes stale exactly like a generated tab does. Name the region and `serve` keeps it current as well:

```bash
edapitool serve --sheet-id YOUR_SHEET_ID \
  --construction-region "Agri Lrg. (ex)!R1:AC60=Badeaux Nutrition Centre"
```

It refreshes when you dock, when you deliver, or when the game reports on the build. The site can be given by its current name, by a name it *used* to have (sites get renamed mid-build), or by its market id. Leave the `=Site Name` off and the block follows whichever site you are currently docked at — useful for a general readout, wrong for a tab devoted to one settlement.

Repeat the flag for more than one region. Each region is authorised separately, so naming one never widens what another may write. `--construction-region` is the `construction` plugin's word: it appears in `serve --help`, under that plugin's name, only when a target enables the plugin, and without one it is refused as an unknown option rather than being quietly ignored.

**Set it once instead of typing it every session.** A flag you have to retype is a flag that stops getting used, so the same binding can live in `~/edapitool/config.json`:

```json
{
  "targets": {
    "construction-workbook": {
      "kind": "gsheet",
      "plugin": "construction",
      "id": "YOUR_SHEET_ID",
      "config": {
        "construction_regions": [
          {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"}
        ]
      }
    }
  }
}
```

Then `edapitool serve` on its own keeps that region current, with nothing typed. Leave `"site"` out and the block follows whichever site you are docked at, exactly as the flag does. The bindings live under the target's `config` block because they are the `construction` plugin's to read, not the tool's. That target can name the same spreadsheet as your `totals` target; the two plugins write different places. A file from before `targets` existed, or one naming the `settlement` plugin from before v0.8.0, needs a small edit to move forward; both are in [configuration.md](configuration.md).

The config file takes an object per region while the command line takes one string, deliberately: a command line has to be a single value, so the site goes after `=`, but a file you edit by hand should not make you pack two delimiters into one place where a typo only shows up at runtime. If you prefer, the string form works in the file too.

**The flag wins outright over the file** — it does not merge with it. If you pass `--construction-region`, that is the complete set of regions for that run, and the config is ignored. Merged sources mean no single place tells you what will happen. An entry the file cannot parse refuses the run and names which entry it was, rather than being skipped quietly; a region silently dropped is one that stops publishing with nothing said.

At startup `serve` lists every target by name. If it is covering less of your sheet than you thought, that line is where you will see it — and if no construction region is declared, it says so rather than leaving you to assume.

A site the setting names but the journal cannot find leaves the region **untouched** rather than blanking it. A name matching nothing is much more likely to be a typo than a build that vanished.

That includes the cells naming where you are. Rather than having the tool paint them, point them at the generated tab, which already carries both:

```
=MarketData!$C$1     the station
=MarketData!$E$1     the system
```

The tool publishes the data; the sheet decides what to show. (`--write-location` makes it paint those cells instead, for a sheet that has not been set up this way. From 0.8.1 it paints them only when they are empty or still hold what the tool last wrote there, so a formula in them is left alone and reported; `--force` is not available on `serve`, so a sheet whose location cells hold formulas simply keeps them. It is deprecated: it may be removed in a release after 2027-01-01, so move those cells to the formulas above.)

Two settings control how eagerly it reacts:

| Flag | Default | What it does |
|---|---|---|
| `--interval` | 2s | how often the journal is checked |
| `--debounce` | 5s | how long the game must be quiet before publishing |

The debounce matters more than it looks. The game emits events in bursts — one real session produced 19 `Market` events — and publishing per event would be pointless writes against a quota. Each new event pushes the deadline out, so a burst results in one publish once it settles. Publishing is also skipped entirely when the data is unchanged, so sitting at a station does not rewrite the same values.

### Your fleet carrier

`serve` keeps `FreighterData` current too. That one target is different in kind from the rest: everything else reads a file the game already wrote to your own disk, while your carrier's hold has to be fetched from Frontier. So it needs a login, and it behaves accordingly.

It refreshes when you move cargo to or from the carrier, or trade at its market — and at least once every fifteen minutes regardless, because **another commander filling a buy order on your carrier changes its hold without anything reaching your journal**. It asks Frontier at most once a minute, so shifting a full hold costs one request rather than dozens, and it always publishes last, so a slow network call cannot hold up the three targets that read local files.

One thing to know, because it looks like a bug the first time you see it: **Frontier's carrier data lags the game.** A transfer that the journal recorded at 03:30 was still absent from Frontier's answer at 03:44, and had appeared by 04:01. So the refresh your transfer triggers will often read the *old* contents and report `FreighterData unchanged -- not written`. It keeps asking, once a minute, until the hold actually changes — you may see several of those lines before the corrected figure is written. That is the tool waiting for Frontier, not the tool failing.

With no Frontier credentials, this target is simply absent: `serve` runs normally, publishes everything else, and says at startup that `FreighterData` is not covered and how to fix it. Nothing else here needs a login — the journal and `Cargo.json` are on your own disk.

Stop it with Ctrl+C; it reports what it actually wrote — targets that had nothing new to publish are not counted.

---

[< Back to the README](../README.md)
