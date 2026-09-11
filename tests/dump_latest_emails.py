"""
Diagnostic: show what a builder's latest emails in Tom's mailbox ACTUALLY look
like — subject, date, attachments, and every link (text -> href -> where it
finally lands). Read-only; downloads nothing to the cache; sends nothing.

Built 2026-09-11 for two open questions that cannot be answered from cached
files:
  * REA:    Tom says he still emails the CSV every Monday, yet the engine's
            newest match is 30 Jul. Is the subject different? Is the CSV an
            attachment or a OneDrive/SharePoint link? What is the filename?
  * Luxton: Stefan changed the newsletter. Which buttons/links exist now, and
            where do they resolve (Google Sheet? PDF? something else)?

Usage (from bundle root, venv active, working Graph auth — either mode):
    python tests/dump_latest_emails.py --builder rea
    python tests/dump_latest_emails.py --builder luxton --resolve
    python tests/dump_latest_emails.py --sender someone@x.com --subject "Stock" --top 3

--resolve follows each link (GET, redirects allowed, body not downloaded) and
prints the final URL + Content-Type. Skips mailto:/tel:/unsubscribe links.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

import requests                                                          # noqa: E402
from bs4 import BeautifulSoup                                            # noqa: E402

from lib.auth import auth_mode, get_access_token, log_credential_expiry  # noqa: E402
from lib.graph_read import (                                             # noqa: E402
    _graph_get, _list_attachments, _list_recent_messages_from,
    load_builders_config, messages_endpoint,
)

SKIP_HREF_PREFIXES = ("mailto:", "tel:", "#")
SKIP_HREF_WORDS = ("unsubscribe", "list-manage.com/profile", "preferences", "facebook.com",
                   "instagram.com", "linkedin.com", "twitter.com", "x.com/")


def _message_with_body(token: str, message_id: str) -> dict:
    return _graph_get(
        f"{messages_endpoint()}/{message_id}",
        token,
        params={"$select": "id,subject,receivedDateTime,from,toRecipients,hasAttachments,body"},
    )


def _resolve(url: str) -> str:
    try:
        r = requests.get(url, allow_redirects=True, stream=True, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0 bolst-stocklist-engine diag"})
        ct = r.headers.get("Content-Type", "?").split(";")[0]
        final = r.url
        r.close()
        return f"-> {r.status_code} {ct}  {final}"
    except Exception as e:  # noqa: BLE001
        return f"-> resolve failed: {type(e).__name__}: {e}"


def dump(sender: str, subject: str | None, top: int, resolve: bool) -> int:
    token = get_access_token()
    print(f"mode={auth_mode()}  sender={sender}  subject~'{subject or '*'}'  top={top}\n")
    msgs = _list_recent_messages_from(token, sender, top, subject=subject)
    if not msgs:
        print("NO MESSAGES matched. Try without --subject, or check the sender address "
              "(Tom may send from a different alias/phone).")
        return 1
    for n, m in enumerate(msgs, 1):
        full = _message_with_body(token, m["id"])
        frm = (full.get("from") or {}).get("emailAddress", {}).get("address", "?")
        print(f"=== #{n}  {full.get('receivedDateTime')}  from {frm}")
        print(f"    subject: {full.get('subject')!r}")
        print(f"    hasAttachments: {full.get('hasAttachments')}")
        if full.get("hasAttachments"):
            for a in _list_attachments(token, m["id"]):
                print(f"      attachment: {a.get('name')!r}  {a.get('contentType')}  "
                      f"{a.get('size')} bytes  inline={a.get('isInline')}")
        body = full.get("body") or {}
        html = body.get("content") or ""
        if body.get("contentType", "").lower() == "html" and html:
            soup = BeautifulSoup(html, "lxml")
            links = []
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith(SKIP_HREF_PREFIXES) or any(w in href.lower() for w in SKIP_HREF_WORDS):
                    continue
                text = " ".join(a.get_text(" ", strip=True).split())
                if not text:
                    img = a.find("img")
                    text = f"[img alt={img.get('alt', '')!r}]" if img else "[no text]"
                links.append((text[:70], href))
            print(f"    links ({len(links)}):")
            for text, href in links:
                print(f"      {text!r}\n        {href[:160]}")
                if resolve:
                    print(f"        {_resolve(href)}")
            snippet = " ".join(soup.get_text(" ", strip=True).split())[:300]
            print(f"    text snippet: {snippet!r}")
        else:
            print(f"    body: {body.get('contentType')} ({len(html)} chars): {html[:300]!r}")
        print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--builder", help="builder id from config/builders.yml (sender + subject_filter taken from there)")
    ap.add_argument("--sender", help="override / ad-hoc sender address")
    ap.add_argument("--subject", help="override / ad-hoc subject filter (Graph $search + client-side)")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--resolve", action="store_true", help="follow each link and print final URL + content type")
    args = ap.parse_args()

    sender, subject = args.sender, args.subject
    if args.builder:
        cfg = load_builders_config(BUNDLE_ROOT)["builders"].get(args.builder)
        if not cfg:
            print(f"unknown builder {args.builder!r}", file=sys.stderr)
            return 2
        sender = sender or cfg["sender"]
        subject = subject if subject is not None else cfg.get("subject_filter")
        extra = cfg.get("secondary_senders") or []
        if extra:
            print(f"(secondary senders in config, run separately with --sender: {extra})")
    if not sender:
        ap.error("--builder or --sender is required")

    log_credential_expiry()
    return dump(sender, subject, args.top, args.resolve)


if __name__ == "__main__":
    sys.exit(main())
