# Running things in order

`edapitool pipeline <step> <step> ...` runs what you name, in the order you name it, and stops at the first failure. It is the answer to "update the regions, then the roll-up tab" as one command, and to "make the settlement tab, then fill it" without typing three commands and watching each.

```bash
# The regions of your own tabs, then the roll-up tab's step
edapitool pipeline regions totals-workbook

# A settlement tab from the template, then its regions, then the roll-up
edapitool pipeline "settlement:new=--type \"industrial large\" --name \"Ind. Lrg. 2\"" regions totals-workbook

# See what a sequence would do, and do nothing
edapitool pipeline market cargo carrier --dry-run
```

The sequence is printed before anything runs, one line per run, saying what it reads and what it writes. `--dry-run` prints it and stops with nothing built, so a new sequence can be read before it is trusted.

## What a step is

A step is one of three things, tried in this order:

| Form | What it names | What runs |
|---|---|---|
| a built-in pipeline: `market`, `cargo`, `carrier`, `regions` | one of the four things `serve` keeps current | that kind's pipeline: read the source, run the plugin steps the file lists for that kind, write the tab. `regions` places every bound region. |
| a target's name: `totals-workbook`, `market-log` | one target from your configuration | that target's plugin step alone, on one reading of its kind. Consecutive targets share one reading, so `totals-workbook market-log` reads the market once. |
| a plugin command: `<plugin>:<command>[=params]` | one of a plugin's own commands | the command, once, with everything after `=` as its own command line; its exit code stops the sequence |

The same three forms are what a recipe in the file's `pipelines` key may list, so what you type and what you save say the same thing the same way. A token that is none of the three refuses the whole sequence by name, with the three meanings it was tried against, and nothing runs. A target named like a built-in (`market`, say) is refused when the file is read, because a step naming it would mean two things.

**A built-in token names a pipeline, not a step.** `market` is "read the station market, hand it to each plugin step in `pipelines.market`, write `MarketData`" -- the whole thing `serve` does for the market, run once. A plugin step lives inside one of those pipelines; it is never a run of its own at the top level, which is why a target token runs its kind's pipeline with only that step.

## Parameters

A command's parameters are everything after the first `=`, split like a POSIX shell: quote a value that has spaces, and use forward slashes in a path, because a backslash is an escape. The split is at the *first* `=`, so an `=` inside a value survives: `settlement:new=--name a=b` hands the plugin `--name a=b`. The tool routes the parameters and never reads them; what they mean is the plugin's business, and the plugin's own `--help` says so.

## Between runs

**Runs share one worker, as `serve` has one.** A region placed by a later `regions` run holds the grid the `market` or `cargo` run before it built, in the same sequence; a region with no run of its kind before it says it is waiting for that kind's first read. A target-only run has a worker of its own, because its market steps differ from the configured list.

**After a command, the configuration is re-read.** A command that adds a target is seen by the run after it. That is what lets a setup command come first in the same sequence as the pipelines that use what it made.

**A run that fails stops the sequence.** The verb says which run failed and that nothing after it ran, and exits with the failing command's own code when a command failed. Runs before it are not undone: each wrote what it wrote.

## `serve` runs the same stages

`edapitool serve` keeps the same four pipelines current while you play, in the order `market`, `cargo`, `regions`, `carrier`: regions after the two tabs, because a market or cargo region places the grid its tab's pipeline just built, and the carrier last, because it is the only stage that leaves the machine and a slow call must not delay the ones that were ready. The verb is one pass through any of them; `serve` is every pass, driven by the journal. There is one list of stages, so the two cannot disagree about what a name means.

## Plugin steps on every kind

Each pipeline runs the plugin steps the file lists for it, in the listed order:

```json
"pipelines": {
  "market":  {"reads": "market",  "steps": ["totals-workbook", "market-log"]},
  "cargo":   {"reads": "cargo",   "steps": ["hold-log"]},
  "carrier": {"reads": "carrier", "steps": ["hold-log"]}
}
```

A step on the `market` pipeline is handed the refresh result (where you are, what the station sells, the comparison); on `cargo`, the ship's hold as a `ShipCargo` record; on `carrier`, the `FleetCarrier` record. Only the market pipeline derives a default list when the file names none -- every enabled target whose plugin takes part. A cargo or carrier pipeline runs only the steps listed, because no plugin declares which kinds it reads, and a step written for the market must not be handed a hold. [Writing a plugin](writing-a-plugin.md) has the step contract.

## Related

- [Configuration](configuration.md) -- the `pipelines` key and the `regions` list on a target
- [Keeping the sheet current](serve.md) -- the same stages, kept current while you play
- [Settlement tabs from a template](settlement-tabs.md) -- the first command worth putting at the front of a sequence
- [Writing a plugin](writing-a-plugin.md) -- steps and commands, and which is which

---

[< Back to the README](../README.md)
