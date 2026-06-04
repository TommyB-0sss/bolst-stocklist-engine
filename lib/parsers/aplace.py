"""
Aplace stocklist parser.

Handles both Aplace files (same 16-column structure):
  - HOUSE AND LAND STOCKLIST    (8 pages, one region per page) → routes to regional
  - APLACE EXCLUSIVE OPPORTUNITIES (Put-Call)                  → routes to one_part

Routing decision is made by builders.yml based on filename, NOT by this parser.
The parser produces canonical StocklistRow objects either way; downstream tags them.

Column layout (zero-indexed, consistent across both files):
  0  SUBURB
  1  LOT NO
  2  ADDRESS              (street name only)
  3  ESTATE
  4  TITLES               ("Titled" / "Mar-27" / etc.)
  5  LAND SIZE (m2)
  6  LAND DIMENSIONS      ("10.5 x 28")
  7  LAND PRICE           ("$397,000")
  8  HOUSE TYPE           (home design name)
  9  FAÇADE TYPE          ("01" / "Custom A" / etc.)
  10 HOUSE SIZE (m2)
  11 BED BATH CAR         ("4 2 2" or "4 2.5 2")
  12 HOUSE PRICE
  13 TOTAL PACKAGE PRICE
  14 RELEASE TYPE         (Put-Call mislabels this column header as "STATUS")
  15 STATUS               ("Available" / "Reserved" / "EOI")

Page region (e.g. "Victoria - South East") comes from the page header text and
is captured as source_region for audit. Downstream region routing uses suburb,
not this label.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .types import StocklistRow

REGION_LINE = re.compile(r"^Victoria(?:\s*-\s*[\w &,]+)?$")
BED_BATH_CAR = re.compile(r"^\s*(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+)\s*$")


def _clean_str(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
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
    try:
        return int(re.sub(r"[^\d-]", "", s))
    except ValueError:
        return None


def _clean_float(value) -> Optional[float]:
    s = _clean_str(value)
    if not s:
        return None
    try:
        return float(re.sub(r"[^\d.\-]", "", s))
    except ValueError:
        return None


def _parse_bed_bath_car(value) -> tuple[Optional[int], Optional[float], Optional[int]]:
    s = _clean_str(value)
    if not s:
        return None, None, None
    match = BED_BATH_CAR.match(s)
    if not match:
        return None, None, None
    return int(match.group(1)), float(match.group(2)), int(match.group(3))


def _extract_page_region(page_text: str) -> Optional[str]:
    """Find the 'Victoria - <something>' line in a page's text."""
    for line in page_text.splitlines():
        line = line.strip()
        if REGION_LINE.match(line):
            return line
    return None


def _row_is_data(row: list) -> bool:
    """A data row has a non-empty SUBURB cell and a numeric LOT NO cell."""
    if not row or len(row) < 2:
        return False
    suburb = _clean_str(row[0])
    lot = _clean_str(row[1])
    if not suburb or not lot:
        return False
    # SUBURB should not be the literal header word
    if suburb.upper() == "SUBURB":
        return False
    return True


def _row_to_stocklist_row(
    row: list,
    *,
    builder: str,
    source_file: str,
    source_region: Optional[str],
    source_row_index: int,
) -> StocklistRow:
    bed, bath, car = _parse_bed_bath_car(row[11] if len(row) > 11 else None)
    return StocklistRow(
        builder=builder,
        suburb=_clean_str(row[0]) or "",
        lot=_clean_str(row[1]),
        street=_clean_str(row[2]) if len(row) > 2 else None,
        estate=_clean_str(row[3]) if len(row) > 3 else None,
        titles=_clean_str(row[4]) if len(row) > 4 else None,
        land_m2=_clean_int(row[5]) if len(row) > 5 else None,
        land_dimensions=_clean_str(row[6]) if len(row) > 6 else None,
        land_price=_clean_money(row[7]) if len(row) > 7 else None,
        home_design=_clean_str(row[8]) if len(row) > 8 else None,
        facade=_clean_str(row[9]) if len(row) > 9 else None,
        house_m2=_clean_float(row[10]) if len(row) > 10 else None,
        bed=bed,
        bath=bath,
        car=car,
        build_price=_clean_money(row[12]) if len(row) > 12 else None,
        total_price=_clean_money(row[13]) if len(row) > 13 else None,
        release_type=_clean_str(row[14]) if len(row) > 14 else None,
        status=_clean_str(row[15]) if len(row) > 15 else None,
        source_file=source_file,
        source_region=source_region,
        source_row_index=source_row_index,
    )


def parse(file_path: Path) -> list[StocklistRow]:
    """Parse an Aplace stocklist PDF into canonical rows."""
    file_path = Path(file_path)
    rows: list[StocklistRow] = []
    row_index = 0

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            source_region = _extract_page_region(page_text)

            for table in page.extract_tables() or []:
                for raw_row in table:
                    if not _row_is_data(raw_row):
                        continue
                    rows.append(
                        _row_to_stocklist_row(
                            raw_row,
                            builder="aplace",
                            source_file=file_path.name,
                            source_region=source_region,
                            source_row_index=row_index,
                        )
                    )
                    row_index += 1

    return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m lib.parsers.aplace <path-to-pdf>", file=sys.stderr)
        sys.exit(1)
    parsed = parse(Path(sys.argv[1]))
    print(f"Parsed {len(parsed)} rows from {sys.argv[1]}")
    for row in parsed[:3]:
        print(row)
    if len(parsed) > 3:
        print("...")
        print(parsed[-1])
