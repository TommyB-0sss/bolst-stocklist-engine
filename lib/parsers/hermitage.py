"""
Hermitage stocklist parser.

Hermitage's weekly stocklist is a 5-page PDF. Each page contains multiple
estate sub-sections, each rendered as its own styled table with green column
headers. Region context (NORTHERN REGION / SOUTH-EASTERN REGION /
WESTERN REGION / REGIONAL) lives in mid-page text between tables, and
estate+suburb context lives in section headers immediately above each
sub-table. "PACKAGES OF THE WEEK" is a special leading section that has no
region label of its own.

Column layout (zero-indexed, 13 columns):
  0  Lot No
  1  Street
  2  Land m2
  3  Titles                ("Titled" / "Mar-27" / etc.)
  4  Land Price            ("$300,000")
  5  Home Design           ("Drake 19" / "Nexus 25 (Dual Key)" / etc.)
  6  Facade                ("Duke" / "Summit" / etc.)
  7  Bed                   single digit
  8  Storey                ("Single" — only value seen)
  9  House m2
  10 Build Price
  11 Total Price
  12 Status                ("Available" — only value seen)

Strategy:
  - extract_tables() per page for cell data (no row-striping in Hermitage,
    so table extraction is reliable here).
  - extract_text_lines() in parallel to find region + section headers with
    their Y positions.
  - Merge tables and header events by Y position to walk the page in document
    order, maintaining (region, estate, suburb) state. Each data row is
    emitted under whatever state was current when its table started.

is_one_part flag:
  Set when Street column == "ONE PART CONTRACT" (per builders.yml). The 240726
  sample contained zero such rows; logic is defensive.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .types import StocklistRow

REGION_LINE = re.compile(
    r"^(NORTHERN REGION|SOUTH-EASTERN REGION|WESTERN REGION|REGIONAL)$"
)
PACKAGES_LINE = re.compile(r"^\*{0,2}PACKAGES OF THE WEEK\*{0,2}$")
COLUMN_HEADER_PREFIX = "Lot No"

# Trailing junk on the suburb side of a section header: postcodes, energy
# ratings ("7 Star Energy Rating" with or without leading hyphen), deposit
# blurbs ("5% Deposit"), or any " - <anything>" suffix.
SUBURB_TAIL = re.compile(
    r"(?:\s*-\s*.*|\s+\d+\s*[Ss]tar\b.*|\s+\d+%.*|\s+\d{4})\s*$"
)


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


def _parse_section_header(line: str) -> Optional[tuple[str, str]]:
    """Return (estate, suburb) from a section header, or None if not a header."""
    s = line.strip()
    if not s or s[0].isdigit():
        return None
    if s.startswith(COLUMN_HEADER_PREFIX) or "$" in s:
        return None
    if REGION_LINE.match(s) or PACKAGES_LINE.match(s):
        return None
    if "," not in s:
        return None
    estate, _, rest = s.partition(",")
    estate = estate.strip()
    suburb = rest.strip()
    # Iteratively strip trailing junk (postcode, rating, deposit, dash-suffix).
    while True:
        cleaned = SUBURB_TAIL.sub("", suburb).strip()
        if cleaned == suburb:
            break
        suburb = cleaned
    if not estate or not suburb:
        return None
    return estate, suburb


def _row_is_data(row: list) -> bool:
    if not row or len(row) < 13:
        return False
    first = _clean_str(row[0])
    if not first or not first[0].isdigit():
        return False
    if first.startswith(COLUMN_HEADER_PREFIX):
        return False
    # Require Street and Land m2 — filters out single-cell artefacts like the
    # page-header date that pdfplumber sweeps into the giant per-page table.
    if not _clean_str(row[1]) or _clean_int(row[2]) is None:
        return False
    return True


def _row_to_stocklist_row(
    row: list,
    *,
    estate: Optional[str],
    suburb: Optional[str],
    source_file: str,
    source_region: Optional[str],
    source_row_index: int,
) -> StocklistRow:
    street = _clean_str(row[1])
    is_one_part = (street or "").upper() == "ONE PART CONTRACT"
    # The "ONE PART CONTRACT" string is a marker, not a real street name —
    # blank the field so renderer leaves the address column empty. The
    # is_one_part flag captures the meaning.
    if is_one_part:
        street = None
    storey = _clean_str(row[8])
    return StocklistRow(
        builder="hermitage",
        suburb=suburb or "",
        estate=estate,
        lot=_clean_str(row[0]),
        street=street,
        titles=_clean_str(row[3]),
        land_m2=_clean_int(row[2]),
        land_price=_clean_money(row[4]),
        home_design=_clean_str(row[5]),
        facade=_clean_str(row[6]),
        house_m2=_clean_float(row[9]),
        bed=_clean_int(row[7]),
        build_price=_clean_money(row[10]),
        total_price=_clean_money(row[11]),
        status=_clean_str(row[12]),
        is_one_part=is_one_part,
        source_file=source_file,
        source_region=source_region,
        source_row_index=source_row_index,
        meta={"storey": storey} if storey else {},
    )


def _scan_page_headers(page) -> list[tuple[float, str, object]]:
    """
    Walk a page's text lines, returning header events with Y position:
      (y, "region",   region_label)
      (y, "section",  (estate, suburb))
      (y, "packages", None)

    Y is the line's top edge; used to interleave with table positions.
    """
    events: list[tuple[float, str, object]] = []
    for line in page.extract_text_lines() or []:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        y = float(line.get("top", 0))
        if PACKAGES_LINE.match(text):
            events.append((y, "packages", None))
            continue
        if REGION_LINE.match(text):
            events.append((y, "region", text))
            continue
        section = _parse_section_header(text)
        if section is not None:
            events.append((y, "section", section))
    return events


def parse(file_path: Path) -> list[StocklistRow]:
    """Parse a Hermitage stocklist PDF into canonical rows."""
    file_path = Path(file_path)
    rows: list[StocklistRow] = []
    row_index = 0

    current_region: Optional[str] = None
    current_estate: Optional[str] = None
    current_suburb: Optional[str] = None

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            header_events = _scan_page_headers(page)
            tables = page.find_tables() or []

            # Build a per-row timeline. Hermitage gives ~1 giant table per page
            # but each row carries its own bbox, so we attribute rows to the
            # most recently-seen section header at the row's Y position.
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
                if kind == "packages":
                    current_region = "PACKAGES OF THE WEEK"
                elif kind == "region":
                    current_region = payload  # type: ignore[assignment]
                elif kind == "section":
                    current_estate, current_suburb = payload  # type: ignore[misc]
                elif kind == "data_row":
                    rows.append(
                        _row_to_stocklist_row(
                            payload,  # type: ignore[arg-type]
                            estate=current_estate,
                            suburb=current_suburb,
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
        print("Usage: python -m lib.parsers.hermitage <path-to-pdf>", file=sys.stderr)
        sys.exit(1)
    parsed = parse(Path(sys.argv[1]))
    print(f"Parsed {len(parsed)} rows from {sys.argv[1]}")
    for row in parsed[:3]:
        print(row)
    if len(parsed) > 3:
        print("...")
        print(parsed[-1])
