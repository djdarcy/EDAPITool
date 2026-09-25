"""
Command-line interface for Elite Dangerous API Tool.

Usage:
    edapitool auth         - Authenticate with Frontier
    edapitool profile      - Get commander profile
    edapitool carrier      - Get fleet carrier data
    edapitool carrier csv  - Export carrier data to CSV
"""

import argparse
import sys
import json
from pathlib import Path
from typing import Mapping, Optional

from .version import __version__, get_version
from .constants import CAPI_SERVER_LIVE, CAPI_SERVER_LEGACY
from .auth import FrontierAuth
from .capi import CAPIClient, CAPIError, CAPINoDataError
from .models import FleetCarrier
from .export import CSVExporter, JSONExporter
# Imported as NAMES, not through the module, and that is load-bearing:
# tests monkeypatch these on this module to stub resolution out. Calling
# settings.get_sheet_id(...) instead would leave those patches inert.
from . import settings
# The resolvers are imported as NAMES because tests monkeypatch them on this
# module; CONFIG_FILE is read through `settings` instead, because it is a
# VALUE -- importing it by name would freeze the path at import time and a
# message naming it would report a different file from the one just read.
from .settings import (
    get_client_id,
    get_sheet_id,
    save,
)


def setup_auth(
    client_id: str,
    redirect_uri: Optional[str] = None,
    manual: bool = False,
) -> FrontierAuth:
    """Set up authentication."""
    auth = FrontierAuth(client_id, redirect_uri=redirect_uri)
    if not auth.is_authenticated:
        print("Not authenticated. Starting authorization flow...")
        print()
        if not manual:
            print("You will be redirected to Frontier's login page.")
            print("After logging in, authorize this application.")
            print()
        if auth.authorize(manual=manual):
            print("Authentication successful!")
        else:
            print("Authentication failed.")
            sys.exit(1)
    return auth


def save_client_id(client_id: str) -> bool:
    """Save client ID to config file for future use."""
    return save("client_id", client_id)


def cmd_auth(args: argparse.Namespace) -> int:
    """Handle auth command."""
    client_id = args.client_id or get_client_id()
    if not client_id:
        print("Error: No client ID provided.")
        print()
        print("To authenticate, you need a Frontier API client ID.")
        print("Register your application at: https://auth.frontierstore.net/client/signup")
        print()
        print("Then either:")
        print("  1. Set ED_CLIENT_ID environment variable")
        print(f"  2. Create {settings.CONFIG_FILE} with: {{\"client_id\": \"your_id\"}}")
        print("  3. Use --client-id argument")
        return 1

    redirect_uri = getattr(args, 'redirect_uri', None)
    manual = getattr(args, 'manual_auth', False)

    auth = setup_auth(client_id, redirect_uri=redirect_uri, manual=manual)

    # Save client ID to config file for future use
    if auth.is_authenticated and args.client_id:
        if save_client_id(client_id):
            print(f"Client ID saved to {settings.CONFIG_FILE}")

    print(f"Authenticated: {auth.is_authenticated}")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    """Handle profile command."""
    client_id = args.client_id or get_client_id()
    if not client_id:
        print("Error: No client ID. Run 'edapitool auth' first.")
        return 1

    redirect_uri = getattr(args, 'redirect_uri', None)
    manual = getattr(args, 'manual_auth', False)

    auth = setup_auth(client_id, redirect_uri=redirect_uri, manual=manual)
    client = CAPIClient(auth)

    try:
        profile = client.get_profile()

        if args.json:
            print(json.dumps(profile, indent=2))
        else:
            commander = profile.get("commander", {})
            print(f"Commander: {commander.get('name', 'Unknown')}")
            print(f"Credits: {commander.get('credits', 0):,}")
            print(f"Current Ship: {profile.get('ship', {}).get('name', 'Unknown')}")

    except CAPIError as e:
        print(f"Error: {e}")
        return 1

    return 0


def cmd_carrier(args: argparse.Namespace) -> int:
    """Handle carrier command."""
    client_id = args.client_id or get_client_id()
    if not client_id:
        print("Error: No client ID. Run 'edapitool auth' first.")
        return 1

    redirect_uri = getattr(args, 'redirect_uri', None)
    manual = getattr(args, 'manual_auth', False)

    # Parse include flags
    include_flags = [f.strip().lower() for f in args.include.split(",") if f.strip()]
    include_stolen = "stolen" in include_flags
    include_mission = "mission" in include_flags

    # Parse export formats (comma-separated)
    export_formats = []
    if args.export:
        export_formats = [f.strip().lower() for f in args.export.split(",") if f.strip()]

    # Resolved the same way every other verb resolves it. This used to read
    # args.sheet_id raw, so a sheet id sitting in the config file or in
    # ED_SHEET_ID was ignored here and honoured everywhere else -- nobody
    # chose that, it is what four independent call sites drift into.
    sheet_id = get_sheet_id(args)
    if "google" in export_formats and not sheet_id:
        print("Error: --export google needs a spreadsheet. Pass --sheet-id,")
        print('       set ED_SHEET_ID, or add "sheet_id" to '
              f"{settings.CONFIG_FILE}.")
        return 1

    auth = setup_auth(client_id, redirect_uri=redirect_uri, manual=manual)
    server = CAPI_SERVER_LEGACY if args.legacy else CAPI_SERVER_LIVE
    client = CAPIClient(auth, server=server)

    try:
        print("Fetching fleet carrier data...", file=sys.stderr)
        print("(This may take up to 60 seconds for large inventories)", file=sys.stderr)
        print(file=sys.stderr)

        from datetime import datetime, timezone

        raw_data = client.get_fleet_carrier()
        # Taken the moment Frontier answered, not when the sheet is written --
        # the two differ by however long the export takes, and the stamp is a
        # claim about when we ASKED. Frontier's payload carries no as-of time
        # of its own (measured 2026-09-15), so our clock is the only one there
        # is, and the field is named to say so.
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # Output raw JSON if requested (before parsing to avoid errors)
        if args.json:
            print(json.dumps(raw_data, indent=2))
            return 0

        # Parse into model
        carrier = FleetCarrier.from_capi(raw_data)

        output_dir = Path(args.output) if args.output else Path.cwd()
        exported_files = {}

        # Handle each export format
        for fmt in export_formats:
            if fmt == "csv":
                exporter = CSVExporter(output_dir)
                files = exporter.export_all(carrier)
                exported_files["csv"] = files

            elif fmt == "json":
                exporter = JSONExporter(output_dir)
                filepath = exporter.export_carrier(carrier, include_raw=args.raw)
                exported_files["json"] = filepath

            elif fmt == "gsheet":
                exporter = CSVExporter(output_dir)
                filepath = exporter.export_cargo_gsheet(
                    carrier,
                    include_stolen=include_stolen,
                    include_mission=include_mission,
                )
                exported_files["gsheet"] = filepath

            elif fmt == "google":
                # Direct Google Sheets export
                try:
                    from .google import GoogleSheetsExporter
                    gs_exporter = GoogleSheetsExporter()
                    gs_exporter.export_cargo(
                        carrier,
                        sheet_id=sheet_id,
                        include_stolen=include_stolen,
                        include_mission=include_mission,
                        checked_at=checked_at,
                        # A one-shot has no memory of a previous reading, so
                        # it cannot say when the hold last CHANGED. Left
                        # blank, which reads as "not known" -- only `serve`,
                        # which sees successive readings, can fill it.
                        changed_at="",
                    )
                    exported_files["google"] = f"Sheet ID: {sheet_id}"
                except ImportError:
                    print("Error: Google Sheets support not installed.")
                    print("Install with: pip install edapitool[gsheets]")
                    return 1

            else:
                print(f"Warning: Unknown export format '{fmt}', skipping.")

        # Print results
        if exported_files:
            print(f"Fleet Carrier: {carrier.identity.display_name} ({carrier.identity.callsign})")
            print(f"Location: {carrier.location.system}")
            print()
            print("Exported:")
            for fmt, result in exported_files.items():
                if isinstance(result, dict):
                    for export_type, filepath in result.items():
                        print(f"  {fmt}/{export_type}: {filepath}")
                else:
                    print(f"  {fmt}: {result}")
        else:
            # Default: print summary
            print(f"Fleet Carrier: {carrier.identity.display_name}")
            print(f"Callsign: {carrier.identity.callsign}")
            print(f"Location: {carrier.location.system}")
            print(f"State: {carrier.location.state}")
            print(f"Fuel: {carrier.fuel} t")
            print(f"Cargo Items: {len(carrier.cargo)}")
            print()
            print(f"Bank Balance: {carrier.finance.balance:,} CR")
            print(f"Weekly Upkeep: {carrier.finance.weekly_upkeep:,} CR")
            print()
            print(f"Commodity Orders: {len(carrier.all_commodities)}")
            print(f"  Sell: {len(carrier.commodity_sales)}")
            print(f"  Buy: {len(carrier.commodity_purchases)}")
            print()
            print(f"Microresource Orders: {len(carrier.all_microresources)}")
            print(f"Locker Items: {len(carrier.locker_items)}")
            print()
            print(f"Enabled Services: {', '.join(carrier.enabled_services)}")

    except CAPINoDataError:
        print("You don't appear to own a fleet carrier.")
        return 1
    except CAPIError as e:
        print(f"Error: {e}")
        return 1

    return 0




# The flags that are a destination plugin's whole purpose: publishing the
# markers back, and explaining the formula a sheet would use to reproduce
# them itself. Asking for either with no destination configured is a real
# error and says which flag needed one. The comparison also needs a plugin,
# but asking for it is the DEFAULT, so its absence is reported as a missing
# comparison rather than a refused command.
DESTINATION_ONLY_FLAGS = (
    ("update_sheet", "--update-sheet"),
    ("show_formula", "--show-formula"),
)


