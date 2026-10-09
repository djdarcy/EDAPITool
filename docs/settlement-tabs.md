# Settlement tabs from a template

The `settlement` plugin makes a tab for a settlement that does not exist in the game yet, so you can plan what to buy before the construction site appears. It copies a template, names the copy, titles it, and seeds the block the tab's own formulas read -- in the same shape the tool will later publish there from the live site. Nothing else on the tab is touched, and none of your formulas pass through the tool.

```
edapitool plugins settlement new --type "industrial large" --name "Ind. Lrg. 2"
```

## What it needs from your workbook

Three things the template workbook already has, named in the plugin's `config` block:

| Key | Default | What it is |
|---|---|---|
| `base_tab` | `Base` | the construction requirements matrix: commodities down column A, one settlement type per column across the header row (the row whose column A starts with `PLANETARY`), counts in the cells |
| `source_tab` | `Agri Lrg. (ex)` | an existing settlement tab the template is made from, the first time |
| `template_tab` | `_settlement template` | the hidden template; made once, reused for every new tab, remade with `--refresh-template` |
| `region` | `R1:AC60` | the block the tab's formulas read, where the live construction data is published |
| `title_cell` | `C3` | where the tab names its settlement type |

A target enables the plugin:

```json
{
  "targets": {
    "settlements": {
      "kind": "gsheet",
      "plugin": "settlement",
      "id": "YOUR_SHEET_ID",
      "config": {}
    }
  }
}
```

`edapitool plugins describe settlement` shows the starter block. The plugin offers no step: `market` and `serve` leave it out, and `edapitool plugins` lists it loaded but not in the pipeline.

## What `new` does

1. Reads the matrix from `base_tab` and finds the type you named -- `"industrial large"`, `"Settlement industrial large"` and the matrix's own ` industrial large` all mean the same column. An unknown type is refused, naming every type the matrix offers.
2. Builds the seed: one row per commodity that type needs, all required and none provided, headed by the site's name (`--site`, else the tab's name) and system (`--system`), with the state `planned`.
3. Refuses if a tab with that name exists. Nothing has been created yet.
4. Makes the template if it is missing: a copy of `source_tab` with its block and title cleared, hidden.
5. Copies the template to `--name`, shows the copy, writes the title cell and the seed -- through a write bound the tool builds for that run covering exactly the new tab's block and title cell.
6. Prints the entry to add to a target's `regions` list, so `serve` keeps the block current once the site exists:

   ```json
   {"region": "Ind. Lrg. 2!R1:AC60", "site": "Ind. Lrg. 2"}
   ```

   and reminds you to add the tab to the Totals Tab's source list. The tool never edits your configuration.

`--dry-run` does steps 1 to 3 and prints what 4 and 5 would do.

## When the site appears

The seed is a placeholder in the live block's exact shape. Once the construction site exists in the game and its binding is in your config, `serve` publishes the real data over it: the same columns, the same rows, now with what the site has received. The tab's formulas do not notice the change of author.

## If you change a settlement tab's formulas

The template is a copy taken once. After editing a settlement tab's formulas, run `new` with `--refresh-template` and the template is remade from `source_tab` before the copy.

## Related

- [Configuration](configuration.md) -- targets, and the `config` block
- [Colony construction](construction.md) -- the live site's data, and the regions a target binds to publish it
- [Running things in order](pipeline.md) -- `settlement:new=...` as the first step of a sequence that then fills the tab
- [Writing your own formulas](writing-your-own-formulas.md) -- what lands in which column of the block
