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
                    from .gsheet import GoogleSheetsExporter
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
    from .service import MarketRefreshService, format_table
    from .sheets import (
        MARKER_EMPTY_DOTTED,
        MARKER_EMPTY_SMALL,
        MARKER_ENOUGH,
        MARKER_PARTIAL,
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

    worksheet = None
    sheet_id = None
    if not args.no_sheet:
        sheet_id = get_sheet_id(args)
        if not sheet_id:
            print("Error: no spreadsheet id. Pass --sheet-id, set ED_SHEET_ID,")
            print("       or add \"sheet_id\" to ~/.ed_capi_config.json.")
            print("       (Use --no-sheet to inspect the market without a spreadsheet.)")
            return 1
        try:
            from .gsheet import GoogleSheetsExporter

            worksheet = GoogleSheetsExporter().worksheet(sheet_id, layout.totals_tab)
        except ImportError:
            print("Error: Google Sheets support not installed.")
            print("Install with: pip install edapitool[gsheets]")
            return 1
        except Exception as exc:
            print(f"Error opening spreadsheet: {exc}")
            return 1

    try:
        result = service.refresh(
            worksheet=worksheet,
            write=args.update_sheet and not args.dry_run,
            write_header=args.write_marker_header,
            show_covered=not args.no_show_covered,
            apply_colour=not args.no_colour,
        )
    except WriteRefused as exc:
        print(f"Refused to write: {exc}")
        return 1
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    if args.json:
        print(json.dumps(_market_result_json(result), indent=2))
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
