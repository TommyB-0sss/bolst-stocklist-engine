"""
Local PDF renderer — Bolst stocklist + Bolst Listings, no Graph send.

Mirrors skills/compose-and-send/send_report.py but:
  - Pulls every builder in lib/builder_roster.py from Tom's Outlook (same fetch
    path as production)
  - Parses a LOCAL REA Ignite CSV (Tom hasn't wired the scheduled email yet)
  - Writes PDF to bundle output/ folder — no Microsoft Graph send

Usage (from bundle root, venv active):
    python skills/render-bolst-pdf/render_local.py
    python skills/render-bolst-pdf/render_local.py --rea-csv <path>
    python skills/render-bolst-pdf/render_local.py --report-date 2026-05-23

Default REA CSV: bolst-property-group-data/HomeLandPkg_Active_All_Agents_20260501.csv
"""

from __future__ import annotations

import sys
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BUNDLE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.graph_read import (  # noqa: E402
    IngestError, fetch_all_for_builder, load_builders_config,
)
from lib.builder_roster import PARSERS                                   # noqa: E402
from lib.parsers.rea_ignite import parse as parse_rea                    # noqa: E402
from lib.parsers.types import StocklistRow                               # noqa: E402
from lib.pdf_render import build_report_pdf                              # noqa: E402
from lib.pick_apply import apply_picks                                   # noqa: E402
from lib.picks_store import read_picks_for                               # noqa: E402
from lib.routing import ONE_PART_REGION_ID, load_config, route           # noqa: E402
from lib.status_filter import load_drop_list, should_keep                # noqa: E402

load_dotenv(BUNDLE_ROOT / ".env")
MELBOURNE = ZoneInfo("Australia/Melbourne")

REPO_ROOT = BUNDLE_ROOT.parent
DEFAULT_REA_CSV = (
    REPO_ROOT / "bolst-property-group-data"
    / "HomeLandPkg_Active_All_Agents_20260501.csv"
)

# PARSERS comes from lib/builder_roster.py — this script kept its own copy and
# was still on 6 builders after Goldstate and Monaco went live, so it rendered a
# clean-looking PDF that silently omitted both.


def _arg(argv: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def _resolve_report_date(argv: list[str]) -> _date:
    val = _arg(argv, "--report-date")
    if val:
        return datetime.strptime(val, "%Y-%m-%d").date()
    return datetime.now(MELBOURNE).date()


def _ingest_all_builders() -> tuple[list[StocklistRow], list[str]]:
    """Identical to send_report._ingest_all_builders — per-builder try/except."""
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


def _picks_to_rows(stored_picks: list[dict]) -> list[StocklistRow]:
    return [
        StocklistRow(
            builder="specialised",
            suburb=p["suburb"],
            estate=p.get("estate"),
            lot=p["lot"],
        )
        for p in stored_picks
    ]


def main(argv: list[str]) -> int:
    report_date = _resolve_report_date(argv)
    rea_csv = Path(_arg(argv, "--rea-csv") or DEFAULT_REA_CSV)

    print(f"=== Local PDF render ===")
    print(f"Report date: {report_date.isoformat()}")
    print(f"REA CSV:     {rea_csv}")
    print()

    # 1. Builders from Outlook
    print("Ingesting all 6 builders live from Tom's Outlook...")
    all_rows, failed_builders = _ingest_all_builders()
    n_ok = 6 - len(set(b.split(":")[0] for b in failed_builders))
    print(f"\nIngested: {len(all_rows)} total rows from {n_ok} of 6 builders")
    if failed_builders:
        print(f"  FAILED:  {failed_builders}")

    # 2. REA listings from local CSV
    print(f"\nParsing REA Ignite CSV: {rea_csv.name}")
    if not rea_csv.exists():
        print(f"  ERROR: CSV not found at {rea_csv}", file=sys.stderr)
        return 1
    listings = parse_rea(rea_csv)
    print(f"  Parsed: {len(listings)} listings")

    # 3. One Part picks (if any reply file exists for this date)
    stored = read_picks_for(report_date, bundle_root=BUNDLE_ROOT)
    if stored is None:
        print(f"\nNo One Part picks for {report_date}.")
        picks_count, unresolved, applied = 0, [], 0
    else:
        print(f"\nPicks file: {len(stored.picks)} picks, "
              f"{len(stored.unresolved)} unresolved")
        pick_rows = _picks_to_rows(stored.picks)
        applied = apply_picks(all_rows, pick_rows)
        picks_count, unresolved = applied, list(stored.unresolved)

    # 4. Route + status filter
    cfg = load_config(BUNDLE_ROOT / "config" / "suburbs.yml")
    drops = load_drop_list(BUNDLE_ROOT / "config" / "status-filter.yml")
    routed = route(all_rows, cfg)
    kept = [r for r in routed if should_keep(r.row.status, drops)]
    one_part_rows = [r for r in kept if r.region_id == ONE_PART_REGION_ID]
    print(f"\nRouted: {len(routed)} -> {len(kept)} kept after status filter "
          f"({len(one_part_rows)} One Part)")

    # 5. Render
    notice = None
    if unresolved:
        notice = "Some entries in your reply could not be applied:  " + \
                 "  ".join(f"- {u}" for u in unresolved)

    pdf_bytes = build_report_pdf(
        kept, cfg,
        bundle_root=BUNDLE_ROOT,
        report_date=report_date,
        one_part_notice=notice,
        listings=listings,
    )
    out_path = (BUNDLE_ROOT / "output"
                / f"bolst-local-{report_date.isoformat()}.pdf")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pdf_bytes)
    print(f"\nRendered: {len(pdf_bytes):,} bytes -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
