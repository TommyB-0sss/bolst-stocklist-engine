"""
Read Tom's overnight One Part reply from Outlook and parse it into picks.

Extracted from skills/one-part-collect/run.py (the old standalone 06:30
poll) so the morning report orchestrator can read the reply INLINE at
send time.

Why inline
----------
Claude Cloud Routines are stateless: every fire is a fresh VM. The old
design had the 06:30 poll write picks to .cache/last_morning_picks.json
and the 07:00 report read them back — but those run on different VMs, so
the file is gone by 07:00 and the editorial One Part flow silently breaks
in the cloud. Reading Tom's reply directly at report time removes the
cross-fire dependency entirely (and drops the schedule from 3 weekday
fires to 2, well under the Pro 5/day cap).

How it finds the reply
----------------------
The evening prompt was sent (yesterday, 16:00) with subject
`[Bolst One Part - <report_date>]`. Replies arrive with "Re:" prepended.
Graph $search tokenizes inconsistently across punctuation (and the
subject uses an em-dash), so we search the punctuation-free anchor
"subject:Bolst One Part" and filter client-side by the plain
"YYYY-MM-DD" date substring. The most recent message NOT sent from Tom's
own Outlook is his reply.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

from lib.auth import get_access_token
from lib.graph_read import (
    messages_endpoint,
    fetch_latest_for_builder,
    load_builders_config,
)
from lib.one_part_candidates import get_specialised_candidates
from lib.parsers.types import StocklistRow
from lib.pick_parser import parse_picks


@dataclass
class CollectedPicks:
    """Result of reading + parsing Tom's One Part reply for a report date."""
    report_date: str
    reply_found: bool = False
    reply_subject: str = ""
    reply_from: str = ""
    picks: list[StocklistRow] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def _search_thread(token: str, report_date_str: str) -> list[dict]:
    """Find all messages on the One Part thread for a given report date,
    most-recent first. Anchor is the punctuation-free subject token;
    date match is a client-side substring so em-dash vs hyphen is moot."""
    response = requests.get(
        messages_endpoint(),
        headers={"Authorization": f"Bearer {token}"},
        params={
            "$search": '"subject:Bolst One Part"',
            "$top": "30",
            "$select": "id,subject,receivedDateTime,from,body",
        },
        timeout=30,
    )
    response.raise_for_status()
    msgs = response.json().get("value", [])
    matching = [m for m in msgs if report_date_str in (m.get("subject") or "")]
    matching.sort(key=lambda m: m.get("receivedDateTime", ""), reverse=True)
    return matching


def _extract_reply_text(html_body: str) -> str:
    """Plain-text from an HTML email body for pick_parser.

    The pick_parser regex (`\\bLot\\s+\\d+\\b`) is naturally selective: the
    original prompt's candidate table shows bare digits (no "Lot " prefix),
    so quoted prompt text won't match — only Tom's free-form "Lot N suburb"
    lines do. Passing the whole quoted body through is therefore safe.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_body or "", "lxml")
    return soup.get_text(separator="\n", strip=True)


def _is_from_tom(msg: dict, tom_address: str) -> bool:
    """True for the original sent prompt (from Tom's own Outlook)."""
    from_addr = (
        (msg.get("from") or {})
        .get("emailAddress", {})
        .get("address", "")
        .lower()
    )
    return from_addr == tom_address.lower()


def collect_picks(report_date_str: str, *, bundle_root: Path,
                  token: Optional[str] = None) -> CollectedPicks:
    """Read Tom's overnight One Part reply for `report_date_str` and parse
    it against today's live Specialised candidates.

    Returns a CollectedPicks. When no reply is found, reply_found=False and
    picks/unresolved are empty (caller treats as "no picks"). Network/auth
    errors propagate — the caller decides whether the One Part layer is
    fatal (it isn't: the morning report still ships with auto-flagged rows).
    """
    if token is None:
        token = get_access_token()

    msgs = _search_thread(token, report_date_str)
    tom_address = os.environ["BOLST_REPORT_SENDER"]
    replies = [m for m in msgs if not _is_from_tom(m, tom_address)]

    if not replies:
        return CollectedPicks(report_date=report_date_str, reply_found=False)

    latest = replies[0]
    reply_from = (latest.get("from") or {}).get("emailAddress", {}).get("address", "?")
    reply_text = _extract_reply_text((latest.get("body") or {}).get("content", ""))

    builders_cfg = load_builders_config(bundle_root)
    specialised_pdf = fetch_latest_for_builder(
        "specialised", builders_cfg, bundle_root=bundle_root,
    )
    candidates = get_specialised_candidates(specialised_pdf)

    result = parse_picks(reply_text, candidates)
    return CollectedPicks(
        report_date=report_date_str,
        reply_found=True,
        reply_subject=latest.get("subject", ""),
        reply_from=reply_from,
        picks=result.picks,
        unresolved=result.unresolved,
    )
