"""
Stage 9.8.7b — Morning report orchestrator (07:00 AEST Tue-Sat).

Live end-to-end production pipeline. Reads all 6 builders' stocklists
from Tom's Outlook, applies any One Part picks Tom replied with overnight,
routes + filters + renders the branded PDF, and sends it via Microsoft
Graph from Tom's Outlook to the configured recipient.

Usage (from bundle root, with venv active):
    python skills/compose-and-send/send_report.py
    python skills/compose-and-send/send_report.py --no-send       # render only
    python skills/compose-and-send/send_report.py --report-date 2026-05-10

Resilience
----------
If any single builder fails to ingest (transient HTTP, format change),
the orchestrator logs and skips that builder rather than aborting the
whole report. The morning report ships with the available 5/6 (or
4/6) builders' data and a footer note. Catastrophic failures
(authentication, render) abort.
"""

from __future__ import annotations

import os
import sys
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BUNDLE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.graph_read import (  # noqa: E402
    IngestError, fetch_all_for_builder, load_builders_config,
)
from lib.graph_send import Attachment, send_mail                         # noqa: E402
from lib.parsers.aldrich import parse as parse_aldrich                   # noqa: E402
from lib.parsers.aplace import parse as parse_aplace                     # noqa: E402
from lib.parsers.hermitage import parse as parse_hermitage               # noqa: E402
from lib.parsers.luxton import parse as parse_luxton                     # noqa: E402
from lib.parsers.rea_ignite import parse as parse_rea                    # noqa: E402
from lib.parsers.specialised import parse as parse_specialised           # noqa: E402
from lib.parsers.urbane import parse as parse_urbane                     # noqa: E402
from lib.parsers.types import ListingRow, StocklistRow                   # noqa: E402
from lib.one_part_collect import collect_picks                          # noqa: E402
from lib.pdf_render import build_report_pdf                              # noqa: E402
from lib.pick_apply import apply_picks                                   # noqa: E402
from lib.routing import ONE_PART_REGION_ID, load_config, route           # noqa: E402
from lib.status_filter import load_drop_list, should_keep                # noqa: E402

load_dotenv(BUNDLE_ROOT / ".env")
MELBOURNE = ZoneInfo("Australia/Melbourne")

PARSERS = {
    "specialised": parse_specialised,
    "aldrich":     parse_aldrich,
    "urbane":      parse_urbane,
    "hermitage":   parse_hermitage,
    "aplace":      parse_aplace,
    "luxton":      parse_luxton,
}


