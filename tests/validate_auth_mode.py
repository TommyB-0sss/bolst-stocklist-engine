"""
Validation for lib/auth.py mode selection and the mode-aware Graph endpoints
(2026-09-11 app-only auth work). NO NETWORK: nothing here talks to Entra —
the MSAL client is never constructed, only the credential parsing and the
mode/endpoint logic are exercised.

Usage (from bundle root, with venv active):
    python tests/validate_auth_mode.py

Scenarios:
  1. No app credential, no override       -> delegated, /me endpoints
  2. Client secret set                    -> app, /users/<sender>; BOLST_MAILBOX overrides
  3. Certificate PEM bundle (b64)         -> kind=certificate, thumbprint == SHA-1, expiry == notAfter
  4. Explicit thumbprint mismatch         -> GraphAuthError
  5. Key-only PEM without thumbprint      -> GraphAuthError
  6. BOLST_AUTH_MODE=app without creds    -> GraphAuthError
  7. /common authority in app mode        -> GraphAuthError before any network call
  8. log_credential_expiry: plain line > 60d, WARNING <= 60d, EXPIRED < 0, delegated note
  9. graph_read.messages_endpoint / graph_send.sendmail_endpoint follow the mode
 10. Certificate wins over secret when both are set
"""

from __future__ import annotations

import base64
import contextlib
import io
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from cryptography import x509                                            # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization         # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa                # noqa: E402
from cryptography.x509.oid import NameOID                                # noqa: E402

import lib.auth as auth                                                  # noqa: E402
from lib.graph_read import messages_endpoint                             # noqa: E402
from lib.graph_send import sendmail_endpoint                             # noqa: E402

AUTH_VARS = [
    "BOLST_AUTH_MODE", "BOLST_MAILBOX", "BOLST_REPORT_SENDER",
    "BOLST_AZURE_CLIENT_SECRET", "BOLST_AZURE_CLIENT_SECRET_EXPIRES",
    "BOLST_AZURE_CLIENT_CERT_PEM_B64", "BOLST_AZURE_CLIENT_CERT_PEM_PATH",
    "BOLST_AZURE_CLIENT_CERT_THUMBPRINT", "BOLST_AZURE_AUTHORITY",
    "BOLST_AZURE_CLIENT_ID",
]
SENDER = "tom@example.invalid"
FAILURES: list[str] = []


@contextlib.contextmanager
def env(**values: str):
    """Set exactly these auth vars (everything else in AUTH_VARS unset), then restore."""
    saved = {k: os.environ.get(k) for k in AUTH_VARS}
    try:
        for k in AUTH_VARS:
            os.environ.pop(k, None)
        for k, v in values.items():
            os.environ[k] = v
        auth.reset_cache()
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        auth.reset_cache()


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def expect_error(name: str, fn) -> None:
    try:
        fn()
    except auth.GraphAuthError:
        check(name, True)
    except Exception as e:  # noqa: BLE001
        check(name, False, f"wrong exception {type(e).__name__}: {e}")
    else:
        check(name, False, "no GraphAuthError raised")


