# Configuration

Everything the tool remembers between runs lives in one hand-edited file, `~/.ed_capi_config.json`. This page is its whole shape.

Two rules govern it, and they are worth knowing before the schema:

**A flag wins outright over the file.** It never merges with it. If you pass `--construction-region`, that is the complete set of regions for that run and the file is ignored, because merged sources mean no single place tells you what will happen.

**Configuration declares what the tool may WRITE; the sheet declares what the tool should LOOK FOR.** A binding — which spreadsheet, which plugin, which ranges it may write — is something you set up once and rarely change, so it lives here. What you currently need, which system you are asking about, which site you are building: those you edit while playing, so the tool reads them from the sheet instead of asking you to restate them in JSON.

## The shape

```json
{
  "client_id": "YOUR_FRONTIER_CLIENT_ID",
  "plugin_dir": "~/.ed_capi_plugins",
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
| `plugin_dir` | Where your own plugins live. Defaults to `~/.ed_capi_plugins`; `ED_PLUGIN_DIR` overrides it. |
| `targets` | The places the tool publishes to, keyed by a name **you** choose. |

## A target

A target is one place the tool publishes to, and you name it. The name is yours — `settlement-workbook`, `alts-sheet`, `nightly-dump` — and it is deliberately not the spreadsheet's id or a file path: a name survives you moving to a different workbook or reorganising a drive, and it is what future features will use to record where a piece of data came from.

| Key | Read by | What it is |
|---|---|---|
| `kind` | the tool | What sort of place this is. `gsheet` today. The kind selects both how the tool talks to the target and what "writing outside your declaration" means for it — a spreadsheet's bounds are cell ranges, a file's would be a path. |
| `plugin` | the tool | Which plugin knows this target's shape. `settlement` is the one that ships. |
| `id` | the `gsheet` kind | The spreadsheet id, the long string out of its URL. |
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

## The older shape still works

Before targets existed, the file named one spreadsheet directly:

```jsonc
// deprecated: the shape before targets existed, shown so you can recognise
// your own file. Write new configuration in the shape above.
{
  "client_id": "YOUR_FRONTIER_CLIENT_ID",
  "sheet_id": "YOUR_SHEET_ID",
  "construction_regions": [
    {"region": "Agri Lrg. (ex)!R1:AC60", "site": "Badeaux Nutrition Centre"}
  ]
}
```

A file in that shape keeps working exactly as it did. The tool reads it as a single target named `default`, of kind `gsheet`, served by the plugin that ships, whose `config` block holds everything else in the file. `"sheet_id"` is a **deprecated alias** kept so no existing install breaks; `ED_SHEET_ID` and `--sheet-id` keep working too, and both still win over the file.

There is nothing you must do about it. When you want a second destination, or want to be explicit, move the keys into a target:

| Before | After |
|---|---|
| `"sheet_id": "X"` | `"targets": {"<your name>": {"kind": "gsheet", "plugin": "settlement", "id": "X"}}` |
| `"construction_regions": [...]` at the top level | the same list, inside that target's `"config"` |

## Two things worth knowing

**An empty `targets` map means the same as no map at all.** `"targets": {}` falls back to the plugins that ship with the tool, exactly as a file without the key does. There is currently no way to spell "load nothing".

**`ED_SHEET_ID` can bring a target into being.** If the environment names a sheet and your file names neither `sheet_id` nor `targets`, the same `default` target is synthesised from the environment variable. That is the older behaviour carried forward — the variable has always been a way to name a spreadsheet without editing the file — but it is worth knowing that it does more than override a value now.

## Precedence

For the spreadsheet id, in order: `--sheet-id`, then `ED_SHEET_ID`, then the first `gsheet` target's `id`, then the old top-level `"sheet_id"`.

For the plugin directory: `ED_PLUGIN_DIR`, then `"plugin_dir"`, then `~/.ed_capi_plugins`.

For construction regions: the `--construction-region` flag if given — outright, not merged — otherwise the target's `config` block.

## Editing it safely

The file is yours and is edited by hand; the tool only ever writes one key at a time into it, through a temporary file moved into place, so an interrupted write cannot truncate what you typed. A value it cannot parse refuses the run and names the entry rather than guessing.

## Related

- [Keeping the sheet current](serve.md) — what `serve` publishes, and the construction-region flag
- [The current station's market](market.md) — the comparison, and `--sheet-id`
- [Frontier OAuth setup](frontier-oauth-setup.md) — where `client_id` comes from
- [Google Sheets setup](google-sheets-setup.md) — credentials for a `gsheet` target
