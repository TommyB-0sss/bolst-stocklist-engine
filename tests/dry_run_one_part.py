"""
Stage 9.7 — End-to-end dry run of the One Part editorial flow.

Takes a synthetic reply text (representing what Tom would send back to
yesterday's evening prompt), runs the full pipeline:

    reply text
      -> lib.pick_parser.parse_picks(reply, candidates)
      -> lib.pick_apply.apply_picks(all_rows, picks)
      -> lib.routing.route + lib.status_filter
      -> lib.pdf_render.build_report_pdf(one_part_notice=...)

and writes the resulting PDF to output/dry_run_one_part-<timestamp>.pdf so
the user can inspect: (a) Tom's picks landed in the One Part Contracts tab,
and (b) the unresolved-entries banner appears with helpful messages.

Usage (from bundle root, with venv active):
    python tests/dry_run_one_part.py "Lot 42, Lot 42 Benalla, Lot 99999 Atlantis"
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.aplace import parse as parse_aplace                # noqa: E402
from lib.parsers.aldrich import parse as parse_aldrich              # noqa: E402
from lib.parsers.hermitage import parse as parse_hermitage          # noqa: E402
from lib.parsers.urbane import parse as parse_urbane                # noqa: E402
from lib.parsers.specialised import parse as parse_specialised      # noqa: E402
from lib.parsers.luxton import parse as parse_luxton                # noqa: E402
from lib.one_part_candidates import get_specialised_candidates      # noqa: E402
from lib.pick_parser import parse_picks                             # noqa: E402
from lib.pick_apply import apply_picks                              # noqa: E402
from lib.routing import load_config, route, ONE_PART_REGION_ID      # noqa: E402
from lib.status_filter import load_drop_list, should_keep           # noqa: E402
from lib.pdf_render import build_report_pdf                         # noqa: E402
from lib.graph_read import fetch_latest_for_builder, load_builders_config  # noqa: E402

DATA = BUNDLE_ROOT.parent / "bolst-property-group-data"


def _live_specialised_path() -> Path:
    """Pull the latest Specialised PDF from Tom's Outlook (cached same-day)."""
    cfg = load_builders_config(BUNDLE_ROOT)
    return fetch_latest_for_builder("specialised", cfg, bundle_root=BUNDLE_ROOT)


def _gather_all_rows(specialised_path: Path) -> list:
    """Gather rows across all 6 builders.

    Stage 9.8.2: Specialised reads LIVE from Tom's Outlook. Other 5
    builders still read from fixtures pending substeps 9.8.3 - 9.8.6.
    """
    rows = []
    for parser, paths in [
        (parse_aplace,      sorted((DATA / "aplacevic@aplace.com.au").glob("*.pdf"))),
        (parse_aldrich,     [DATA / "Corey.b@aldrichhomes.com.au" / "Stocklist C44.pdf"]),
        (parse_hermitage,   sorted((DATA / "houseandland@hermitagehomes.com.au").glob("*.pdf"))),
        (parse_urbane,      sorted((DATA / "mikayla+2Esalva=orbithomes.com.au@hubspotfree.hs-send.com").glob("*.pdf"))),
        (parse_specialised, [specialised_path]),
        (parse_luxton,      sorted((DATA / "stefanc@luxtonhomes.com.au").glob("*.xlsx"))),
    ]:
        for p in paths:
            if p.exists():
                rows.extend(parser(p))
    return rows


def _build_notice(pick_count: int, unresolved: list[str]) -> str | None:
    """Compose the One Part tab notice from poll results.

    Cases:
      - picks > 0, unresolved == 0 -> no notice (clean reply)
      - picks > 0, unresolved > 0  -> notice listing the unresolved entries
      - picks == 0, unresolved == 0 -> "no picks received" notice
      - picks == 0, unresolved > 0 -> just the unresolved messages
    """
    if pick_count == 0 and not unresolved:
        return "No Specialised picks received - reply to yesterday's prompt to add."
    if not unresolved:
        return None
    header = "Some entries in your reply could not be applied:"
    bullets = "  ".join(f"- {u}" for u in unresolved)
    return f"{header}  {bullets}"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('Usage: python tests/dry_run_one_part.py "Lot 42, Lot 42 Benalla, ..."',
              file=sys.stderr)
        return 1
    reply_text = argv[1]
    print(f"Reply text: {reply_text!r}\n")

    # Stage 9.8.2 — pull live Specialised from Tom's Outlook (cached same-day)
    print("Fetching latest Specialised PDF live from Tom's Outlook...")
    specialised_path = _live_specialised_path()
    print(f"  Using: {specialised_path.name}\n")

    # Stage 9.3 — parse picks from reply
    candidates = get_specialised_candidates(specialised_path)
    result = parse_picks(reply_text, candidates)
    print(f"Pick parser: {len(result.picks)} pick(s), {len(result.unresolved)} unresolved")
    for p in result.picks:
        print(f"  PICK:        Lot {p.lot} {p.suburb} / {p.estate} (${p.total_price:,})")
    for u in result.unresolved:
        print(f"  UNRESOLVED:  {u}")
    print()

    # Stage 9.4 — apply picks to all parsed rows
    all_rows = _gather_all_rows(specialised_path)
    print(f"Pipeline gather: {len(all_rows)} parsed rows across all 6 builders")
    n_applied = apply_picks(all_rows, result.picks)
    print(f"apply_picks: {n_applied} row(s) promoted to is_one_part=True")
    if n_applied != len(result.picks):
        print(f"  ! drift: {len(result.picks)} picks but {n_applied} applied")
    print()

    # Routing + status filter (existing Stage 7 pipeline)
    cfg = load_config(BUNDLE_ROOT / "config" / "suburbs.yml")
    drops = load_drop_list(BUNDLE_ROOT / "config" / "status-filter.yml")
    routed = route(all_rows, cfg)
    kept = [r for r in routed if should_keep(r.row.status, drops)]
    print(f"Routing:    {len(routed)} routed, {len(kept)} kept after status filter")

    # Spot-check: how many ended up in the One Part region?
    one_part_rows = [r for r in kept if r.region_id == ONE_PART_REGION_ID]
    one_part_specialised = [r for r in one_part_rows if r.row.builder == "specialised"]
    print(f"One Part region: {len(one_part_rows)} total "
          f"({len(one_part_specialised)} from Specialised picks, "
          f"{len(one_part_rows) - len(one_part_specialised)} auto-flagged from other builders)")
    print()

    # Stage 9.5 — build notice from picks + unresolved
    notice = _build_notice(len(result.picks), result.unresolved)
    if notice:
        print(f"One Part notice banner: {notice!r}")
    else:
        print("One Part notice banner: (none — all picks resolved cleanly)")
    print()

    # Render
    pdf_bytes = build_report_pdf(
        kept, cfg,
        bundle_root=BUNDLE_ROOT,
        one_part_notice=notice,
    )
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = BUNDLE_ROOT / "output" / f"dry_run_one_part-{timestamp}.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pdf_bytes)
    print(f"PDF written: {out_path}  ({len(pdf_bytes):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
