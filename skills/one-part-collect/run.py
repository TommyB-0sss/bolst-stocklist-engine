"""
Manual One Part poll — debug / ad-hoc inspection only.

NOTE (2026-06-02): the production morning report now reads Tom's reply
INLINE via lib.one_part_collect.collect_picks. Claude Cloud Routines are
stateless, so the old design (this poll writes .cache/last_morning_picks.json
at 06:30, the report reads it at 07:00) was removed — those run on
different VMs. There is no longer a scheduled morning-poll routine.

This script is retained so you can manually inspect what the report would
see for a given date, and it still writes the legacy cache file for
ad-hoc use. It is NOT on the cloud report path.

Usage (from bundle root, venv active):
    python skills/one-part-collect/run.py
    python skills/one-part-collect/run.py --report-date 2026-05-10
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BUNDLE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.one_part_collect import collect_picks       # noqa: E402
from lib.picks_store import StoredPicks, write_picks  # noqa: E402

load_dotenv(BUNDLE_ROOT / ".env")
MELBOURNE = ZoneInfo("Australia/Melbourne")


def _report_date_str(argv: list[str]) -> str:
    if "--report-date" in argv:
        return argv[argv.index("--report-date") + 1]
    return datetime.now(MELBOURNE).strftime("%Y-%m-%d")


def main(argv: list[str]) -> int:
    report_date_str = _report_date_str(argv)
    print(f"Polling One Part replies for report date: {report_date_str}",
          file=sys.stderr)

    collected = collect_picks(report_date_str, bundle_root=BUNDLE_ROOT)
    if not collected.reply_found:
        print("  No reply found.", file=sys.stderr)
    else:
        print(f"  Reply from {collected.reply_from}: {len(collected.picks)} picks, "
              f"{len(collected.unresolved)} unresolved", file=sys.stderr)
        for p in collected.picks:
            print(f"  PICK:       Lot {p.lot} {p.suburb} / {p.estate}", file=sys.stderr)
        for u in collected.unresolved:
            print(f"  UNRESOLVED: {u}", file=sys.stderr)

    stored = StoredPicks(
        report_date=report_date_str,
        reply_subject=collected.reply_subject or f"(no reply for {report_date_str})",
        polled_at=datetime.now(MELBOURNE).isoformat(),
        picks=[
            {"lot": p.lot, "suburb": p.suburb, "estate": p.estate}
            for p in collected.picks
        ],
        unresolved=collected.unresolved,
    )
    dest = write_picks(stored, bundle_root=BUNDLE_ROOT)
    print(f"\nWrote picks to {dest}\n  (legacy cache — NOT used by the cloud "
          f"report path; the report reads the reply inline).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
