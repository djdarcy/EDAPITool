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
    return {"My Tab": ["L3:L", "C2"]}
```

**What you declare you will write, and nothing more.** The tool builds a guard from this and hands it to you; every write you make goes through it. A write outside your declaration is refused.

You do not build your own guard, and you cannot widen it at runtime. That is deliberate and it is measured: a plugin trusted to police itself did not catch its own transposed constant, and a guard built by the tool from that same declaration did.

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
| `ctx.options` | the command's flags, including `write` |

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
- [Keeping the sheet current](serve.md) — what the shipped settlement plugin publishes
- [Using it as a Python library](python-api.md) — the readers a plugin can reuse
