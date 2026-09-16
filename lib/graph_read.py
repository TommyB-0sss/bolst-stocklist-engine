"""
Microsoft Graph read helpers — Outlook ingest layer.

Replaces the fixture-path defaults across all 6 builder pipelines with live
reads from Tom's Outlook (`tom@bolstpropertygroup.com.au`, OAuth grant
established Stage 1.6). Keeps parsers + downstream pipeline unchanged —
they still receive a Path; this module is what fills it.

Public API
----------
    fetch_latest_for_builder(builder_id, builders_config, *,
                             cache_dir=None, skip_cache=False) -> Path

Dispatches by `ingestion` mode in builders.yml:
  - 'attachment'  : search Outlook by sender (+ optional subject_filter),
                    download first attachment matching filename_patterns
  - 'html_link'   : NOT YET IMPLEMENTED (Stages 9.8.4–9.8.6 will add it)

Caching
-------
Downloaded files cache to `.cache/builder-downloads/<builder>/YYYYMMDD-<filename>`
to keep same-day reruns cheap and deterministic. The One Part flow runs at
both 16:00 and 06:30 — both reads should see the same file. Pass
skip_cache=True to force a fresh fetch.

Implementation notes
--------------------
- Graph $top=20 messages per sender is enough headroom; latest stocklist
  is always in the most recent few. Aldrich is the noisiest sender (per-
  package emails) and even there 20 covers ~2 weeks of activity.
- Attachment bytes are base64-encoded in the Graph response; we decode
  before writing to disk.
- Filename pattern matching uses fnmatch (glob), matching builders.yml's
  `filename_patterns` semantics.
"""

from __future__ import annotations

import base64
import fnmatch
import re
import sys
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests

from lib.auth import get_access_token, graph_user_base


def messages_endpoint() -> str:
    """Mailbox messages collection for the active auth mode (lib.auth):
    /me/messages with a delegated token, /users/<mailbox>/messages with an
    app-only token. A function, not a constant, so the mode can be decided
    by the environment at call time."""
    return f"{graph_user_base()}/messages"

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_TOP_MESSAGES = 20


class IngestError(Exception):
    """Raised when a builder's stocklist cannot be located in Tom's Outlook."""


def _default_cache_dir(bundle_root: Path, builder_id: str) -> Path:
    return bundle_root / ".cache" / "builder-downloads" / builder_id


def _cache_path(cache_dir: Path, filename: str, when: _date) -> Path:
    return cache_dir / f"{when.strftime('%Y%m%d')}-{filename}"