def cmd_market(args: argparse.Namespace) -> int:
    """
    Compare the current station's market against the spreadsheet's
    outstanding requirements, and optionally mark them in the sheet.
    """
    # The composition root asks the loader which destination is configured;
    # nothing here names a plugin. Everything below is handed a layout and
    # never asks whose it is.
    #
    # Having NONE is an ordinary state, not a failure. Where you are, what
    # the station sells, how fresh the reading is and the csv or json of it
    # all come from the journal, and none of that was ever a plugin's to
    # provide -- so only the three things a destination is actually for
    # refuse without one. This command used to return 1 here for all of
    # them, which made "the core ships no destination" a sentence the core
    # could not survive being true.
    destination, problem = _resolve_destination(getattr(args, "_plugins", None))
    if destination is None:
        needed = [flag for attribute, flag in DESTINATION_ONLY_FLAGS
                  if getattr(args, attribute, False)]
        if needed:
            print(f"Error: {' and '.join(needed)} needs a destination plugin,"
                  " and none is configured.")
            # The loader's own listing: which plugins exist, and that each is
            # available rather than broken. "No plugin" alone leaves a person
            # with nowhere to go next.
            print("\n".join(problem.splitlines()[1:]))
            return 1

    if getattr(args, "show_formula", False):
        # The formula reproduces the plugin's own glyphs and thresholds, so
        # the plugin is the one that can say it. A plugin with no marker
        # column has no formula to show, and says so rather than crashing.
        formula_help = getattr(destination.module, "formula_help", None)
        if not callable(formula_help):
            print(f"The {destination.name!r} plugin has no formula help.")
            return 1
        print(formula_help())
        return 0

    from .service import MarketRefreshService, format_table
    from .sheets import WriteRefused

    # Core builds the enforcer from what the plugin declares it writes; the
    # target's kind supplies the vocabulary. The plugin is handed the result.
    from .loader import GSHEET, build_enforcer

    layout = None
    if destination is not None:
        # Only what the person actually TYPED. Each of these five flags is
        # one destination's vocabulary -- a roll-up tab, a requirement
        # header, which sign means "still to buy" -- and every one of them
        # defaults to None so that "not given" is distinguishable from
        # "given". Passing an untyped flag's default handed every plugin the
        # first plugin's words, so a file destination was refused for not
        # understanding --need-sign, which nobody had asked for; and where
        # the default came FROM the plugin it was core couriering a value
        # out of the plugin only to hand it straight back.
        #
        # `--empty-glyph-marker` names a glyph family; which glyphs those are is
        # the plugin's to decide, so the choice travels to it as a word.
        layout, problem = _plugin_layout(destination, **_layout_overrides(args, "market"))
        if layout is None:
            print(problem)
            return 1
        guard = build_enforcer(destination.kind, layout.writes())
    else:
        # No destination declared anything, so nothing may be written. Built
        # from an empty declaration rather than left as None, because the
        # service would otherwise construct its own from a layout it does not
        # have -- and because deny-by-default is the honest reading of "no
        # plugin has claimed any cell here".
        guard = build_enforcer(GSHEET, {})

    capi_client = None
    if args.use_capi:
        client_id = args.client_id or get_client_id()
        if not client_id:
            print("Error: --use-capi needs a client ID. Run 'edapitool auth' first.")
            return 1
        auth = setup_auth(client_id)
        capi_client = CAPIClient(auth)

    try:
        service = MarketRefreshService(
            journal_dir=Path(args.journal_dir) if args.journal_dir else None,
            layout=layout,
            capi_client=capi_client,
            guard=guard,
            plugin=destination.module if destination is not None else None,
            target=_target_name(destination) if destination is not None else "",
        )
    except ValueError as exc:
        # The registry refuses a supplier name offered twice -- a plugin
        # claiming "location" or "market", which core supplies -- and names
        # both offerers. The refresh below was guarded; the constructor,
        # where that refusal is raised, was not, so it arrived as a traceback.
        print(f"Error: {exc}")
        return 1

    # Parsed here rather than beside its use below, because whether a
    # spreadsheet is required depends on which export was asked for.
    formats = [f.strip().lower() for f in (args.export or "").split(",") if f.strip()]

    worksheet = None
    sheet_id = None
    no_comparison = None
    # A spreadsheet is required for the COMPARISON, not for the MARKET. Where
    # the station is, what it sells, at what price and how fresh the data is
    # all come from the journal or CAPI. Only "what do I still need" lives in
    # the sheet -- so an absent spreadsheet should cost the comparison, not the
    # whole command. Writing is different: --update-sheet and --export
    # market-tab have nothing to do without one.
    needs_sheet = args.update_sheet or "market-tab" in formats
    if layout is None:
        # There is no tab to open without a layout to name one, and nothing
        # to compare against without a plugin to read requirements. Said
        # rather than left blank, for the same reason as the branches below:
        # an empty comparison rendered as an answer means "you need nothing
        # here", and the truth is that nobody was asked.
        no_comparison = "no destination plugin is configured"
        sheet_id = None if args.no_sheet else get_sheet_id(args)
    elif not args.no_sheet:
        sheet_id = get_sheet_id(args)
        if not sheet_id:
            if needs_sheet:
                print("Error: no spreadsheet id. Pass --sheet-id, set ED_SHEET_ID,")
                print(f"       or add \"sheet_id\" to {settings.CONFIG_FILE}.")
                print("       (Use --no-sheet to inspect the market without a"
                      " spreadsheet.)")
                return 1
            # Absent configuration, not broken configuration. Carry on and say
            # so; a sheet id that IS set and fails to open still errors below,
            # because hiding that would hide a real misconfiguration.
            no_comparison = "no spreadsheet configured"

        if sheet_id:
            try:
                from .google import GoogleSheetsExporter

                worksheet = GoogleSheetsExporter().worksheet(sheet_id, layout.totals_tab)
            except ImportError:
                print("Error: Google Sheets support not installed.")
                print("Install with: pip install edapitool[gsheets]")
                return 1
            except Exception as exc:
                # A sheet id was configured and could not be opened. That is a
                # broken setup, not an absent one, and it stays an error --
                # degrading here would hide a typo'd id or a revoked credential
                # behind a silently missing comparison.
                print(f"Error opening spreadsheet: {exc}")
                return 1
    else:
        no_comparison = "--no-sheet"

    try:
        # The plugin's words travel sealed: whatever it declared and the
        # person typed, by the plugin's own names, unread here.
        result = service.refresh(
            worksheet=worksheet,
            # A plugin flag that shapes the PLAN (`--no-glyph-markers`) does not
            # veto the write. Vetoing left the location cells stale too --
            # everything travels in one batch -- so the one flag meant for a
            # formula-driven sheet was the one flag that stopped it being
            # told where you are.
            write=args.update_sheet and not args.dry_run,
            options=_plugin_options(args, "market"),
        )
    except WriteRefused as exc:
        print(f"Refused to write: {exc}")
        return 1
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    # Emitting the market as data is deliberately independent of the marker
    # rendering: it runs whether or not the comparison succeeded, and needs no
    # spreadsheet for the csv/json forms.
    exported: list[str] = []
    if formats:
        try:
            exported = _export_market(args, result, formats, sheet_id)
        except Exception as exc:
            print(f"Error exporting market: {exc}")
            return 1

    if args.json:
        payload = _market_result_json(result)
        payload["exported"] = exported
        # Stated rather than implied: a caller parsing this needs to tell
        # "nothing was outstanding here" from "nobody asked the spreadsheet".
        payload["comparison_skipped"] = no_comparison
        print(json.dumps(payload, indent=2))
        # `ok` reports whether a market reading was obtained -- not_docked,
        # stale_market, no_journal and the rest. None of its reasons involve a
        # spreadsheet, so a missing sheet never makes this exit 2, and a
        # commander who is not docked still should.
        return 0 if result.ok else 2

    print(f"Commander : {result.location.commander or 'unknown'}")
    print(f"System    : {result.system or 'unknown'}")
    print(f"Station   : {result.station}")
    if result.market is not None:
        age = result.market.age_seconds
        age_text = f", {age/60:.0f} min old" if age is not None else ""
        print(
            f"Market    : {len(result.market)} commodities "
            f"via {result.market.source}{age_text}"
        )
    print()

    if not result.ok:
        print(f"No comparison: {result.advice()}")
    elif no_comparison:
        # Without a requirements source there is no comparison to render, and
        # an empty one must not be rendered as an answer: format_table([])
        # prints "(nothing outstanding)" and the summary prints zeroes, which
        # together say "you need nothing here" when the truth is that nobody
        # was asked. Same shape as the not-ok branch above, for the same reason.
        print(f"No comparison: {no_comparison}")
    else:
        print(format_table(result.matches))
        print()
        print(f"Summary   : {result.summary.describe()}")

    if result.snapshot and result.snapshot.unparsed_rows:
        print()
        print("Warning: rows whose quantity could not be read (formula recalculating?):")
        for row, name, raw in result.snapshot.unparsed_rows:
            print(f"  row {row}: {name} = {raw!r}")

    unknown = result.summary.unknown
    if unknown:
        print()
        print("Warning: commodity names not recognized (add to name_aliases.json):")
        for match in unknown:
            print(f"  row {match.row}: {match.name!r}")

    if result.plan is not None:
        print()
        if result.written:
            print(f"Wrote {len(result.plan.updates)} ranges to '{layout.totals_tab}'.")
            _report_plan(result.plan, layout)
        elif args.update_sheet:
            print("DRY RUN - would write:")
            for update in result.plan.updates:
                preview = update["values"]
                if len(preview) > 3:
                    preview = f"{len(preview)} rows"
                print(f"  {layout.totals_tab}!{update['range']} = {preview}")
            _report_plan(result.plan, layout)
        else:
            print("(read-only; pass --update-sheet to write markers)")

    return 0 if result.ok else 2


def _condense_cells(cells) -> str:
    """
    "L5", "L6", "L7", "L9"  ->  "L5:L7, L9".

    Twenty single cells printed one per line is a wall nobody reads, and a
    report nobody reads is the same as no report.
    """
    runs: list[list[tuple[str, int]]] = []
    for cell in cells:
        column = cell.rstrip("0123456789")
        row = int(cell[len(column):] or 0)
        if runs and runs[-1][-1][0] == column and runs[-1][-1][1] == row - 1:
            runs[-1].append((column, row))
        else:
            runs.append([(column, row)])
    spans = []
    for run in runs:
        head, tail = run[0], run[-1]
        spans.append(
            f"{head[0]}{head[1]}" if head == tail
            else f"{head[0]}{head[1]}:{tail[0]}{tail[1]}"
        )
    return ", ".join(spans)


