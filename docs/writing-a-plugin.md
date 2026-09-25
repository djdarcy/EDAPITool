# Writing a plugin

A plugin tells the tool about one place you publish to — a spreadsheet, a file, eventually something else — and what it should read from there. It is a Python package with a handful of module-level functions, and nothing else. There is no base class to inherit and no registry to sign up to.

This page is the whole contract. If something here is not enough to write a plugin from, that is a bug in this page.

## Where a plugin lives

Either beside the ones that ship, or in your own directory:

```
~/edapitool/plugins/myplugin/__init__.py
```

Point `ED_PLUGIN_DIR` somewhere else if you prefer, or set `"plugin_dir"` in your config. A plugin of yours with the same name as one that ships **replaces** it, and the tool says so when it does.

Nothing is loaded because it is there. The tool loads what your configuration names:

```json
{
  "targets": {
    "my-destination": {
      "kind": "gsheet",
      "plugin": "myplugin",
      "id": "YOUR_SHEET_ID",
      "config": {"anything": "your plugin reads this; the tool never does"}
    }
  }
}
```

See [Configuration](configuration.md) for the rest of that shape. To check what the tool can see:

```
edapitool plugins
edapitool plugins describe myplugin
```

`plugins` lists what is installed and what state each one is in, and it imports only what your configuration already enables. `describe` imports the one plugin you name — naming it is how you say you want it run.

Some names belong to the `plugins` verb itself: `list`, `describe` and `help` work today, and `enable`, `disable`, `check`, `config`, `info`, `show`, `status`, `install`, `uninstall`, `remove`, `update`, `new` and `init` are held back for later. A plugin directory with one of those names, in any case, or a name starting with `-`, is refused when it would load, and the listing says why, because `edapitool plugins <name>` could never reach it. Rename the directory.

## The contract

Every one of these is optional except `KIND`. A plugin that defines only some of them is a plugin that does only some things.

### `KIND`

```python
KIND = "gsheet"
```

What sort of place this destination is. It selects the **enforcer** — the thing that decides whether a write you attempt is one you declared. Two kinds exist today:

| `KIND` | A destination that is | Declarations look like | Enforced by |
|---|---|---|---|
| `gsheet` | a Google spreadsheet | `{"Tab Name": ["A1:B20"]}` | cell-range containment |
| `jsonl` | a file records are appended to | `{"__file__": ["/path/to/file.jsonl"]}` | the resolved path, exactly |

A target's `kind` in your configuration overrides whatever the plugin declares, which is how one plugin can serve two kinds of target if it is written to.

### `layout(**overrides)`

```python
def layout(**overrides):
    return MyLayout(**{k: v for k, v in overrides.items() if v is not None})
```

Returns an object describing where things are in your destination — tab names, columns, a path, whatever your kind needs. The tool passes command-line overrides in; you decide which of them mean anything. Whatever you return must have a `writes()` method (below).

This is the one place your destination's specifics belong. A plugin is allowed to hardcode a real spreadsheet — that is what a plugin *is*. Isolation is the goal here, not genericity.

### `writes()`

```python
def writes():
    return {"My Tab": ["C2", "G2", "L3", "L5:L"]}
```

**What you declare you will write, and nothing more.** The tool builds a guard from this and hands it to you; every write you make goes through it. A write outside your declaration is refused.

You do not build your own guard, and you cannot widen it at runtime. That is deliberate and it is measured: a plugin trusted to police itself did not catch its own transposed constant, and a guard built by the tool from that same declaration did.

**Declare what you write, not the smallest rectangle containing it.** Several narrow ranges beat one wide one, and it costs nothing to list them. The roll-up plugin (then called `settlement`, now `totals`) used to declare `L3:L` for a column it actually writes as `L3` plus `L5` downward — so a write to `L4`, a row it has never touched and whose neighbours are all `=SUM(...)`, would have been waved straight through. It now declares the two ranges separately, and `L4` is refused. A declaration wider than your behaviour is not a safety margin; it is the one write nobody intended, pre-authorized.

Two plugins declaring overlapping regions of the same destination is reported at load time, because whoever reads the result afterwards cannot tell which of you wrote what.

### `supplies()`

```python
def supplies():
    return {"requirements": _read_requirements}

def _read_requirements(ctx):
    ...
    return whatever_you_read
```

**What the tool can ask you for.** Each entry is a name and a function. The function is called **at most once per refresh** and its answer is remembered, so several consumers asking for the same thing cause one read. That is not an optimisation detail: Frontier's fleet-carrier endpoint refuses a second query for fifteen minutes, so two consumers each fetching for themselves would leave one of them with nothing.

