"""
Microsoft Graph OAuth — device-code flow + persistent token cache.

Single source of truth for access tokens. All engine skills (compose-and-send,
ingest-builder-stocklist, one-part-prompt, one-part-collect) call get_access_token()
to receive a current bearer token for Graph API calls.

First run: prints a device code + URL; user signs in as Tom in a browser.
Subsequent runs: silent — refresh token does the work for ~90 days.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import msal
from dotenv import load_dotenv

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_DIR = BUNDLE_ROOT / ".credentials"
TOKEN_CACHE_PATH = CREDENTIALS_DIR / "token.json"

load_dotenv(BUNDLE_ROOT / ".env")


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if not cache.has_state_changed:
        return
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")


def _build_app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        client_id=os.environ["BOLST_AZURE_CLIENT_ID"],
        authority=os.environ["BOLST_AZURE_AUTHORITY"],
        token_cache=cache,
    )


def get_access_token() -> str:
    """Return a current Graph access token. Runs interactive device-code flow if no cached refresh token exists."""
    scopes = os.environ["BOLST_AZURE_SCOPES"].split()
    cache = _load_cache()
    app = _build_app(cache)

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache)
            return result["access_token"]

    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise RuntimeError(f"Failed to start device flow: {json.dumps(flow, indent=2)}")

    print("=" * 70, file=sys.stderr)
    print(flow["message"], file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Device flow failed: {json.dumps(result, indent=2)}")

    _save_cache(cache)
    return result["access_token"]


if __name__ == "__main__":
    token = get_access_token()
    print(f"OK — got access token, length {len(token)}, prefix {token[:24]}...")
