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
