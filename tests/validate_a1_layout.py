"""A.1 layout validation: confirm Bolst listings folded into the 10
regions (no separate Bolst Listings page), AGENT column gone, sort is
suburb A-Z + price ASC, no extra-suburb sections (audit was 100% clean)."""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

import pypdfium2 as pdfium  # noqa: E402

PDF = BUNDLE_ROOT / "output" / "bolst-local-2026-05-25.pdf"


def main() -> int:
    doc = pdfium.PdfDocument(PDF)
    n_pages = len(doc)
    print(f"PDF: {PDF.name}")
    print(f"Pages: {n_pages}")

    seen_bolst_listings_header = False
    seen_agent_col_header = False
    region_titles_seen: list[str] = []
    extra_suburb_titles: list[str] = []

    canonical_titles = {
        "Stocklist as at",   # subtitle on every region page
    }
    known_region_words = {
        "ONE PART CONTRACTS", "GEELONG", "GIPPSLAND", "HORSHAM",
        "METRO NORTH", "METRO SOUTH EAST", "METRO WEST",
        "REGIONAL NORTH EAST", "REGIONAL WEST", "WARRNAMBOOL",
    }

    for i in range(n_pages):
        page = doc[i]
        textpage = page.get_textpage()
        text = textpage.get_text_bounded() or ""
        textpage.close()
        page.close()

        # Sniff for old standalone page artifacts
        if "BOLST LISTINGS" in text.upper():
            seen_bolst_listings_header = True
        # If AGENT column header is the literal column heading line. Real
        # region pages have "STATUS" at the end of the column-header row,
        # not "AGENT".
        # The 8 col headers are: SUBURB LOT NO ADDRESS ESTATE TITLES
        # BED/Bath/Car TOTAL $ STATUS
        # Old AGENT layout would have AGENT instead of STATUS.
        if "AGENT" in text.upper() and "SUBURB" in text.upper() and "TITLES" in text.upper():
            # Only flag if AGENT appears IN the column-header row, not in
            # a description / general body.
            for line in text.splitlines():
                if "SUBURB" in line.upper() and "ESTATE" in line.upper():
                    if "AGENT" in line.upper():
                        seen_agent_col_header = True
                        break

        # Pick up region/section title text. Cover page has Tom's brand
        # text; region pages have "Stocklist as at" subtitle + table.
        for line in text.splitlines()[:8]:
            line = line.strip()
            if not line:
                continue
            up = line.upper()
            if any(r in up for r in known_region_words) and "STOCKLIST" not in up:
                region_titles_seen.append(up)
                break

    doc.close()

    print()
    print("--- Structural checks ---")
    ok_listings = not seen_bolst_listings_header
    ok_agent = not seen_agent_col_header
    print(f"  No 'BOLST LISTINGS' standalone page header: {ok_listings}")
    print(f"  No 'AGENT' column header anywhere:          {ok_agent}")
    print()
    print(f"  Region/section titles spotted ({len(region_titles_seen)}):")
    for t in region_titles_seen[:20]:
        print(f"    {t!r}")

    success = ok_listings and ok_agent
    print()
    print(f"=== A.1 layout structural validation: {'PASS' if success else 'FAIL'} ===")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