def _report_plan(plan, layout) -> None:
    """
    What the plan does to each cell it governs, in the writes ledger's terms.

    The same lines on BOTH paths -- the dry run and the real write -- so the
    one can be read against the other. A silent skip looks exactly like a
    write that worked, which is how #25 went unnoticed for three releases in
    the other direction; so every held cell is named, and so is every cell
    the tool refreshed as its own.

    The marked rows are qualified when some of their cells were held: "Wrote
    0 ranges" beside "marked rows: [17]" read as a contradiction until the
    reader did the arithmetic (found by the v0.8.0 checklist run).
    """
    tab = layout.totals_tab
    column = getattr(layout, "marker_column", None)
    held = set(plan.held or plan.skipped)
    marked = plan.marked_rows
    held_marked = [row for row in marked if column and f"{column}{row}" in held]
    line = f"  marked rows: {marked or '(none)'}"
    if held_marked:
        line += f" -- {len(held_marked)} held, not written: {held_marked}"
    print(line)
    for label, cells in (
        ("ours and refreshed", plan.refreshed),
        ("empty and filled", plan.filled),
        ("forced (--force)", plan.forced),
        ("held and left alone", plan.held or plan.skipped),
    ):
        if cells:
            print(f"  {label} ({len(cells)}): {tab}!{_condense_cells(cells)}")
    if plan.held or plan.skipped:
        print("  pass --force to overwrite the held cells (there is no undo)")


def _site_recency(site):
    """Sort key for 'most recently updated site', with a floor for no stamp."""
    from datetime import datetime, timezone

    return site.timestamp or datetime.min.replace(tzinfo=timezone.utc)


