"""
Google Sheets export functionality for Elite Dangerous data.

Requires optional dependencies:
    pip install edapitool[gsheets]

Or manually:
    pip install gspread google-auth google-auth-oauthlib
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Optional

from ..cargo import data_row, header_row, verify_contract
from ..models import FleetCarrier
from ..sheets import Destination, WriteGuard, WriteRefused, index_to_column

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


def carrier_grid(
    data: list[dict],
    checked_at: str = "",
    changed_at: str = "",
) -> list[list]:
    """
    The fleet carrier's hold as a cargo tab, honouring the shared contract.

    Takes rows already grouped and priced by :meth:`GoogleSheetsExporter.
    export_cargo` -- each a dict of ``display_name`` / ``quantity`` /
    ``unit_price`` -- and lays them out as B/C/D plus this tab's own Total
    Value column.

    Pure, and separate from the writer, for the same reason ``market`` and
    ``ship`` build their grids as functions: a grid you cannot construct
    without a network connection is a grid nobody tests.

    Total Value is emitted as a FORMULA rather than a computed number. The
    spreadsheet does its own arithmetic; the tool supplies the operands.

    The metadata row, and why its wording is not the other tabs' (#19)
    -----------------------------------------------------------------
    ``MarketData`` and ``ShipCargo`` head their grids with ``Updated (UTC)``,
    which is the GAME's own event timestamp -- those tabs read files the game
    wrote, so the data can say how old it is.

    This tab cannot. Frontier's fleet-carrier payload was captured and
    searched on 2026-09-15: there is no timestamp at the top level and none on
    a cargo item (``commodity``, ``locName``, ``mission``, ``originSystem``,
    ``qty``, ``stolen``, ``value``). And the endpoint lags the game by 14-31
    minutes, so the moment we fetched is emphatically not the moment the data
    describes.

    So both stamps here are OUR clock and say so:

        ``checked_at``  when the tool last asked Frontier
        ``changed_at``  when the answer last differed from the one before

    Together they separate "we have not looked" from "we looked and nothing
    has moved" -- a distinction this tab could not express at all, which is
    how it sat 5,348 t stale with nothing on the sheet to show it. Either may
    be empty, which reads as "not known"; an unknown stamp is left blank
    rather than defaulted to now, because "changed just now" is a claim, and
    the more dangerous one for looking reassuring.

    Row 1 was already a blank spacer, so none of this moves the header off
    row 2 or the commodities off row 4.
    """
    rows: list[list] = [
        # Labels in the key column, values beside them -- ShipCargo's idiom,
        # for its reason: no commodity is named "Last checked", so a VLOOKUP
        # over $B:$D can never land here.
        ["", "Last checked", checked_at, "Last changed", changed_at],
        header_row(["Total Value"]),             # row 2: B/C/D + this tab's tail
        ["", "TOTAL", f"=SUM(C4:C{3 + len(data)})", "",
         f"=SUM(E4:E{3 + len(data)})"],          # row 3: totals
    ]
    for i, item in enumerate(data):
        row_num = 4 + i
        rows.append(data_row(
            item["display_name"],
            item["quantity"],
            item["unit_price"],
            extra=[f"=C{row_num}*D{row_num}"],
        ))

    # Fail before writing rather than after. A tab whose columns have drifted
    # takes every VLOOKUP index in the workbook with it, silently.
    verify_contract(rows, header_row_index=1)
    return rows


class GoogleSheetsExporter:
    """Export data directly to Google Sheets."""

    # Tabs this class is permitted to REWRITE WHOLESALE.
    #
    # This used to be the inverse -- a deny list, PROTECTED_TABS = ["Base",
    # "1st", "2", "3", "Sheet3"] -- which failed open in the worst possible
    # way: three of those five tabs do not exist in the real workbook, while
    # every tab holding irreplaceable hand-entered work ("Totals Tab",
    # "Agri Lrg. (ex)", "Sat. (ex)", "Extr. (ex)") was absent from the list and
    # therefore writable. Any tab nobody thought of was fair game.
    #
    # An allow list fails closed. `export_cargo` calls worksheet.clear(), so
    # the only safe target is a tab this tool generates in full.
    WRITABLE_TABS = frozenset({"FreighterData", "MarketData", "ShipCargo"})

    # OAuth scopes required for Google Sheets
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        writable_tabs: Optional[Iterable[str]] = None,
        region_guard: Optional[WriteGuard] = None,
    ):
        """
        Initialize Google Sheets exporter.

        Args:
            credentials_path: Path to service account JSON or OAuth client secrets.
                             Defaults to ~/.ed_gsheet_credentials.json
            token_path: Path to store OAuth tokens.
                       Defaults to ~/.ed_gsheet_token.json
            writable_tabs: Override the wholesale-rewrite allow list. Only pass
                          this for a tab you are certain this tool generates.
            region_guard: Allowlist for writes to a REGION of a tab the tool
                          does not own outright. Absent, no region is writable:
                          a tab holding someone's hand-entered work is opted
                          into explicitly or not at all.
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
        self.writable_tabs = (
            frozenset(writable_tabs) if writable_tabs is not None else self.WRITABLE_TABS
        )
        self.region_guard = region_guard
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
                # Google access tokens last about an hour. Without this refresh
                # step the tool falls through to a full interactive consent
                # flow every time the hour rolls over -- which is merely
                # annoying for a one-off CLI run and completely fatal for a
                # long-running daemon, since nobody is at the keyboard to
                # click through a browser prompt.
                if not creds.valid and creds.expired and creds.refresh_token:
                    from google.auth.transport.requests import Request

                    creds.refresh(Request())
                    self._save_token(creds)

                if creds.valid:
                    self._client = _gspread.authorize(creds)
                    return self._client
            except Exception:
                # A revoked or malformed token falls through to a fresh
                # interactive authorization below.
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
        self._save_token(creds)

        self._client = _gspread.authorize(creds)
        return self._client

    def _save_token(self, creds: Any) -> None:
        """Persist credentials, including a token refreshed since last run."""
        try:
            self.token_path.write_text(creds.to_json())
        except OSError:
            # An unwritable token file costs a re-authorization next run, but
            # must not abort the operation the user actually asked for.
            pass

    def open_spreadsheet(self, sheet_id: str) -> Any:
        """Open a spreadsheet by id. Read-only by itself; writes go through callers."""
        return self._get_client().open_by_key(sheet_id)

    def worksheet(self, sheet_id: str, tab_name: str) -> Any:
        """
        Get one worksheet by title.

        Raises a clear error naming the tabs that DO exist, because a renamed
        or mistyped tab is the most common setup mistake and the default
        gspread message does not say what was available.
        """
        spreadsheet = self.open_spreadsheet(sheet_id)
        try:
            return spreadsheet.worksheet(tab_name)
        except _gspread.WorksheetNotFound:
            titles = [ws.title for ws in spreadsheet.worksheets()]
            raise ValueError(
                f"Tab {tab_name!r} not found in spreadsheet {sheet_id}. "
                f"Tabs present: {', '.join(repr(t) for t in titles)}"
            ) from None

    def worksheet_titles(self, sheet_id: str) -> list[str]:
        """List the tab names in a spreadsheet."""
        return [ws.title for ws in self.open_spreadsheet(sheet_id).worksheets()]

    def export_market(
        self,
        market,
        sheet_id: str,
        tab_name: str = "MarketData",
    ) -> int:
        """
        Write a station's market to a generated tab.

        The exact peer of :meth:`export_cargo`: this tool owns the tab and
        rewrites it wholesale; the spreadsheet decides what to do with it via
        its own formulas. The tool writes no glyphs, no colours and no opinion
        about presentation -- a market is a fact about a station, and how it
        should be displayed is the consumer's business.

        Consume it the same way the carrier's cargo is already consumed:

            =VLOOKUP($B5, MarketData!$B:$G, 2, FALSE)   -> stock
            =VLOOKUP($B5, MarketData!$B:$G, 3, FALSE)   -> buy price

        Returns the number of commodity rows written.

        Raises:
            ValueError: If the target tab is not on the wholesale-rewrite allow list
        """
        from ..market import sheet_grid

        return self.export_grid(sheet_grid(market), sheet_id, tab_name)

    @staticmethod
    def _write_region(worksheet: Any, destination: Destination, rows: list) -> None:
        """
        Clear the whole declared reserve, then write the grid inside it.

        Nothing about the previous write is remembered between calls, so a
        restarted process clears exactly as a fresh one does. That is not a
        stylistic preference about purity -- it is the difference between a
        correct clear and a silently incorrect one.

        The alternative is to remember the last extent and clear only that.
        It is cheaper, and it is correct in almost every scenario, which is
        what makes it dangerous: it fails only when the process restarts
        between two publishes, and then it clears a region it believes is
        empty and leaves the previous grid's tail behind. ``serve`` dies with
        its shell, so a restart between publishes is an ordinary Tuesday. The
        cells it strands are unrecoverable in practice, because afterwards
        nothing -- not the tool, not the sheet, not the reader -- has any
        record that they were ever written.

        Clearing the reserve rather than the grid is what makes a shrink safe:
        the reserve is declared, so its extent does not depend on what was
        written last time, or on anyone having been watching.
        """
        # A reserve that runs off the edge of the grid is silently CLIPPED by
        # Google Sheets, not rejected: the call succeeds and quietly covers
        # less than was declared. Measured on a 29-column tab with a reserve
        # ending at column AD -- the write returned success and the clear
        # stopped at AC. That divergence is invisible afterwards, and a
        # reserve that does not clear what it claims to is the one failure
        # this whole mechanism exists to prevent. So check it here, where the
        # worksheet's real extent is finally knowable.
        # Mind the asymmetry, which is a trap in its own right: CellRange
        # numbers ROWS from 1 and COLUMNS from 0, so the last valid column
        # index is one less than the column count while the last valid row
        # index equals the row count.
        rows_available = getattr(worksheet, "row_count", None)
        cols_available = getattr(worksheet, "col_count", None)
        bounds = destination.bounds
        if rows_available is not None and bounds.last_row > rows_available:
            raise WriteRefused(
                f"Refusing to write {destination.describe()}: the reserve ends "
                f"at row {bounds.last_row} but the tab has {rows_available} "
                f"rows. Sheets would clip the clear and report success. "
                f"Resize the tab or narrow the region."
            )
        if cols_available is not None and bounds.last_col >= cols_available:
            raise WriteRefused(
                f"Refusing to write {destination.describe()}: the reserve ends "
                f"at column {index_to_column(bounds.last_col)} but the tab has "
                f"{cols_available} columns (through "
                f"{index_to_column(cols_available - 1)}). Sheets would clip the "
                f"clear and report success. Resize the tab or narrow the region."
            )

        worksheet.batch_clear([destination.range_a1()])
        if not rows:
            return

        height = len(rows)
        width = max((len(r) for r in rows), default=0)
        first_col = destination.bounds.first_col
        first_row = destination.bounds.first_row
        target = (
            f"{index_to_column(first_col)}{first_row}:"
            f"{index_to_column(first_col + width - 1)}{first_row + height - 1}"
        )
        worksheet.update(rows, target, value_input_option="RAW")

    def _authorize(self, destination: Destination, rows: list) -> None:
        """
        Decide whether this write is permitted, before any of it happens.

        Two gates, because there are two kinds of ownership and conflating
        them is how a region writer becomes a way to widen writes:

        * A **whole tab** is one this tool generates in full, so the check is
          the wholesale-rewrite allow list, unchanged since it replaced a deny
          list that failed open.
        * A **region** sits on a tab holding someone's hand-entered work. It
          must be named by an explicit allowlist entry, and the grid must fit
          inside the reserve that entry describes. Absent a guard, no region
          is writable at all -- opting a tab in is deliberate or it does not
          happen.
        """
        if destination.owns_whole_tab:
            if destination.tab not in self.writable_tabs:
                raise ValueError(
                    f"Refusing to rewrite tab '{destination.tab}': this export "
                    f"clears the whole worksheet, so it is only permitted on "
                    f"tabs this tool generates. "
                    f"Allowed: {', '.join(sorted(self.writable_tabs))}"
                )
            return

        if self.region_guard is None:
            raise WriteRefused(
                f"Refusing to write {destination.describe()}: no region "
                f"allowlist is configured, so no region of a tab this tool "
                f"does not own is writable."
            )
        # Raises WriteRefused, naming what IS permitted, when the declared
        # reserve is not covered by the allowlist.
        self.region_guard.check(destination.tab, destination.range_a1())

        height = len(rows)
        width = max((len(r) for r in rows), default=0)
        if not destination.fits(rows=height, cols=width):
            raise WriteRefused(
                f"Refusing to write {destination.describe()}: the grid is "
                f"{height} rows x {width} columns but the reserve is "
                f"{destination.reserved_rows} x {destination.reserved_cols}. "
                f"Widen the declared region rather than spilling out of it."
            )

    def export_grid(
        self,
        rows: list,
        sheet_id: str,
        tab_name: "str | Destination" = "MarketData",
    ) -> int:
        """
        Write a prepared grid to a generated tab, or to a region of one.

        Domain-neutral on purpose: it takes rows somebody else built and does
        not care whether they describe a market, a ship's hold, or something
        not written yet. Split out from :meth:`export_market` so callers can
        write the deliberately-empty grid when there is nothing current --
        actively clearing the target rather than leaving the previous contents
        sitting there looking fresh.

        ``tab_name`` may be a plain tab name, which means the tool owns that
        whole tab -- the shape every generated tab has always had, and the
        degenerate case of a region whose bounds are the sheet. Pass a
        :class:`~APITool.sheets.Destination` instead to publish into a
        rectangle of a tab that holds other content too.

        Assumes three leading rows of metadata and headers, which every
        generated tab in this project uses, and reports the count of data
        rows below them.
        """
        destination = (
            tab_name if isinstance(tab_name, Destination)
            else Destination.whole_tab(tab_name)
        )
        self._authorize(destination, rows)

        spreadsheet = self._get_client().open_by_key(sheet_id)
        try:
            worksheet = spreadsheet.worksheet(destination.tab)
        except _gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=destination.tab, rows=max(len(rows) + 20, 100), cols=8
            )

        if destination.owns_whole_tab:
            worksheet.clear()
            worksheet.update(rows, value_input_option="RAW")
        else:
            self._write_region(worksheet, destination, rows)
        # Three rows of metadata and headers precede the commodities.
        return max(0, len(rows) - 3)

    def export_cargo(
        self,
        carrier: FleetCarrier,
        sheet_id: str,
        tab_name: str = "FreighterData",
        include_stolen: bool = False,
        include_mission: bool = False,
        checked_at: str = "",
        changed_at: str = "",
    ) -> int:
        """
        Export cargo data directly to a Google Sheet.

        Returns the number of commodity rows written, for the caller to
        report as it sees fit -- matching ``export_grid``, and for the same
        reason: a writer that prints takes the reporting decision away from
        whoever called it.

        Args:
            carrier: FleetCarrier data
            sheet_id: Google Sheet ID (from URL)
            tab_name: Name of tab to write to (default: "FreighterData")
            include_stolen: Include stolen cargo items
            include_mission: Include mission-reserved cargo items
            checked_at: when the tool last asked Frontier, ISO-8601. Ours,
                not Frontier's -- see :func:`carrier_grid`
            changed_at: when the answer last differed. Blank if not known

        Raises:
            ValueError: If the target tab is not on the wholesale-rewrite allow list
        """
        # Safety check: this method calls worksheet.clear(), so it may only
        # target a tab this tool generates in full. Deny by default.
        if tab_name not in self.writable_tabs:
            raise ValueError(
                f"Refusing to rewrite tab '{tab_name}': this export clears the whole "
                f"worksheet, so it is only permitted on tabs this tool generates. "
                f"Allowed: {', '.join(sorted(self.writable_tabs))}"
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

        rows = carrier_grid(data, checked_at=checked_at, changed_at=changed_at)

        # Batch update for efficiency
        worksheet.update(rows, value_input_option="USER_ENTERED")

        # Returned, never printed. A library function writing to stdout means
        # the caller cannot choose whether, where, or how to report -- and
        # once this began being called on EVERY check rather than only when
        # the hold changed, that print fired beside a "nothing changed" line
        # and the pair read as a contradiction. `cmd_carrier` reports its own
        # exports; the daemon builds its own message from the result.
        return len(data)
