# Configuration

Everything the tool remembers between runs lives in one directory, `~/edapitool/`, and the settings themselves are one hand-edited file inside it, `~/edapitool/config.json`. This page is its whole shape.

## Where the files are

| File | What it holds |
|---|---|
| `~/edapitool/config.json` | your settings — the rest of this page |
| `~/edapitool/tokens.json` | Frontier OAuth tokens, written by `edapitool auth` |
| `~/edapitool/plugins/` | plugins you write or install yourself |
| `~/edapitool/gsheet_credentials.json` | Google API credentials, if you use a spreadsheet |
| `~/edapitool/gsheet_token.json` | the Google token the tool refreshes |
| `~/edapitool/store.db` | everything the tool has read from the game and from Frontier, kept as read — see [The observation store](store.md) |

**`ED_CONFIG_DIR` overrides all of it**, and it does not fall back: point it somewhere and that is where every one of these files is, whether or not it exists yet. That is the same rule the command-line flags follow — an explicit setting is the whole answer, not one merged with what is on disk. It is also how to run the tool against a throwaway configuration without touching your own:

**cmd.exe**
```cmd
set ED_CONFIG_DIR=%TEMP%\edapitool-scratch
```
**PowerShell**
```powershell
$env:ED_CONFIG_DIR = "$env:TEMP\edapitool-scratch"
```
**POSIX**
```bash
export ED_CONFIG_DIR=/tmp/edapitool-scratch
```

## Your first run writes the file for you

If `config.json` does not exist when any command runs, the tool writes a starting one and says so in one line, then carries on. Like a freshly installed web server's stock config, it explains itself: a header of `#` comment lines describes every key, and the JSON below it holds two working targets on the **public template workbook** — `totals-workbook` for the roll-up tab (the `totals` plugin) and `regions-workbook` for blocks placed in regions of your own tabs (no plugin: its `regions` list binds them, and the entry shipped is a placeholder for you to replace) — so the first `edapitool market` shows something real. Writing to that workbook (`--update-sheet`, `serve`) is expected to fail with a permission error, because it is not yours: make your own copy of it in Google Sheets and put its id in `"id"` of both targets. Each plugin's block in that file comes from the plugin itself (`edapitool plugins describe totals` shows the same), so it cannot drift from what the plugin accepts.

The tool never overwrites a file that exists. `--version` and `--help` write nothing. To run without the write at all — a script, a scratch shell — set `ED_NO_STOCK_CONFIG=1`.

Two rules govern it, and they are worth knowing before the schema:

**A flag wins outright over the file.** It never merges with it. If you pass `--construction-region`, that is the complete set of regions for that run and the file is ignored, because merged sources mean no single place tells you what will happen.

**Configuration declares what the tool may WRITE; the sheet declares what the tool should LOOK FOR.** A binding — which spreadsheet, which plugin, which ranges it may write — is something you set up once and rarely change, so it lives here. What you currently need, which system you are asking about, which site you are building: those you edit while playing, so the tool reads them from the sheet instead of asking you to restate them in JSON.

## The shape

```json
{
  "client_id": "YOUR_FRONTIER_CLIENT_ID",
  "plugin_dir": "~/edapitool/plugins",
  "targets": {
    "totals-workbook": {
      "kind": "gsheet",
      "plugin": "totals",
      "id": "YOUR_SHEET_ID",
      "config": {"totals_tab": "Totals Tab"}
    },
    "regions-workbook": {
      "kind": "gsheet",
      "id": "YOUR_SHEET_ID",
      "regions": [
        {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"}
      ]
    }
  }
}
```

Two targets can name the same spreadsheet. That is not an overlap: the tool compares the ranges each plugin declares it writes with every region a target binds, and refuses a region laid over a declared range.

| Key | What it is |
|---|---|
| `client_id` | Your Frontier OAuth client id. See [Frontier OAuth setup](frontier-oauth-setup.md). |
| `plugin_dir` | Where your own plugins live. Defaults to `~/edapitool/plugins`; `ED_PLUGIN_DIR` overrides it. |
| `targets` | The places the tool publishes to, keyed by a name **you** choose. |
| `pipelines` | Which targets' plugins run on a kind of data, and in what order. Optional; see below. |

### `pipelines`

```json
"pipelines": {
  "market":  {"reads": "market",  "steps": ["totals-workbook", "market-log"]},
  "cargo":   {"reads": "cargo",   "steps": ["hold-log"]},
  "carrier": {"reads": "carrier", "steps": ["hold-log"]}
}
```