def _graph_get(
    url: str,
    token: str,
    params: Optional[dict] = None,
    *,
    advanced_query: bool = False,
) -> dict:
    """
    GET against Graph. Set advanced_query=True when combining $filter on
    derived properties (e.g. from/emailAddress/address) with $orderby —
    Graph rejects those without the eventual-consistency header + $count.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if advanced_query:
        headers["ConsistencyLevel"] = "eventual"
    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _build_from_search(sender: str, subject: Optional[str] = None) -> str:
    """KQL $search string: messages from `sender`, optionally narrowed to a
    subject substring.

    Narrowing by subject is ESSENTIAL for low-frequency senders whose latest
    matching email would otherwise fall outside the $top window once a
    high-volume sender posts other mail on top of it. Tom's weekly REA CSV is
    the case in point — without `subject:`, his ~daily outbound buries the
    Monday CSV well beyond the 20 most-recent by Tuesday.
    """
    # Graph $search wants the WHOLE KQL expression inside ONE pair of double
    # quotes: "from:<sender> AND subject:<subject>". The earlier form used a
    # separate quote pair per term ('"from:X" AND "subject:Y"'), which Graph
    # silently degraded to from:<sender> only — so multi-word/low-frequency
    # subjects (REA's "REA CSV", Aldrich's "stocklist") were never filtered and
    # the real mail fell past the $top window. Every other quoting variant
    # (unquoted, per-value quotes, parens) returns HTTP 400. Validated against
    # Tom's live mailbox 2026-06-04: this form scopes to 5 msgs and finds the
    # weekly REA CSV; _passes_subject_filter re-checks the substring client-side.
    inner = f"from:{sender}"
    if subject:
        inner += f" AND subject:{subject}"
    return f'"{inner}"'


def _list_recent_messages_from(token: str, sender: str, top: int,
                               subject: Optional[str] = None) -> list[dict]:
    """Return up to top-N most recent messages from a given sender, newest first.

    Graph rejects $filter on `from/emailAddress/address` combined with
    $orderby (InefficientFilter — "restriction or sort order too complex").
    Workaround: use $search="from:<address>" which Graph indexes for fast
    sender lookup, then sort client-side by receivedDateTime descending.
    $search results aren't deterministically date-ordered server-side.

    When `subject` is supplied it's added to the $search so the window is
    scoped to matching-subject mail (see _build_from_search).
    """
    params = {
        "$search": _build_from_search(sender, subject),
        "$top": str(top),
        "$select": "id,subject,receivedDateTime,sentDateTime,hasAttachments",
    }
    data = _graph_get(messages_endpoint(), token, params=params)
    messages = data.get("value", [])
    messages.sort(key=lambda m: m.get("receivedDateTime", ""), reverse=True)
    return messages


def _list_attachments(token: str, message_id: str) -> list[dict]:
    """Return all attachments for a message, with contentBytes inline."""
    url = f"{messages_endpoint()}/{message_id}/attachments"
    data = _graph_get(url, token)
    return data.get("value", [])


def _filename_matches(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def _passes_subject_filter(subject: str, subject_filter: Optional[str]) -> bool:
    if not subject_filter:
        return True
    return subject_filter.lower() in (subject or "").lower()


def _list_recent_messages_with_body(token: str, sender: str, top: int) -> list[dict]:
    """Like _list_recent_messages_from but includes `body` for HTML parsing."""
    params = {
        "$search": f'"from:{sender}"',
        "$top": str(top),
        "$select": "id,subject,receivedDateTime,hasAttachments,body",
    }
    data = _graph_get(messages_endpoint(), token, params=params)
    messages = data.get("value", [])
    messages.sort(key=lambda m: m.get("receivedDateTime", ""), reverse=True)
    return messages


def _try_sender_for_attachment(
    token: str,
    sender: str,
    patterns: list[str],
    subject_filter: Optional[str],
    cache_dir: Path,
    skip_cache: bool,
) -> Optional[Path]:
    """Search a single sender's recent messages for a matching attachment.

    Returns the cached file path if found, None if no matching attachment
    in the top-N messages from this sender. Used as a building block by
    _fetch_attachment_mode for primary + secondary_senders fallback.
    """
    messages = _list_recent_messages_from(
        token, sender, DEFAULT_TOP_MESSAGES, subject=subject_filter,
    )
    for msg in messages:
        if not msg.get("hasAttachments"):
            continue
        if not _passes_subject_filter(msg.get("subject", ""), subject_filter):
            continue
        attachments = _list_attachments(token, msg["id"])
        for att in attachments:
            name = att.get("name", "")
            if not _filename_matches(name, patterns):
                continue
            received_date = _parse_received_date(msg.get("receivedDateTime", ""))
            cache_dir.mkdir(parents=True, exist_ok=True)
            dest = _cache_path(cache_dir, name, received_date)
            if dest.exists() and not skip_cache:
                return dest
            content_b64 = att.get("contentBytes")
            if content_b64 is None:
                continue
            dest.write_bytes(base64.b64decode(content_b64))
            return dest
    return None


def _fetch_attachment_mode(
    builder_id: str,
    builder_cfg: dict,
    cache_dir: Path,
    skip_cache: bool,
) -> list[Path]:
    primary = builder_cfg["sender"]
    secondaries = builder_cfg.get("secondary_senders", []) or []
    senders = [primary, *secondaries]
    patterns = builder_cfg.get("filename_patterns", [])
    subject_filter = builder_cfg.get("subject_filter")

    token = get_access_token()
    tried: list[str] = []
    for sender in senders:
        tried.append(sender)
        result = _try_sender_for_attachment(
            token, sender, patterns, subject_filter, cache_dir, skip_cache,
        )
        if result is not None:
            return [result]

    raise IngestError(
        f"{builder_id}: no attachment matching {patterns} in last "
        f"{DEFAULT_TOP_MESSAGES} message(s) from "
        f"{' or '.join(tried)}"
        + (f" (subject filter: '{subject_filter}')" if subject_filter else "")
    )


def _parse_received_date(received_iso: str) -> _date:
    """Graph returns receivedDateTime as ISO8601 UTC like '2026-05-09T03:14:00Z'."""
    if not received_iso:
        return _date.today()
    try:
        return datetime.strptime(received_iso[:10], "%Y-%m-%d").date()
    except ValueError:
        return _date.today()


def _format_url_template(template: str, when: _date) -> str:
    """Substitute date tokens in a builder's url_template.

    Supported tokens (case-insensitive): {ddmmyy}, {ddmmyyyy}, {yyyymmdd}.
    Hermitage uses {ddmmyy} which produces e.g. "090526" for 2026-05-09.
    """
    return (
        template
        .replace("{ddmmyy}", when.strftime("%d%m%y"))
        .replace("{DDMMYY}", when.strftime("%d%m%y"))
        .replace("{ddmmyyyy}", when.strftime("%d%m%Y"))
        .replace("{DDMMYYYY}", when.strftime("%d%m%Y"))
        .replace("{yyyymmdd}", when.strftime("%Y%m%d"))
        .replace("{YYYYMMDD}", when.strftime("%Y%m%d"))
    )


def _download_to_cache(
    url: str,
    cache_dir: Path,
    filename: str,
    when: _date,
    skip_cache: bool,
    expected_content_types: tuple[str, ...] = ("application/pdf",),
) -> Path:
    """GET a public URL and write the body to the cache. Returns the cached path."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = _cache_path(cache_dir, filename, when)
    if dest.exists() and not skip_cache:
        return dest
    response = requests.get(url, timeout=DEFAULT_TIMEOUT_SECONDS, allow_redirects=True)
    response.raise_for_status()
    ct = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if expected_content_types and ct and ct not in expected_content_types:
        raise IngestError(
            f"unexpected Content-Type '{ct}' from {url} "
            f"(expected one of {expected_content_types})"
        )
    dest.write_bytes(response.content)
    return dest