Your supplier is handed the refresh (`ctx`, below). Return data. Return `None` if you cannot supply it this time — for instance if you need a handle you were not given.

Supplier names share one namespace across the tool and every loaded plugin. The tool supplies `location` and `market` itself; claiming one of those is refused by name at startup.

### `subscribes()`

```python
from APITool.registry import Subscription

def subscribes():
    return [Subscription("markers", ("requirements",), _publish)]

def _publish(ctx):
    ...
    return "a short status"
```

**What you publish, and what must be supplied first.** Each `Subscription` is a name, the supplier names it needs, and a function. The tool pulls those needs, then calls you. Return a short status describing what you did.

A supplier returns *data* and is pulled; a subscriber returns a *status* and is pushed. They are deliberately not the same shape, and one registry cannot serve both.

Your subscriber runs whether or not the comparison found anything, and whether or not any particular handle exists — the tool does not decide on your behalf that you have nothing to do. If you need something you were not given, say so and return:

```python
def _publish(ctx):
    if ctx.worksheet is None:
        return "no worksheet: nothing published"
    ...
```

### `default_config()` and `check_config(config)`

```python
def default_config():
    return {"some_setting": ["a starter value"]}

def check_config(config):
    problems = []
    if not isinstance(config.get("some_setting"), list):
        problems.append('"some_setting" must be a list')
    return problems
```

Your `config` block's schema is yours. The tool carries that block without reading it, so it cannot validate it and does not try — it asks you, at load time, and repeats whatever you return, naming the target. Return an empty list when there is nothing wrong.

A `check_config` that raises is treated as your plugin's defect and reported as one; it does not stop other targets loading. `default_config()` is what `plugins describe` shows someone setting your plugin up for the first time.

### `flags()`

```python
from APITool.registry import Flag

def flags():
    return [
        Flag("market", "--my-tab", "my_tab", "string", layout=True,
             help="Which tab to read (default: the plugin's own)"),
        Flag("market", "--quiet-cells", "quiet_cells", "store_true",
             help="Leave the cells you would colour uncoloured"),
    ]
```

**Your command-line words.** Each `Flag` names the verb it belongs to (`market` or `serve`), its spelling, the name its value arrives under, and its kind: `store_true`, `string`, `choices` (with `choices=[...]`), or `append`. The tool adds them to that verb's `--help` in a group titled with your plugin's name, and only when a target enables your plugin — someone who has not enabled it never sees them, and typing one is refused as an unknown option.

Where the value goes depends on `layout`. A flag with `layout=True` describes the *shape* of your destination, and when your plugin is the destination its value is passed to your `layout(**overrides)` under its name — `None` when nobody typed it, which means "use your own default". Every other flag's value arrives in `ctx.options` under its name, for your subscribers to read. `ctx.options` holds every enabled plugin's words for the command, not only yours, so read the names you declared and ignore the rest. The tool never reads any of them: it carries them.

Two loaded plugins declaring the same spelling on the same verb are refused at load, naming both, because one parser cannot hold both and "the later one wins" would make the word mean something different depending on the order of your configuration. Pick spellings that say whose they are.

### `commands()`

```python
from APITool.registry import Command

def commands():
    return {
        "setup": Command("setup", _setup, "write the target this plugin needs",
                         safe_unconfigured=True),
        "check": Command("check", _check, "read the destination and report what is wrong"),
    }

def _setup(tail, target):
    print(f"setting up with {tail}")
    return 0

def _check(tail, target):
    print(f"checking {target.name}")
    return 0
```

**Things a person can ask your plugin to do**, as `edapitool plugins <name> <command> ...`. `plugins <name>` on its own, or with `--help`, lists your commands. Everything after the command's name reaches your handler unread, as a list of strings, so parse it however you like — an `argparse` of your own that exits is fine, and its exit code is kept. Return the command's exit code.

The second argument is the target that enables your plugin, or `None` when none does. That is the reason for `safe_unconfigured`: a command marked safe runs on a plugin that is installed but not enabled, which is what a setup command needs, since its job is often to produce the very target that would enable it. A command not marked safe is refused on an unenabled plugin, by name, with the configuration line to add, and your handler is never called. Default to not safe: a handler written to read a destination should never be handed `None` and left to guess.

Naming a plugin imports it even when no target enables it — naming it is the consent — and never imports another plugin the configuration has not enabled. (Enabled plugins are imported by every command, this one included, because that is where their flags come from.) A handler that raises is reported with the command it was, and the tool exits 1.

## An example of splitting one plugin into two

v0.8.0 split the shipped `settlement` plugin, and the reasons are a fair guide to where the edges of a plugin belong. It held two things. One was the roll-up tab: a place with a `layout()`, a comparison it `supplies()`, and glyph markers it `subscribes()` to paint. The other was the construction blocks: a list of regions a target binds to construction sites, read by `serve`, with no tab of its own and nothing to compare.

