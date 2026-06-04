"""
Specialised Home Constructions stocklist parser.

Single PDF per week from `nlimbo@specialisedhomeconstructions.com.au`. Routes to
regional. One Part rows are NOT in this file — they come via Tom's editorial
reply (one-part-prompt skill).

PARSING STRATEGY: text-based, line-by-line — NOT table-based.
The PDF uses alternating-row striping that breaks pdfplumber's line-based table
detection (it splits each section's table into multiple sub-tables, dropping
shaded rows). pdfplumber.extract_text() returns clean per-line text including
all rows, so we walk lines and match patterns:

  - Section header line:  "<SUBURB> - <ESTATE>" (e.g. "BENALLA - LIVINGSTON",
    "ECHUCA- McMAHONS PLACE", "MOOROOPNA – THE OUTLOOK") — sets context
  - Column header line:   "LOT NO. ADDRESS SUBURB ESTATE TITLES AREA FLOORPLAN
                           PACKAGE PRICE" — skip
  - Data line: "<lot> <address...> <suburb...> <estate...> <titles> <area>m2
                <floorplan> <bed - bath - car> $<price>"

Address/suburb/estate are space-separated and any can be multi-word — the
section header tells us how many words for suburb and estate, which lets us
slice the row's middle deterministically.

Source PDF lacks a STATUS column — Specialised only publishes available stock.
Parser defaults status="Available". Revisit if Specialised ever starts including
reserved/EOI rows.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .types import StocklistRow

SKIP_LINE_PREFIXES = ("STOCKLIST", "Note:", "LOT NO.")
SECTION_HEADER = re.compile(r"^(.+?)\s*[-–—]\s*(.+?)\s*$")

# Section headers like "SWAN HILL - HEIRLOOM ESTATE" include a generic
# "Estate" suffix that the per-row data omits ("Heirloom" only). If we
# keep "Estate" in the section's estate string, _split_lot_address_suburb_estate
# would count one too many estate words and misalign suburb + street by 1
# token — producing the "Ave Swan" / "Coronation" defect (2026-05-25).
SECTION_ESTATE_SUFFIX = re.compile(r"\s+estate\s*$", re.IGNORECASE)

# Match the right-side fields of a data row, working from the end.
# Example: "...Forbes 17 4 - 2 - 2 $643,219"
DATA_ROW_TAIL = re.compile(
    r"^(.+?)\s+"                          # group 1: everything left of titles
    r"([A-Z][a-z]+-\d+|Titled)\s+"        # group 2: titles ("Dec-26", "Sept-26", "Titled")
    r"(\d+)m2?\s+"                        # group 3: area in m²
    r"([A-Z][a-z]+\s+\d+)\s+"             # group 4: floorplan ("Forbes 17")
    r"(\d+)\s*-\s*(\d+(?:\.\d+)?)\s*-\s*(\d+)\s+"  # groups 5-7: bed/bath/car
    r"\$([\d,]+)\s*$"                     # group 8: price
)


def _clean_str(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _is_section_header(line: str) -> bool:
    if not line:
        return False
    if line.startswith(SKIP_LINE_PREFIXES):
        return False
    if line[0].isdigit():
        return False
    if not re.search(r"[-–—]", line):
        return False
    return True


def _parse_section_header(line: str) -> Optional[tuple[str, str]]:
    """Return (suburb, estate) from a section header line, or None if it doesn't match."""
    match = SECTION_HEADER.match(line)
    if not match:
        return None
    suburb_raw = match.group(1).strip()
    estate_raw = match.group(2).strip()
    estate_raw = SECTION_ESTATE_SUFFIX.sub("", estate_raw).strip()
    if not suburb_raw or not estate_raw:
        return None
    return suburb_raw, estate_raw


def _split_lot_address_suburb_estate(
    head: str, suburb_word_count: int, estate_word_count: int
) -> Optional[tuple[str, str, str, str]]:
    """
    From the leading portion of a data line ('<lot> <address...> <suburb...> <estate...>'),
    pull lot from the left, suburb+estate from the right (using section context),
    leave address as the middle.
    """
    tokens = head.split()
    needed = 1 + suburb_word_count + estate_word_count + 1  # at least one address word
    if len(tokens) < needed:
        return None
    lot = tokens[0]
    estate_tokens = tokens[-estate_word_count:]
    suburb_tokens = tokens[-(estate_word_count + suburb_word_count):-estate_word_count]
    address_tokens = tokens[1:-(estate_word_count + suburb_word_count)]
    if not address_tokens:
        return None
    return (
        lot,
        " ".join(address_tokens),
        " ".join(suburb_tokens),
        " ".join(estate_tokens),
    )


def _clean_money(value) -> Optional[int]:
    s = _clean_str(value)
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def parse(file_path: Path) -> list[StocklistRow]:
    """Parse a Specialised stocklist PDF into canonical rows."""
    file_path = Path(file_path)
    rows: list[StocklistRow] = []
    row_index = 0
    current_section: Optional[tuple[str, str]] = None  # (suburb, estate) word counts derived from len(split())

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith(SKIP_LINE_PREFIXES):
                    continue

                if _is_section_header(line):
                    parsed_section = _parse_section_header(line)
                    if parsed_section:
                        current_section = parsed_section
                    continue

                # Try to parse as a data row.
                if not line[0].isdigit() or current_section is None:
                    continue

                tail_match = DATA_ROW_TAIL.match(line)
                if not tail_match:
                    continue

                section_suburb, section_estate = current_section
                head = tail_match.group(1)
                titles = tail_match.group(2)
                area = int(tail_match.group(3))
                floorplan = tail_match.group(4)
                bed = int(tail_match.group(5))
                bath = float(tail_match.group(6))
                car = int(tail_match.group(7))
                price = _clean_money(tail_match.group(8))

                split = _split_lot_address_suburb_estate(
                    head,
                    suburb_word_count=len(section_suburb.split()),
                    estate_word_count=len(section_estate.split()),
                )
                if split is None:
                    continue
                lot, street, suburb, estate = split

                rows.append(
                    StocklistRow(
                        builder="specialised",
                        lot=lot,
                        street=street,
                        suburb=suburb,
                        estate=estate,
                        titles=titles,
                        land_m2=area,
                        home_design=floorplan,
                        bed=bed,
                        bath=bath,
                        car=car,
                        total_price=price,
                        # Specialised omits the STATUS column — all listed packages are available.
                        status="Available",
                        source_file=file_path.name,
                        source_row_index=row_index,
                    )
                )
                row_index += 1

    return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m lib.parsers.specialised <path-to-pdf>", file=sys.stderr)
        sys.exit(1)
    parsed = parse(Path(sys.argv[1]))
    print(f"Parsed {len(parsed)} rows from {sys.argv[1]}")
    for row in parsed[:3]:
        print(row)
    if len(parsed) > 3:
        print("...")
        print(parsed[-1])
