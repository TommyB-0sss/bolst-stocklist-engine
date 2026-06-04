"""
Aldrich stocklist parser.

Aldrich's weekly stocklist is a 6-page PDF (sample: Stocklist C44.pdf) with
one region per page (West may overflow onto a second page). Each row
already carries its full context (estate, suburb, status) as cells, so —
unlike Hermitage — no Y-correlation between data rows and surrounding text
is needed. The page region header ("Exclusive Packages", "West", "North",
"South-East", "Geelong") is the only piece of context that must be lifted
from page text, and even that's a single line at the top of each page.

Column layout (zero-indexed, 19 columns):
   0  Lot No.
   1  Estate Name
   2  Suburb
   3  Status                  ("Available" / "Exclusive" / "On Hold" /
                                "Not Available" / "Sold" / "Resale")
   4  Home Design             ("Bristol 15", "Swindon 20A", etc.)
   5  Land Price              ("$352,800")
   6  Build Price
   7  Package Price           (= Land + Build, exact arithmetic)
   8  Land Rebate OR Land Discount   ("$8,000" or empty)
   9  Title Status            ("Titled" / "MAR 2027" / etc.)
   10 Orientation             ("North", "South East", etc.)
   11 Land Size (m2)
   12 LAND Width              (e.g. "12.50")
   13 LAND Length             (e.g. "25.00")
   14 House Size (m2)
   15 Storeys                 ("Single" — only value seen)
   16 Beds
   17 Baths
   18 Garage                  ("Single" / "Double" — string, not int)

Aldrich has no Street column and no Facade column, unlike Hermitage.

Mapping to StocklistRow:
  - land_dimensions  = f"{LAND Width} x {LAND Length}"  (matches Aplace format)
  - car              = mapped from Garage string: Single=1, Double=2, Triple=3.
                       Raw string still preserved in meta["garage"] for traceability.
                       Unknown values (rare) fall back to None.
  - meta carries:    storey / orientation / garage / land_rebate
  - facade, street   are None (no source columns for these)

Sub-section labels "Titled Packages" / "Untitled Packages" appear inside
each region's table; they're filtered by _row_is_data because their first
cell isn't digit-led.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .types import StocklistRow

REGION_HEADERS = frozenset({
    "Exclusive Packages",
    "West",
    "North",
    "South-East",
    "Geelong",
})

COLUMN_HEADER_PREFIX = "Lot No"


def _clean_str(value) -> Optional[str]:
    """Strip and collapse internal whitespace (including newlines from wrapped
    cell text like 'Cloverton Midtown\\nEstate'). Returns None for empty."""
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


def _clean_float(value) -> Optional[float]:
    s = _clean_str(value)
    if not s:
        return None
    try:
        return float(re.sub(r"[^\d.\-]", "", s))
    except ValueError:
        return None


_GARAGE_TO_CAR = {
    "single": 1,
    "double": 2,
    "triple": 3,
    "quad": 4,
    "quadruple": 4,
}


def _garage_to_car(garage: Optional[str]) -> Optional[int]:
    if not garage:
        return None
    return _GARAGE_TO_CAR.get(garage.strip().lower())


def _detect_page_region(page) -> Optional[str]:
    """Return the region label printed at the top of this page, or None."""
    for line in page.extract_text_lines() or []:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        if text in REGION_HEADERS:
            return text
        if text.startswith(COLUMN_HEADER_PREFIX):
            return None
    return None


def _row_is_data(row: list) -> bool:
    if not row or len(row) < 19:
        return False
    lot = _clean_str(row[0])
    if not lot or not lot[0].isdigit() or lot.startswith(COLUMN_HEADER_PREFIX):
        return False
    # Suburb required — filters phantom continuation rows from wrapped estate
    # names where pdfplumber sometimes emits a follow-on row with only the
    # tail of the estate string filled in.
    if not _clean_str(row[2]):
        return False
    return True


def _row_to_stocklist_row(
    row: list,
    *,
    source_file: str,
    source_region: Optional[str],
    source_row_index: int,
) -> StocklistRow:
    width = _clean_str(row[12])
    length = _clean_str(row[13])
    if width and length:
        land_dimensions = f"{width} x {length}"
    else:
        land_dimensions = width or length

    meta: dict = {}
    if (storey := _clean_str(row[15])):
        meta["storey"] = storey
    if (orientation := _clean_str(row[10])):
        meta["orientation"] = orientation
    if (garage := _clean_str(row[18])):
        meta["garage"] = garage
    if (rebate := _clean_money(row[8])):
        meta["land_rebate"] = rebate

    return StocklistRow(
        builder="aldrich",
        suburb=_clean_str(row[2]) or "",
        estate=_clean_str(row[1]),
        lot=_clean_str(row[0]),
        street=None,
        titles=_clean_str(row[9]),
        land_m2=_clean_int(row[11]),
        land_dimensions=land_dimensions,
        land_price=_clean_money(row[5]),
        home_design=_clean_str(row[4]),
        facade=None,
        house_m2=_clean_float(row[14]),
        bed=_clean_int(row[16]),
        bath=_clean_float(row[17]),
        car=_garage_to_car(_clean_str(row[18])),
        build_price=_clean_money(row[6]),
        total_price=_clean_money(row[7]),
        release_type=None,
        status=_clean_str(row[3]),
        is_one_part=False,
        source_file=source_file,
        source_region=source_region,
        source_row_index=source_row_index,
        meta=meta,
    )


def parse(file_path: Path) -> list[StocklistRow]:
    """Parse an Aldrich stocklist PDF into canonical rows."""
    file_path = Path(file_path)
    rows: list[StocklistRow] = []
    row_index = 0

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            region = _detect_page_region(page)
            for table in page.find_tables() or []:
                for raw_row in table.extract() or []:
                    if not _row_is_data(raw_row):
                        continue
                    rows.append(
                        _row_to_stocklist_row(
                            raw_row,
                            source_file=file_path.name,
                            source_region=region,
                            source_row_index=row_index,
                        )
                    )
                    row_index += 1

    return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m lib.parsers.aldrich <path-to-pdf>", file=sys.stderr)
        sys.exit(1)
    parsed = parse(Path(sys.argv[1]))
    print(f"Parsed {len(parsed)} rows from {sys.argv[1]}")
    for row in parsed[:3]:
        print(row)
    if len(parsed) > 3:
        print("...")
        print(parsed[-1])
