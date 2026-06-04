"""
Stage 9.8.7a — Picks persistence between morning poll (06:30) and morning send (07:00).

The 06:30 morning poll runs `pick_parser.parse_picks()` against Tom's
overnight reply, then writes the result here. The 07:00 morning report
orchestrator reads it, applies picks via `pick_apply.apply_picks()`, and
renders the PDF.

Storage
-------
JSON file at `.cache/last_morning_picks.json`. Single file (overwritten
each morning). Schema:

    {
      "report_date":   "2026-05-10",
      "reply_subject": "[Bolst One Part - 2026-05-10]",
      "polled_at":     "2026-05-10T06:30:14+10:00",
      "picks": [
        {"lot": "508", "suburb": "Benalla", "estate": "Livingston"},
        ...
      ],
      "unresolved": [
        "Lot 42 is ambiguous - appears in Benalla, Newborough; reply with a suburb to disambiguate",
        ...
      ]
    }

The orchestrator validates report_date matches today's report. Stale
picks (e.g. yesterday's file still on disk because Tom didn't reply
today) are ignored — caller treats as "no picks".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime
from pathlib import Path

PICKS_FILENAME = "last_morning_picks.json"


@dataclass
class StoredPicks:
    report_date: str  # ISO date "YYYY-MM-DD"
    reply_subject: str = ""
    polled_at: str = ""
    picks: list[dict] = field(default_factory=list)  # [{"lot","suburb","estate"}, ...]
    unresolved: list[str] = field(default_factory=list)


def _store_path(bundle_root: Path) -> Path:
    return bundle_root / ".cache" / PICKS_FILENAME


def write_picks(stored: StoredPicks, *, bundle_root: Path) -> Path:
    """Persist a StoredPicks to .cache/last_morning_picks.json. Returns the path."""
    dest = _store_path(bundle_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_date": stored.report_date,
        "reply_subject": stored.reply_subject,
        "polled_at": stored.polled_at or datetime.now().isoformat(),
        "picks": stored.picks,
        "unresolved": stored.unresolved,
    }
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


def read_picks_for(report_date: _date, *, bundle_root: Path) -> StoredPicks | None:
    """Load picks for a specific report date. Returns None if file missing or stale.

    The orchestrator passes today's report date; if the persisted file is
    for a different date (e.g. Tom didn't reply today, yesterday's file
    still sits on disk), we treat it as "no picks" rather than apply
    yesterday's picks against today's data.
    """
    src = _store_path(bundle_root)
    if not src.exists():
        return None
    try:
        payload = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if payload.get("report_date") != report_date.strftime("%Y-%m-%d"):
        return None
    return StoredPicks(
        report_date=payload.get("report_date", ""),
        reply_subject=payload.get("reply_subject", ""),
        polled_at=payload.get("polled_at", ""),
        picks=payload.get("picks", []),
        unresolved=payload.get("unresolved", []),
    )
