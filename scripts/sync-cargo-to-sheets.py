#!/usr/bin/env python3
"""
Sync fleet carrier cargo to Google Sheets.

This script is designed for scheduled/cron execution. It exports cargo data
to a Google Sheet for inventory tracking.

Configuration (in order of precedence):
1. Command-line arguments
2. Environment variables: ED_CLIENT_ID, ED_SHEET_ID
3. Config file: ~/.ed_capi_config.json

Usage:
    python sync-cargo-to-sheets.py
    python sync-cargo-to-sheets.py --sheet-id YOUR_SHEET_ID

Cron example (every 15 minutes - respects CAPI rate limit):
    */15 * * * * /path/to/python /path/to/sync-cargo-to-sheets.py >> /path/to/sync.log 2>&1

Windows Task Scheduler:
    Program: python
    Arguments: C:\\path\\to\\sync-cargo-to-sheets.py
    Start in: C:\\path\\to\\APITool
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime


# Default sheet ID - update this to your sheet
DEFAULT_SHEET_ID = "1iphZWZqOH6iigBJYO0Tk4jxAAkX-QAcELMotb9T5aXA"


def get_config():
    """Load configuration from config file."""
    config_file = Path.home() / ".ed_capi_config.json"
    if config_file.exists():
        try:
            return json.loads(config_file.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def get_client_id():
    """Get client ID from env var or config file."""
    # Environment variable takes precedence
    client_id = os.environ.get("ED_CLIENT_ID")
    if client_id:
        return client_id

    # Fall back to config file
    config = get_config()
    return config.get("client_id")


def get_sheet_id():
    """Get sheet ID from env var or default."""
    return os.environ.get("ED_SHEET_ID", DEFAULT_SHEET_ID)


def log(message):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def main():
    """Run the cargo sync."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Sync fleet carrier cargo to Google Sheets"
    )
    parser.add_argument(
        "--sheet-id",
        help=f"Google Sheet ID (default: {DEFAULT_SHEET_ID[:20]}...)",
    )
    parser.add_argument(
        "--client-id",
        help="Frontier API client ID (reads from config if not provided)",
    )
    parser.add_argument(
        "--include",
        default="",
        help="Include cargo types: stolen,mission",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show command without executing",
    )
    parser.add_argument(
        "--also-csv",
        action="store_true",
        help="Also export CSV files locally",
    )

    args = parser.parse_args()

    # Resolve configuration
    client_id = args.client_id or get_client_id()
    sheet_id = args.sheet_id or get_sheet_id()

    if not client_id:
        log("ERROR: No client ID found.")
        log("Set ED_CLIENT_ID environment variable or run:")
        log("  edapitool auth --client-id YOUR_CLIENT_ID")
        return 1

    # Build command
    export_formats = ["google"]
    if args.also_csv:
        export_formats.append("csv")
        export_formats.append("gsheet")

    cmd = [
        "edapitool", "carrier",
        "--export", ",".join(export_formats),
        "--sheet-id", sheet_id,
        "--client-id", client_id,
    ]

    if args.include:
        cmd.extend(["--include", args.include])

    if args.dry_run:
        log("DRY RUN - would execute:")
        # Mask client ID in output
        display_cmd = " ".join(cmd).replace(client_id, client_id[:8] + "...")
        print(f"  {display_cmd}")
        return 0

    log(f"Syncing cargo to Google Sheet: {sheet_id[:20]}...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                log(line)

        if result.returncode != 0:
            log(f"ERROR: Export failed with code {result.returncode}")
            if result.stderr:
                for line in result.stderr.strip().split("\n"):
                    log(f"  {line}")
            return result.returncode

        log("Sync complete!")
        return 0

    except FileNotFoundError:
        log("ERROR: edapitool not found. Is it installed?")
        log("  pip install -e .[gsheets]")
        return 1
    except Exception as e:
        log(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