A pipeline is keyed by the **data kind** it runs on — `market`, `cargo` or `carrier` — and `reads` says the same kind (a pipeline named for one kind reading another is refused). The kind is not a target's `kind` (`gsheet`, `jsonl`), which says what sort of place a target is. `steps` lists step tokens, and the plugins' steps run on that kind's data in the listed order: on `market`, the roll-up tab is compared and marked first, then the file is appended to with the result. This is the one place that says "this runs, then this" for every refresh; [running things in order](pipeline.md) is the same grammar typed once.

A step token is a target's name. The same grammar also knows the built-in pipelines (`market`, `cargo`, `carrier`, `regions`) and a plugin's commands (`<plugin>:<command>[=params]`); those are things a typed sequence runs *around* a refresh, so listing one inside a refresh's steps is refused by name. A target named like a built-in is refused when the file is read.

**Leave `market` out and its order is derived**: every enabled target whose plugin takes part — it offers a step, or suppliers a step may pull — runs, in the order the targets are listed. With one such target that is exactly what `market` did before; with two, both run. A `cargo` or `carrier` pipeline derives nothing: it runs only the steps you list, because no plugin says which kinds it reads, and a step written for the market must not be handed a hold. `edapitool plugins` shows the market pipeline it will run, and `serve` prints it when it starts.

A pipeline that cannot run is refused by name, and then **nothing** in it runs — an entry that is silently dropped is the failure this key exists to prevent. The refusals: a step that is none of the three things a step can be; a target served by a plugin already loaded for another target (one target per plugin in this release); the same plugin listed twice; a target whose plugin offers neither a step nor suppliers; a built-in or a command listed inside a refresh; and a pipeline name this release does not run (`market`, `cargo` and `carrier`, each reading its own kind; a recipe under another name arrives later and is refused rather than ignored until then). `market` prints a refusal and still answers the market, because reading it needs no step; `serve` and `pipeline` refuse and stop.

## A target

A target is one place the tool publishes to, and you name it. The name is yours — `totals-workbook`, `alts-sheet`, `nightly-dump` — and it is deliberately not the spreadsheet's id or a file path: a name survives you moving to a different workbook or reorganising a drive, and it is what future features will use to record where a piece of data came from.

| Key | Read by | What it is |
|---|---|---|
| `kind` | the tool | What sort of place this is: `gsheet` or `jsonl`. The kind selects both how the tool talks to the target and what "writing outside your declaration" means for it — a spreadsheet's bounds are cell ranges, a file's is a path. |
| `plugin` | the tool | Which plugin knows this target's shape. Three ship: `totals` for the roll-up tab, `jsonl` for a file, `settlement` for a tab from a template. `edapitool plugins` lists what you have. A target that only binds regions names none. |
| `id` | the `gsheet` kind | The spreadsheet id, the long string out of its URL. |
| `path` | the `jsonl` kind | Where the file is. The plugin appends one record per refresh and may write nowhere else. |
| `config` | **the plugin, never the tool** | Whatever that plugin reads. The tool carries this block without looking inside it. |
| `regions` | the tool | Rectangles of this target's own tabs the tool keeps current, each naming a region and what goes there. [Below](#regions). |

A target names a plugin, or binds regions, or both; one that does neither is refused when the file is read, because it names nothing to do.

