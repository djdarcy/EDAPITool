"""
Elite Dangerous Companion API (CAPI) client.

Provides access to game data including:
- Commander profile
- Market data
- Fleet carrier information
- Ship/module data
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import requests

from .config import (
    CAPI_SERVER_LIVE,
    CAPI_SERVER_LEGACY,
    CAPI_SERVER_BETA,
    CAPI_PATH_PROFILE,
    CAPI_PATH_MARKET,
    CAPI_PATH_SHIPYARD,
    CAPI_PATH_FLEETCARRIER,
    CAPI_PATH_COMMUNITYGOALS,
    DEFAULT_TIMEOUT,
    FLEETCARRIER_TIMEOUT,
    MIN_QUERY_INTERVAL,
    FLEETCARRIER_COOLDOWN,
)
from .auth import FrontierAuth


class CAPIError(Exception):
    """Base exception for CAPI errors."""

    pass


class CAPIAuthError(CAPIError):
    """Authentication error with CAPI."""

    pass


class CAPIRateLimitError(CAPIError):
    """Rate limit exceeded."""

    pass


class CAPINoDataError(CAPIError):
    """No data available (e.g., no fleet carrier owned)."""

    pass


class CAPIClient:
    """
    Client for the Elite Dangerous Companion API.

    Example usage:
        auth = FrontierAuth(client_id="your_client_id")
        if not auth.is_authenticated:
            auth.authorize()

        client = CAPIClient(auth)
        profile = client.get_profile()
        carrier = client.get_fleet_carrier()
    """

    def __init__(
        self,
        auth: FrontierAuth,
        server: str = CAPI_SERVER_LIVE,
        debug_dir: Optional[Path] = None,
    ):
        """
        Initialize the CAPI client.

        Args:
            auth: Authenticated FrontierAuth instance
            server: CAPI server URL (default: live server)
            debug_dir: Optional directory to save debug JSON responses
        """
        self.auth = auth
        self.server = server
        self.debug_dir = debug_dir
        self._last_query_time: float = 0
        self._last_fc_query_time: float = 0

    def _get_headers(self) -> dict:
        """Get request headers with authorization."""
        token = self.auth.access_token
        if not token:
            raise CAPIAuthError("No access token available. Please authenticate first.")
        return {
            "Authorization": f"Bearer {token}",
            "User-Agent": "EDAPITool/0.1.0",
        }

    def _check_rate_limit(self, is_fleet_carrier: bool = False) -> None:
        """Check and enforce rate limiting."""
        now = time.time()

        if is_fleet_carrier:
            elapsed = now - self._last_fc_query_time
            if elapsed < FLEETCARRIER_COOLDOWN:
                wait_time = FLEETCARRIER_COOLDOWN - elapsed
                raise CAPIRateLimitError(
                    f"Fleet carrier query cooldown. Wait {wait_time:.0f} seconds."
                )
        else:
            elapsed = now - self._last_query_time
            if elapsed < MIN_QUERY_INTERVAL:
                # For regular queries, just wait
                time.sleep(MIN_QUERY_INTERVAL - elapsed)

    def _save_debug(self, endpoint: str, data: dict) -> None:
        """Save response to debug file if debug_dir is set."""
        if not self.debug_dir:
            return

        self.debug_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        endpoint_name = endpoint.strip("/").replace("/", "_")
        filename = f"{endpoint_name}.{timestamp}.json"
        filepath = self.debug_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _request(
        self,
        endpoint: str,
        timeout: int = DEFAULT_TIMEOUT,
        is_fleet_carrier: bool = False,
    ) -> dict:
        """
        Make an authenticated request to the CAPI.

        Args:
            endpoint: API endpoint path
            timeout: Request timeout in seconds
            is_fleet_carrier: Whether this is a fleet carrier query

        Returns:
            JSON response as dictionary

        Raises:
            CAPIAuthError: Authentication failed
            CAPIRateLimitError: Rate limit exceeded
            CAPINoDataError: No data available
            CAPIError: Other API errors
        """
        self._check_rate_limit(is_fleet_carrier)

        url = f"{self.server}{endpoint}"

        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=timeout,
            )

            # Update query times
            if is_fleet_carrier:
                self._last_fc_query_time = time.time()
            self._last_query_time = time.time()

            # Handle response codes
            if response.status_code == 200:
                data = response.json()
                self._save_debug(endpoint, data)
                return data

            elif response.status_code == 204:
                raise CAPINoDataError(f"No data available for {endpoint}")

            elif response.status_code == 401:
                raise CAPIAuthError("Authentication failed. Token may be expired.")

            elif response.status_code == 422:
                # Token expired, try to refresh
                if self.auth.refresh():
                    # Retry the request
                    return self._request(endpoint, timeout, is_fleet_carrier)
                raise CAPIAuthError("Token expired and refresh failed.")

            elif response.status_code == 429:
                raise CAPIRateLimitError("Rate limit exceeded. Please wait.")

            else:
                raise CAPIError(
                    f"CAPI request failed: {response.status_code} - {response.text}"
                )

        except requests.Timeout:
            raise CAPIError(f"Request timed out after {timeout} seconds")
        except requests.RequestException as e:
            raise CAPIError(f"Request failed: {e}")

    def get_profile(self) -> dict:
        """
        Get commander profile data.

        Returns:
            Commander profile including name, credits, ranks, ships, etc.
        """
        return self._request(CAPI_PATH_PROFILE)

    def get_market(self) -> dict:
        """
        Get current station market data.

        Returns:
            Market data for the current docked station.
        """
        return self._request(CAPI_PATH_MARKET)

    def get_shipyard(self) -> dict:
        """
        Get current station shipyard data.

        Returns:
            Available ships at the current docked station.
        """
        return self._request(CAPI_PATH_SHIPYARD)

    def get_fleet_carrier(self) -> dict:
        """
        Get fleet carrier data.

        Returns:
            Complete fleet carrier data including:
            - Identity (callsign, name)
            - Location and status
            - Cargo and inventory
            - Market orders
            - Financial information
            - Services and crew
            - Travel history

        Raises:
            CAPINoDataError: Player doesn't own a fleet carrier
            CAPIRateLimitError: Must wait 15 minutes between queries
        """
        return self._request(
            CAPI_PATH_FLEETCARRIER,
            timeout=FLEETCARRIER_TIMEOUT,
            is_fleet_carrier=True,
        )

    def get_community_goals(self) -> dict:
        """
        Get active community goals.

        Returns:
            List of active community goals with progress.
        """
        return self._request(CAPI_PATH_COMMUNITYGOALS)

    @staticmethod
    def use_live_server() -> str:
        """Get the live server URL."""
        return CAPI_SERVER_LIVE

    @staticmethod
    def use_legacy_server() -> str:
        """Get the legacy server URL."""
        return CAPI_SERVER_LEGACY

    @staticmethod
    def use_beta_server() -> str:
        """Get the beta/PTS server URL."""
        return CAPI_SERVER_BETA