def make_cert(days_valid: int) -> tuple[str, str, x509.Certificate]:
    """Self-signed cert + key as PEM strings (what openssl req -x509 produces)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "bolst-test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=days_valid))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return key_pem, cert_pem, cert


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def main() -> int:
    print("=== validate_auth_mode ===")

    print("\n1. no credential -> delegated")
    with env(BOLST_REPORT_SENDER=SENDER):
        check("mode is delegated", auth.auth_mode() == "delegated")
        check("base is /me", auth.graph_user_base().endswith("/v1.0/me"))

    print("\n2. client secret -> app-only on the sender mailbox")
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_SECRET="not-a-real-secret"):
        check("mode is app", auth.auth_mode() == "app")
        check("base names the sender mailbox",
              auth.graph_user_base() == f"https://graph.microsoft.com/v1.0/users/{SENDER}")
        cred = auth.load_app_credential()
        check("kind is secret", cred.kind == "secret")
        check("expiry unknown without _EXPIRES", cred.expires is None)
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_SECRET="x",
             BOLST_MAILBOX="other@example.invalid",
             BOLST_AZURE_CLIENT_SECRET_EXPIRES="2028-03-01"):
        check("BOLST_MAILBOX overrides the sender",
              auth.graph_user_base().endswith("/users/other@example.invalid"))
        check("secret expiry parsed", auth.load_app_credential().expires == date(2028, 3, 1))

    print("\n3. certificate PEM bundle")
    key_pem, cert_pem, cert = make_cert(days_valid=1095)
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_CERT_PEM_B64=b64(key_pem + cert_pem)):
        cred = auth.load_app_credential()
        check("kind is certificate", cred.kind == "certificate")
        check("thumbprint is the SHA-1 fingerprint",
              cred.thumbprint == cert.fingerprint(hashes.SHA1()).hex())
        check("expiry is the cert notAfter date",
              cred.expires == cert.not_valid_after_utc.date())
        check("msal credential carries key + thumbprint",
              isinstance(cred.msal_credential, dict)
              and cred.msal_credential.get("thumbprint") == cred.thumbprint
              and "PRIVATE KEY" in cred.msal_credential.get("private_key", ""))
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_CERT_PEM_B64=b64(key_pem + cert_pem),
             BOLST_AZURE_CLIENT_CERT_THUMBPRINT=cert.fingerprint(hashes.SHA1()).hex().upper()):
        check("explicit matching thumbprint accepted (case-insensitive)",
              auth.load_app_credential().thumbprint == cert.fingerprint(hashes.SHA1()).hex())

    print("\n4. thumbprint mismatch")
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_CERT_PEM_B64=b64(key_pem + cert_pem),
             BOLST_AZURE_CLIENT_CERT_THUMBPRINT="00" * 20):
        expect_error("mismatching thumbprint raises", auth.load_app_credential)

    print("\n5. key-only bundle without thumbprint")
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_CERT_PEM_B64=b64(key_pem)):
        expect_error("key-only bundle without thumbprint raises", auth.load_app_credential)
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_CERT_PEM_B64=b64(key_pem),
             BOLST_AZURE_CLIENT_CERT_THUMBPRINT="ab" * 20):
        check("key-only bundle WITH thumbprint accepted",
              auth.load_app_credential().thumbprint == "ab" * 20)
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_CERT_PEM_B64="%%%not-base64%%%"):
        expect_error("garbage b64 raises a config error", auth.load_app_credential)

    print("\n6. forced app mode without a credential")
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AUTH_MODE="app"):
        expect_error("BOLST_AUTH_MODE=app without credential raises", auth.auth_mode)
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AUTH_MODE="delegated", BOLST_AZURE_CLIENT_SECRET="x"):
        check("BOLST_AUTH_MODE=delegated overrides a present credential",
              auth.auth_mode() == "delegated")
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AUTH_MODE="bogus"):
        expect_error("unknown BOLST_AUTH_MODE raises", auth.auth_mode)

    print("\n7. /common authority rejected before any network")
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_SECRET="x",
             BOLST_AZURE_CLIENT_ID="00000000-0000-0000-0000-000000000000",
             BOLST_AZURE_AUTHORITY="https://login.microsoftonline.com/common"):
        expect_error("/common authority raises", auth._confidential_app)
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_SECRET="x",
             BOLST_AZURE_CLIENT_ID="00000000-0000-0000-0000-000000000000",
             BOLST_AZURE_AUTHORITY=""):
        expect_error("empty authority raises", auth._confidential_app)

    print("\n8. expiry logging")
    today = date(2026, 9, 14)
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_SECRET="x",
             BOLST_AZURE_CLIENT_SECRET_EXPIRES="2028-09-14"):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            days = auth.log_credential_expiry(today=today)
        check("far expiry -> days returned", days == (date(2028, 9, 14) - today).days, f"days={days}")
        check("far expiry -> plain stdout line, nothing on stderr",
              "credential expires 2028-09-14" in out.getvalue() and err.getvalue() == "")
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_SECRET="x",
             BOLST_AZURE_CLIENT_SECRET_EXPIRES="2026-10-14"):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            days = auth.log_credential_expiry(today=today)
        check("30 days left -> WARNING on stderr", days == 30 and "WARNING" in err.getvalue())
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_SECRET="x",
             BOLST_AZURE_CLIENT_SECRET_EXPIRES="2026-09-01"):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            days = auth.log_credential_expiry(today=today)
        check("past expiry -> EXPIRED on stderr", days < 0 and "EXPIRED" in err.getvalue())
    with env(BOLST_REPORT_SENDER=SENDER):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            days = auth.log_credential_expiry(today=today)
        check("delegated -> None + migration note on stderr",
              days is None and "delegated" in err.getvalue())
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_CERT_PEM_B64=b64(key_pem + cert_pem)):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            days = auth.log_credential_expiry()
        check("certificate expiry logged from the cert itself",
              days is not None and 1090 <= days <= 1095 and "(certificate)" in out.getvalue())

    print("\n9. endpoints follow the mode")
    with env(BOLST_REPORT_SENDER=SENDER):
        check("delegated messages endpoint",
              messages_endpoint() == "https://graph.microsoft.com/v1.0/me/messages")
        check("delegated sendMail endpoint",
              sendmail_endpoint() == "https://graph.microsoft.com/v1.0/me/sendMail")
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_SECRET="x"):
        check("app-only messages endpoint",
              messages_endpoint() == f"https://graph.microsoft.com/v1.0/users/{SENDER}/messages")
        check("app-only sendMail endpoint",
              sendmail_endpoint() == f"https://graph.microsoft.com/v1.0/users/{SENDER}/sendMail")
    with env(BOLST_AZURE_CLIENT_SECRET="x"):
        expect_error("app-only without any mailbox var raises", auth.graph_user_base)

    print("\n10. certificate wins over secret")
    with env(BOLST_REPORT_SENDER=SENDER, BOLST_AZURE_CLIENT_SECRET="x",
             BOLST_AZURE_CLIENT_CERT_PEM_B64=b64(key_pem + cert_pem)):
        check("kind is certificate when both set", auth.load_app_credential().kind == "certificate")

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
