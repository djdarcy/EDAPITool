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
from typing import Optional

from .version import __version__, get_version
from .config import CAPI_SERVER_LIVE, CAPI_SERVER_LEGACY
from .auth import FrontierAuth
from .capi import CAPIClient, CAPIError, CAPINoDataError
from .models import FleetCarrier
from .export import CSVExporter, JSONExporter


def get_client_id() -> Optional[str]:
    """Get client ID from environment or config file."""
    import os

    # Try environment variable first
    client_id = os.environ.get("ED_CLIENT_ID")
    if client_id:
        return client_id

    # Try config file
    config_file = Path.home() / ".ed_capi_config.json"
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
            return config.get("client_id")
        except (json.JSONDecodeError, IOError):
            pass

    return None


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
    config_file = Path.home() / ".ed_capi_config.json"
    try:
        # Load existing config or create new
        if config_file.exists():
            config = json.loads(config_file.read_text())
        else:
            config = {}

        config["client_id"] = client_id
        config_file.write_text(json.dumps(config, indent=2))
        return True
    except (IOError, json.JSONDecodeError) as e:
        print(f"Warning: Could not save client ID to config: {e}", file=sys.stderr)
        return False


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
        print("  2. Create ~/.ed_capi_config.json with: {\"client_id\": \"your_id\"}")
        print("  3. Use --client-id argument")
        return 1

    redirect_uri = getattr(args, 'redirect_uri', None)
    manual = getattr(args, 'manual_auth', False)

    auth = setup_auth(client_id, redirect_uri=redirect_uri, manual=manual)

    # Save client ID to config file for future use
    if auth.is_authenticated and args.client_id:
        if save_client_id(client_id):
            print(f"Client ID saved to ~/.ed_capi_config.json")

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

    # Validate google export has sheet-id
    if "google" in export_formats and not args.sheet_id:
        print("Error: --sheet-id is required when using --export google")
        return 1

    auth = setup_auth(client_id, redirect_uri=redirect_uri, manual=manual)
    server = CAPI_SERVER_LEGACY if args.legacy else CAPI_SERVER_LIVE
    client = CAPIClient(auth, server=server)

    try:
        print("Fetching fleet carrier data...", file=sys.stderr)
        print("(This may take up to 60 seconds for large inventories)", file=sys.stderr)
        print(file=sys.stderr)

        raw_data = client.get_fleet_carrier()

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
                        sheet_id=args.sheet_id,
                        include_stolen=include_stolen,
                        include_mission=include_mission,
                    )
                    exported_files["google"] = f"Sheet ID: {args.sheet_id}"
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


def get_sheet_id(args: argparse.Namespace) -> Optional[str]:
    """Resolve the spreadsheet id from args, environment, or saved config."""
    import os

    if getattr(args, "sheet_id", None):
        return args.sheet_id
    env = os.environ.get("ED_SHEET_ID")
    if env:
        return env
    config_file = Path.home() / ".ed_capi_config.json"
    if config_file.exists():
        try:
            return json.loads(config_file.read_text()).get("sheet_id")
        except (json.JSONDecodeError, IOError):
            pass
    return None


