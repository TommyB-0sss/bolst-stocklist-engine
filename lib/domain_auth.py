"""
Domain.com.au OAuth — Authorization Code flow + persistent token cache.

Single source of truth for Domain API access tokens. Mirrors the public shape
of lib/auth.py (which handles Microsoft Graph): callers use get_access_token()
and the auth flow is hidden inside this module.

First run: opens Tom's browser to Domain's consent page; redirect is caught
by a tiny localhost server on :8765; auth code is exchanged for tokens.
Subsequent runs: silent — refresh token does the work for ~90 days.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_DIR = BUNDLE_ROOT / ".credentials"
TOKEN_CACHE_PATH = CREDENTIALS_DIR / "domain_token.json"

DOMAIN_AUTH_URL = "https://auth.domain.com.au/v1/connect/authorize"
DOMAIN_TOKEN_URL = "https://auth.domain.com.au/v1/connect/token"

REDIRECT_HOST = "localhost"
REDIRECT_PORT = 8765
REDIRECT_PATH = "/callback"
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}{REDIRECT_PATH}"

DEFAULT_SCOPES = "openid api_listings_read api_agencies_read offline_access"

load_dotenv(BUNDLE_ROOT / ".env")


def _load_cache() -> dict:
    if TOKEN_CACHE_PATH.exists():
        return json.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(token_data: dict) -> None:
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    token_data["expires_at"] = int(time.time()) + token_data.get("expires_in", 0) - 60
    TOKEN_CACHE_PATH.write_text(json.dumps(token_data, indent=2), encoding="utf-8")


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    creds = f"{client_id}:{client_secret}"
    return "Basic " + base64.b64encode(creds.encode("ascii")).decode("ascii")


def _post_token(form: dict) -> dict:
    client_id = os.environ["DOMAIN_CLIENT_ID"]
    client_secret = os.environ["DOMAIN_CLIENT_SECRET"]
    response = requests.post(
        DOMAIN_TOKEN_URL,
        headers={"Authorization": _basic_auth_header(client_id, client_secret)},
        data=form,
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Domain token endpoint returned {response.status_code}: {response.text}"
        )
    return response.json()


class _CallbackHandler(BaseHTTPRequestHandler):
    captured_code: str | None = None
    captured_state: str | None = None
    captured_error: str | None = None

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        parsed = urlparse(self.path)
        if parsed.path != REDIRECT_PATH:
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        _CallbackHandler.captured_code = params.get("code", [None])[0]
        _CallbackHandler.captured_state = params.get("state", [None])[0]
        _CallbackHandler.captured_error = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if _CallbackHandler.captured_error:
            self.wfile.write(
                f"<h1>Auth failed: {_CallbackHandler.captured_error}</h1>".encode("utf-8")
            )
        else:
            self.wfile.write(
                b"<h1>Domain auth complete.</h1><p>You can close this tab and return to the terminal.</p>"
            )

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


def _run_authorization_code_flow() -> dict:
    client_id = os.environ["DOMAIN_CLIENT_ID"]
    scopes = os.environ.get("DOMAIN_SCOPES", DEFAULT_SCOPES)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)

    auth_url = DOMAIN_AUTH_URL + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": scopes,
        "state": state,
        "nonce": nonce,
    })

    _CallbackHandler.captured_code = None
    _CallbackHandler.captured_state = None
    _CallbackHandler.captured_error = None

    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _CallbackHandler)

    print("=" * 70, file=sys.stderr)
    print("Opening browser for Domain.com.au authorisation...", file=sys.stderr)
    print(f"If the browser does not open, visit this URL manually:", file=sys.stderr)
    print(auth_url, file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    webbrowser.open(auth_url)

    while _CallbackHandler.captured_code is None and _CallbackHandler.captured_error is None:
        server.handle_request()

    if _CallbackHandler.captured_error:
        raise RuntimeError(f"Domain auth returned error: {_CallbackHandler.captured_error}")

    if _CallbackHandler.captured_state != state:
        raise RuntimeError(
            f"State mismatch (possible CSRF): expected {state!r}, got {_CallbackHandler.captured_state!r}"
        )

    return _post_token({
        "grant_type": "authorization_code",
        "code": _CallbackHandler.captured_code,
        "redirect_uri": REDIRECT_URI,
    })


def get_access_token() -> str:
    """Return a current Domain API access token.

    Refreshes silently using the cached refresh_token when possible.
    Falls back to interactive Authorization Code flow if no cached
    refresh token exists or refresh fails.
    """
    cache = _load_cache()

    if cache.get("access_token") and cache.get("expires_at", 0) > time.time():
        return cache["access_token"]

    if cache.get("refresh_token"):
        try:
            new_tokens = _post_token({
                "grant_type": "refresh_token",
                "refresh_token": cache["refresh_token"],
            })
            new_tokens.setdefault("refresh_token", cache["refresh_token"])
            _save_cache(new_tokens)
            return new_tokens["access_token"]
        except RuntimeError as exc:
            print(f"Silent refresh failed, re-authenticating: {exc}", file=sys.stderr)

    new_tokens = _run_authorization_code_flow()
    if "refresh_token" not in new_tokens:
        raise RuntimeError(
            "Domain did not return a refresh_token. Ensure 'offline_access' is in DOMAIN_SCOPES."
        )
    _save_cache(new_tokens)
    return new_tokens["access_token"]


if __name__ == "__main__":
    token = get_access_token()
    print(f"OK — got Domain access token, length {len(token)}, prefix {token[:24]}...")
