"""List all section headers in the Specialised PDF + check how many end in 'ESTATE'."""

from __future__ import annotations

import re
import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

import pdfplumber  # noqa: E402

from lib.parsers.specialised import (  # noqa: E402
    SECTION_HEADER, _is_section_header, _parse_section_header,
)

PDF = BUNDLE_ROOT / ".cache" / "builder-downloads" / "specialised" / "20260519-Stocklist 19.05.25.pdf"


def main() -> int:
    headers: list[tuple[str, str]] = []
    with pdfplumber.open(PDF) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.splitlines():
                line = raw.strip()
                if _is_section_header(line):
                    parsed = _parse_section_header(line)
                    if parsed:
                        headers.append(parsed)

    print(f"Found {len(headers)} section headers in {PDF.name}\n")
    suffix_re = re.compile(r"\s+estate\s*$", re.IGNORECASE)
    for s, e in headers:
        flag = "  <-- ESTATE SUFFIX" if suffix_re.search(e) else ""
        stripped = suffix_re.sub("", e)
        suburb_wc = len(s.split())
        estate_wc_raw = len(e.split())
        estate_wc_stripped = len(stripped.split())
        print(f"  {s!r:40s} - {e!r:40s}"
              f"  swc={suburb_wc} ewc_raw={estate_wc_raw} ewc_strip={estate_wc_stripped}"
              f"{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
