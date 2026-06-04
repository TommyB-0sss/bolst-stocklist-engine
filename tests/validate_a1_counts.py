"""Cross-check: simulate the bucket logic that build_report_pdf uses
and print per-region row counts (builder + listings) for inspection."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.graph_read import fetch_all_for_builder, load_builders_config  # noqa: E402
from lib.parsers.aldrich import parse as parse_aldrich  # noqa: E402
from lib.parsers.aplace import parse as parse_aplace  # noqa: E402
from lib.parsers.hermitage import parse as parse_hermitage  # noqa: E402
from lib.parsers.luxton import parse as parse_luxton  # noqa: E402
from lib.parsers.rea_ignite import parse as parse_rea  # noqa: E402
from lib.parsers.specialised import parse as parse_specialised  # noqa: E402
from lib.parsers.urbane import parse as parse_urbane  # noqa: E402
from lib.pdf_render import (BOLST_EXTRA_PREFIX, _route_listings,  # noqa: E402
                            _section_row_from_listing,
                            _section_row_from_routed)
from lib.routing import load_config, route  # noqa: E402
from lib.status_filter import load_drop_list, should_keep  # noqa: E402

PARSERS = {
    "specialised": parse_specialised,
    "aldrich":     parse_aldrich,
    "urbane":      parse_urbane,
    "hermitage":   parse_hermitage,
    "aplace":      parse_aplace,
    "luxton":      parse_luxton,
}

REA_CSV = BUNDLE_ROOT / ".cache" / "builder-downloads" / "rea" / "20260525-REA Listings.csv"


def main() -> int:
    cfg = load_config(BUNDLE_ROOT / "config" / "suburbs.yml")
    drops = load_drop_list(BUNDLE_ROOT / "config" / "status-filter.yml")
    builders_cfg = load_builders_config(BUNDLE_ROOT)

    # Builders
    all_rows = []
    for bid, parser in PARSERS.items():
        for p in fetch_all_for_builder(bid, builders_cfg, bundle_root=BUNDLE_ROOT):
            all_rows.extend(parser(p))
    routed = route(all_rows, cfg)
    kept = [r for r in routed if should_keep(r.row.status, drops)]

    # Listings
    listings = parse_rea(REA_CSV)
    listing_buckets = _route_listings(listings, cfg)

    # Per-region tally
    builder_by_region = defaultdict(int)
    for r in kept:
        builder_by_region[r.region_id] += 1
    listing_by_region = defaultdict(int)
    extra_by_suburb = defaultdict(int)
    for region_id, ls in listing_buckets.items():
        if region_id.startswith(BOLST_EXTRA_PREFIX):
            suburb = region_id[len(BOLST_EXTRA_PREFIX):]
            extra_by_suburb[suburb] += len(ls)
        else:
            listing_by_region[region_id] += len(ls)

    print("Per-region row counts after A.1 merge:")
    print(f"{'region':<22} {'builders':>10} {'listings':>10} {'total':>10}")
    print("-" * 56)
    total_b = total_l = 0
    for rid in cfg.region_names:
        b = builder_by_region[rid]
        l = listing_by_region[rid]
        total_b += b
        total_l += l
        marker = "  <- NEW LISTINGS" if l else ""
        print(f"  {rid:<20} {b:>10} {l:>10} {b+l:>10}{marker}")
    print("-" * 56)
    print(f"  {'TOTAL':<20} {total_b:>10} {total_l:>10} {total_b+total_l:>10}")

    if extra_by_suburb:
        print()
        print("Bolst-extra (unmapped) sections:")
        for s, c in sorted(extra_by_suburb.items()):
            print(f"    {s}: {c} listing(s)")
    else:
        print()
        print("No bolst-extra sections this run (all listings mapped cleanly).")

    # Quick ASC sort sanity check on each non-empty region
    print()
    print("Sort sanity (first 3 rows of each non-empty region):")
    # Re-bucket as SectionRows like build_report_pdf does
    by_region = defaultdict(list)
    for rr in kept:
        by_region[rr.region_id].append(_section_row_from_routed(rr))
    for rid, ls in listing_buckets.items():
        if not rid.startswith(BOLST_EXTRA_PREFIX):
            for L in ls:
                by_region[rid].append(_section_row_from_listing(L))

    from lib.pdf_render import _section_sort_key
    issues = 0
    for rid in cfg.region_names:
        rows = sorted(by_region.get(rid, []), key=_section_sort_key)
        if not rows:
            continue
        print(f"  {rid}:")
        for r in rows[:3]:
            print(f"    {r.suburb!r:18s}  ${r.price_int or 0:>10,}  {r.address[:30]!r}")
        # Check ASC within first suburb
        first_suburb = rows[0].suburb
        prices_in_first = [r.price_int for r in rows if r.suburb == first_suburb
                           and r.price_int is not None]
        if prices_in_first != sorted(prices_in_first):
            print(f"    !!! SORT NOT ASCENDING within '{first_suburb}': {prices_in_first}")
            issues += 1

    print()
    print(f"Sort issues found: {issues}")
    return 0 if issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
