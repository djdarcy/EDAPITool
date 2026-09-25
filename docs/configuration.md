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

**If you have these as dotfiles in your home directory, move them.** Earlier versions kept them as `~/.ed_capi_config.json`, `~/.ed_capi_tokens.json` and so on, scattered through a home directory; v0.7.5 keeps them in one place and looks in exactly that place. There is no fallback to the old names — one rule and no search, so a run can never read a file you had forgotten about. Move each one to `~/edapitool/` under the name in the table above while nothing is running. Moving `tokens.json` while a `serve` daemon is running is the one worth waiting for.

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

If `config.json` does not exist when any command runs, the tool writes a starting one and says so in one line, then carries on. Like a freshly installed web server's stock config, it explains itself: a header of `#` comment lines describes every key, and the JSON below it holds one working target — the settlement plugin pointed at the **public template workbook**, so the first `edapitool market` shows something real. Writing to that workbook (`--update-sheet`, `serve`) is expected to fail with a permission error, because it is not yours: make your own copy of it in Google Sheets and put its id in the target's `"id"`. The plugin's own block in that file comes from the plugin itself (`edapitool plugins describe settlement` shows the same), so it cannot drift from what the plugin accepts.

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
    "settlement-workbook": {
      "kind": "gsheet",
      "plugin": "settlement",
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

| Key | What it is |
|---|---|
| `client_id` | Your Frontier OAuth client id. See [Frontier OAuth setup](frontier-oauth-setup.md). |
| `plugin_dir` | Where your own plugins live. Defaults to `~/edapitool/plugins`; `ED_PLUGIN_DIR` overrides it. |
| `targets` | The places the tool publishes to, keyed by a name **you** choose. |

## A target

A target is one place the tool publishes to, and you name it. The name is yours — `settlement-workbook`, `alts-sheet`, `nightly-dump` — and it is deliberately not the spreadsheet's id or a file path: a name survives you moving to a different workbook or reorganising a drive, and it is what future features will use to record where a piece of data came from.

| Key | Read by | What it is |
|---|---|---|
| `kind` | the tool | What sort of place this is: `gsheet` or `jsonl`. The kind selects both how the tool talks to the target and what "writing outside your declaration" means for it — a spreadsheet's bounds are cell ranges, a file's is a path. |
| `plugin` | the tool | Which plugin knows this target's shape. Two ship: `settlement` for the workbook, `jsonl` for a file. `edapitool plugins` lists what you have. |
| `id` | the `gsheet` kind | The spreadsheet id, the long string out of its URL. |
| `path` | the `jsonl` kind | Where the file is. The plugin appends one record per refresh and may write nowhere else. |
| `config` | **the plugin, never the tool** | Whatever that plugin reads. The tool carries this block without looking inside it. |

The first target listed is the one single-destination commands (`market`, `serve`) talk to.

### `config` is the plugin's

Nothing the tool ships parses a key inside a `config` block, and that is checked: a probe walks the keys `settings.py` reads and the examples in these docs, and reports a count that must be zero. So the contents of `config` are documented by whichever plugin reads them — for `settlement`, that is `construction_regions`:

```json
{
  "targets": {
    "settlement-workbook": {
      "kind": "gsheet",
      "plugin": "settlement",
      "id": "YOUR_SHEET_ID",
      "config": {
        "construction_regions": [
          {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"},
          {"region": "Other Tab!R1:AC60"}
        ]
      }
    }
  }
}
```

Each entry names a tab, a range within it, and optionally the construction site whose progress goes there. Leave `site` out and the block follows whichever site you are docked at. Details, and the command-line spelling of the same thing, are in [keeping the sheet current](serve.md).

A malformed entry refuses the run and names itself — `construction_regions[1] has no "region"` — rather than being skipped quietly, because a binding silently dropped is a region that stops publishing with nothing said.

## The older shape, and what to do about it

Before targets existed, the file named one spreadsheet directly:

```jsonc
// deprecated: the shape before targets existed, shown so you can recognise
// your own file. As of v0.7.5 it no longer selects a destination -- see
// below for the two edits that move it forward.
{
  "client_id": "YOUR_FRONTIER_CLIENT_ID",
  "sheet_id": "YOUR_SHEET_ID",
  "construction_regions": [
    {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"}
  ]
}
```

**A file in that shape now publishes nowhere.** v0.7.4 read it as a single target named `default`, served by whichever plugin shipped; v0.7.5 removed that. The tool still runs — it reads your journal, prints the station, and exports CSV and JSON — but nothing is enabled until a `targets` entry names a plugin. Choosing which code runs against your spreadsheet should be something you said, not something the tool assumed because only one plugin happened to be installed.

Moving a file of that shape forward is two edits:

| Before | After |
|---|---|
| `"sheet_id": "X"` | `"targets": {"<your name>": {"kind": "gsheet", "plugin": "settlement", "id": "X"}}` |
| `"construction_regions": [...]` at the top level | the same list, inside that target's `"config"` |

`edapitool plugins` lists what is installed, and `edapitool plugins describe <name>` prints a starter `config` block for any of them.

`"sheet_id"` itself was **not** removed. It still names a spreadsheet, and the commands that publish a generated tab without any plugin — `carrier --export google`, `ship --export ship-tab`, `--publish-to` — still read it. What it no longer does is select a plugin: it says *where*, and a target says *who*.

## Two things worth knowing

**An empty `targets` map means the same as no map at all** — nothing is enabled, exactly as when the key is absent. Both are how you spell "load nothing", and as of v0.7.5 that is also the default.

**`ED_SHEET_ID` overrides a value; it does not bring a target into being.** The variable has always been a way to name a spreadsheet without editing the file, and that is all it does. It cannot enable a plugin, because enabling one is a decision that belongs in the file where you can see it.

## Precedence

For the spreadsheet id, in order: `--sheet-id`, then `ED_SHEET_ID`, then the first `gsheet` target's `id`, then the top-level `"sheet_id"`.

For the plugin directory: `ED_PLUGIN_DIR`, then `"plugin_dir"`, then `~/edapitool/plugins`.

For every file the tool owns: `ED_CONFIG_DIR` if it is set, otherwise `~/edapitool/<name>`. One rule and no search — the tool does not look in a second place, so there is never a question about which file a run read.

For construction regions: the `--construction-region` flag if given — outright, not merged — otherwise the target's `config` block.

## Editing it safely

The file is yours and is edited by hand; the tool only ever writes one key at a time into it, through a temporary file moved into place, so an interrupted write cannot truncate what you typed. A value it cannot parse refuses the run and names the entry rather than guessing.

**Comments go in the header, and only there.** Lines starting with `#` above the first `{` are comments; the tool skips them when it reads and keeps them when it writes, so notes you add at the top survive `edapitool auth`. A `#` inside the JSON is an error. One cost, stated plainly: outside JSON tools (`python -m json.tool`, an editor's JSON validation) reject a file with a header, because it is not pure JSON. The JSON below the header is.

**Every write keeps the previous copy as `config.json.bak`.** If the file ever fails to parse — a stray comma after a hand edit — the tool says so on stderr, naming the file and the error, and runs from `config.json.bak` when that copy parses. It never silently reads a broken file as "no settings", which is what earlier versions did. A broken file is not backed up over the good copy; fix the file, or copy `config.json.bak` back over it.

## Related

- [Keeping the sheet current](serve.md) — what `serve` publishes, and the construction-region flag
- [The current station's market](market.md) — the comparison, and `--sheet-id`
- [Frontier OAuth setup](frontier-oauth-setup.md) — where `client_id` comes from
- [Google Sheets setup](google-sheets-setup.md) — credentials for a `gsheet` target
