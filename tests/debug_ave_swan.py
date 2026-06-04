"""One-shot: dump every Specialised row whose suburb contains 'Ave Swan'
and print the raw text of the surrounding PDF section so we can diagnose
the parser slicing."""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

import pdfplumber  # noqa: E402

from lib.parsers.specialised import parse as parse_specialised  # noqa: E402

PDF = BUNDLE_ROOT / ".cache" / "builder-downloads" / "specialised" / "20260519-Stocklist 19.05.25.pdf"


def main() -> int:
    rows = parse_specialised(PDF)
    print(f"Parsed {len(rows)} rows from {PDF.name}\n")
    suspects = [r for r in rows if r.suburb and "Ave Swan" in r.suburb]
    print(f"Suspects with suburb containing 'Ave Swan': {len(suspects)}\n")
    for r in suspects:
        print("-" * 60)
        print(f"  builder         = {r.builder!r}")
        print(f"  lot             = {r.lot!r}")
        print(f"  street          = {r.street!r}")
        print(f"  suburb          = {r.suburb!r}")
        print(f"  estate          = {r.estate!r}")
        print(f"  titles          = {r.titles!r}")
        print(f"  bed/bath/car    = {r.bed} / {r.bath} / {r.car}")
        print(f"  total_price     = {r.total_price!r}")
        print(f"  source_region   = {r.source_region!r}")
        print(f"  source_file     = {r.source_file!r}")
        print(f"  source_row_idx  = {r.source_row_index!r}")
        print(f"  meta            = {r.meta!r}")
    print()
    print("=" * 70)
    print("Raw text of the source PDF (all pages) — scan for 'Ave' / 'Swan':")
    print("=" * 70)
    with pdfplumber.open(PDF) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if any(needle in text for needle in ("Ave", "Swan")):
                print(f"\n--- Page {i} ---")
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if "Ave" in line or "Swan" in line:
                        # Print line + a few surrounding lines for context
                        all_lines = text.splitlines()
                        idx = line_no - 1
                        lo = max(0, idx - 2)
                        hi = min(len(all_lines), idx + 3)
                        context_lines = all_lines[lo:hi]
                        for j, cl in enumerate(context_lines, start=lo + 1):
                            marker = ">>" if j == line_no else "  "
                            print(f"  {marker} L{j:3d}: {cl}")
                        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
