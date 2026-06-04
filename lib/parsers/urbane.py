"""
Urbane stocklist parser.

Urbane's weekly stocklist is a 3-page PDF (sample:
"Urbane Homes H&L Package Stocklist - April 2026 (24-04) - v001.pdf";
page 3 is an empty footer notice). Each row carries its own estate + suburb
in cells (like Aldrich), but region markers are inline within the table as
styled section rows of the form `/// METRO NORTH \\\` (like Hermitage). So
estate/suburb come from cells; source_region is tracked via per-row Y
correlation with the inline header events.

Sender-agnostic: Urbane's stocklist may be forwarded by either Tyana Troise
(canonical, direct attachment) or Mikayla Salva (HubSpot newsletter). The
PDF itself is the same content either way; the parser takes a file path
and has no sender-specific logic. Sender routing lives in builders.yml.

Column layout (zero-indexed, 16 columns — pdfplumber emits an empty
leading column for the left margin, so all data sits at index +1):
  0  (empty margin)
  1  LOT NO
  2  STREET NAME
  3  SUBURB
  4  ESTATE
  5  LAND SIZE (m2)              ("349m2" — unit suffix stripped)
  6  LAND DIMENSIONS             ("12.5 x 28")
  7  ORIENTATION                 ("E", "W", "N", "S")
  8  TITLES                      ("TITLED" or "Sep-27" etc.)
  9  HOUSE TYPE                  ("Brampton192" or "Surrey 180")
  10 BED BATH CAR                ("4-2-2" — dashes, not spaces)
  11 FACADE                      ("Lisbon", "Sagres", "Sevile" (sic), etc.)
  12 BUILD PRICE
  13 LAND PRICE
  14 HOUSE & LAND TOTAL
  15 NOTES                       ("$25K Land Rebate Applicable", etc.)

Urbane has no Status column — every listed row is implicitly Available
(rows that are sold/reserved just don't appear). Parser sets status to
"Available" for all rows.

No house_m2 column either; the m2 number embedded in House Type strings
("Brampton192") is dwelling-design metadata, not a per-lot value, so we
leave house_m2 = None and preserve home_design as the raw string.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .types import StocklistRow

REGION_LINE = re.compile(r"^/{3}\s*([A-Z][A-Z\s]*?)\s*\\{3}")
BED_BATH_CAR = re.compile(r"^\s*(\d+)\s*-\s*(\d+(?:\.\d+)?)\s*-\s*(\d+)\s*$")
COLUMN_HEADER_PREFIX = "LOT NO"


def _clean_str(value) -> Optional[str]:
    if value is None:
        return None
    s = " ".join(str(value).split())
    return s if s else None


def _clean_money(value) -> Optional[int]:
    s = _clean_str(value)
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def _clean_int(value) -> Optional[int]:
    s = _clean_str(value)
    if not s:
        return None
    match = re.search(r"\d+", s)
    return int(match.group(0)) if match else None


def _parse_bed_bath_car(value) -> tuple[Optional[int], Optional[float], Optional[int]]:
    s = _clean_str(value)
    if not s:
        return None, None, None
    match = BED_BATH_CAR.match(s)
    if not match:
        return None, None, None
    return int(match.group(1)), float(match.group(2)), int(match.group(3))


def _parse_region_line(line: str) -> Optional[str]:
    """Return the region label from `/// METRO NORTH \\\\\\` style markers."""
    s = line.strip()
    match = REGION_LINE.match(s)
    return match.group(1).strip() if match else None


def _row_is_data(row: list) -> bool:
    if not row or len(row) < 15:
        return False
    lot = _clean_str(row[1])
    if not lot or not lot[0].isdigit() or lot.startswith(COLUMN_HEADER_PREFIX):
        return False
    if not _clean_str(row[3]):  # suburb required
        return False
    return True


def _row_to_stocklist_row(
    row: list,
    *,
    source_file: str,
    source_region: Optional[str],
    source_row_index: int,
) -> StocklistRow:
    bed, bath, car = _parse_bed_bath_car(row[10] if len(row) > 10 else None)

    meta: dict = {}
    if (orientation := _clean_str(row[7])):
        meta["orientation"] = orientation
    if len(row) > 15:
        if (notes := _clean_str(row[15])):
            meta["notes"] = notes

    return StocklistRow(
        builder="urbane",
        suburb=_clean_str(row[3]) or "",
        estate=_clean_str(row[4]),
        lot=_clean_str(row[1]),
        street=_clean_str(row[2]),
        titles=_clean_str(row[8]),
        land_m2=_clean_int(row[5]),
        land_dimensions=_clean_str(row[6]),
        land_price=_clean_money(row[13]),
        home_design=_clean_str(row[9]),
        facade=_clean_str(row[11]),
        house_m2=None,
        bed=bed,
        bath=bath,
        car=car,
        build_price=_clean_money(row[12]),
        total_price=_clean_money(row[14]),
        release_type=None,
        status="Available",
        is_one_part=False,
        source_file=source_file,
        source_region=source_region,
        source_row_index=source_row_index,
        meta=meta,
    )


def _scan_page_headers(page) -> list[tuple[float, str, object]]:
    """Find inline region marker lines and return them with Y position."""
    events: list[tuple[float, str, object]] = []
    for line in page.extract_text_lines() or []:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        region = _parse_region_line(text)
        if region:
            y = float(line.get("top", 0))
            events.append((y, "region", region))
    return events


def parse(file_path: Path) -> list[StocklistRow]:
    """Parse an Urbane stocklist PDF into canonical rows."""
    file_path = Path(file_path)
    rows: list[StocklistRow] = []
    row_index = 0

    current_region: Optional[str] = None

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            header_events = _scan_page_headers(page)
            tables = page.find_tables() or []

            timeline: list[tuple[float, str, object]] = list(header_events)
            for table in tables:
                extracted = table.extract() or []
                for i, raw_row in enumerate(extracted):
                    if not _row_is_data(raw_row):
                        continue
                    row_y = float(table.rows[i].bbox[1])
                    timeline.append((row_y, "data_row", raw_row))
            timeline.sort(key=lambda e: e[0])

            for _y, kind, payload in timeline:
                if kind == "region":
                    current_region = payload  # type: ignore[assignment]
                elif kind == "data_row":
                    rows.append(
                        _row_to_stocklist_row(
                            payload,  # type: ignore[arg-type]
                            source_file=file_path.name,
                            source_region=current_region,
                            source_row_index=row_index,
                        )
                    )
                    row_index += 1

    return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m lib.parsers.urbane <path-to-pdf>", file=sys.stderr)
        sys.exit(1)
    parsed = parse(Path(sys.argv[1]))
    print(f"Parsed {len(parsed)} rows from {sys.argv[1]}")
    for row in parsed[:3]:
        print(row)
    if len(parsed) > 3:
        print("...")
        print(parsed[-1])
