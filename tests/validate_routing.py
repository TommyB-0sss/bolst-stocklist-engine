"""
End-to-end Stage 7 validator: parsers → routing → status filter.

Usage (from bundle root, with venv active):
    python tests/validate_routing.py

Tests STRUCTURAL invariants over the live data flowing through the full
Stage 7 pipeline. Drift-tolerant — does not assert specific row counts,
status names, or estate distributions.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.aplace import parse as parse_aplace                # noqa: E402
from lib.parsers.aldrich import parse as parse_aldrich              # noqa: E402
from lib.parsers.hermitage import parse as parse_hermitage          # noqa: E402
from lib.parsers.urbane import parse as parse_urbane                # noqa: E402
from lib.parsers.specialised import parse as parse_specialised      # noqa: E402
from lib.parsers.luxton import parse as parse_luxton                # noqa: E402
from lib.routing import (                                            # noqa: E402
    load_config, route, FEATURED_SOURCE_REGIONS,
    ONE_PART_REGION_ID, UNCATEGORISED_REGION_ID,
)
from lib.status_filter import load_drop_list, should_keep            # noqa: E402

DATA = BUNDLE_ROOT.parent / "bolst-property-group-data"


def _gather_all_rows() -> list:
    rows = []
    for parser, paths in [
        (parse_aplace,      sorted((DATA / "aplacevic@aplace.com.au").glob("*.pdf"))),
        (parse_aldrich,     [DATA / "Corey.b@aldrichhomes.com.au" / "Stocklist C44.pdf"]),
        (parse_hermitage,   sorted((DATA / "houseandland@hermitagehomes.com.au").glob("*.pdf"))),
        (parse_urbane,      sorted((DATA / "mikayla+2Esalva=orbithomes.com.au@hubspotfree.hs-send.com").glob("*.pdf"))),
        (parse_specialised, [DATA / "nlimbo@specialisedhomeconstructions.com.au" / "Stocklist 28.04.26.pdf"]),
        (parse_luxton,      sorted((DATA / "stefanc@luxtonhomes.com.au").glob("*.xlsx"))),
    ]:
        for p in paths:
            if p.exists():
                rows.extend(parser(p))
    return rows


def main() -> int:
    cfg = load_config(BUNDLE_ROOT / "config" / "suburbs.yml")
    drops = load_drop_list(BUNDLE_ROOT / "config" / "status-filter.yml")

    print(f"Config: {len(cfg.region_ids)} regions, "
          f"{len(cfg.suburb_aliases)} aliases, "
          f"{len(cfg.suburb_to_region)} suburbs.")
    print(f"Status drop list: {sorted(drops)}\n")

    rows = _gather_all_rows()
    routed = route(rows, cfg)
    kept = [r for r in routed if should_keep(r.row.status, drops)]
    dropped_n = len(routed) - len(kept)

    print(f"Parsed:        {len(rows)} rows")
    print(f"Routed:        {len(routed)} rows")
    print(f"Status-dropped:{dropped_n} rows")
    print(f"Kept:          {len(kept)} rows")
    print(f"\nKept by region:")
    for rid, n in sorted(Counter(r.region_id for r in kept).items(), key=lambda x: -x[1]):
        name = cfg.region_names.get(rid, "(uncategorised)")
        print(f"  {rid:25s} ({name:20s}) = {n}")

    unc = [r for r in kept if r.is_uncategorised]
    if unc:
        print(f"\nUncategorised (kept-but-needs-Tom-review): {len(unc)}")
        for k, n in Counter((r.row.builder, r.row.suburb, r.routing_reason) for r in unc).items():
            print(f"  {k}: {n}")

    featured = [r for r in routed if r.meta.get("featured")]
    print(f"\nFeatured rows: {len(featured)} (Hermitage PACKAGES + Aldrich Exclusive)")

    # --- Structural invariants ---
    fails: list[str] = []

    if len(routed) != len(rows):
        fails.append(f"routing dropped rows: {len(rows)} in, {len(routed)} out")

    valid_region_ids = cfg.region_ids | {UNCATEGORISED_REGION_ID}
    bad = {r.region_id for r in routed} - valid_region_ids
    if bad:
        fails.append(f"unknown region_id(s) emitted: {bad}")

    if not all(r.routing_reason for r in routed):
        fails.append("some routed rows have empty routing_reason")

    # is_one_part precedence: every is_one_part row must be in one-part region.
    for r in routed:
        if r.row.is_one_part and r.region_id != ONE_PART_REGION_ID:
            fails.append(
                f"is_one_part row routed to {r.region_id!r}, expected "
                f"{ONE_PART_REGION_ID!r}: {r.row.builder}/{r.row.suburb}/lot {r.row.lot}"
            )
            break

    # Corollary: every row in one-part region must be is_one_part=True.
    for r in routed:
        if r.region_id == ONE_PART_REGION_ID and not r.row.is_one_part:
            fails.append(
                f"row in one-part region without is_one_part=True: "
                f"{r.row.builder}/{r.row.suburb}/lot {r.row.lot}"
            )
            break

    # Featured flag iff source_region is a featured marker.
    for r in routed:
        expected_featured = r.row.source_region in FEATURED_SOURCE_REGIONS
        actual_featured = bool(r.meta.get("featured"))
        if expected_featured != actual_featured:
            fails.append(
                f"featured-flag mismatch: source_region={r.row.source_region!r}, "
                f"meta.featured={actual_featured}, builder={r.row.builder}"
            )
            break

    # Uncategorised rows must have a clear routing_reason.
    for r in routed:
        if r.is_uncategorised and not (
            r.routing_reason.startswith("suburb_unmapped:")
            or r.routing_reason == "suburb_empty"
        ):
            fails.append(
                f"uncategorised row with unclear reason: {r.routing_reason!r}"
            )
            break

    # --- Status filter sanity ---
    sf_fails = []
    if not should_keep(None, drops):
        sf_fails.append("None status should be kept")
    if not should_keep("", drops):
        sf_fails.append("blank status should be kept")
    if not should_keep("Available", drops):
        sf_fails.append("'Available' should be kept")
    if not should_keep("Contact signed", drops):  # the Stefan typo — explicit kept-by-design
        sf_fails.append("'Contact signed' (typo) should be kept (per Inam 2026-05-08)")
    # Each drop-list entry must work case-insensitively.
    for entry in drops:
        if should_keep(entry, drops):
            sf_fails.append(f"drop-list entry {entry!r} unexpectedly kept (uppercase)")
        if should_keep(entry.title(), drops):
            sf_fails.append(f"drop-list entry {entry.title()!r} unexpectedly kept (titlecase)")
        if should_keep(entry.lower(), drops):
            sf_fails.append(f"drop-list entry {entry.lower()!r} unexpectedly kept (lowercase)")
    fails.extend(sf_fails)

    print("\n--- Structural checks ---")
    if fails:
        print(f"FAIL ({len(fails)} violation(s)):")
        for f in fails:
            print(f"  - {f}")
        return 2
    print(f"PASS - {len(routed)} rows route cleanly through Stage 7 pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
