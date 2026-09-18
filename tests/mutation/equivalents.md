# Mutation survivors triaged as equivalent or don't-care

Guarded authority, not an allowlist. Each group is headed by the target file's content hash (`git hash-object`, first 12); when the file's current hash no longer matches, every entry under it is **stale** and must be re-triaged before reuse. Only separated-generation runs (modes 1–2) write here.

## APITool/loader.py @ 4a8d7b01c9af

Re-headed 2026-09-18 twice — after unit 2 added the kinds section (`93611c219003`) and after unit 3 added conflict detection — and the entries below were re-triaged against each new file; the guarded lines are byte-identical throughout.

- `if spec is None or spec.loader is None:` → `if spec is None and spec.loader is None:` — **don't-care**. `scan()` yields only directories holding an `__init__.py`, so `importlib.util.spec_from_file_location` cannot return `None` for anything `load()` receives; the guard defends a state that cannot arise through the loader's own front door, and a failure there is caught by `load()` as `Broken` with a differently spelled reason. 2026-09-18, mode 1.

- `return WriteGuard.build(dict(declaration))` → `return WriteGuard.build(declaration)` — **equivalent**. `WriteGuard.build` only calls `.items()` on what it is given, so any `Mapping` behaves identically to its `dict` copy; the copy is type-narrowing, not behaviour. 2026-09-18, mode 1.

## APITool/service.py @ 02e54c3e8b91

- `if guard is None:` → `if not guard:` (the core-built fallback in `MarketRefreshService.__init__`) — **equivalent**. `WriteGuard` is a plain frozen dataclass with no `__bool__` or `__len__`, so every instance is truthy and the two tests select the same branch for anything a caller can pass; `bool(WriteGuard.build({}))` is `True`. 2026-09-18, mode 1.

## APITool/sheets/writer.py @ c8cb5c536277

- the formats loop in `MarkerWriter.build_plan` checking `plan.updates` instead of `plan.formats` — **equivalent** for every reachable state. Every format range is a single cell `{marker_column}{row}` for a row in `[first_data_row, last_data_row]`, and the updates list always carries `marker_range(last_data_row)` spanning exactly those cells; the updates check therefore passes only when every format cell would pass too. The check is a deliberate fence against a future renderer whose formats stray, and stays. 2026-09-18, mode 1.

## APITool/cli.py @ 4db6550a0181

- `getattr(args, "show_formula", False)` → `getattr(args, "show_formula", True)` in `cmd_market` — **equivalent**. `--show-formula` is defined on the market parser with `action="store_true"` (`cli.py:1323`), so every parsed namespace carries the attribute and the default is never consulted. 2026-09-18, mode 1.

### Stale — APITool/loader.py @ 7d4d4f228017 (superseded by the heading above)