def _arg(argv: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        return argv[i + 1]
    return default


def _today_report_date(argv: list[str]) -> _date:
    val = _arg(argv, "--report-date")
    if val:
        return datetime.strptime(val, "%Y-%m-%d").date()
    return datetime.now(MELBOURNE).date()


def _build_notice(pick_count: int, unresolved: list[str]) -> str | None:
    if not unresolved:
        return None
    header = "Some entries in your reply could not be applied:"
    bullets = "  ".join(f"- {u}" for u in unresolved)
    return f"{header}  {bullets}"


def _ingest_all_builders() -> tuple[list[StocklistRow], list[str]]:
    """Fetch + parse all 6 builders. Returns (rows, failed_builder_ids).

    Per-builder try/except so one builder's transient failure doesn't
    abort the morning report. The morning email mentions which builders
    failed via the optional notice/footer.
    """
    builders_cfg = load_builders_config(BUNDLE_ROOT)
    rows: list[StocklistRow] = []
    failed: list[str] = []
    for builder_id, parser in PARSERS.items():
        print(f"  [{builder_id}] fetching...", file=sys.stderr)
        try:
            paths = fetch_all_for_builder(
                builder_id, builders_cfg, bundle_root=BUNDLE_ROOT,
            )
        except IngestError as e:
            print(f"    SKIP: {e}", file=sys.stderr)
            failed.append(builder_id)
            continue
        except Exception as e:
            print(f"    SKIP: {type(e).__name__}: {e}", file=sys.stderr)
            failed.append(builder_id)
            continue
        for path in paths:
            try:
                builder_rows = parser(path)
                rows.extend(builder_rows)
                print(f"    {path.name}: {len(builder_rows)} rows", file=sys.stderr)
            except Exception as e:
                print(f"    parse failed for {path.name}: {e}", file=sys.stderr)
                failed.append(f"{builder_id}:{path.name}")
    return rows, failed


def _log_rea_freshness(path: Path) -> None:
    """Log whether the REA CSV is current-week or older. REA is a WEEKLY file
    (Tom emails himself one each Monday, reused all week); the cache filename
    is 'YYYYMMDD-<name>' carrying the email's received date. We use the most
    recent available regardless of age, but surface staleness so a missed
    Monday is visible rather than silent."""
    try:
        d = datetime.strptime(path.name[:8], "%Y%m%d").date()
    except ValueError:
        return
    today = datetime.now(MELBOURNE).date()
    week_start = today - timedelta(days=today.weekday())  # this week's Monday
    if d >= week_start:
        print(f"    REA CSV is current-week (dated {d.isoformat()}).", file=sys.stderr)
    else:
        age = (today - d).days
        print(f"    REA CSV is from a PRIOR week (dated {d.isoformat()}, "
              f"{age} days old) — using most recent available.", file=sys.stderr)


def _ingest_rea_listings() -> tuple[list[ListingRow], Optional[str]]:
    """Fetch + parse Tom's daily 'REA CSV' email. Returns (listings, error).

    The REA feed is independent of the 6 builder pipelines: it produces
    ListingRows (not StocklistRows), bypasses the status filter, and
    folds into regions at render time via lib/pdf_render._route_listings.

    Non-fatal: if Tom skipped the export today, log a warning and return
    an empty list so the morning report still ships with builder rows.
    """
    builders_cfg = load_builders_config(BUNDLE_ROOT)
    try:
        paths = fetch_all_for_builder(
            "rea", builders_cfg, bundle_root=BUNDLE_ROOT,
        )
    except IngestError as e:
        return [], str(e)
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"

    listings: list[ListingRow] = []
    for p in paths:
        try:
            parsed = parse_rea(p)
            listings.extend(parsed)
            print(f"    {p.name}: {len(parsed)} listings", file=sys.stderr)
            _log_rea_freshness(p)
        except Exception as e:
            return listings, f"parse failed for {p.name}: {e}"
    return listings, None


def _format_subject(report_date: _date) -> str:
    # Build day-without-leading-zero manually because Windows strftime
    # doesn't support %-d. Result: "Bolst Stocklist - Sat 9 May".
    return (
        f"Bolst Stocklist - {report_date.strftime('%a')} "
        f"{report_date.day} {report_date.strftime('%b')}"
    )


def _format_long_date(report_date: _date) -> str:
    """e.g. 'Saturday 9 May 2026'."""
    return (
        f"{report_date.strftime('%A')} "
        f"{report_date.day} {report_date.strftime('%B %Y')}"
    )


def main(argv: list[str]) -> int:
    no_send = "--no-send" in argv
    report_date = _today_report_date(argv)
    print(f"=== Morning report orchestrator ===")
    print(f"Report date: {report_date.isoformat()}")
    print(f"Recipient:   {os.environ['BOLST_REPORT_RECIPIENT']}")
    print(f"Sender:      {os.environ['BOLST_REPORT_SENDER']}")
    print(f"No-send:     {no_send}\n")

    # 1. Ingest all 6 builders live
    print("Ingesting all 6 builders live from Outlook...")
    all_rows, failed_builders = _ingest_all_builders()
    print(f"\nIngested: {len(all_rows)} total rows from "
          f"{6 - len(set(b.split(':')[0] for b in failed_builders))} of 6 builders")
    if failed_builders:
        print(f"  FAILED:  {failed_builders}")

    # 1b. Ingest Bolst's own REA Active Listings export (subject "REA CSV"
    # from Tom to himself). Non-fatal — if Tom skipped the export today,
    # the report still ships with builder rows + empty REA section.
    print("\nIngesting Bolst REA Active Listings...")
    listings, rea_error = _ingest_rea_listings()
    if not listings:
        # REA is MANDATORY (Inam 2026-06-02): never ship a report with no
        # listings. Tom emails himself the weekly REA CSV (subject 'REA CSV',
        # attachment REA*.csv); we use the most recent one regardless of age,
        # but if there is NONE at all we hold the entire report.
        print("\nABORT: REA listings are mandatory and none were found.",
              file=sys.stderr)
        print(f"  reason: {rea_error or 'the REA CSV produced zero listings'}",
              file=sys.stderr)
        print("  action: Tom must email himself the REA CSV "
              "(subject 'REA CSV', attachment REA*.csv). "
              "Report NOT generated or sent.", file=sys.stderr)
        return 1
    print(f"\n  REA listings: {len(listings)} rows")

    # 2. Read Tom's overnight One Part reply DIRECTLY from Outlook and apply.
    # Folded in from the old standalone 06:30 poll: Routines are stateless,
    # so the .cache picks-file handoff didn't survive across cloud VM fires.
    # Reading the reply here removes that cross-fire dependency. Non-fatal —
    # a Graph hiccup on the reply read shouldn't sink the whole report, which
    # still ships with the auto-flagged Hermitage/Luxton One Part rows.
    try:
        collected = collect_picks(report_date.isoformat(), bundle_root=BUNDLE_ROOT)
        if collected.reply_found:
            print(f"\nOne Part reply from {collected.reply_from}: "
                  f"{len(collected.picks)} picks, {len(collected.unresolved)} unresolved")
        else:
            print(f"\nNo One Part reply found for {report_date} - no picks applied.")
        applied = apply_picks(all_rows, collected.picks)
        print(f"  apply_picks: {applied} of {len(collected.picks)} promoted to is_one_part=True")
        picks_count, unresolved = applied, list(collected.unresolved)
    except Exception as e:
        print(f"\nOne Part reply read FAILED ({type(e).__name__}: {e}) - "
              f"shipping with auto-flagged rows only.", file=sys.stderr)
        picks_count, unresolved, applied = 0, [], 0

    # 3. Routing + status filter (existing Stage 7)
    cfg = load_config(BUNDLE_ROOT / "config" / "suburbs.yml")
    drops = load_drop_list(BUNDLE_ROOT / "config" / "status-filter.yml")
    routed = route(all_rows, cfg)
    kept = [r for r in routed if should_keep(r.row.status, drops)]
    one_part_rows = [r for r in kept if r.region_id == ONE_PART_REGION_ID]
    print(f"\nRouted:   {len(routed)} -> {len(kept)} kept after status filter")
    print(f"One Part: {len(one_part_rows)} rows ({applied} from Tom's picks, "
          f"{len(one_part_rows) - applied} auto-flagged)")

    # 4. Render branded PDF
    notice = _build_notice(picks_count, unresolved)
    if notice:
        print(f"\nOne Part notice banner: {notice!r}")
    pdf_bytes = build_report_pdf(
        kept, cfg,
        bundle_root=BUNDLE_ROOT,
        report_date=report_date,
        one_part_notice=notice,
        listings=listings,
    )
    out_path = BUNDLE_ROOT / "output" / f"bolst-stocklist-{report_date.isoformat()}.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pdf_bytes)
    print(f"\nRendered: {len(pdf_bytes):,} bytes -> {out_path}")

    if no_send:
        print("\n--no-send specified - skipping Graph send.")
        return 0

    # 5. Send via Graph
    subject = _format_subject(report_date)
    body_text = (
        f"Morning - Bolst stocklist report attached.\n\n"
        f"Report date: {_format_long_date(report_date)}\n"
        f"Builders ingested today: {6 - len(set(b.split(':')[0] for b in failed_builders))}/6\n"
        f"Total builder rows (post status filter): {len(kept)}\n"
        f"Bolst REA listings folded in: {len(listings)}\n"
        f"One Part rows: {len(one_part_rows)} "
        f"({applied} from your picks, "
        f"{len(one_part_rows) - applied} auto-flagged)\n"
    )
    if failed_builders:
        body_text += f"\nBuilders skipped this morning: {', '.join(failed_builders)}\n"
    if rea_error:
        body_text += f"\nREA Active Listings: skipped today ({rea_error})\n"

    recipient = os.environ["BOLST_REPORT_RECIPIENT"]
    print(f"\nSending '{subject}' to {recipient}...")
    response = send_mail(
        recipient=recipient,
        subject=subject,
        body_text=body_text,
        attachments=[Attachment(
            filename=out_path.name,
            content=pdf_bytes,
        )],
    )
    if response.status_code == 202:
        print("OK - 202 Accepted. Morning report queued by Graph.")
        return 0
    print(f"FAILED - HTTP {response.status_code}", file=sys.stderr)
    print(response.text, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