def cmd_construction(args: argparse.Namespace) -> int:
    """
    Report what a colony construction site still needs.

    No spreadsheet, no Frontier login, no cooldown: the whole state comes from
    a `ColonisationConstructionDepot` event in the commander's own journal.
    Following `ship`'s rule rather than the one `market` originally had -- see
    issue #10 -- every output here works with nothing configured at all.
    """
    import json as _json
    from pathlib import Path as _Path

    from .catalog import load_catalog, normalize
    from .construction import locations_from_events, sites_from_events, station_key
    from .export import construction_payload
    from .journal import JournalReader, iter_events

    formats = {f.strip().lower() for f in (args.export or "").split(",") if f.strip()}
    unknown = formats - {"csv", "json"}
    if unknown:
        print(f"Error: unknown export format(s): {', '.join(sorted(unknown))}")
        print("       Valid: csv, json")
        return 1

    reader = JournalReader(_Path(args.journal_dir) if args.journal_dir else None)
    if not reader.exists():
        print("Error: no Elite Dangerous journal directory found.")
        print("       Set ED_JOURNAL_DIR if your Saved Games folder is elsewhere.")
        return 1

    # Scan several files: a site visited earlier in the session leaves no event
    # in the newest log, and reporting "no sites" because of that would be a
    # lie about the world rather than about the scan.
    all_files = reader.journal_files()
    # `--scan-files` with no number arrives as 0 and means "every file". The
    # default is 120 because a shallower scan silently hides sites: on a real
    # 621-file journal, 6 files showed 3 of 6 builds and left a fourth without
    # a name, which reads as a gap in the data rather than a gap in the scan.
    depth = len(all_files) if args.scan_files == 0 else max(1, args.scan_files)
    events = []
    for path in all_files[-depth:]:
        events.extend(iter_events(path))
    sites = sites_from_events(events, load_catalog())
    places = locations_from_events(events, market_ids=sites.keys())

    if not sites:
        print("No construction sites found in the journal.")
        print("Dock at one to record what it needs; nothing else is required.")
        return 0

    if args.list:
        scanned = (f"all {depth}" if args.scan_files == 0 else f"the last {depth}")
        rows = sorted(sites.items(), key=lambda kv: -kv[1].progress)
        statuses = {m: s.status(stale_after_days=args.stale_after) for m, s in rows}
        hidden = [m for m, st in statuses.items() if st != "active"]
        if not args.all:
            rows = [(m, s) for m, s in rows if statuses[m] == "active"]

        if args.all:
            print(f"{len(rows)} construction site(s) in {scanned} journal files:")
        else:
            print(f"{len(rows)} active of {len(sites)} construction site(s) "
                  f"in {scanned} journal files:")
        print()

        unnamed = 0
        for market_id, site in rows:
            where = places.get(market_id)
            status = statuses[market_id]
            age = site.age_days()
            state = f"{site.progress*100:.1f}%" if status == "active" else status
            name = where.short_station if where else "(name unknown)"
            system = where.system if where else ""
            seen = f"{age}d ago" if age is not None else ""
            # Former names go last and in parentheses: a rename mid-build is
            # real, and a reader whose notes say the old name needs to see the
            # connection rather than conclude the site vanished.
            former = ""
            if where and where.former_names:
                former = "  (was " + ", ".join(where.former_names) + ")"
            print(f"  {state:>8}  {name:<30} {system:<26} {seen:>9}  {market_id}{former}")
            unnamed += 0 if where else 1
        print()
        if hidden and not args.all:
            kinds = {}
            for market_id in hidden:
                kinds[statuses[market_id]] = kinds.get(statuses[market_id], 0) + 1
            summary = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
            print(f"{len(hidden)} site(s) not shown ({summary}). Use --all to include them.")
            if "stale" in kinds:
                # Say what "stale" actually means, because the game never marks
                # a lapsed build failed -- this is our inference, not its verdict.
                print(f"A site is called stale after {args.stale_after} days without the game")
                print("mentioning it. Elite Dangerous does not report an expired build as")
                print("failed, so time is the only signal there is.")
            print()
        # Said ONCE, however many sites lack a name. The advice does not get
        # truer by repetition, and a hint under every row buries the listing
        # it is meant to annotate.
        if unnamed:
            print(f"{unnamed} site(s) have no name: the journal records what they need but")
            print("no dock there, so only the MarketID identifies them. Dock once to fix,")
            print("or widen the scan with --scan-files and no number.")
            print()
        print("Select one with --site NAME (add --system when two share a name), or --site MARKETID.")
        return 0

    # Which site? An explicit --site wins; otherwise wherever the commander is
    # standing; otherwise the most recently updated one.
    chosen = None
    if args.site:
        wanted = str(args.site).strip()
        if wanted.isdigit() and int(wanted) in sites:
            chosen = sites[int(wanted)]
        else:
            key = station_key(wanted)
            system_key = normalize(args.system) if args.system else ""
            matches = []
            for market_id, site in sites.items():
                where = places.get(market_id)
                if not (key and where and where.answers_to(wanted)):
                    continue
                if system_key and normalize(where.system) != system_key:
                    continue
                matches.append((market_id, site, where))
            if len(matches) > 1:
                # Two builds can share a name, and picking the first silently
                # would report one site's shortfall as another's.
                print(f"Error: {args.site!r} matches {len(matches)} sites. Add --system:")
                for market_id, _, where in matches:
                    print(f"       --system {where.system!r}   ({market_id})")
                return 1
            if matches:
                chosen = matches[0][1]
        if chosen is None:
            print(f"Error: no construction site matching {args.site!r}.")
            for market_id in sites:
                where = places.get(market_id)
                print(f"       {market_id}  {where.describe if where else '(name unknown -- dock there once)'}")
            return 1
    else:
        here = reader.read_state(scan_files=min(depth, 6))
        chosen = sites.get(here.market_id) if here.market_id else None
        if chosen is None:
            chosen = max(sites.values(), key=_site_recency)

    payload = construction_payload(chosen)

    if args.publish_to:
        if not args.region:
            print("Error: --publish-to needs --region, e.g. --region R1:AD60.")
            print("       The region is declared rather than inferred because")
            print("       publishing clears it: without knowing where the block")
            print("       ends, a site that shrinks would leave the tail of its")
            print("       last report sitting there looking current.")
            return 1
        sheet_id = get_sheet_id(args)
        if not sheet_id:
            print("Error: --publish-to needs a spreadsheet. Pass --sheet-id,")
            print('       set ED_SHEET_ID, or add "sheet_id" to '
                  f"{settings.CONFIG_FILE}.")
            return 1

        from .export import (CONSTRUCTION_REGION_TABLE_ROW,
                             construction_region_rows)
        from .google import GoogleSheetsExporter
        from .sheets import Destination, WriteGuard, WriteRefused

        try:
            destination = Destination.region(args.publish_to, args.region)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1

        grid = construction_region_rows(chosen, places.get(chosen.market_id))
        # The person naming a region on the command line IS the authorization;
        # the guard still runs, so a grid that outgrew its reserve is refused
        # rather than quietly spilling into the columns beside it.
        guard = WriteGuard.build({destination.tab: [args.region]})
        try:
            GoogleSheetsExporter(region_guard=guard).export_grid(
                grid, sheet_id=sheet_id, tab_name=destination,
            )
        except WriteRefused as exc:
            print(f"Error: {exc}")
            return 1
        leading = CONSTRUCTION_REGION_TABLE_ROW - 1
        print(f"Published {len(grid) - leading} commodities to "
              f"{destination.describe()}")
        return 0

    if args.json:
        if args.all_sites:
            payload = {"sites": [construction_payload(s) for s in sites.values()]}
        print(_json.dumps(payload, indent=2))
        return 0

    if formats:
        from .export import ConstructionExporter

        out_dir = _Path(args.output) if args.output else None
        exporter = ConstructionExporter(out_dir)
        for fmt in sorted(formats):
            if fmt == "csv":
                print(f"Exported csv: {exporter.export_csv(chosen)}")
            else:
                print(f"Exported json: {exporter.export_json(chosen)}")

    site = chosen
    state = "complete" if site.complete else ("FAILED" if site.failed else "in progress")
    where = places.get(site.market_id)
    if where and where.short_station:
        print(f"Site      : {where.short_station} ({state})")
        print(f"System    : {where.system or 'unknown'}")
    else:
        # Never docked there in the scanned window, so the journal has the
        # contents but not the name. Say which, rather than printing a bare id.
        print(f"Site      : {site.market_id} ({state})")
        print("System    : unknown -- dock at the site once to record its name")
    if site.timestamp:
        print(f"Updated   : {site.timestamp.isoformat()}")
    print(f"Progress  : {site.progress * 100:.1f}%  "
          f"({site.total_provided:,} of {site.total_required:,} t)")
    print()
    outstanding = site.outstanding
    if not outstanding:
        print("Nothing outstanding -- every commodity is delivered.")
        return 0

    width = max(len(r.name) for r in outstanding)
    print(f"  {'commodity':<{width}}  {'still need':>10}  {'delivered':>10}  {'pays':>8}")
    print("  " + "-" * (width + 34))
    for r in outstanding:
        print(f"  {r.name:<{width}}  {r.remaining:>10,}  {r.provided:>10,}  {r.payment:>8,}")
    print()
    print(f"  {len(outstanding)} commodities outstanding, "
          f"{site.total_remaining:,} t to deliver")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Keep MarketData and ShipCargo current while the game runs."""
    from . import daemon as daemon_mod

    # Two plugins may serve one workbook from v0.8.0: the one that publishes
    # the roll-up tab (the destination, for the location cells and the
    # markers) and the one that binds construction regions. Either may be
    # absent; both absent is the "no destination" refusal.
    plugins = getattr(args, "_plugins", None)
    destination, problem = _resolve_destination(plugins)
    binder = plugins.offering("construction_regions") if plugins is not None else None
    if destination is None and binder is None:
        print(problem)
        return 1

    sheet_id = get_sheet_id(args)
    if not sheet_id:
        print("Error: serve needs a spreadsheet id. Pass --sheet-id,")
        print(f"       set ED_SHEET_ID, or add \"sheet_id\" to {settings.CONFIG_FILE}.")
        return 1

    journal_dir = Path(args.journal_dir) if args.journal_dir else None

    # The plugin's serve words, by its own dest names: which regions to
    # keep current, whether to paint the location cells. Core spells the
    # two it must route (a region binder, a daemon parameter) and nothing
    # else; a plugin without them simply has none.
    serve_options = _plugin_options(args, "serve")
    region_override = serve_options.get("construction_region")
    write_location = bool(serve_options.get("write_location", False))

    # Where the construction blocks go is a binding the plugin reads from its
    # own config block; core carries the block unread and asks. A plugin
    # with no such bindings publishes no regions.
    bind = getattr(binder.module, "construction_regions", None) if binder is not None else None
    block = binder.target.config if binder is not None and binder.target is not None else {}
    if not callable(bind) and region_override:
        # A plugin that takes no bindings publishes no regions, which is
        # right -- but a flag that cannot take effect is not silently
        # dropped. Both of this surface's rules would break at once: the
        # flag is supposed to win outright, and a setting that cannot be
        # honoured is supposed to say so rather than leave the person with
        # silence indistinguishable from having typed nothing.
        who = destination.name if destination is not None else "loaded"
        print(f"Error: the {who!r} plugin takes no construction regions, "
              "so --construction-region cannot be honoured.")
        return 1
    try:
        regions = bind(block, region_override) if callable(bind) else []
    except ValueError as exc:
        print(f"Error: {exc}")
        # Only say where it came from when it came from the config file; a
        # bad value typed on the command line is already in front of you.
        # The guard is an `if` rather than a ternary inside the print,
        # because that form still printed an empty line for the flag case.
        if not region_override:
            print(f"       (from {settings.CONFIG_FILE})")
        return 1

    from .loader import GSHEET, build_enforcer

    if destination is not None:
        layout, problem = _plugin_layout(destination, **_layout_overrides(args, "serve"))
        if layout is None:
            print(problem)
            return 1
        guard = build_enforcer(destination.kind, layout.writes())
    else:
        layout = _NoLayout()
        guard = build_enforcer(GSHEET, layout.writes())
    try:
        worker = daemon_mod.build(
            sheet_id=sheet_id,
            journal_dir=journal_dir,
            layout=layout,
            guard=guard,
            plugin=destination.module if destination is not None else None,
            # Named after whichever plugin is doing the serving: the roll-up
            # tab's target when one is loaded, else the bindings' own.
            target=_target_name(destination if destination is not None else binder),
            ship_tab=args.ship_tab,
            write_location=write_location,
            construction_regions=regions,
            interval=args.interval,
            debounce=args.debounce,
        )
    except ImportError:
        print("Error: Google Sheets support not installed.")
        print("Install with: pip install edapitool[gsheets]")
        return 1
    except Exception as exc:
        # build() opens the requirements tab, which raises ValueError for a name
        # that is not there and gspread's own errors for a bad id or revoked
        # credential -- none of them ImportError. `market` already reports these
        # in one friendly line; without this, `serve` differed only by showing
        # the user a traceback.
        print(f"Error opening spreadsheet: {exc}")
        return 1

    if args.once:
        targets = worker.publishers()
        print(f"Publishing {len(targets)} target(s) once.")
        for target in targets:
            try:
                print(daemon_mod.PublishResult.of(target.publish()).message)
            except Exception as exc:
                print(f"  ! {target.name} failed: {exc}")
                return 1
        return 0

    # Prime before the loop so the backlog of a session already in progress
    # does not fire a publish for every dock that has already happened.
    state = worker.watcher.prime()
    where = state.station_display or state.system or "unknown"
    print(f"Watching the journal from {where}.")
    print(worker.describe_targets())
    for gap in worker.describe_gaps():
        print(f"  {gap}")
    if not regions:
        print("  NOT published: any construction region -- declare one with "
              "--construction-region 'Tab!R1:AC60=Site Name'")
    print(f"Poll {args.interval}s, debounce {args.debounce}s. Ctrl+C to stop.")
    print()

    # Publish once before watching. Priming establishes position WITHOUT
    # replaying the backlog, which is right -- but it means the tabs keep
    # whatever they held when the last run stopped, and nothing corrects them
    # until the game happens to emit an event. A restart is exactly when the
    # sheet is most likely to be wrong, and "correct only once something
    # happens" is indistinguishable from "correct" to anyone reading it.
    print("Catching up:")
    worker.catch_up()
    print()

    try:
        worker.run()
    except KeyboardInterrupt:
        stats = worker.stats
        print()
        # Every target, not just the two that predate regions -- a summary
        # that names a subset is the same failure as a banner that does.
        done = ", ".join(f"{n} x{c}" for n, c in stats.by_target.items())             or "nothing"
        print(
            f"Stopped. {stats.polls} polls, {stats.events} events, "
            f"{stats.errors} errors. Published: {done}."
        )
    return 0


def _export_market(args, result, formats: list[str], sheet_id) -> list[str]:
    """
    Emit the station market as data. Returns human-readable descriptions.

    csv/json need no spreadsheet and no Google credentials -- that is the point
    of them. market-tab writes a generated tab the spreadsheet can VLOOKUP.
    """
    from .export import MarketExporter

    done: list[str] = []
    output_dir = Path(args.output) if args.output else None

    if result.market is None and ("csv" in formats or "json" in formats):
        print("No current market to export; skipping csv/json.")

    if result.market is not None:
        exporter = MarketExporter(output_dir)
        if "csv" in formats:
            done.append(f"csv: {exporter.export_csv(result.market)}")
        if "json" in formats:
            done.append(f"json: {exporter.export_json(result.market)}")

    if "market-tab" in formats:
        if not sheet_id:
            raise ValueError("--export market-tab needs a spreadsheet id")
        from .google import GoogleSheetsExporter
        from .service import market_data_rows

        # Writes the deliberately-empty grid when there is no current market,
        # so the tab is actively cleared rather than left holding the previous
        # station's prices under a fresh-looking header.
        rows = GoogleSheetsExporter().export_grid(
            market_data_rows(result), sheet_id=sheet_id
        )
        done.append(f"market-tab: {rows} commodity rows -> MarketData")

    for line in done:
        print(f"Exported {line}")
    return done


def _market_result_json(result) -> dict:
    """Machine-readable form of a refresh, for scripts and the HTTP API."""
    return {
        "ok": result.ok,
        "reason": result.reason,
        "advice": result.advice(),
        "system": result.system,
        "station": result.station,
        "docked": result.location.docked,
        "market_id": result.location.market_id,
        "market": None
        if result.market is None
        else {
            "station": result.market.station,
            "source": result.market.source,
            "items": len(result.market),
            "timestamp": result.market.timestamp.isoformat()
            if result.market.timestamp
            else None,
            "age_seconds": result.market.age_seconds,
        },
        "matches": [
            {
                "row": m.row,
                "origin": m.origin,
                "commodity": m.name,
                "need": m.need,
                "state": m.state.value,
                "stock": m.stock,
                "unit_price": m.unit_price,
                "buyable_qty": m.buyable_qty,
                "estimated_cost": m.estimated_cost,
                "mark": m.should_mark,
            }
            for m in sorted(result.matches, key=lambda x: x.row)
        ],
        "marked_rows": result.plan.marked_rows if result.plan else [],
        "written": result.written,
        "summary": result.summary.describe() if result.ok else result.advice(),
    }


def cmd_ship(args: argparse.Namespace) -> int:
    """
    Report the current ship's cargo hold.

    A spreadsheet is required for exactly one thing here -- writing the
    generated ShipCargo tab -- and for nothing else. Reading the hold, printing
    it, and writing CSV or JSON all work with no Google credentials configured
    and no sheet id anywhere. That asymmetry is deliberate: see issue #10,
    where the market verb got this wrong and demanded a spreadsheet before it
    would emit JSON.
    """
    import json as _json
    from pathlib import Path as _Path

    from .catalog import load_catalog
    from .export import ShipCargoExporter, ship_payload
    from .journal import JournalReader
    from . import ship as ship_mod

    formats = {f.strip().lower() for f in (args.export or "").split(",") if f.strip()}
    unknown = formats - {"csv", "json", "ship-tab"}
    if unknown:
        print(f"Error: unknown export format(s): {', '.join(sorted(unknown))}")
        print("       Valid: csv, json, ship-tab")
        return 1

    reader = JournalReader(_Path(args.journal_dir) if args.journal_dir else None)
    if not reader.exists():
        print("Error: no Elite Dangerous journal directory found.")
        print("       Set ED_JOURNAL_DIR if your Saved Games folder is elsewhere.")
        return 1

    raw = reader.read_cargo_json()
    if raw is None:
        print("No Cargo.json found. The game writes it when your hold changes;")
        print("it appears once you have loaded or unloaded something.")
        return 1

    cargo = ship_mod.from_journal(raw, load_catalog())

    if not cargo.is_ship:
        # The SRV writes to the same file. Reporting its hold as the ship's
        # would feed a real number about the wrong vessel into column M.
        print(f"Cargo.json currently describes the {cargo.vessel or 'unknown vessel'},")
        print("not your ship. Board your ship so the game rewrites it.")
        return 1

    if args.json:
        print(_json.dumps(ship_payload(cargo), indent=2, ensure_ascii=False))
    else:
        stamp = cargo.timestamp.isoformat() if cargo.timestamp else "unknown"
        print(f"Ship cargo as of {stamp}")
        print(f"  {cargo.total:,} t across {len(cargo)} commodit"
              f"{'y' if len(cargo) == 1 else 'ies'}")
        if cargo.items:
            width = max(len(i.name) for i in cargo.items)
            print()
            for item in sorted(cargo.items, key=lambda i: i.key):
                stolen = f"   ({item.stolen} stolen)" if item.stolen else ""
                print(f"  {item.name:<{width}}  {item.count:>7,}{stolen}")
        if cargo.total != cargo.count:
            print()
            print(f"  Note: the file reports {cargo.count:,} t total but itemises "
                  f"{cargo.total:,} t.")

    written = []
    if formats & {"csv", "json"}:
        exporter = ShipCargoExporter(_Path(args.output) if args.output else None)
        if "csv" in formats:
            written.append(f"csv:  {exporter.export_csv(cargo)}")
        if "json" in formats:
            written.append(f"json: {exporter.export_json(cargo)}")

    if "ship-tab" in formats:
        sheet_id = get_sheet_id(args)
        if not sheet_id:
            print()
            print("Error: --export ship-tab needs a spreadsheet id. Pass --sheet-id,")
            print(f"       set ED_SHEET_ID, or add \"sheet_id\" to {settings.CONFIG_FILE}.")
            return 1
        grid = ship_mod.sheet_grid(cargo)
        if args.dry_run:
            print()
            print(f"Would write {len(grid)} rows to '{args.ship_tab}':")
            for row in grid[:6]:
                print(f"    {row}")
            if len(grid) > 6:
                print(f"    ... {len(grid) - 6} more")
        else:
            try:
                from .google import GoogleSheetsExporter
            except ImportError:
                print("Error: Google Sheets support not installed.")
                print("Install with: pip install edapitool[gsheets]")
                return 1
            try:
                GoogleSheetsExporter().export_grid(grid, sheet_id, args.ship_tab)
            except Exception as exc:
                print(f"Error writing '{args.ship_tab}': {exc}")
                return 1
            written.append(f"tab:  {args.ship_tab} ({len(grid) - 3} commodities)")

    if written:
        print()
        for line in written:
            print(f"  {line}")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    """Handle version command."""
    print(f"ED API Tool {get_version()}")
    return 0


class _Defaults:
    """
    Argparse defaults read from a destination's layout, tolerant of gaps.

    Any attribute the layout lacks -- or every attribute, when no destination
    is loaded -- reads as ``None``, so a flag becomes "no default" and its
    help text says so. The tool still runs: reading the journal, exporting
    CSV and JSON, and printing its own version need no spreadsheet, and #18's
    sixth criterion says that with none configured the tool publishes open
    formats only.

    Tolerance of a PRESENT layout is the half that a second plugin needs. The
    flags below name this workbook's conventions -- a roll-up tab, a
    requirement header -- and a plugin for a different sheet has no reason to
    know those words. The first plugin planted by the loader's probe crashed
    ``--version`` here, because the parser read them as bare attributes.

    Deliberately not a dict or a ``SimpleNamespace``: an unknown attribute
    returning None silently is the right behaviour HERE -- a flag nobody can
    default is simply undefaulted -- and it would be the wrong behaviour
    almost anywhere else, so it gets a named type that says which one it is.
    """

    def __init__(self, layout=None):
        self._layout = layout

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._layout, name, None)


def cmd_plugins(args: argparse.Namespace) -> int:
    """
    What is installed, what configuration turns on, and what went wrong.

    Split in two along consent, which is what the two-phase discovery is for.
    ``list`` imports only what configuration already enables -- you asked for
    those by writing them into ``targets``, and every other command imports
    them anyway. Everything else is reported from the scan alone, because
    showing what an unloaded plugin can do would mean running code you have
    not asked to run. ``describe`` imports the one plugin you name, and
    naming it is the asking.

    Since v0.8.0 the verb is also the door to a plugin's own commands (#33):
    ``plugins <name>`` lists what that plugin offers and ``plugins <name>
    <command> ...`` runs one, the tail handed over unread. The three words
    the verb keeps for itself -- ``list``, ``describe``, ``help`` -- are
    refused as plugin names at load (``loader.RESERVED``), so a plugin can
    never be shadowed by them.
    """
    from . import settings
    from .loader import (BUILT, RESERVED, SEVERITY_WARN, SHIPPED_DIR, enabled_from,
                         kinds_from, load, scan, targets_by_plugin)

    name = getattr(args, "name", None)
    tail = list(getattr(args, "tail", None) or [])
    # The verb's own words are matched in any case, as the loader refuses
    # them in any case: `plugins LIST` is the listing, never a plugin.
    if name is not None and name.lower() in RESERVED:
        name = name.lower()
        if name not in BUILT:
            print(f"Error: `plugins {name}` is reserved for a later version and does "
                  f"nothing yet.")
            print(f"       Available now: {', '.join(BUILT)}, or a plugin's name.")
            return 2

    if name == "help":
        parser = getattr(args, "_plugins_parser", None)
        if parser is not None:
            parser.print_help()
        return 0

    user_dir = settings.get_plugin_dir()
    found = scan(SHIPPED_DIR, user_dir)
    if not found:
        print("No plugins found.")
        print(f"  shipped: {SHIPPED_DIR}")
        print(f"  yours:   {user_dir}")
        return 0

    # Read before the describe branch, because `describe` needs them too: a
    # plugin is described as its target configures it, not as it ships.
    try:
        targets = settings.get_targets()
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    if name == "describe":
        if not tail:
            print("Error: `plugins describe` needs a plugin name.")
            print(f"       Found: {', '.join(sorted(f.name for f in found))}")
            return 2
        return _describe_plugin(tail[0], found, targets)

    if name is not None and name not in RESERVED:
        return _run_plugin_command(name, tail, found, targets)

    enabled = enabled_from(targets, found)
    result = load(found, enabled, kinds_from(targets), severity=SEVERITY_WARN,
                  targets=targets_by_plugin(targets))
    by_plugin = targets_by_plugin(targets)

    # A blank line BETWEEN sections, never before the first one. With nothing
    # loaded -- now the ordinary state of a fresh install rather than a
    # broken one -- the listing used to open on a stray empty line.
    written = False

    def section(heading: str) -> None:
        nonlocal written
        print(f"\n{heading}" if written else heading)
        written = True

    if result.loaded:
        section(f"Loaded {len(result.loaded)}:")
        for entry in result.loaded:
            target = by_plugin.get(entry.name)
            serves = f"serves {target.name!r}" if target is not None else "no target configured"
            print(f"  {entry.name:<18} {entry.found.origin:<8} {entry.kind or '(no kind)':<8} {serves}")
            if entry.found.shadows is not None:
                print(f"  {'':<18} shadows the shipped plugin at {entry.found.shadows}")
            for complaint in entry.complaints:
                where = target.name if target is not None else entry.name
                print(f"  {'':<18} CONFIG {where}: {complaint}")

    if result.broken:
        section(f"NOT loaded {len(result.broken)}:")
        for entry in result.broken:
            print(f"  {entry.name:<18} {entry.reason}")
            print(f"  {'':<18} the tool is unaffected; other plugins loaded normally")

    if result.available:
        section(f"Available but not loaded {len(result.available)}:")
        for entry in result.available:
            print(f"  {entry.name:<18} {entry.origin:<8} {entry.location}")
            if entry.reserved:
                print(f"  {'':<18} RESERVED name -- `plugins {entry.name}` is the verb's own; "
                      "rename the directory to enable it")
            else:
                print(f"  {'':<18} never configured -- add a \"targets\" entry naming it")
        print(f"  {'':<18} (see: edapitool plugins describe <name>)")

    for conflict in result.conflicts:
        print(f"\nCONFLICT  {conflict.describe()}")

    return 0


def _described_declaration(entry) -> dict:
    """
    What a loaded plugin writes, as its target configures it. Empty if nothing.

    Two sources, and the more specific one wins when it says anything. A
    plugin's ``writes()`` is what it declares with no target at all; a layout
    built from its target knows where that target actually is. For a sheet
    plugin the two agree, because its tabs and ranges are its own. For a file
    plugin they cannot: it declares no path until a target names one, so
    describing it from ``writes()`` alone reported "writes nothing" about a
    plugin that was about to append to a file.

    The target-derived declaration is preferred only when it declares
    something. A plugin whose layout declares less than its module does is
    not thereby declaring less -- it simply keeps the answer in the other
    place, and the honest report is the fuller one.

    Buckets that exist but are empty do not count: ``{"__file__": []}`` is
    how a file plugin says "nowhere yet", and reads as nothing declared.
    """
    def declared(mapping) -> dict:
        return {k: list(v) for k, v in (mapping or {}).items() if v}

    shipped = declared(entry.declaration)
    if entry.target is None:
        return shipped
    try:
        configured = declared(entry.module.layout(**_target_overrides(entry)).writes())
    except Exception:  # noqa: BLE001 -- a layout that raises is reported elsewhere
        return shipped
    return configured or shipped


def _describe_plugin(name: str, found, targets=None) -> int:
    """
    One plugin's own account of itself. Imports it -- that is what naming it means.

    Described AS CONFIGURED, not as shipped: the target this plugin serves is
    handed over, so its kind and its write bound are the ones that will
    actually apply. A file plugin declares no path until a target gives it
    one, and describing it without that target reported "writes nothing"
    about a plugin that was about to append to a file.
    """
    from .loader import SEVERITY_IGNORE, kinds_from, load, targets_by_plugin

    if name not in {f.name for f in found}:
        print(f"Error: no plugin named {name!r}.")
        print(f"       Found: {', '.join(sorted(f.name for f in found))}")
        return 1

    targets = targets or {}
    result = load(found, [name], kinds_from(targets), severity=SEVERITY_IGNORE,
                  targets=targets_by_plugin(targets))
    if result.broken:
        entry = result.broken[0]
        print(f"{name} did not load: {entry.reason}")
        return 1

    entry = result.first()
    module = entry.module
    print(f"{entry.name}")
    print(f"  location   {entry.found.location}")
    print(f"  origin     {entry.found.origin}")
    print(f"  kind       {entry.kind or '(declares none)'}")

    declaration = _described_declaration(entry)
    if declaration:
        print("  writes")
        for where, items in declaration.items():
            for item in items:
                print(f"    {where}: {item}")
    else:
        print("  writes     nothing as shipped")

    for label, asked in (("supplies", "supplies"), ("subscribes", "subscribes")):
        ask = getattr(module, asked, None)
        if not callable(ask):
            print(f"  {label:<10} (none)")
            continue
        try:
            offered = ask()
        except Exception as exc:  # noqa: BLE001 -- the plugin's defect, reported
            print(f"  {label:<10} could not be asked: {type(exc).__name__}: {exc}")
            continue
        names = sorted(offered) if isinstance(offered, dict) else [
            getattr(s, "name", str(s)) for s in offered]
        print(f"  {label:<10} {', '.join(names) or '(none)'}")

    starter = getattr(module, "default_config", None)
    if callable(starter):
        import json as _json
        try:
            block = starter()
        except Exception as exc:  # noqa: BLE001
            print(f"  config     could not be asked: {type(exc).__name__}: {exc}")
        else:
            print("  config     a starter block for this plugin's \"config\":")
            for line in _json.dumps(block, indent=2).splitlines():
                print(f"    {line}")
    return 0


def _plugin_commands(module) -> dict:
    """
    The ``Command`` records a plugin offers, by name, or none.

    Read from ``commands()`` when the plugin defines it. Anything that is not
    a mapping of ``Command`` records is the plugin's defect and is reported
    as one by the caller, never guessed at.
    """
    from .registry import Command

    ask = getattr(module, "commands", None)
    if not callable(ask):
        return {}
    offered = ask()
    if not isinstance(offered, Mapping):
        raise TypeError(f"commands() returned {type(offered).__name__}, not a mapping")
    out = {}
    for key, command in offered.items():
        if not isinstance(command, Command):
            raise TypeError(f"commands()[{key!r}] is {type(command).__name__}, not a Command")
        out[str(key)] = command
    return out


def _run_plugin_command(name: str, tail: list[str], found, targets=None) -> int:
    """
    ``plugins <name> [command ...]``: import that one plugin and hand it its tail.

    The named plugin is imported here even if nothing enables it -- naming
    it is the consent -- and no other: the plugins the configuration enables
    were already imported by discovery, as for every command, and an
    unenabled plugin nobody named never is. It is handed the target that
    enables it, or None when nothing does. With no
    command, or ``--help`` in its place, the plugin's commands are listed
    with which of them run without a target. A command that needs a target
    on a plugin no target names is refused by name, so that "it did nothing"
    never reads as "it worked".
    """
    from .loader import SEVERITY_IGNORE, kinds_from, load, targets_by_plugin

    if name not in {f.name for f in found}:
        print(f"Error: no plugin named {name!r}.")
        print(f"       Found: {', '.join(sorted(f.name for f in found))}")
        return 1

    targets = targets or {}
    result = load(found, [name], kinds_from(targets), severity=SEVERITY_IGNORE,
                  targets=targets_by_plugin(targets))
    if result.broken:
        entry = result.broken[0]
        print(f"{name} did not load: {entry.reason}")
        print("  the tool is unaffected; fix the plugin, or remove its directory")
        return 1

    entry = result.first()
    try:
        commands = _plugin_commands(entry.module)
    except Exception as exc:  # noqa: BLE001 -- the plugin's defect, reported
        print(f"{name}: its commands could not be read: {type(exc).__name__}: {exc}")
        return 1

    enabled = entry.target is not None
    if not tail or tail[0] in ("--help", "-h", "help"):
        if not commands:
            print(f"{name} declares no commands.")
            return 0
        where = (f"enabled by target {entry.target.name!r}" if enabled
                 else "not enabled by any target: only commands marked "
                      "'runs without a target' will run")
        print(f"{name} -- {where}")
        width = max(len(key) for key in commands)
        for key, command in commands.items():
            unconfigured = "  (runs without a target)" if command.safe_unconfigured else ""
            print(f"  {key:<{width}}  {command.help}{unconfigured}")
        print(f"  usage: edapitool plugins {name} <command> [its own arguments]")
        return 0

    word, rest = tail[0], tail[1:]
    command = commands.get(word)
    if command is None:
        print(f"Error: {name} has no command {word!r}.")
        if commands:
            print(f"       It offers: {', '.join(commands)}")
        else:
            print("       It declares no commands.")
        return 1

    if not enabled and not command.safe_unconfigured:
        print(f"Error: `plugins {name} {word}` needs the {name} plugin enabled, and no "
              f"target in your configuration names it.")
        print(f"       Add a \"targets\" entry with \"plugin\": \"{name}\" "
              f"(see: edapitool plugins describe {name}).")
        return 1

    try:
        code = command.handler(rest, entry.target)
    except SystemExit as exc:  # the plugin's own parser said its piece
        return int(exc.code or 0) if isinstance(exc.code, int) or exc.code is None else 1
    except Exception as exc:  # noqa: BLE001 -- the plugin's defect, reported
        print(f"Error: `plugins {name} {word}` failed: {type(exc).__name__}: {exc}")
        return 1
    return 0 if code is None else int(code)


def _discover_once():
    """
    The loader's answer for this run, or ``(None, why)``.

    Called once, before the parser is built, so that the flags a loaded
    plugin declares can be registered; the result rides on the parsed
    arguments (``args._plugins``) so no command discovers a second time.
    """
    from .loader import discover

    try:
        return discover(), None
    except ValueError as exc:
        return None, f"Error: {exc}"


def _resolve_destination(plugins=None):
    """
    The loaded destination a command talks to, or ``(None, why)``.

    Selection is the loader's: it scans the shipped and user plugin
    directories and loads what the configuration's ``targets`` enable. This
    function only asks. A configuration that names nothing loadable is
    reported with the loader's own listing, so the person sees which plugin
    was found, which was enabled, and which broke -- not just "no plugin".
    """
    if plugins is None:
        plugins, problem = _discover_once()
        if plugins is None:
            return None, problem
    # The destination is the plugin that PUBLISHES. Since v0.8.0 the
    # construction bindings are a plugin of their own that never subscribes,
    # so "the first loaded plugin" is no longer the same question.
    destination = plugins.publisher()
    if destination is None:
        lines = ["Error: no destination plugin is loaded."]
        lines += [f"  {line}" for line in plugins.describe()]
        return None, "\n".join(lines)
    return destination, None


def _destination_defaults(plugins=None):
    """
    The configured destination's layout, or a stand-in with no values.

    Resolved at call time and tolerant of absence, for the same reason the
    service's own resolvers are: removing the destination package must leave a
    working generic tool, and that has to include the argument parser. Every
    failure -- no plugin found, a plugin that does not import, a malformed
    ``targets`` entry -- means "no defaults" here, and the command that
    actually needs the destination is the one that reports why.
    """
    try:
        if plugins is None:
            plugins, _ = _discover_once()
        destination = plugins.publisher() if plugins is not None else None
        if destination is None:
            return _Defaults()
        # Inside the guard, not after it: a plugin can import cleanly and
        # still raise when asked for its layout, and the tester sweep for
        # v0.7.2 found that case taking `--version` down with a traceback.
        return _Defaults(destination.module.layout())
    except Exception:  # noqa: BLE001 -- the command reports it; --help must not
        return _Defaults()


def _target_name(destination) -> str:
    """The configured target's name, or "" when configuration named none."""
    target = getattr(destination, "target", None)
    return target.name if target is not None else ""