They now ship as `totals` and `construction`, and a workbook uses both, as two targets naming the same spreadsheet. The tool finds each by what it offers rather than by its name: the destination for `market` is the first enabled plugin with a `layout()`, and `serve` takes its construction blocks from whichever enabled plugin offers `construction_regions`. Each plugin declares only its own flags (`--construction-region` is `construction`'s; `--totals-tab`, `--force` and the rest are `totals`'), so each plugin's `--help` group is honest about whose words they are.

The test for a split: if you can describe a piece of your plugin without mentioning the rest of it, and some destination would want that piece alone, it is a plugin of its own.

## The refresh: what `ctx` carries

Every supplier and subscriber is handed the same object.

| | |
|---|---|
| `ctx.get(name)` | ask for a supplier's value — pulled once, then remembered |
| `ctx.has(name)` | whether anything supplies that name |
| `ctx.supplied()` | every name available this refresh |
| `ctx.layout` | what your `layout()` returned |
| `ctx.guard` | the enforcer the tool built from your `writes()` |
| `ctx.worksheet` | the sheet handle, for a `gsheet` target; `None` otherwise |
| `ctx.target` | the name you gave this target in your configuration |
| `ctx.result` | this refresh's result, on a subscriber |
| `ctx.checked_at` | when the data was current, as a string |
| `ctx.options` | the values of the enabled plugins' flags for this command, by the names they declared, plus `write` |

`ctx.options["write"]` is the one to respect: when it is false the person asked for a dry run, so work out what you *would* do, say so, and write nothing.

## A worked example: appending to a file

A complete plugin for a `jsonl` target, short enough to read in one go.

```python
"""Append one record per refresh to a file."""
import json
from dataclasses import dataclass
from pathlib import Path

from APITool.registry import Subscription

KIND = "jsonl"


@dataclass(frozen=True)
class FileLayout:
    path: str = ""

    def writes(self):
        return {"__file__": [self.path] if self.path else []}


def layout(**overrides):
    return FileLayout(**{k: v for k, v in overrides.items() if v is not None})


def writes():
    return FileLayout().writes()


def default_config():
    return {"path": "~/ed/observations.jsonl"}


def check_config(config):
    if config and not isinstance(config.get("path", ""), str):
        return ['"path" must be a string']
    return []


def _previous(ctx):
    """A file has prior state too: the last record already in it."""
    path = getattr(ctx.layout, "path", "")
    handle = Path(path).expanduser() if path else None
    if handle is None or not handle.is_file():
        return None
    lines = [ln for ln in handle.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return json.loads(lines[-1]) if lines else None


def _append(ctx):
    path = getattr(ctx.layout, "path", "")
    if not path:
        return "no path configured: nothing written"

    record = {"checked_at": ctx.checked_at,
              "system": getattr(ctx.result.location, "system", None)}

    # Through the guard BEFORE opening anything: a guard consulted after the
    # write reports a refusal that has already happened.
    if ctx.guard is not None:
        ctx.guard.check(path)
    if not ctx.options.get("write"):
        return f"would append 1 record to {path}"

    handle = Path(path).expanduser()
    handle.parent.mkdir(parents=True, exist_ok=True)
    with handle.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return f"appended 1 record to {path}"


def supplies():
    return {"previous": _previous}


def subscribes():
    return [Subscription("record", (), _append)]
```

Configure it and it runs:

```json
{
  "targets": {
    "nightly-dump": {
      "kind": "jsonl",
      "plugin": "myfileplugin",
      "config": {"path": "~/ed/observations.jsonl"}
    }
  }
}
```

Note what did *not* have to happen for a file destination to work: nothing in the tool's contract changed, no interface widened, and no special case was added for "not a spreadsheet". If you find yourself needing any of those to write a plugin, that is worth reporting — it means the contract is shaped like one kind of destination rather than like a destination.

## What a plugin must not do

- **Do not build your own guard.** Declare, and use the one you are handed.
- **Do not import another plugin.** If two plugins need the same thing, it belongs in the shared toolkit (`APITool.sheets` for spreadsheet mechanics), and moving it there is the right change.
- **Do not make your own internals configurable.** A plugin hardcodes a real destination on purpose. What varies for a *user over time* — which sites they are tracking — belongs in your `config` block; what a destination *is* does not.

## Related

- [Configuration](configuration.md) — targets, kinds, and the `config` block
- [Keeping the sheet current](serve.md) — what the shipped `totals` and `construction` plugins publish
- [Using it as a Python library](python-api.md) — the readers a plugin can reuse
