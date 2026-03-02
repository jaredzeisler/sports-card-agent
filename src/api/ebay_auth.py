"""eBay OAuth2 token management with browser-based auth and token refresh."""

import base64
import json
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from datetime import datetime, timezone

import httpx

from config.settings import get_settings

TOKEN_FILE = Path(__file__).resolve().parent.parent.parent / ".ebay_tokens.json"

# eBay OAuth2 scopes needed for selling
SELL_SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.finances",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
]


def _basic_auth(settings=None) -> str:
    s = settings or get_settings()
    return base64.b64encode(f"{s.ebay_app_id}:{s.ebay_cert_id}".encode()).decode()


def _token_url(settings=None) -> str:
    s = settings or get_settings()
    if s.ebay_sandbox:
        return "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    return "https://api.ebay.com/identity/v1/oauth2/token"


def _auth_url(settings=None) -> str:
    s = settings or get_settings()
    if s.ebay_sandbox:
        return "https://auth.sandbox.ebay.com/oauth2/authorize"
    return "https://auth.ebay.com/oauth2/authorize"


def save_tokens(tokens: dict):
    """Persist tokens to disk."""
    tokens["saved_at"] = datetime.now(timezone.utc).isoformat()
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


def load_tokens() -> dict | None:
    """Load tokens from disk."""
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def exchange_code_for_tokens(code: str, redirect_uri: str, settings=None) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    s = settings or get_settings()
    resp = httpx.post(
        _token_url(s),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {_basic_auth(s)}",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    tokens = {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data["expires_in"],
        "refresh_token_expires_in": data.get("refresh_token_expires_in", 47304000),
        "obtained_at": time.time(),
    }
    save_tokens(tokens)
    return tokens


def refresh_access_token(refresh_token: str, settings=None) -> dict:
    """Use refresh token to get a new access token."""
    s = settings or get_settings()
    resp = httpx.post(
        _token_url(s),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {_basic_auth(s)}",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(SELL_SCOPES),
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    tokens = load_tokens() or {}
    tokens["access_token"] = data["access_token"]
    tokens["expires_in"] = data["expires_in"]
    tokens["obtained_at"] = time.time()
    save_tokens(tokens)
    return tokens


def get_valid_user_token(settings=None) -> str:
    """Get a valid user access token, refreshing if needed.

    Falls back to the static token in .env if no OAuth tokens are stored.
    """
    s = settings or get_settings()

    tokens = load_tokens()
    if tokens:
        elapsed = time.time() - tokens.get("obtained_at", 0)
        expires_in = tokens.get("expires_in", 7200)
        if elapsed < expires_in - 300:  # 5 min buffer
            return tokens["access_token"]

        # Try refresh
        if tokens.get("refresh_token"):
            try:
                refreshed = refresh_access_token(tokens["refresh_token"], s)
                return refreshed["access_token"]
            except httpx.HTTPStatusError:
                pass  # Refresh token may be expired

    # Fallback to static token from .env
    if s.ebay_user_token:
        return s.ebay_user_token

    raise RuntimeError(
        "No valid eBay user token. Run 'cardagent ebay auth' to authenticate."
    )


def start_auth_flow(port: int = 8471, settings=None) -> dict:
    """Start the OAuth2 authorization code flow.

    Opens the browser for user consent, captures the redirect, and exchanges
    the code for tokens.
    """
    s = settings or get_settings()
    redirect_uri = f"http://localhost:{port}/callback"

    # If no redirect URI configured, use the RuName from .env or this local one
    ru_name = s.ebay_redirect_uri or redirect_uri

    auth_params = {
        "client_id": s.ebay_app_id,
        "response_type": "code",
        "redirect_uri": ru_name,
        "scope": " ".join(SELL_SCOPES),
    }
    consent_url = f"{_auth_url(s)}?{urlencode(auth_params)}"

    # Capture the auth code via a temporary local server
    auth_code = None

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            auth_code = qs.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>eBay authorization successful!</h2>"
                b"<p>You can close this tab and return to the terminal.</p></body></html>"
            )

        def log_message(self, fmt, *args):
            pass  # Suppress server logs

    print(f"\nOpening eBay consent page in your browser...")
    print(f"If it doesn't open, visit:\n{consent_url}\n")
    webbrowser.open(consent_url)

    server = HTTPServer(("localhost", port), CallbackHandler)
    server.timeout = 120  # 2 minute timeout
    server.handle_request()

    if not auth_code:
        raise RuntimeError("Did not receive authorization code from eBay.")

    tokens = exchange_code_for_tokens(auth_code, ru_name, s)
    print("eBay authentication successful! Tokens saved.")
    return tokens
