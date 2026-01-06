"""
Google Sheets export functionality for Elite Dangerous data.

Requires optional dependencies:
    pip install edapitool[gsheets]

Or manually:
    pip install gspread google-auth google-auth-oauthlib
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .models import FleetCarrier

# Only import gspread at runtime, not for type checking
if TYPE_CHECKING:
    import gspread

try:
    import gspread as _gspread
    from google.oauth2.service_account import Credentials
    from google.oauth2.credentials import Credentials as UserCredentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    GSPREAD_AVAILABLE = True
except ImportError:
    _gspread = None  # type: ignore
    GSPREAD_AVAILABLE = False


class GoogleSheetsExporter:
    """Export data directly to Google Sheets."""

    # Tabs that should NEVER be modified (user's live tracking data)
    PROTECTED_TABS = ["Base", "1st", "2", "3", "Sheet3"]

    # OAuth scopes required for Google Sheets
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
    ):
        """
        Initialize Google Sheets exporter.

        Args:
            credentials_path: Path to service account JSON or OAuth client secrets.
                             Defaults to ~/.ed_gsheet_credentials.json
            token_path: Path to store OAuth tokens.
                       Defaults to ~/.ed_gsheet_token.json
        """
        if not GSPREAD_AVAILABLE:
            raise ImportError(
                "Google Sheets support requires additional dependencies. "
                "Install with: pip install edapitool[gsheets]"
            )

        self.credentials_path = Path(credentials_path) if credentials_path else (
            Path.home() / ".ed_gsheet_credentials.json"
        )
        self.token_path = Path(token_path) if token_path else (
            Path.home() / ".ed_gsheet_token.json"
        )
        self._client: Optional[Any] = None  # gspread.Client when available

    def _get_client(self) -> Any:  # Returns gspread.Client
        """Get authenticated gspread client."""
        if self._client:
            return self._client

        # Try service account first
        if self.credentials_path.exists():
            try:
                creds = Credentials.from_service_account_file(
                    str(self.credentials_path),
                    scopes=self.SCOPES,
                )
                self._client = _gspread.authorize(creds)
                return self._client
            except Exception:
                pass  # Try OAuth flow instead

        # Try OAuth user credentials
        if self.token_path.exists():
            try:
                creds = UserCredentials.from_authorized_user_file(
                    str(self.token_path),
                    scopes=self.SCOPES,
                )
                if creds.valid:
                    self._client = _gspread.authorize(creds)
                    return self._client
            except Exception:
                pass

        # Need to do OAuth flow
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"No credentials found at {self.credentials_path}\n"
                "Please set up Google API credentials:\n"
                "1. Go to https://console.cloud.google.com/apis/credentials\n"
                "2. Create OAuth 2.0 Client ID (Desktop app)\n"
                "3. Download JSON and save to ~/.ed_gsheet_credentials.json"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.credentials_path),
            scopes=self.SCOPES,
        )
        creds = flow.run_local_server(port=0)

        # Save token for future use
        self.token_path.write_text(creds.to_json())

        self._client = _gspread.authorize(creds)
        return self._client

    def export_cargo(
        self,
        carrier: FleetCarrier,
        sheet_id: str,
        tab_name: str = "CargoData",
        include_stolen: bool = False,
        include_mission: bool = False,
    ) -> None:
        """
        Export cargo data directly to a Google Sheet.

        Args:
            carrier: FleetCarrier data
            sheet_id: Google Sheet ID (from URL)
            tab_name: Name of tab to write to (default: "CargoData")
            include_stolen: Include stolen cargo items
            include_mission: Include mission-reserved cargo items

        Raises:
            ValueError: If trying to write to a protected tab
        """
        # Safety check: don't overwrite protected tabs
        if tab_name in self.PROTECTED_TABS:
            raise ValueError(
                f"Cannot write to protected tab '{tab_name}'. "
                f"Protected tabs: {', '.join(self.PROTECTED_TABS)}"
            )

        # Step 1: Filter cargo based on flags
        filtered = [
            c for c in carrier.cargo
            if (include_stolen or not c.stolen)
            and (include_mission or not c.mission)
            and c.quantity > 0
        ]

        # Step 2: Group by commodity, track max-qty stack for each
        groups: dict[str, dict] = {}
        for item in filtered:
            key = item.commodity
            if key not in groups:
                groups[key] = {
                    "items": [],
                    "max_qty_item": item,
                    "total_qty": 0,
                    "display_name": item.localized_name,
                }
            groups[key]["items"].append(item)
            groups[key]["total_qty"] += item.quantity
            if item.quantity > groups[key]["max_qty_item"].quantity:
                groups[key]["max_qty_item"] = item

        # Step 3: Calculate unit prices and prepare data
        data = []
        for key, group in groups.items():
            max_item = group["max_qty_item"]
            unit_price = max_item.value // max_item.quantity if max_item.quantity > 0 else 0
            data.append({
                "display_name": group["display_name"],
                "quantity": group["total_qty"],
                "unit_price": unit_price,
            })

        # Sort alphabetically
        data.sort(key=lambda x: x["display_name"])

        # Step 4: Connect to Google Sheets
        client = self._get_client()
        spreadsheet = client.open_by_key(sheet_id)

        # Get or create the tab
        try:
            worksheet = spreadsheet.worksheet(tab_name)
        except _gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=tab_name,
                rows=len(data) + 10,
                cols=5,
            )

        # Step 5: Clear existing data and write new data
        worksheet.clear()

        # Prepare all rows
        rows = []

        # Row 1: Empty
        rows.append(["", "", "", "", ""])

        # Row 2: Headers
        rows.append(["", "Display Name", "Quantity", "Unit Price", "Total Value"])

        # Row 3: Totals with formulas
        rows.append(["", "TOTAL", f"=SUM(C4:C{3 + len(data)})", "", f"=SUM(E4:E{3 + len(data)})"])

        # Row 4+: Data
        for i, item in enumerate(data):
            row_num = 4 + i
            rows.append([
                "",
                item["display_name"],
                item["quantity"],
                item["unit_price"],
                f"=C{row_num}*D{row_num}",
            ])

        # Batch update for efficiency
        worksheet.update(rows, value_input_option="USER_ENTERED")

        print(f"Exported {len(data)} cargo items to '{tab_name}' tab")
