# Mutation survivors triaged as equivalent or don't-care

Guarded authority, not an allowlist. Each group is headed by the target file's content hash (`git hash-object`, first 12); when the file's current hash no longer matches, every entry under it is **stale** and must be re-triaged before reuse. Only separated-generation runs (modes 1–2) write here.

## APITool/loader.py @ 659001ae4161

Re-headed 2026-09-18 three times — after unit 2 added the kinds section (`93611c219003`), after unit 3 added conflict detection (`4a8d7b01c9af`), and after slice C added the target pass-through and the `sheet_id` alias — and the entries below were re-triaged against each new file; the guarded lines are byte-identical throughout.

- `if spec is None or spec.loader is None:` → `if spec is None and spec.loader is None:` — **don't-care**. `scan()` yields only directories holding an `__init__.py`, so `importlib.util.spec_from_file_location` cannot return `None` for anything `load()` receives; the guard defends a state that cannot arise through the loader's own front door, and a failure there is caught by `load()` as `Broken` with a differently spelled reason. 2026-09-18, mode 1.

- `return WriteGuard.build(dict(declaration))` → `return WriteGuard.build(declaration)` — **equivalent**. `WriteGuard.build` only calls `.items()` on what it is given, so any `Mapping` behaves identically to its `dict` copy; the copy is type-narrowing, not behaviour. 2026-09-18, mode 1.

## APITool/service.py @ 557c32f1974c

Re-headed 2026-09-18 after slice C added the target name to the refresh (`02e54c3e8b91` superseded); the guarded line is byte-identical and the entry was re-triaged against it.

- `if guard is None:` → `if not guard:` (the core-built fallback in `MarketRefreshService.__init__`) — **equivalent**. `WriteGuard` is a plain frozen dataclass with no `__bool__` or `__len__`, so every instance is truthy and the two tests select the same branch for anything a caller can pass; `bool(WriteGuard.build({}))` is `True`. 2026-09-18, mode 1.

## APITool/sheets/writer.py @ ea9224f461ea

Re-headed 2026-09-25 after slice 4's writes ledger (`69b5d364c812` superseded): the two entries below were re-triaged and still hold -- the format-guard loop and `_free_runs` are untouched, and "skipped rows" now reads "held rows", the same set. Two new entries from the v0.8.1 unit-3 sweep follow them.

Re-headed 2026-09-21 after slice E's #25 fix replaced the wholesale marker write with contiguous free runs (`c8cb5c536277` superseded). **The entry below was not carried across — its reasoning was invalidated by that change and had to be rebuilt**, which is what re-triage is for. Its old argument was that the plan's single `marker_range(last_data_row)` update spanned every format cell; the plan no longer carries such a range.

- the formats loop in `MarkerWriter.build_plan` checking `plan.updates` instead of `plan.formats` — **equivalent** for every reachable state, for a NEW reason. Every format range is still a single cell `{marker_column}{row}`, and since the colour filter drops the formats of skipped rows, every surviving format cell is a row in some free run — so it lies inside one of the update ranges the first loop already checked. Containment is restored by the filter rather than by one wide range. Re-measured as M19 in the v0.7.6 sweep: survived. The check is a deliberate fence against a future renderer whose formats stray, and stays. 2026-09-21, mode 1.

- `if start is not None:` → `if start:` (closing a run in `_free_runs`) — **equivalent**. `start` holds either `None` or a row number taken from `first_row + offset`, and A1 row numbers are 1-based, so it can never be falsy-but-not-None. A layout claiming `first_data_row = 0` would produce `L0:L24`, which Google rejects before this line is reached. Measured as M01, survived three rounds. 2026-09-21, mode 1.

- `return None` → `return {}` in `MarkerWriter._read_back`'s except branch — **equivalent**. `_record` stops on `None`; with `{}` it continues to `ledger.record(tab, {})`, and an empty record writes nothing (`StoreLedger.record` and `MemoryLedger.record` both return False on empty values). Either way a failed read-back records nothing. Measured as M10 in the v0.8.1 unit-3 sweep. 2026-09-25, mode 1.

- `len(answers) > len(cells)` → `>=` in `_read_formulas` — **don't-care**. It differs only when a worksheet returns fewer answers than ranges requested; gspread's `batch_get` returns one ValueRange per range, and a fake that did otherwise would test a worksheet that does not exist. Measured as M08 in the same sweep. 2026-09-25, mode 1.

## APITool/cli.py @ b18142c044eb

Re-headed again 2026-09-25 for v0.8.1 (`ddf9dad4e744` superseded): slice 4 replaced `_report_skipped` with `_report_plan`; `_plugin_commands`, where the first entry lives, is untouched and was re-triaged. Two entries from the v0.8.1 unit-5 sweep follow it.

Re-headed 2026-09-25 after slice 3 (v0.8.0) moved the plugin's words out of core (`ddb22512ced6` superseded), and three more times the same day, after the reserved-word correction touched `cmd_plugins` (`ace9806dbd0a`), a docstring correction in `_run_plugin_command` (`56628dc6d69d`), and the sign-in flags' help group (`fae32c8736af`); `_plugin_commands`, where the entry below lives, is byte-identical through both and the entry was re-triaged against it. The `show_formula` entry below it is NOT carried forward: since v0.8.0 `--show-formula` is declared by the totals plugin, so on an install without that plugin the namespace lacks the attribute and the default IS consulted -- the old reasoning no longer holds and the mutant would need re-triage (likely killable) if it were generated again.

- `out[str(key)] = command` → `out[key] = command` in `_plugin_commands` — **don't-care**. `commands()` is documented as a mapping *by name*, and a name is the word a person types, so every plugin keys with a string already; `str()` is a courtesy for a plugin that keyed by an enum or a number, and a test pinning it would promise something the contract does not. Measured as M10 in the v0.8.0 unit-4 sweep. 2026-09-25, mode 1.

- `set(plan.held or plan.skipped)` → `set(plan.held and plan.skipped)` in `_report_plan` — **equivalent**. `MarkerWriter.build_plan` always sets `plan.skipped = list(plan.held)`, so the two lists are both empty or both equal, and `a or b` and `a and b` return the same list. The `or` exists for a caller that builds a `MarkerPlan` with only `skipped` filled. Measured as M01 in the v0.8.1 unit-5 sweep. 2026-09-25, mode 1.

- `if plan.held or plan.skipped:` → `if plan.held and plan.skipped:` before the `--force` hint — **equivalent**, for the same reason. Measured as M08 in the same sweep. 2026-09-25, mode 1.

### Stale — APITool/cli.py @ ddb22512ced6 (superseded by the heading above)

- `getattr(args, "show_formula", False)` → `getattr(args, "show_formula", True)` in `cmd_market` — was **equivalent** while `--show-formula` was defined on the market parser with `action="store_true"`, so every parsed namespace carried the attribute and the default was never consulted. 2026-09-18, mode 1. No longer true from v0.8.0; see the heading above.

### Stale — APITool/loader.py @ 7d4d4f228017 (superseded by the heading above)