def _plugin_layout(destination, **overrides):
    """
    The destination's layout with the command line's overrides, or ``(None, why)``.

    A plugin that imports and then fails to build its layout is the plugin's
    defect, and the command says so by name rather than handing the person
    a traceback -- the same courtesy the loader extends to a failed import.

    The overrides are named for the flags that carry them, and those flag
    names are one destination's vocabulary: ``--need-sign`` means something
    to a settlement tab and nothing at all to a file. A plugin that cannot
    take one is not broken, and the person who typed it is not wrong either
    -- they are talking to a plugin that does not speak that word, and that
    is what the message says. Silently dropping the flag would be the worse
    answer: a setting that cannot take effect says so.

    Beneath the command line sit the target's own keys. A target carries
    what its KIND needs -- ``id`` for a sheet, ``path`` for a file -- and
    some of those are the plugin's business while others are the adapter's.
    Core cannot tell which is which and must not learn: it asks the layout
    which names it accepts and hands over exactly that intersection. So a
    file plugin is told where its file is, a sheet's ``id`` stays with the
    exporter, and neither fact is written down in this module.
    """
    supplied = {k: v for k, v in overrides.items() if v is not None}
    overrides = {**_target_overrides(destination), **supplied}
    try:
        return destination.module.layout(**overrides), None
    except TypeError as exc:
        unknown = _unknown_override(exc, overrides)
        if unknown is not None:
            flag = "--" + unknown.replace("_", "-")
            return None, (f"Error: the {destination.name!r} plugin does not understand "
                          f"{flag}.\n       Its layout takes: "
                          f"{_accepted_overrides(destination) or '(no overrides)'}")
        return None, (f"Error: plugin {destination.name!r} could not build its "
                      f"layout: {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 -- reporting, not handling
        return None, (f"Error: plugin {destination.name!r} could not build its "
                      f"layout: {type(exc).__name__}: {exc}")


def _unknown_override(exc: TypeError, overrides: dict) -> Optional[str]:
    """Which override a layout rejected, when that is what the TypeError says."""
    message = str(exc)
    if "unexpected keyword argument" not in message:
        return None
    return next((name for name in overrides if f"'{name}'" in message), None)


def _layout_fields(destination) -> list[str]:
    """
    The names a plugin's layout accepts, asked of the layout itself.

    Core has no list of these anywhere, and that is the point: it learns
    what a plugin's layout takes by building a default one and looking,
    so a new plugin's vocabulary needs no entry here.
    """
    import inspect

    try:
        built = destination.module.layout()
    except Exception:  # noqa: BLE001 -- the caller is already reporting a failure
        return []
    if hasattr(built, "__dataclass_fields__"):
        return [f.name for f in built.__dataclass_fields__.values()]
    try:
        return list(inspect.signature(type(built)).parameters)
    except (TypeError, ValueError):
        return []


def _target_overrides(destination) -> dict:
    """
    The configured target's keys that this plugin's layout can take.

    Both halves of the entry are offered: the plugin's own ``config`` block
    and the kind's ``params``, in that order, so a key that appears in both
    is taken from the more specific one. Core reads neither -- it asks the
    layout which NAMES it accepts and hands over that intersection, so a
    plugin that would rather read its block itself simply does not name
    those keys on its layout, and nothing here changes.
    """
    target = getattr(destination, "target", None)
    if target is None:
        return {}
    offered = {**(getattr(target, "config", None) or {}),
               **(getattr(target, "params", None) or {})}
    accepted = set(_layout_fields(destination))
    return {k: v for k, v in offered.items() if k in accepted and v is not None}


def _accepted_overrides(destination) -> str:
    """The override names a plugin's layout does take, for the message above."""
    return ", ".join("--" + n.replace("_", "-")
                     for n in sorted(_layout_fields(destination)))


def cmd_store(args: argparse.Namespace) -> int:
    """
    The three store verbs. Exit 0 when the verb did what it says; 1 when
    it refused or found something; 2 when there is no store to act on.

    None of them creates the store: a fresh install has no ``store.db``
    until something is archived, and a verb that checks a file must not
    make one to have something to check.
    """
    from . import store

    verb = args.store_command or "verify"
    path = store.store_path()
    if not path.is_file():
        print(f"No store at {path} -- nothing has been archived yet.")
        return 0 if verb == "verify" else 2

    try:
        conn = store.open_store(path)
    except store.StoreVersionError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    try:
        if verb == "verify":
            problems = store.verify(conn)
            if problems:
                print(f"Store {path}: {len(problems)} problem(s)")
                for problem in problems:
                    print(f"  - {problem}")
                return 1
            print(f"Store OK: {path}")
            return 0
        if verb == "backup":
            try:
                copy = store.backup(conn)
            except store.StoreError as exc:
                print(f"Refused: {exc}", file=sys.stderr)
                return 1
            print(f"Backed up to {copy}")
            return 0
        if verb == "rebuild":
            try:
                rebuilt = store.rebuild(conn)
            except store.StoreError as exc:
                print(f"Refused: {exc}", file=sys.stderr)
                return 1
            print(f"Rebuilt {', '.join(rebuilt)} from the primary tables.")
            return 0
        print(f"Unknown store verb: {verb}", file=sys.stderr)
        return 1
    finally:
        conn.close()


HELP_WORDS = ("-h", "--help", "--version", "-V")


def _first_run_write(argv: list[str]) -> Optional[str]:
    """
    The stock-config write (#30), decided from argv before anything parses.

    It has to run before discovery now: the parser is built from the plugins
    the configuration enables, and a first run has no configuration until
    this writes one -- so a first `market --force` would have had no
    `--force` to parse. The exemptions are the same as before, read from the
    raw arguments: `--help`/`--version` anywhere write nothing, a bare
    invocation writes nothing, and the `store` verbs write nothing because a
    verb that reports whether a file is sound must not create another.
    """
    if not argv or argv[0] == "store" or any(word in HELP_WORDS for word in argv):
        return None
    from .stockconfig import write_if_missing

    return write_if_missing()


def _add_plugin_groups(verb_parser, verb: str, plugins) -> None:
    """
    One argparse group per loaded plugin that declares flags for ``verb``.

    The group is titled by the plugin's name, so `--help` says whose word
    each flag is; a plugin that declares nothing for this verb adds no
    group; with no plugin loaded there is nothing to add -- the help is
    honest about the install it runs in.
    """
    if plugins is None:
        return
    for entry in plugins.loaded:
        mine = [flag for flag in entry.flags if flag.verb == verb]
        if not mine:
            continue
        group = verb_parser.add_argument_group(
            f"the {entry.name} plugin",
            f"Words the {entry.name!r} plugin declares; they mean nothing without it.",
        )
        for flag in mine:
            flag.add_to(group)


def _plugin_options(args: argparse.Namespace, verb: str) -> dict:
    """
    What the loaded destination declared for ``verb``, as it was typed.

    Collected by the plugin's own ``dest`` names and passed on unread: the
    mapping is the plugin's vocabulary travelling through core in a sealed
    envelope. Core adds nothing here; ``write`` is added by the caller.
    The flags marked ``layout`` are the layout's (see _layout_overrides)
    and are left out of the envelope.
    """
    plugins = getattr(args, "_plugins", None)
    if plugins is None:
        return {}
    # Every loaded plugin's words for this verb, not only the publisher's:
    # the construction plugin declares `--construction-region` on serve and
    # publishes nothing. Two plugins cannot declare one spelling (the
    # loader refuses that), so the merge cannot collide.
    return {
        flag.dest: getattr(args, flag.dest)
        for entry in plugins.loaded
        for flag in entry.flags
        if flag.verb == verb and not flag.layout and hasattr(args, flag.dest)
    }


def _layout_overrides(args: argparse.Namespace, verb: str) -> dict:
    """
    The typed values of the destination's ``layout=True`` flags for ``verb``.

    Handed to the plugin's ``layout(**overrides)`` by ``dest``; core never
    learns which field a name is. An untyped flag is ``None``, which the
    plugin reads as "use your own default".
    """
    plugins = getattr(args, "_plugins", None)
    destination = plugins.publisher() if plugins is not None else None
    if destination is None:
        return {}
    return {
        flag.dest: getattr(args, flag.dest, None)
        for flag in destination.flags
        if flag.verb == verb and flag.layout
    }


class _NoLayout:
    """
    The layout `serve` runs with when no plugin publishes a roll-up tab.

    A construction-only configuration still wants MarketData, ShipCargo and
    its regions kept current; it has no tab of its own to name and nothing
    of its own to write, so the location cells stay untouched and the guard
    is built from an empty declaration.
    """

    totals_tab = None

    def writes(self) -> dict:
        return {}


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point."""
    argv = list(sys.argv[1:] if argv is None else argv)

    # A first run writes the stock, commented config before anything else
    # (#30) -- before discovery, because discovery is what reads it.
    wrote = _first_run_write(argv)

    # One discovery per run. The parser below is built from what loaded: a
    # plugin's declared flags become a group on the verbs it names, so the
    # help shows the words of the install it runs in and no others. Failure
    # here is not fatal -- `--version` and `--help` must survive a broken
    # plugin -- and the command that needs a destination reports why.
    _plugins, _plugin_problem = _discover_once()

    # Flag defaults and their help text both read from the destination rather
    # than repeating its values, so `--help` stays truthful by construction:
    # point this at a different plugin and the help changes with it. Spelling
    # a tab name into an argparse default instead would put one person's sheet
    # back into the generic layer through the one door no layering test
    # watches -- a literal, which no import graph can see.
    #
    # But it is asked for, never required. v0.7.0 imported it unconditionally
    # here and thereby made EVERY invocation need a plugin -- `--version`
    # included -- while every test in the seam suite stayed green, because
    # they asked whether modules IMPORT and not whether commands RUN. With no
    # destination installed the flags simply have no defaults, which is the
    # honest answer: there is no sheet to name one from.
    _destination = _destination_defaults(_plugins)

    # Create parent parser with common arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    # A named group, so every verb's help shows these under a heading that
    # says what they are for rather than argparse's catch-all "options:"
    # (#28 criterion 1). A group on a parent parser is copied to each child.
    _signing_in = parent_parser.add_argument_group(
        "signing in to Frontier",
        "Only for commands that ask Frontier's API; the journal needs none of these.")
    _signing_in.add_argument(
        "--client-id",
        help="Frontier API client ID",
    )
    _signing_in.add_argument(
        "--redirect-uri",
        help="Custom OAuth redirect URI (for manual auth flow)",
    )
    _signing_in.add_argument(
        "--manual-auth",
        action="store_true",
        help="Use manual authorization (copy/paste code from browser)",
    )

    # Main parser
    parser = argparse.ArgumentParser(
        prog="edapitool",
        description="Elite Dangerous API Tool - Extract game data from CAPI",
        parents=[parent_parser],
    )
    parser.add_argument(
        "--version", "-V",
        action="store_true",
        help="Show version and exit",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Auth command
    auth_parser = subparsers.add_parser(
        "auth",
        help="Authenticate with Frontier",
        parents=[parent_parser],
    )

    # Profile command
    profile_parser = subparsers.add_parser(
        "profile",
        help="Get commander profile",
        parents=[parent_parser],
    )
    profile_parser.add_argument("--json", action="store_true", help="Output raw JSON")

    # Carrier command
    carrier_parser = subparsers.add_parser(
        "carrier",
        help="Get fleet carrier data",
        parents=[parent_parser],
    )
    carrier_parser.add_argument("--json", action="store_true", help="Output raw JSON")
    carrier_parser.add_argument(
        "--export", "-e",
        type=str,
        help="Export formats: csv,gsheet,google,json (comma-separated for multiple)",
    )
    carrier_parser.add_argument(
        "--output", "-o",
        help="Output directory for exports",
    )
    carrier_parser.add_argument(
        "--include",
        type=str,
        default="",
        help="Include cargo types: stolen,mission (comma-separated). Default excludes both.",
    )
    carrier_parser.add_argument(
        "--sheet-id",
        type=str,
        help="Google Sheet ID for direct export (required with --export google)",
    )
    carrier_parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use Legacy galaxy server instead of Live",
    )
    carrier_parser.add_argument(
        "--raw",
        action="store_true",
        help="Include raw CAPI response in JSON export",
    )

    # Market command
    market_parser = subparsers.add_parser(
        "market",
        help="Compare the current station's market against the spreadsheet",
        parents=[parent_parser],
    )
    # Grouped rather than listed. Twenty-four flags printed as one flat run
    # is not a reference, and six of them concern the glyph column alone --
    # so someone looking for "how do I stop it writing there" had to read all
    # twenty-four to find out which three were the answer. Measured on this
    # very release: a reader asked to judge whether `--force`'s warning was
    # adequate reported the text as good and the PLACEMENT as the problem,
    # it being flag sixteen of twenty-four with no visual break around it.
    #
    # The renames #28 also calls for are deliberately NOT here. A group
    # heading changes nothing anyone has ever typed, so it does not have to
    # wait for a breaking release; renaming `marker` to `glyph-marker` does.
    _finding = market_parser.add_argument_group(
        "finding the market",
        "Where the reading comes from. Neither of these needs a spreadsheet.",
    )
    _sheet = market_parser.add_argument_group(
        "the spreadsheet",
        "Which workbook, and where the numbers are in it.",
    )
    _writing = market_parser.add_argument_group(
        "writing to it",
        "Nothing here happens unless you ask for it.",
    )
    _data = market_parser.add_argument_group(
        "exporting data",
        "The market as data, for your own formulas to read.",
    )

    _finding.add_argument(
        "--journal-dir",
        help="Elite Dangerous journal directory (default: Saved Games location)",
    )
    _finding.add_argument(
        "--use-capi",
        action="store_true",
        help="Also query the Frontier CAPI market (live stock; needs authentication)",
    )

    _sheet.add_argument(
        "--sheet-id",
        help="Google Sheet ID (or set ED_SHEET_ID, or sheet_id in your config file)",
    )
    _sheet.add_argument(
        "--no-sheet",
        action="store_true",
        help="Inspect location and market without opening the spreadsheet",
    )
    _writing.add_argument(
        "--update-sheet",
        action="store_true",
        help="Write column markers to the spreadsheet",
    )
    _writing.add_argument(
        "--dry-run",
        action="store_true",
        help="With --update-sheet, show exactly what would be written and write nothing",
    )
    # The roll-up tab's own words -- which tab, which column, which glyphs,
    # --force, --write-location -- are no longer here. The plugin that owns
    # them declares them (its `flags()`), and _add_plugin_groups registers
    # them below under the plugin's own name, only when it is loaded.

    _data.add_argument(
        "--export", "-e",
        type=str,
        help="Emit the station market as data: csv,json (files), market-tab (a "
             "generated MarketData tab in the spreadsheet). Comma-separated. None "
             "of these depend on our marker formatting.",
    )
    _data.add_argument(
        "--output", "-o",
        help="Output directory for --export csv/json",
    )
    _data.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )

    # Version command
    ship_parser = subparsers.add_parser(
        "ship",
        help="Report the current ship's cargo hold",
        parents=[parent_parser],
    )
    ship_parser.add_argument(
        "--json", action="store_true", help="Output the hold as JSON on stdout"
    )
    ship_parser.add_argument(
        "--export", "-e",
        help="Comma-separated: csv, json, ship-tab (only ship-tab needs a spreadsheet)",
    )
    ship_parser.add_argument(
        "--output", "-o",
        help="Output directory for --export csv/json",
    )
    ship_parser.add_argument(
        "--sheet-id",
        help="Google Sheet ID; required only for --export ship-tab",
    )
    ship_parser.add_argument(
        "--ship-tab",
        default="ShipCargo",
        help="Name of the generated tab (default: 'ShipCargo')",
    )
    ship_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --export ship-tab, show what would be written and write nothing",
    )
    ship_parser.add_argument(
        "--journal-dir",
        help="Elite Dangerous journal directory (default: Saved Games location)",
    )

    construction_parser = subparsers.add_parser(
        "construction",
        help="What a colony construction site still needs",
        # Deliberately NOT parents=[parent_parser]. That parent carries only
        # Frontier OAuth options -- client id, redirect uri, manual auth -- and
        # this verb never authenticates: it reads the commander's own journal.
        # Advertising three credential flags on the one verb whose selling
        # point is "no login required" tells the reader the opposite of the
        # truth about what it needs.
    )
    construction_parser.add_argument(
        "--json", action="store_true", help="Output the site as JSON on stdout"
    )
    construction_parser.add_argument(
        "--export", "-e", help="Comma-separated: csv, json (neither needs a spreadsheet)"
    )
    construction_parser.add_argument(
        "--output", "-o", help="Output directory for --export"
    )
    construction_parser.add_argument(
        "--site",
        help="Which site: a MarketID, or the station name as you would type it "
             "(the game's 'Planetary Construction Site: ' prefix is optional). "
             "Defaults to wherever you are docked, else the most recent",
    )
    construction_parser.add_argument(
        "--system",
        help="Disambiguate --site when two construction sites share a station name",
    )
    construction_parser.add_argument(
        "--all", action="store_true",
        help="Include completed, failed and stale sites (default: active only)",
    )
    construction_parser.add_argument(
        "--stale-after", type=int, default=60, metavar="DAYS",
        help="Days without the game mentioning a site before it counts as "
             "stale (default: 60). The game never marks a lapsed build failed, "
             "so elapsed time is the only available signal",
    )
    construction_parser.add_argument(
        "--list", action="store_true",
        help="List every construction site the journal knows about, and exit",
    )
    construction_parser.add_argument(
        "--all-sites", action="store_true",
        help="With --json, emit every known site rather than one",
    )
    construction_parser.add_argument(
        "--scan-files", type=int, nargs="?", default=120, const=0,
        metavar="N",
        help="How many journal files back to read (default: 120). Pass the "
             "flag with no number to read ALL of them. Measured on a 621-file "
             "journal: 6 files found 3 sites in 0.09s, 120 found all 6 in "
             "1.0s, and every file took 4.4s to find no more",
    )
    construction_parser.add_argument(
        "--journal-dir", help="Elite Dangerous journal directory"
    )
    construction_parser.add_argument(
        "--publish-to", metavar="TAB",
        help="Publish the site as a data block into a REGION of this tab, "
             "beside whatever else the tab already holds. Requires --region "
             "and --sheet-id",
    )
    construction_parser.add_argument(
        "--region", metavar="A1:B2",
        help="The rectangle on --publish-to that this block owns. Declared, "
             "never guessed: everything inside it is cleared on every publish, "
             "so a shrinking site leaves nothing behind, and everything "
             "outside it is never touched. Reserve more than you need -- "
             "growing inside the reserve costs nothing",
    )
    construction_parser.add_argument(
        "--sheet-id", help="Google Sheet ID (or ED_SHEET_ID, or the config file)"
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="Keep the generated tabs current while the game runs",
        parents=[parent_parser],
    )
    # Three groups, and the third has one member on purpose: it is the only
    # flag here that writes into a cell this tool does not generate, and a
    # heading of its own is the cheapest way to say so.
    _watch = serve_parser.add_argument_group(
        "what it watches",
        "The journal, and how patiently.",
    )
    _publish = serve_parser.add_argument_group(
        "where it publishes",
        "Tabs this tool generates in full.",
    )

    _watch.add_argument(
        "--journal-dir", help="Elite Dangerous journal directory"
    )
    _watch.add_argument(
        "--interval", type=float, default=2.0,
        help="Seconds between journal polls (default: 2)",
    )
    _watch.add_argument(
        "--debounce", type=float, default=5.0,
        help="Seconds of quiet before publishing. One play session emitted 19 "
             "Market events; without this each would be a separate write "
             "(default: 5)",
    )
    _watch.add_argument(
        "--once", action="store_true",
        help="Publish both tabs once and exit, instead of watching",
    )

    _publish.add_argument(
        "--sheet-id",
        help='Google Sheet ID (or ED_SHEET_ID, or "sheet_id" in the config '
             'file)',
    )
    _publish.add_argument(
        "--ship-tab", default="ShipCargo", help="Tab for the ship's hold"
    )
    # `--totals-tab`, `--construction-region` and `--write-location` are the
    # roll-up plugin's words; it declares them and they are registered here
    # under its name only when it is loaded (_add_plugin_groups).

    plugins_parser = subparsers.add_parser(
        "plugins",
        help="What destinations are installed, which are on, and what broke; "
             "or a plugin's own commands: plugins <name> <command>",
        description=(
            "With no name: the installed plugins and their state (imports only "
            "what your configuration already enables). Three names are the "
            "verb's own: `list` (the same listing), `describe <plugin>` (one "
            "plugin's kind, what it writes, supplies and subscribes to), and "
            "`help` (this page). Any other name is a plugin, and what follows "
            "it is that plugin's own command line: `plugins <name>` lists the "
            "commands it offers, `plugins <name> <command> ...` runs one. "
            "Naming a plugin IMPORTS it -- that is the consent to run it; a "
            "plugin no target enables may run only the commands it marks "
            "safe without one."
        ),
    )
    plugins_parser.add_argument(
        "name", nargs="?", metavar="NAME",
        help="list | describe | help, or a plugin's name",
    )
    plugins_parser.add_argument(
        "tail", nargs=argparse.REMAINDER, metavar="...",
        help="For describe: the plugin. For a plugin: its command and that "
             "command's own arguments, passed through unread",
    )

    store_parser = subparsers.add_parser(
        "store",
        help="The observation store: what the tool has read, kept where the "
             "game cannot overwrite it",
    )
    store_sub = store_parser.add_subparsers(dest="store_command")
    store_sub.add_parser(
        "verify",
        help="Check the store file is sound (integrity, known tables, no "
             "orphaned rows); writes nothing",
    )
    store_sub.add_parser(
        "backup",
        help="Copy the store to store.db.bak-<stamp> beside it, after verify "
             "passes; a store that fails verify is never copied over a good one",
    )
    store_sub.add_parser(
        "rebuild",
        help="Drop and re-project every derived table from the primary ones; "
             "primary tables (sources, observations, writes) are never touched",
    )

    version_parser = subparsers.add_parser("version", help="Show version")

    # The plugins' own words, last in each verb's help, under their own name.
    _add_plugin_groups(market_parser, "market", _plugins)
    _add_plugin_groups(serve_parser, "serve", _plugins)

    args = parser.parse_args(argv)
    args._plugins = _plugins
    args._plugin_problem = _plugin_problem
    args._plugins_parser = plugins_parser

    if args.version:
        return cmd_version(args)

    if wrote and args.command:
        print(wrote)

    if args.command == "auth":
        return cmd_auth(args)
    elif args.command == "profile":
        return cmd_profile(args)
    elif args.command == "carrier":
        return cmd_carrier(args)
    elif args.command == "market":
        return cmd_market(args)
    elif args.command == "ship":
        return cmd_ship(args)
    elif args.command == "construction":
        return cmd_construction(args)
    elif args.command == "serve":
        return cmd_serve(args)
    elif args.command == "plugins":
        return cmd_plugins(args)
    elif args.command == "store":
        return cmd_store(args)
    elif args.command == "version":
        return cmd_version(args)
    else:
        parser.print_help()
        return 0


def carrier_main(argv: Optional[list[str]] = None) -> int:
    """Shortcut entry point for carrier command."""
    if argv is None:
        argv = sys.argv[1:]
    return main(["carrier"] + list(argv))


if __name__ == "__main__":
    sys.exit(main())