def cmd_market(args: argparse.Namespace) -> int:
    """
    Compare the current station's market against the spreadsheet's
    outstanding requirements, and optionally mark them in the sheet.
    """
    if getattr(args, "show_formula", False):
        from .workbook.markers import marker_formula_help

        print(marker_formula_help())
        return 0

    from .service import MarketRefreshService, format_table
    from .workbook.markers import (
        MARKER_EMPTY_DOTTED,
        MARKER_EMPTY_SMALL,
        MARKER_ENOUGH,
        MARKER_PARTIAL,
    )
    from .sheets import (
        SIGN_NEGATIVE,
        SIGN_POSITIVE,
        SheetLayout,
        WriteRefused,
    )
    from .matcher import MatchState

    # Only override the glyph family when a non-default empty marker is asked
    # for; the default keeps the graded quarter/half/three-quarter partial
    # scale, which a wholesale override collapses to a single glyph.
    markers = None
    if args.empty_marker != "hollow":
        empty = MARKER_EMPTY_SMALL if args.empty_marker == "small" else MARKER_EMPTY_DOTTED
        markers = {
            MatchState.ENOUGH: MARKER_ENOUGH,
            MatchState.PARTIAL: MARKER_PARTIAL,
            MatchState.EMPTY: empty,
        }

    layout = SheetLayout(
        totals_tab=args.totals_tab,
        need_header=args.need_header,
        need_sign=SIGN_NEGATIVE if args.need_sign == "negative" else SIGN_POSITIVE,
        marker_column=args.marker_column,
        markers=markers,
    )

    capi_client = None
    if args.use_capi:
        client_id = args.client_id or get_client_id()
        if not client_id:
            print("Error: --use-capi needs a client ID. Run 'edapitool auth' first.")
            return 1
        auth = setup_auth(client_id)
        capi_client = CAPIClient(auth)

    service = MarketRefreshService(
        journal_dir=Path(args.journal_dir) if args.journal_dir else None,
        layout=layout,
        capi_client=capi_client,
    )

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
    if not args.no_sheet:
        sheet_id = get_sheet_id(args)
        if not sheet_id:
            if needs_sheet:
                print("Error: no spreadsheet id. Pass --sheet-id, set ED_SHEET_ID,")
                print("       or add \"sheet_id\" to ~/.ed_capi_config.json.")
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
        result = service.refresh(
            worksheet=worksheet,
            # --no-markers shapes the PLAN, it does not veto the write. Vetoing
            # left the location cells stale too -- everything travels in one
            # batch -- so the one flag meant for a formula-driven sheet was the
            # one flag that stopped it being told where you are.
            write=args.update_sheet and not args.dry_run,
            write_header=args.write_marker_header,
            show_covered=not args.no_show_covered,
            apply_colour=not args.no_colour,
            include_markers=not args.no_markers,
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
            print(f"Marked rows: {result.plan.marked_rows or '(none)'}")
        elif args.update_sheet:
            print("DRY RUN - would write:")
            for update in result.plan.updates:
                preview = update["values"]
                if len(preview) > 3:
                    preview = f"{len(preview)} rows"
                print(f"  {layout.totals_tab}!{update['range']} = {preview}")
            print(f"  marked rows: {result.plan.marked_rows or '(none)'}")
        else:
            print("(read-only; pass --update-sheet to write markers)")

    return 0 if result.ok else 2


def cmd_serve(args: argparse.Namespace) -> int:
    """Keep MarketData and ShipCargo current while the game runs."""
    from . import daemon as daemon_mod
    from .sheets import SheetLayout

    sheet_id = get_sheet_id(args)
    if not sheet_id:
        print("Error: serve needs a spreadsheet id. Pass --sheet-id,")
        print("       set ED_SHEET_ID, or add \"sheet_id\" to ~/.ed_capi_config.json.")
        return 1

    journal_dir = Path(args.journal_dir) if args.journal_dir else None
    try:
        worker = daemon_mod.build(
            sheet_id=sheet_id,
            journal_dir=journal_dir,
            layout=SheetLayout(totals_tab=args.totals_tab),
            ship_tab=args.ship_tab,
            write_location=args.write_location,
            interval=args.interval,
            debounce=args.debounce,
        )
    except ImportError:
        print("Error: Google Sheets support not installed.")
        print("Install with: pip install edapitool[gsheets]")
        return 1
    except Exception as exc:
        # build() opens the Totals Tab, which raises ValueError for a tab name
        # that is not there and gspread's own errors for a bad id or revoked
        # credential -- none of them ImportError. `market` already reports these
        # in one friendly line; without this, `serve` differed only by showing
        # the user a traceback.
        print(f"Error opening spreadsheet: {exc}")
        return 1

    if args.once:
        print("Publishing both tabs once.")
        print(worker.publish_market())
        print(worker.publish_cargo())
        return 0

    # Prime before the loop so the backlog of a session already in progress
    # does not fire a publish for every dock that has already happened.
    state = worker.watcher.prime()
    where = state.station_display or state.system or "unknown"
    print(f"Watching the journal from {where}.")
    print(f"Publishing MarketData and {args.ship_tab} to the spreadsheet.")
    print(f"Poll {args.interval}s, debounce {args.debounce}s. Ctrl+C to stop.")
    print()

    try:
        worker.run()
    except KeyboardInterrupt:
        stats = worker.stats
        print()
        print(
            f"Stopped. {stats.polls} polls, {stats.events} events, "
            f"{stats.market_publishes} market and {stats.cargo_publishes} "
            f"cargo publishes, {stats.errors} errors."
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
            print("       set ED_SHEET_ID, or add \"sheet_id\" to ~/.ed_capi_config.json.")
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


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point."""
    # Create parent parser with common arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
        "--client-id",
        help="Frontier API client ID",
    )
    parent_parser.add_argument(
        "--redirect-uri",
        help="Custom OAuth redirect URI (for manual auth flow)",
    )
    parent_parser.add_argument(
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
    market_parser.add_argument(
        "--sheet-id",
        help="Google Sheet ID (or set ED_SHEET_ID, or sheet_id in ~/.ed_capi_config.json)",
    )
    market_parser.add_argument(
        "--update-sheet",
        action="store_true",
        help="Write location cells and column markers to the spreadsheet",
    )
    market_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --update-sheet, show exactly what would be written and write nothing",
    )
    market_parser.add_argument(
        "--no-sheet",
        action="store_true",
        help="Inspect location and market without opening the spreadsheet",
    )
    market_parser.add_argument(
        "--use-capi",
        action="store_true",
        help="Also query the Frontier CAPI market (live stock; needs authentication)",
    )
    market_parser.add_argument(
        "--journal-dir",
        help="Elite Dangerous journal directory (default: Saved Games location)",
    )
    market_parser.add_argument(
        "--totals-tab",
        default="Totals Tab",
        help="Name of the roll-up tab (default: 'Totals Tab')",
    )
    market_parser.add_argument(
        "--need-header",
        default="Left to buy",
        help="Header text of the outstanding-quantity column (default: 'Left to buy')",
    )
    market_parser.add_argument(
        "--need-sign",
        choices=["positive", "negative"],
        default="positive",
        help="Which sign means 'still to buy' (use 'negative' for a combined "
             "signed column where -229 means buy 229)",
    )
    market_parser.add_argument(
        "--marker-column",
        default="L",
        help="Column to write markers into (default: L)",
    )
    market_parser.add_argument(
        "--export", "-e",
        type=str,
        help="Emit the station market as data: csv,json (files), market-tab (a "
             "generated MarketData tab in the spreadsheet). Comma-separated. None "
             "of these depend on our marker formatting.",
    )
    market_parser.add_argument(
        "--output", "-o",
        help="Output directory for --export csv/json",
    )
    market_parser.add_argument(
        "--no-markers",
        action="store_true",
        help="Do not write the marker column. Pair with '--export market-tab' to let "
             "the spreadsheet render markers from the data using its own formulas.",
    )
    market_parser.add_argument(
        "--show-formula",
        action="store_true",
        help="Print the spreadsheet formula that reproduces the marker column from a "
             "MarketData tab, then exit",
    )
    market_parser.add_argument(
        "--no-show-covered",
        action="store_true",
        help="Do not mark commodities the station sells that you already have enough of "
             "(they are shown greyed out by default, so a blank cell means 'not sold here')",
    )
    market_parser.add_argument(
        "--no-colour", "--no-color",
        dest="no_colour",
        action="store_true",
        help="Write only the glyphs, leaving cell background and font colour alone",
    )
    market_parser.add_argument(
        "--write-marker-header",
        action="store_true",
        help="Also label the cell above the markers (default: leave it alone, "
             "it is yours)",
    )
    market_parser.add_argument(
        "--empty-marker",
        choices=["hollow", "small", "dotted"],
        default="hollow",
        help="Glyph for 'station sells it but has none right now': "
             "hollow circle (default, matches the filled/half-filled family), "
             "small white bullet, or dotted circle",
    )
    market_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

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

    serve_parser = subparsers.add_parser(
        "serve",
        help="Keep the generated tabs current while the game runs",
        parents=[parent_parser],
    )
    serve_parser.add_argument(
        "--sheet-id", help="Google Sheet ID (or ED_SHEET_ID, or the config file)"
    )
    serve_parser.add_argument(
        "--journal-dir", help="Elite Dangerous journal directory"
    )
    serve_parser.add_argument(
        "--ship-tab", default="ShipCargo", help="Tab for the ship's hold"
    )
    serve_parser.add_argument(
        "--totals-tab", default="Totals Tab",
        help="Name of the roll-up tab whose location cells are refreshed "
             "with --write-location (default: 'Totals Tab')",
    )
    serve_parser.add_argument(
        "--interval", type=float, default=2.0,
        help="Seconds between journal polls (default: 2)",
    )
    serve_parser.add_argument(
        "--debounce", type=float, default=5.0,
        help="Seconds of quiet before publishing. One play session emitted 19 "
             "Market events; without this each would be a separate write "
             "(default: 5)",
    )
    serve_parser.add_argument(
        "--once", action="store_true",
        help="Publish both tabs once and exit, instead of watching",
    )
    serve_parser.add_argument(
        "--write-location", action="store_true",
        help="Write the current system and station into the roll-up tab's "
             "location cells. Off by default: those cells are better as "
             "formulas reading the generated MarketData tab, and writing "
             "literals would overwrite them. Use only for a sheet that still "
             "expects the tool to paint them",
    )

    version_parser = subparsers.add_parser("version", help="Show version")

    args = parser.parse_args(argv)

    if args.version:
        return cmd_version(args)

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
    elif args.command == "serve":
        return cmd_serve(args)
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
