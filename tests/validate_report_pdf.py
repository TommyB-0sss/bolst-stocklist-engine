"""
Validation script for the Stage 8 branded PDF render.

Usage (from bundle root, with venv active):
    python tests/validate_report_pdf.py

Runs the full pipeline (parsers -> routing -> status filter -> render) and
checks STRUCTURAL invariants of the resulting PDF: valid file, expected
page count for the region distribution, all region subtitles present,
empty regions show the placeholder message.

Drift-tolerant — does not assert specific row counts or estate names.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pdfplumber

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.aplace import parse as parse_aplace                # noqa: E402
from lib.parsers.aldrich import parse as parse_aldrich              # noqa: E402
from lib.parsers.hermitage import parse as parse_hermitage          # noqa: E402
from lib.parsers.urbane import parse as parse_urbane                # noqa: E402
from lib.parsers.specialised import parse as parse_specialised      # noqa: E402
from lib.parsers.luxton import parse as parse_luxton                # noqa: E402
from lib.routing import load_config, route                          # noqa: E402
from lib.status_filter import load_drop_list, should_keep           # noqa: E402
from lib.pdf_render import build_report_pdf                         # noqa: E402

DATA = BUNDLE_ROOT.parent / "bolst-property-group-data"


def _gather() -> list:
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

    rows = _gather()
    routed = route(rows, cfg)
    kept = [r for r in routed if should_keep(r.row.status, drops)]
    print(f"Pipeline: {len(rows)} parsed -> {len(routed)} routed -> {len(kept)} kept")

    pdf_bytes = build_report_pdf(kept, cfg, bundle_root=BUNDLE_ROOT)
    print(f"Rendered: {len(pdf_bytes):,} bytes")

    fails: list[str] = []

    # --- File-level structural checks ---
    if len(pdf_bytes) < 100:
        fails.append("PDF too small to be valid")
    if not pdf_bytes.startswith(b"%PDF-"):
        fails.append("PDF missing %PDF- magic bytes")

    # Save to disk so pdfplumber can read it (and so the user can open it).
    out = BUNDLE_ROOT / "output" / "bolst-stocklist-validator.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf_bytes)

    with pdfplumber.open(out) as pdf:
        n_pages = len(pdf.pages)
        print(f"\nPage count: {n_pages}")

        # We render 10 region pages (Horsham gets a placeholder page) +
        # at least 1 footer page = >= 11. Long regions overflow to multiple
        # pages, so >= 11 is the floor, not an exact match.
        if n_pages < 11:
            fails.append(f"page count {n_pages} < 11 (10 region pages + 1 footer)")

        # Every region declared in the config must appear on at least one
        # page (its name shows up in a subtitle).
        rows_by_region = Counter(r.region_id for r in kept)
        all_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        # The subtitle 'Stocklist as at <date> | <N> packages' should appear
        # for every region. Sanity-check each region produces at least one
        # subtitle string in the PDF text.
        subtitle_count = all_text.count("Stocklist as at")
        if subtitle_count < len(cfg.region_ids):
            fails.append(f"only {subtitle_count} subtitles found, expected "
                         f">= {len(cfg.region_ids)} (one per region)")

        # Empty regions must display the "No packages this week" message.
        empty_regions = [rid for rid in cfg.region_ids if rows_by_region.get(rid, 0) == 0]
        if empty_regions and "No packages this week" not in all_text:
            fails.append(f"empty regions {empty_regions} but 'No packages this week' "
                         f"missing from PDF")

        # Page dimensions: page 0 is the merged cover (Tom's Front Cover.pdf,
        # Letter portrait 612x792). Page 1 onwards is region content (A4
        # landscape ~842x595).
        if len(pdf.pages) >= 2:
            second = pdf.pages[1]
            if not (820 < second.width < 860 and 580 < second.height < 615):
                fails.append(f"page 1 dimensions {second.width}x{second.height} "
                             f"don't look like landscape A4 (~842x595 pt)")

        # Each non-empty region produces a column-header line in the
        # rendered PDF text. Count occurrences vs unique non-empty regions.
        non_empty_regions = sum(1 for c in rows_by_region.values() if c > 0)
        # Header line includes "SUBURB LOT NO ADDRESS ESTATE" — fingerprint.
        header_appearances = all_text.count("SUBURB LOT NO ADDRESS")
        if header_appearances < non_empty_regions:
            fails.append(f"column-header appears {header_appearances} times, "
                         f"expected >= {non_empty_regions} non-empty regions")

    # --- Per-region row counts in PDF subtitle should match kept rows ---
    # subtitle text contains "| N packages" and "| N package"; sum these
    # against expected.
    import re
    pkg_matches = re.findall(r"\| (\d+) package", all_text)
    # Each region produces one "first" subtitle (no "(continued)") with the
    # actual count, plus possibly N additional "(continued)" subtitles with
    # the same count. So count-of-distinct-counts is messier; just sanity-
    # check the distinct values include every region's actual row count.
    expected_counts = set(rows_by_region.values())  # includes 0
    actual_counts = {int(m) for m in pkg_matches}
    missing = expected_counts - actual_counts
    if missing:
        fails.append(f"PDF subtitles missing expected row counts: {missing}")

    print("\n--- Structural checks ---")
    if fails:
        print(f"FAIL ({len(fails)} violation(s)):")
        for f in fails:
            print(f"  - {f}")
        return 2
    print(f"PASS - PDF rendered cleanly. {n_pages} pages, "
          f"{len(kept)} rows across {len(cfg.region_ids)} regions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
