"""
OAuth2 authentication handler for Frontier's CAPI service.

To use the CAPI, you need to:
1. Register your application at https://auth.frontierstore.net/client/signup
2. Obtain a client_id
3. Use this module to authenticate users via OAuth2

Note: Tokens expire and need refresh every ~25 days.
"""

import json
import secrets
import webbrowser
import hashlib
import base64
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
import threading

import requests

from .config import (
    AUTH_SERVER,
    AUTH_PATH_AUTH,
    AUTH_PATH_TOKEN,
    TOKEN_FILE,
    OAUTH_SCOPES,
)


class TokenStorage:
    """Handles secure storage and retrieval of OAuth tokens."""

    def __init__(self, token_file: Optional[Path] = None):
        self.token_file = token_file or Path.home() / TOKEN_FILE

    def save(self, tokens: dict) -> None:
        """Save tokens to file."""
        tokens["saved_at"] = datetime.now().isoformat()
        self.token_file.write_text(json.dumps(tokens, indent=2))
        # Set restrictive permissions on Unix systems
        try:
            self.token_file.chmod(0o600)
        except (OSError, AttributeError):
            pass  # Windows doesn't support chmod the same way

    def load(self) -> Optional[dict]:
        """Load tokens from file if they exist."""
        if not self.token_file.exists():
            return None
        try:
            return json.loads(self.token_file.read_text())
        except (json.JSONDecodeError, IOError):
            return None

    def clear(self) -> None:
        """Remove stored tokens."""
        if self.token_file.exists():
            self.token_file.unlink()


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth2 callback."""

    def log_message(self, format, *args):
        """Suppress HTTP server logs."""
        pass

    def do_GET(self):
        """Handle the OAuth callback."""
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        if "code" in query:
            self.server.auth_code = query["code"][0]
            self.server.auth_state = query.get("state", [None])[0]
            response = b"<html><body><h1>Authorization successful!</h1><p>You can close this window.</p></body></html>"
            self.send_response(200)
        else:
            self.server.auth_code = None
            self.server.auth_error = query.get("error", ["unknown"])[0]
            response = b"<html><body><h1>Authorization failed</h1><p>Please try again.</p></body></html>"
            self.send_response(400)

        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(response)


class FrontierAuth:
    """
    Handles OAuth2 authentication with Frontier's auth service.

    Uses PKCE (Proof Key for Code Exchange) for security.

    Supports two authorization modes:
    - Automatic: Local HTTP server captures callback (requires localhost redirect)
    - Manual: User copies authorization code from browser URL
    """

    # Default redirect URI for manual auth flow (doesn't need to be a real server)
    DEFAULT_REDIRECT_URI = "https://localhost/callback"

    def __init__(
        self,
        client_id: str,
        redirect_uri: Optional[str] = None,
        redirect_port: int = 8085,
        token_storage: Optional[TokenStorage] = None,
    ):
        """
        Initialize the auth handler.

        Args:
            client_id: Your registered application's client ID
            redirect_uri: Custom redirect URI (for manual flow or custom domains)
            redirect_port: Local port for OAuth callback (default 8085, ignored if redirect_uri set)
            token_storage: Optional custom token storage handler
        """
        self.client_id = client_id
        self.redirect_port = redirect_port
        self.storage = token_storage or TokenStorage()

        # Use custom redirect_uri if provided, otherwise default to localhost
        if redirect_uri:
            self.redirect_uri = redirect_uri
            self._use_local_server = False
        else:
            self.redirect_uri = f"http://localhost:{redirect_port}/callback"
            self._use_local_server = True

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

        # Store PKCE verifier for manual flow
        self._pending_verifier: Optional[str] = None
        self._pending_state: Optional[str] = None

        # Try to load existing tokens
        self._load_tokens()

    def _load_tokens(self) -> bool:
        """Load tokens from storage."""
        tokens = self.storage.load()
        if tokens:
            self._access_token = tokens.get("access_token")
            self._refresh_token = tokens.get("refresh_token")
            if "expires_at" in tokens:
                self._token_expiry = datetime.fromisoformat(tokens["expires_at"])
            return True
        return False

    def _save_tokens(self) -> None:
        """Save current tokens to storage."""
        if self._access_token:
            tokens = {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "expires_at": self._token_expiry.isoformat()
                if self._token_expiry
                else None,
            }
            self.storage.save(tokens)

    def _generate_pkce(self) -> tuple[str, str]:
        """Generate PKCE code verifier and challenge."""
        # Generate random verifier (43-128 chars)
        verifier = secrets.token_urlsafe(32)

        # Create SHA256 hash, then base64url encode
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

        return verifier, challenge

    @property
    def is_authenticated(self) -> bool:
        """Check if we have valid tokens."""
        if not self._access_token:
            return False
        if self._token_expiry and datetime.now() >= self._token_expiry:
            return False
        return True

    @property
    def access_token(self) -> Optional[str]:
        """Get the current access token, refreshing if needed."""
        if not self._access_token:
            return None

        # Check if token is expired or about to expire (5 min buffer)
        if self._token_expiry:
            if datetime.now() >= self._token_expiry - timedelta(minutes=5):
                if self._refresh_token:
                    self.refresh()

        return self._access_token

    def authorize(self, timeout: int = 120, manual: bool = False) -> bool:
        """
        Initiate OAuth2 authorization flow.

        Args:
            timeout: Seconds to wait for user authorization (auto mode only)
            manual: If True, use manual code entry instead of local server

        Returns:
            True if authorization successful
        """
        # Force manual mode if not using local server
        if not self._use_local_server:
            manual = True

        if manual:
            return self.authorize_manual()
        else:
            return self.authorize_auto(timeout)

    def authorize_auto(self, timeout: int = 120) -> bool:
        """
        Automatic authorization using local HTTP server.

        Opens browser for user to authorize, then captures callback.

        Args:
            timeout: Seconds to wait for user authorization

        Returns:
            True if authorization successful
        """
        # Generate PKCE values
        verifier, challenge = self._generate_pkce()
        state = secrets.token_urlsafe(16)

        # Build authorization URL
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(OAUTH_SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{AUTH_SERVER}{AUTH_PATH_AUTH}?{urllib.parse.urlencode(params)}"

        # Start local server to receive callback
        try:
            server = HTTPServer(("localhost", self.redirect_port), OAuthCallbackHandler)
        except OSError as e:
            print(f"Could not start local server on port {self.redirect_port}: {e}")
            print("Falling back to manual authorization...")
            return self.authorize_manual()

        server.auth_code = None
        server.auth_error = None
        server.auth_state = None
        server.timeout = timeout

        # Open browser
        print(f"Opening browser for authorization...")
        print(f"If browser doesn't open, visit: {auth_url}")
        webbrowser.open(auth_url)

        # Wait for callback (with timeout)
        server.handle_request()
        server.server_close()

        if not server.auth_code:
            print(f"Authorization failed: {server.auth_error}")
            return False

        if server.auth_state != state:
            print("Authorization failed: state mismatch (possible CSRF attack)")
            return False

        # Exchange code for tokens
        return self._exchange_code(server.auth_code, verifier)

    def authorize_manual(self) -> bool:
        """
        Manual authorization flow - user copies code from browser URL.

        This flow works even if the redirect URI doesn't point to a real server.
        The user will see a "page not found" error but can copy the code from the URL.

        Returns:
            True if authorization successful
        """
        # Generate PKCE values
        verifier, challenge = self._generate_pkce()
        state = secrets.token_urlsafe(16)

        # Store for later use
        self._pending_verifier = verifier
        self._pending_state = state

        # Build authorization URL
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(OAUTH_SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{AUTH_SERVER}{AUTH_PATH_AUTH}?{urllib.parse.urlencode(params)}"

        print()
        print("=" * 60)
        print("MANUAL AUTHORIZATION FLOW")
        print("=" * 60)
        print()
        print("1. Open this URL in your browser:")
        print()
        print(f"   {auth_url}")
        print()
        print("2. Log in to your Frontier account and authorize the app")
        print()
        print("3. You'll be redirected to a page that may show an error")
        print("   (This is expected if the redirect URL isn't a real server)")
        print()
        print("4. Copy the ENTIRE URL from your browser's address bar")
        print("   It will look like: https://...?code=XXXXX&state=YYYYY")
        print()
        print("=" * 60)
        print()

        # Try to open browser
        try:
            webbrowser.open(auth_url)
            print("(Browser should have opened automatically)")
            print()
        except Exception:
            pass

        # Get the callback URL from user
        callback_url = input("Paste the full callback URL here: ").strip()

        if not callback_url:
            print("No URL provided.")
            return False

        return self.complete_manual_auth(callback_url)

    def complete_manual_auth(self, callback_url: str) -> bool:
        """
        Complete manual authorization by parsing the callback URL.

        Args:
            callback_url: The full URL from the browser after authorization

        Returns:
            True if authorization successful
        """
        if not self._pending_verifier:
            print("No pending authorization. Call authorize_manual() first.")
            return False

        # Parse the callback URL
        try:
            parsed = urllib.parse.urlparse(callback_url)
            query = urllib.parse.parse_qs(parsed.query)
        except Exception as e:
            print(f"Could not parse URL: {e}")
            return False

        # Check for error
        if "error" in query:
            error = query["error"][0]
            error_desc = query.get("error_description", [""])[0]
            print(f"Authorization failed: {error}")
            if error_desc:
                print(f"  {error_desc}")
            return False

        # Get the code
        if "code" not in query:
            print("No authorization code found in URL.")
            print("Make sure you copied the complete URL including the ?code=... part")
            return False

        code = query["code"][0]

        # Verify state if present
        if "state" in query:
            if query["state"][0] != self._pending_state:
                print("Warning: State mismatch. This could indicate a security issue.")
                # Continue anyway for usability, but warn the user

        # Exchange code for tokens
        verifier = self._pending_verifier
        self._pending_verifier = None
        self._pending_state = None

        return self._exchange_code(code, verifier)

    def _exchange_code(self, code: str, verifier: str) -> bool:
        """Exchange authorization code for tokens."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }

        try:
            response = requests.post(
                f"{AUTH_SERVER}{AUTH_PATH_TOKEN}",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            response.raise_for_status()

            tokens = response.json()
            self._access_token = tokens["access_token"]
            self._refresh_token = tokens.get("refresh_token")

            # Calculate expiry time
            expires_in = tokens.get("expires_in", 3600)
            self._token_expiry = datetime.now() + timedelta(seconds=expires_in)

            self._save_tokens()
            print("Authorization successful!")
            return True

        except requests.RequestException as e:
            print(f"Token exchange failed: {e}")
            return False

    def refresh(self) -> bool:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            print("No refresh token available")
            return False

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self.client_id,
        }

        try:
            response = requests.post(
                f"{AUTH_SERVER}{AUTH_PATH_TOKEN}",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            response.raise_for_status()

            tokens = response.json()
            self._access_token = tokens["access_token"]
            self._refresh_token = tokens.get("refresh_token", self._refresh_token)

            expires_in = tokens.get("expires_in", 3600)
            self._token_expiry = datetime.now() + timedelta(seconds=expires_in)

            self._save_tokens()
            return True

        except requests.RequestException as e:
            print(f"Token refresh failed: {e}")
            return False

    def logout(self) -> None:
        """Clear stored tokens."""
        self._access_token = None
        self._refresh_token = None
        self._token_expiry = None
        self.storage.clear()
