"""
Microsoft Graph authentication — one entry point, two modes.

    get_access_token()  -> bearer token for Graph
    graph_user_base()   -> "https://graph.microsoft.com/v1.0/me"             (delegated)
                           "https://graph.microsoft.com/v1.0/users/<mailbox>" (app-only)

APP-ONLY mode (preferred — added 2026-09-11 after the third token outage)
------------------------------------------------------------------------
OAuth 2.0 client-credentials grant. The engine authenticates AS THE ENTRA APP
REGISTRATION, using a client secret (the form chosen 2026-09-11 — Microsoft's
24-month portal maximum is enough for now) or a certificate (supported, deferred;
wins if both are set), and reaches
Tom's mailbox through /users/<mailbox>/... with APPLICATION permissions
(Mail.Read + Mail.Send, admin-consented, restricted to Tom's mailbox by an
Exchange application access policy — RUNBOOK §9).

Why: the delegated design froze a user refresh token into a static cloud
secret. Every Tom password reset (3 Aug 2026, then the Sep hack-attempt reset)
revoked it, and the frozen snapshot also aged out after ~1 month in July.
Client credentials hold NO refresh token: every run mints a fresh ~1-hour
access token from the app credential, so neither failure mode exists. The only
remaining maintenance is the credential's own expiry, which is a known date
that log_credential_expiry() prints on every run.

App-only is selected automatically when one of these is set:
    BOLST_AZURE_CLIENT_CERT_PEM_B64    base64 (ONE line) of a PEM bundle holding
                                       the private key + the certificate
    BOLST_AZURE_CLIENT_CERT_PEM_PATH   the same bundle as a file (local dev)
    BOLST_AZURE_CLIENT_SECRET          a client secret (simpler; max 2-year life)
Optional:
    BOLST_AZURE_CLIENT_CERT_THUMBPRINT SHA-1 hex; only needed if the PEM bundle
                                       has no CERTIFICATE block to derive it from
    BOLST_AZURE_CLIENT_SECRET_EXPIRES  YYYY-MM-DD as shown in the portal, so the
                                       expiry logger can count down
    BOLST_MAILBOX                      mailbox to read from / send as; defaults
                                       to BOLST_REPORT_SENDER
    BOLST_AUTH_MODE                    app | delegated | auto (default auto)

DELEGATED mode (legacy fallback)
--------------------------------
Device-code flow + persistent MSAL cache in .credentials/token.json. Kept so
the engine keeps running until admin consent is granted. Delete once app-only
is live in the cloud.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import msal
from dotenv import load_dotenv

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_DIR = BUNDLE_ROOT / ".credentials"
TOKEN_CACHE_PATH = CREDENTIALS_DIR / "token.json"

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
APP_ONLY_SCOPES = ["https://graph.microsoft.com/.default"]
EXPIRY_WARN_DAYS = 60

load_dotenv(BUNDLE_ROOT / ".env")


class GraphAuthError(RuntimeError):
    """No Graph access token could be obtained. The message carries the AADSTS
    code + description so the routine log explains itself."""


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------

def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _has_app_credential() -> bool:
    return bool(
        _env("BOLST_AZURE_CLIENT_CERT_PEM_B64")
        or _env("BOLST_AZURE_CLIENT_CERT_PEM_PATH")
        or _env("BOLST_AZURE_CLIENT_SECRET")
    )


def auth_mode() -> str:
    """'app' (client credentials) or 'delegated' (device-code flow)."""
    forced = _env("BOLST_AUTH_MODE").lower()
    if forced == "app":
        if not _has_app_credential():
            raise GraphAuthError(
                "BOLST_AUTH_MODE=app but no app credential is set "
                "(BOLST_AZURE_CLIENT_CERT_PEM_B64 / _PATH or BOLST_AZURE_CLIENT_SECRET)"
            )
        return "app"
    if forced == "delegated":
        return "delegated"
    if forced and forced != "auto":
        raise GraphAuthError(
            f"BOLST_AUTH_MODE must be app | delegated | auto, got {forced!r}"
        )
    return "app" if _has_app_credential() else "delegated"


def mailbox() -> str:
    """The mailbox the engine reads from and sends as in app-only mode."""
    mb = _env("BOLST_MAILBOX") or _env("BOLST_REPORT_SENDER")
    if not mb:
        raise GraphAuthError(
            "BOLST_MAILBOX (or BOLST_REPORT_SENDER) must be set for app-only Graph calls"
        )
    return mb


def graph_user_base() -> str:
    """Base URL for mailbox calls. A delegated token implies a signed-in user, so
    /me works. An app-only token has no user, so the mailbox must be named."""
    if auth_mode() == "app":
        return f"{GRAPH_ROOT}/users/{mailbox()}"
    return f"{GRAPH_ROOT}/me"


# ---------------------------------------------------------------------------
# App-only: credential loading (offline — no network in this section)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AppCredential:
    kind: str                       # "certificate" | "secret"
    msal_credential: object         # what ConfidentialClientApplication expects
    expires: Optional[date]         # None when unknown
    thumbprint: Optional[str] = None


_PEM_BLOCK = re.compile(
    r"-----BEGIN ([A-Z ]+)-----\r?\n.*?-----END \1-----", re.S
)


def _split_pem(bundle: str) -> tuple[Optional[str], Optional[str]]:
    """Return (private_key_pem, certificate_pem) from a PEM bundle; either may be None."""
    key_pem = cert_pem = None
    for m in _PEM_BLOCK.finditer(bundle):
        label = m.group(1)
        if "PRIVATE KEY" in label and key_pem is None:
            key_pem = m.group(0)
        elif label == "CERTIFICATE" and cert_pem is None:
            cert_pem = m.group(0)
    return key_pem, cert_pem


def _load_pem_bundle() -> Optional[str]:
    b64 = _env("BOLST_AZURE_CLIENT_CERT_PEM_B64")
    if b64:
        try:
            return base64.b64decode(b64, validate=False).decode("utf-8")
        except Exception as e:  # noqa: BLE001 — surface a precise config error
            raise GraphAuthError(
                f"BOLST_AZURE_CLIENT_CERT_PEM_B64 is not valid base64 PEM: {e}"
            ) from e
    path = _env("BOLST_AZURE_CLIENT_CERT_PEM_PATH")
    if path:
        p = Path(path)
        if not p.is_absolute():
            p = BUNDLE_ROOT / p
        if not p.exists():
            raise GraphAuthError(f"BOLST_AZURE_CLIENT_CERT_PEM_PATH not found: {p}")
        return p.read_text(encoding="utf-8")
    return None


def load_app_credential() -> AppCredential:
    """Build the MSAL client credential from the environment. Certificate wins
    over secret when both are present."""
    bundle = _load_pem_bundle()
    if bundle:
        key_pem, cert_pem = _split_pem(bundle)
        if not key_pem:
            raise GraphAuthError("certificate PEM bundle has no PRIVATE KEY block")
        thumbprint = (
            _env("BOLST_AZURE_CLIENT_CERT_THUMBPRINT").replace(":", "").replace(" ", "").lower()
        )
        expires: Optional[date] = None
        if cert_pem:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes

            cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
            derived = cert.fingerprint(hashes.SHA1()).hex()  # Entra keys certs by SHA-1
            if thumbprint and thumbprint != derived:
                raise GraphAuthError(
                    "BOLST_AZURE_CLIENT_CERT_THUMBPRINT does not match the certificate "
                    "in the PEM bundle — wrong cert or stale thumbprint"
                )
            thumbprint = derived
            expires = cert.not_valid_after_utc.date()
        if not thumbprint:
            raise GraphAuthError(
                "PEM bundle has no CERTIFICATE block, so "
                "BOLST_AZURE_CLIENT_CERT_THUMBPRINT is required"
            )
        return AppCredential(
            kind="certificate",
            msal_credential={"private_key": key_pem, "thumbprint": thumbprint},
            expires=expires,
            thumbprint=thumbprint,
        )

    secret = _env("BOLST_AZURE_CLIENT_SECRET")
    if secret:
        expires = None
        raw = _env("BOLST_AZURE_CLIENT_SECRET_EXPIRES")
        if raw:
            try:
                expires = date.fromisoformat(raw)
            except ValueError:
                print(
                    f"[auth] WARNING: BOLST_AZURE_CLIENT_SECRET_EXPIRES={raw!r} is not "
                    "YYYY-MM-DD; expiry will not be tracked",
                    file=sys.stderr,
                )
        return AppCredential(kind="secret", msal_credential=secret, expires=expires)

    raise GraphAuthError("no app credential set")


# ---------------------------------------------------------------------------
# App-only: token acquisition
# ---------------------------------------------------------------------------

# One credential + one confidential client per process. MSAL keeps the access
# token in its in-memory cache, so the many get_access_token() calls in a run
# cost one round-trip to Entra, not one per builder.
_APP_CACHE: dict[str, object] = {}


def reset_cache() -> None:
    """Forget the cached credential/client (tests flip env vars between cases)."""
    _APP_CACHE.clear()


def _app_credential() -> AppCredential:
    """Cached, offline: parses the credential but touches no network."""
    if "cred" not in _APP_CACHE:
        _APP_CACHE["cred"] = load_app_credential()
    return _APP_CACHE["cred"]  # type: ignore[return-value]


def _confidential_app() -> msal.ConfidentialClientApplication:
    """Cached MSAL client. Constructing it performs Entra tenant discovery (network)."""
    if "app" not in _APP_CACHE:
        authority = _env("BOLST_AZURE_AUTHORITY").rstrip("/")
        if not authority or authority.endswith(("/common", "/organizations", "/consumers")):
            raise GraphAuthError(
                "app-only auth needs a tenant-specific BOLST_AZURE_AUTHORITY "
                "(https://login.microsoftonline.com/<tenant-id>), not /common"
            )
        cred = _app_credential()
        _APP_CACHE["app"] = msal.ConfidentialClientApplication(
            client_id=os.environ["BOLST_AZURE_CLIENT_ID"],
            authority=authority,
            client_credential=cred.msal_credential,
        )
    return _APP_CACHE["app"]  # type: ignore[return-value]


def _get_app_only_token() -> str:
    app = _confidential_app()
    result = app.acquire_token_for_client(scopes=APP_ONLY_SCOPES) or {}
    if "access_token" in result:
        return result["access_token"]
    raise GraphAuthError(
        "app-only token request failed: "
        f"{result.get('error')}: {result.get('error_description')} "
        f"(correlation_id={result.get('correlation_id')})"
    )


def credential_expiry() -> Optional[date]:
    """Expiry date of the active app credential, or None (delegated / unknown)."""
    if auth_mode() != "app":
        return None
    return _app_credential().expires


def log_credential_expiry(today: Optional[date] = None) -> Optional[int]:
    """Print ONE line describing the active credential and return days-to-expiry
    (None when unknown or delegated). Called at the top of every routine run so
    the log always answers 'when does this die?'. Warns at <= 60 days. Offline."""
    if auth_mode() != "app":
        print(
            "[auth] mode=delegated (device-code refresh token in .credentials/token.json). "
            "This dies on any mailbox password reset — migrate to app-only (RUNBOOK §9).",
            file=sys.stderr,
        )
        return None
    cred = _app_credential()
    head = f"[auth] mode=app-only ({cred.kind}) mailbox={mailbox()}"
    if cred.expires is None:
        print(f"{head} credential expiry unknown — set BOLST_AZURE_CLIENT_SECRET_EXPIRES to track it")
        return None
    today = today or datetime.now(timezone.utc).date()
    days = (cred.expires - today).days
    line = f"{head} credential expires {cred.expires.isoformat()} ({days} days)"
    if days < 0:
        print(f"{line} — EXPIRED. Rotate now (RUNBOOK §9).", file=sys.stderr)
    elif days <= EXPIRY_WARN_DAYS:
        print(f"{line} — WARNING: renew soon (RUNBOOK §9 rotation).", file=sys.stderr)
    else:
        print(line)
    return days


# ---------------------------------------------------------------------------
# Delegated (legacy): device-code flow + on-disk MSAL cache
# ---------------------------------------------------------------------------

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


def _get_delegated_token() -> str:
    """Silent refresh from the cache, else interactive device-code sign-in."""
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
        raise GraphAuthError(f"Failed to start device flow: {json.dumps(flow, indent=2)}")

    print("=" * 70, file=sys.stderr)
    print(flow["message"], file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise GraphAuthError(f"Device flow failed: {json.dumps(result, indent=2)}")

    _save_cache(cache)
    return result["access_token"]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_access_token() -> str:
    """Return a current Graph access token for the active mode."""
    if auth_mode() == "app":
        return _get_app_only_token()
    return _get_delegated_token()


if __name__ == "__main__":
    # python lib/auth.py            -> mode + expiry line + token acquired
    # python lib/auth.py --verify   -> also GETs the mailbox inbox (read-only)
    log_credential_expiry()
    token = get_access_token()
    print(f"OK — {auth_mode()} token acquired (length {len(token)})")
    if "--verify" in sys.argv:
        import requests

        url = f"{graph_user_base()}/mailFolders/inbox"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "displayName,totalItemCount"},
            timeout=30,
        )
        if r.status_code == 200:
            d = r.json()
            print(f"OK — reached {url}: '{d.get('displayName')}' holds {d.get('totalItemCount')} items")
        else:
            hint = ""
            if r.status_code in (401, 403):
                hint = (" — 401/403 in app-only mode usually means admin consent is missing "
                        "for the APPLICATION permissions, or the Exchange application access "
                        "policy does not (yet) include this mailbox; policy changes can take "
                        "up to an hour to apply.")
            print(f"FAILED — HTTP {r.status_code} on {url}: {r.text[:400]}{hint}", file=sys.stderr)
            sys.exit(1)
