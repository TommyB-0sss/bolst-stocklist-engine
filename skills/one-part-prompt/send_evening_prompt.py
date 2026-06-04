"""
send_evening_prompt.py — Stage 9.2 evening One Part prompt.

Sends Tom (or, during build phase, Inam) an HTML email at 16:00 AEST listing
tomorrow's Specialised candidates so he can reply with the lots he wants on
the One Part Contracts tab.

Usage (from bundle root, with venv active):
    python skills/one-part-prompt/send_evening_prompt.py
    python skills/one-part-prompt/send_evening_prompt.py path/to/stocklist.pdf

Subject: `[Bolst One Part — YYYY-MM-DD]` where YYYY-MM-DD is tomorrow's report
date in Australia/Melbourne timezone. The morning poll skill matches replies
by literal subject prefix, so do not change this format here without updating
`skills/one-part-collect` too.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BUNDLE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.graph_read import fetch_latest_for_builder, load_builders_config  # noqa: E402
from lib.graph_send import send_mail  # noqa: E402
from lib.one_part_candidates import CandidateGroup, get_specialised_candidates  # noqa: E402

load_dotenv(BUNDLE_ROOT / ".env")

# Default behaviour: fetch the latest Specialised PDF live from Tom's
# Outlook. CLI override (argv[1]) bypasses for repeatable testing against
# a known file.

MELBOURNE = ZoneInfo("Australia/Melbourne")

BRAND_GREEN = "#0D3823"
BRAND_GOLD = "#C9A24A"
ZEBRA_GRAY = "#F2F2F2"


def _fmt_price(p: int | None) -> str:
    return f"${p:,}" if p else "—"


def _fmt_bbc(bed: int | None, bath: float | None, car: int | None) -> str:
    if bed is None and bath is None and car is None:
        return "—"
    parts = [
        str(bed) if bed is not None else "?",
        str(int(bath)) if bath is not None and float(bath).is_integer() else (str(bath) if bath is not None else "?"),
        str(car) if car is not None else "?",
    ]
    return "-".join(parts)


def _row_html(row, idx: int) -> str:
    bg = ZEBRA_GRAY if idx % 2 == 1 else "#FFFFFF"
    cells = [
        escape(row.lot or "—"),
        escape(row.street or "—"),
        escape(row.titles or "—"),
        escape(row.home_design or "—"),
        _fmt_bbc(row.bed, row.bath, row.car),
        _fmt_price(row.total_price),
    ]
    tds = "".join(
        f'<td style="padding:6px 10px;border-bottom:1px solid #EEE;font-size:13px;">{c}</td>'
        for c in cells
    )
    return f'<tr style="background:{bg};">{tds}</tr>'


def _group_html(group: CandidateGroup) -> str:
    header_cells = ["Lot", "Address", "Titles", "Floorplan", "Bed-Bath-Car", "Price"]
    ths = "".join(
        f'<th style="padding:8px 10px;text-align:left;font-size:12px;'
        f'color:#FFFFFF;background:{BRAND_GREEN};font-weight:600;">{c}</th>'
        for c in header_cells
    )
    rows_html = "".join(_row_html(r, i) for i, r in enumerate(group.rows))
    title = escape(f"{group.suburb} — {group.estate}")
    count = len(group.rows)
    return (
        f'<div style="margin:18px 0 0;">'
        f'<div style="font-size:14px;font-weight:600;color:{BRAND_GREEN};'
        f'margin-bottom:4px;">{title} '
        f'<span style="color:#888;font-weight:400;">({count} lot{"s" if count != 1 else ""})</span>'
        f'</div>'
        f'<table cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse;width:100%;max-width:720px;">'
        f'<thead><tr>{ths}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>'
        f'</div>'
    )


def _build_html_body(groups: list[CandidateGroup], report_date: str, total_rows: int) -> str:
    intro = (
        f'<p style="font-size:14px;color:#222;">Hi Tom,</p>'
        f'<p style="font-size:14px;color:#222;">'
        f"Below are the {total_rows} Specialised candidates for tomorrow's "
        f"({escape(report_date)}) One Part Contracts tab. "
        f"<strong>Reply to this email</strong> with the lots you want "
        f"included, in the format <code>Lot &lt;number&gt; &lt;suburb&gt;</code> "
        f"— e.g. <code>Lot 17 Elliminyt, Lot 205 Thornhill Park</code>."
        f"</p>"
        f'<p style="font-size:13px;color:#444;">'
        f"<strong>Why the suburb matters:</strong> some lot numbers repeat "
        f"across estates (e.g. Lot 42 exists in both Benalla and Newborough "
        f"this week). Including the suburb avoids ambiguity. We poll your "
        f"reply at 06:30 AEST and ship the report at 06:50."
        f"</p>"
        f'<p style="font-size:13px;color:#666;">'
        f"No reply by 06:45 = the One Part tab ships with auto-flagged lots only "
        f"(Hermitage and Luxton One Part rows)."
        f"</p>"
    )
    body_groups = "".join(_group_html(g) for g in groups)
    footer = (
        f'<p style="font-size:12px;color:#888;margin-top:24px;">'
        f"Bolst Stocklist Engine · evening prompt · reply on this thread."
        f"</p>"
    )
    return (
        f'<html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        f'background:#FFFFFF;color:#222;padding:16px;">'
        f"{intro}{body_groups}{footer}"
        f"</body></html>"
    )


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        pdf_path = Path(argv[1])
        print(f"Using CLI-provided fixture: {pdf_path}", file=sys.stderr)
    else:
        print("Fetching latest Specialised stocklist from Tom's Outlook...",
              file=sys.stderr)
        builders_cfg = load_builders_config(BUNDLE_ROOT)
        pdf_path = fetch_latest_for_builder(
            "specialised", builders_cfg, bundle_root=BUNDLE_ROOT,
        )
        print(f"  Downloaded: {pdf_path.name}", file=sys.stderr)
    if not pdf_path.exists():
        print(f"ERROR: stocklist PDF not found at {pdf_path}", file=sys.stderr)
        return 1

    recipient = os.environ.get(
        "BOLST_ONE_PART_RECIPIENT", os.environ["BOLST_REPORT_RECIPIENT"],
    )
    sender = os.environ["BOLST_REPORT_SENDER"]

    now_mel = datetime.now(MELBOURNE)
    report_date = (now_mel + timedelta(days=1)).strftime("%Y-%m-%d")
    subject = f"[Bolst One Part — {report_date}]"

    print(f"Loading candidates from {pdf_path.name}...", file=sys.stderr)
    groups = get_specialised_candidates(pdf_path)
    total_rows = sum(len(g.rows) for g in groups)
    print(f"  {total_rows} candidate rows in {len(groups)} group(s)", file=sys.stderr)

    if total_rows == 0:
        print("WARN: zero candidates — sending empty prompt anyway.", file=sys.stderr)

    html = _build_html_body(groups, report_date, total_rows)

    print(f"Sending '{subject}' to {recipient} as {sender}...", file=sys.stderr)
    response = send_mail(recipient=recipient, subject=subject, body_html=html)

    if response.status_code == 202:
        print("OK — 202 Accepted. Evening prompt queued by Microsoft Graph.", file=sys.stderr)
        return 0
    print(f"FAILED — HTTP {response.status_code}", file=sys.stderr)
    print(f"Response body:\n{response.text}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