def _extract_button_href(html_body: str, text_contains: str) -> Optional[str]:
    """Find the first <a href> whose visible text contains a given substring.

    Case-insensitive substring match. Used to locate "Download — Victoria
    Stocklist" style buttons in newsletter-style email HTML where the file
    URL isn't predictable.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_body or "", "lxml")
    needle = text_contains.lower()
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip()
        if needle in text.lower():
            return a["href"]
    return None


# Match the sheet ID across both Google Sheets URL flavours:
#   /spreadsheets/d/{ID}/edit
#   /spreadsheets/u/0/d/{ID}/htmlview
GOOGLE_SHEETS_ID_RE = re.compile(r"/spreadsheets/(?:u/\d+/)?d/([a-zA-Z0-9_-]+)")
GOOGLE_SHEETS_XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _resolve_google_sheets_xlsx_url(button_url: str) -> str:
    """Follow MailChimp/redirect chain to a Google Sheets URL, return /export?format=xlsx URL.

    Used by Luxton (MailChimp button -> public Google Sheets). Raises
    IngestError if the final URL isn't on docs.google.com or doesn't
    contain a recognisable spreadsheet ID.
    """
    response = requests.get(
        button_url, allow_redirects=True, timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    match = GOOGLE_SHEETS_ID_RE.search(response.url)
    if not match:
        raise IngestError(
            f"google_sheets_xlsx: redirect chain ended at {response.url} — "
            f"no spreadsheet ID found"
        )
    sheet_id = match.group(1)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"


def _fetch_html_link_mode(
    builder_id: str,
    builder_cfg: dict,
    cache_dir: Path,
    skip_cache: bool,
) -> list[Path]:
    """html_link ingestion: email has no attachment; PDF lives behind a link.

    Returns LIST of paths because some builders (Aplace) ship multiple
    stocklists in one email — each button = one PDF.

    Strategies (per builders.yml link_strategy):
      url_template — substitute date tokens from receivedDateTime, fetch.
                     Returns [single Path]. Used by Hermitage (predictable
                     hubfs filename pattern).
      buttons      — parse email HTML body, find <a> tags whose visible
                     text matches text_contains, follow each href, save as
                     filename. Returns [Path, ...] — one per button.
                     Used by Aplace and (incoming 9.8.6) Luxton.
    """
    sender = builder_cfg["sender"]
    subject_filter = builder_cfg.get("subject_filter")
    strategy = builder_cfg.get("link_strategy", {}) or {}
    url_template = strategy.get("url_template")
    buttons = strategy.get("buttons") or []

    token = get_access_token()
    if buttons:
        messages = _list_recent_messages_with_body(token, sender, DEFAULT_TOP_MESSAGES)
    else:
        messages = _list_recent_messages_from(token, sender, DEFAULT_TOP_MESSAGES)
    if not messages:
        raise IngestError(
            f"{builder_id}: no messages from {sender} in Tom's mailbox"
        )

    if subject_filter:
        messages = [
            m for m in messages
            if _passes_subject_filter(m.get("subject", ""), subject_filter)
        ]
        if not messages:
            raise IngestError(
                f"{builder_id}: no messages matching subject filter "
                f"'{subject_filter}' from {sender}"
            )
    latest = messages[0]
    received_date = _parse_received_date(latest.get("receivedDateTime", ""))

    if url_template:
        url = _format_url_template(url_template, received_date)
        filename = url.rsplit("/", 1)[-1]
        try:
            path = _download_to_cache(
                url, cache_dir, filename, received_date, skip_cache,
            )
            return [path]
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            raise IngestError(
                f"{builder_id}: url_template fetch failed (HTTP {status}) - {url}. "
                f"Add fallback_button_text handler in graph_read._fetch_html_link_mode "
                f"(scheduled for 9.8.4b if Hermitage's pattern ever drifts)."
            ) from e

    if buttons:
        body_html = (latest.get("body") or {}).get("content", "")
        if not body_html:
            raise IngestError(f"{builder_id}: latest email has no HTML body to parse")
        results: list[Path] = []
        missing: list[str] = []
        for btn in buttons:
            text_match = btn.get("text_contains")
            filename = btn.get("filename")
            fmt = btn.get("format", "pdf")
            if not (text_match and filename):
                continue
            href = _extract_button_href(body_html, text_match)
            if not href:
                missing.append(text_match)
                continue
            try:
                if fmt == "google_sheets_xlsx":
                    download_url = _resolve_google_sheets_xlsx_url(href)
                    expected = (GOOGLE_SHEETS_XLSX_CONTENT_TYPE,)
                else:
                    download_url = href
                    expected = ("application/pdf",)
                path = _download_to_cache(
                    download_url, cache_dir, filename, received_date, skip_cache,
                    expected_content_types=expected,
                )
                results.append(path)
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else "?"
                missing.append(f"{text_match} (HTTP {status})")
            except IngestError as e:
                missing.append(f"{text_match} ({e})")
        if not results:
            raise IngestError(
                f"{builder_id}: no buttons resolved. Missing: {missing}"
            )
        if missing:
            # PARTIAL ingest. Previously this returned silently, so a builder
            # who shipped only one of two configured stocklists looked
            # identical to a complete ingest and the missing packages vanished
            # with no trace (found 2026-08-06: Aplace's "100% Upfront
            # commission" and Luxton's "2 Part Stock List" had both dropped out
            # of the senders' latest emails). Still non-fatal — a partial list
            # beats holding the whole report — but it must be visible.
            print(
                f"    WARNING: {builder_id}: only {len(results)} of "
                f"{len(buttons)} configured stocklist(s) resolved from the "
                f"{latest.get('receivedDateTime', '?')} email. MISSING: "
                f"{missing}. Those packages are ABSENT from this report.",
                file=sys.stderr,
            )
        return results

    raise IngestError(
        f"{builder_id}: html_link ingestion has neither url_template nor "
        f"buttons in builders.yml link_strategy"
    )


def fetch_all_for_builder(
    builder_id: str,
    builders_config: dict,
    *,
    bundle_root: Path,
    cache_dir: Optional[Path] = None,
    skip_cache: bool = False,
) -> list[Path]:
    """
    Locate and download ALL stocklists for a given builder.

    Most builders ship a single file per week and return [Path]. Aplace
    ships two PDFs in one email (Victoria Stocklist + Upfront Commission)
    and returns [Path, Path]. Use this when the caller needs everything.

    See fetch_latest_for_builder for single-file callers (One Part flow).
    """
    builder_cfg = builders_config.get("builders", {}).get(builder_id)
    if builder_cfg is None:
        raise IngestError(f"unknown builder '{builder_id}' in builders.yml")

    mode = builder_cfg.get("ingestion", "attachment")
    cache = cache_dir or _default_cache_dir(bundle_root, builder_id)

    if mode == "attachment":
        return _fetch_attachment_mode(builder_id, builder_cfg, cache, skip_cache)
    if mode == "html_link":
        return _fetch_html_link_mode(builder_id, builder_cfg, cache, skip_cache)
    raise IngestError(f"{builder_id}: unknown ingestion mode '{mode}'")


def fetch_latest_for_builder(
    builder_id: str,
    builders_config: dict,
    *,
    bundle_root: Path,
    cache_dir: Optional[Path] = None,
    skip_cache: bool = False,
) -> Path:
    """
    Single-file convenience wrapper around fetch_all_for_builder.

    Returns the first file. For single-file builders (Specialised, Aldrich,
    Urbane, Hermitage, Luxton) this IS the only file. For multi-file
    builders (Aplace) this returns one of the files; use fetch_all_for_builder
    when you need all of them.
    """
    paths = fetch_all_for_builder(
        builder_id, builders_config,
        bundle_root=bundle_root, cache_dir=cache_dir, skip_cache=skip_cache,
    )
    return paths[0]


def load_builders_config(bundle_root: Path) -> dict:
    """Convenience loader — keeps callers from importing yaml directly."""
    import yaml
    with open(bundle_root / "config" / "builders.yml", "r", encoding="utf-8") as fp:
        return yaml.safe_load(fp)