`market`, and the market half of `serve`, run the `market` pipeline: every enabled target whose plugin takes part, in order (see [`pipelines`](#pipelines)). `totals` and `jsonl` take part; a target that only binds regions does not, because a region is a place the tool writes to, not a step. A configuration with only such a target gives `market --update-sheet` nothing to compare against, and the command says so.

### `config` is the plugin's

Nothing the tool ships parses a key inside a `config` block, and that is checked: a probe walks the keys `settings.py` reads and the examples in these docs, and reports a count that must be zero. So the contents of `config` are documented by whichever plugin reads them. For `totals` it is `totals_tab`, the tab it reads what you need from and writes its markers into (the plugin's own default is `Totals`; the template workbook's tab is `Totals Tab`, which is why the stock file names it). For `jsonl` it is `only`, the fields each record keeps. For `settlement` it is the five names in [settlement tabs](settlement-tabs.md).

### `regions`

A region is a rectangle of a tab you keep, into which the tool places a block of its data — a construction site's progress, the market, your ship's hold, your carrier's hold — and keeps it current while you play. Regions are the tool's own, so they sit on the target itself rather than inside any plugin's block:

```json
{
  "targets": {
    "regions-workbook": {
      "kind": "gsheet",
      "id": "YOUR_SHEET_ID",
      "regions": [
        {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"},
        {"region": "Other Tab!R1:AC60"},
        {"region": "Hauling!H1:N200", "data": "market"},
        {"region": "Hauling!P1:U40", "data": "cargo"}
      ]
    }
  }
}
```

Each entry names a tab and a range within it. A construction entry optionally names the site whose progress goes there; leave `site` out and the block follows whichever site you are docked at. Add `"data"` for anything else: `data` is `construction` (what an entry without it means), `market`, `cargo` or `carrier`. A market, cargo or carrier region holds exactly what the `MarketData`, `ShipCargo` or `FreighterData` tab holds, placed in a tab you keep, and `serve` refreshes it at the same moment as that tab. A carrier region is rewritten every time the carrier is checked, so its `Last checked` stamp stays as honest as the tab's, and it needs the same Frontier login the carrier tab does; without one, `serve` says the region is not published. `site` chooses a construction build, so it is refused on any other kind rather than ignored. The command-line flag, `--construction-region`, is always a construction block. Reserve enough rows: a market can run past a hundred commodities, and a block that outgrows its region is refused rather than spilling past it.

A malformed entry refuses the run when the file is read and names itself — `targets['regions-workbook'].regions[1] has no "region"` — rather than being skipped quietly, because a binding silently dropped is a region that stops publishing with nothing said. The same target may also name a plugin; a target that binds regions and names none is served with no plugin at all. The command-line spelling of a construction region, `serve --construction-region`, is in [keeping the sheet current](serve.md); a one-off write of any kind into a region is `--publish-to TAB --region A1:B2` on `profile`, `carrier`, `market`, `ship` and `construction`.

## `sheet_id` says where; a target says who

A top-level `"sheet_id"` names a spreadsheet, and the commands that publish a generated tab without any plugin — `carrier --export google`, `ship --export ship-tab`, `--publish-to` — read it. It does not select a plugin: nothing is enabled until a `targets` entry names one, because choosing which code runs against your spreadsheet should be something you said, not something the tool assumed. `edapitool plugins` lists what is installed, and `edapitool plugins describe <name>` prints a starter `config` block for any of them.

The `totals` plugin's default tab is `Totals`; a workbook whose tab is called something else names it in the target's config (`"config": {"totals_tab": "Totals Tab"}`).

## Two things worth knowing

**An empty `targets` map means the same as no map at all** — nothing is enabled, exactly as when the key is absent. Both are how you spell "load nothing", and that is the default.

**`ED_SHEET_ID` overrides a value; it does not bring a target into being.** The variable has always been a way to name a spreadsheet without editing the file, and that is all it does. It cannot enable a plugin, because enabling one is a decision that belongs in the file where you can see it.

## Precedence

For the spreadsheet id, in order: `--sheet-id`, then `ED_SHEET_ID`, then the first `gsheet` target's `id`, then the top-level `"sheet_id"`.

For the plugin directory: `ED_PLUGIN_DIR`, then `"plugin_dir"`, then `~/edapitool/plugins`.

For every file the tool owns: `ED_CONFIG_DIR` if it is set, otherwise `~/edapitool/<name>`. One rule and no search — the tool does not look in a second place, so there is never a question about which file a run read.

For regions: the `--construction-region` flag if given — outright, not merged — otherwise every `gsheet` target's `regions` list.

## Editing it safely

The file is yours and is edited by hand; the tool only ever writes one key at a time into it, through a temporary file moved into place, so an interrupted write cannot truncate what you typed. A value it cannot parse refuses the run and names the entry rather than guessing.

**Comments go in the header, and only there.** Lines starting with `#` above the first `{` are comments; the tool skips them when it reads and keeps them when it writes, so notes you add at the top survive `edapitool auth`. A `#` inside the JSON is an error. One cost, stated plainly: outside JSON tools (`python -m json.tool`, an editor's JSON validation) reject a file with a header, because it is not pure JSON. The JSON below the header is.

**Every write keeps the previous copy as `config.json.bak`.** If the file ever fails to parse — a stray comma after a hand edit — the tool says so on stderr, naming the file and the error, and runs from `config.json.bak` when that copy parses. It never silently reads a broken file as "no settings", which is what earlier versions did. A broken file is not backed up over the good copy; fix the file, or copy `config.json.bak` back over it.

## Related

- [Keeping the sheet current](serve.md) — what `serve` publishes, and the construction-region flag
- [Running things in order](pipeline.md) — the `pipeline` verb: the same step grammar, typed once
- [The current station's market](market.md) — the comparison, and `--sheet-id`
- [Frontier OAuth setup](frontier-oauth-setup.md) — where `client_id` comes from
- [Google Sheets setup](google-sheets-setup.md) — credentials for a `gsheet` target
