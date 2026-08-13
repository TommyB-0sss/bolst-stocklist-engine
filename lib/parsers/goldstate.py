"""
Goldstate Homes stocklist parser.

Goldstate's stocklist is a 3-page PDF reached via a body hyperlink in their
campaign email (ingestion: html_link), not an attachment. Page 3 is an
SMSF 1-Part explainer written as prose, not row data.

Structure — one giant pdfplumber table per page, whose rows arrive in
document order and carry three kinds of content:

  * region label      single populated cell: WEST / NORTH / SOUTH-EAST / REGIONAL
  * section header    single populated cell: "<Estate>, <Suburb> <postcode>? (<deposit>)?"
  * column header     first cell == "Title date", repeated above every section
  * data row          all 16 columns populated

Because the headers appear inline in the same table, we can walk rows in
order and carry (region, estate, suburb) state forward — no Y-position
merge is needed (contrast lib/parsers/hermitage.py, which does need one).

Column layout (zero-indexed, 16 columns):
  0  Title date       "Titled" / "Mar-27"
  1  Lot #
  2  Street address
  3  Orien            aspect: "East" / "South West"
  4  Width            metres
  5  Depth            metres
  6  Land m2
  7  Land Price
  8  House name       "Havana 17" / "Harmony 21 - Dual Key (3+1)"
  9  Facade
  10 Beds
  11 Storeys          "Single" / "Double"
  12 House m2
  13 House price
  14 Total price
  15 Status           "Available" (only value seen)

BATH AND CAR ARE ABSENT from the source, as with Hermitage. Those fields stay
None and the renderer shows "4-?-?". Confirmed against the 22/07/2026 sample:
no bath or car column exists to map.

is_one_part:
  Always False. Goldstate's SMSF 1-Part offer is described in page-3 prose
  ("conversion fee is $60,000, Dual Key designs and the Lincoln 20 are
  excluded") rather than flagged per row, so there is nothing to key on. Rows
  route to their suburb's region like any other stock.

Sample provenance: bolst_goldstate.pdf (22/07/2026), 70 data rows across
20 estates and 4 builder regions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .types import StocklistRow

N_COLUMNS = 16

EXPECTED_HEADER = [
    "Title date", "Lot #", "Street address", "Orien", "Width", "Depth",
    "Land m2", "Land Price", "House name", "Facade", "Beds", "Storeys",
    "House m2", "House price", "Total price", "Status",
]

COLUMN_HEADER_FIRST_CELL = "Title date"

REGION_LINE = re.compile(r"^(WEST|NORTH|SOUTH-EAST|REGIONAL)$", re.IGNORECASE)

# Trailing "(5% deposit)" / "(10% deposit)" on the suburb side of a header.
DEPOSIT_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")

# Trailing 4-digit postcode: "Melton South 3338" -> "Melton South". Some
# headers omit it entirely ("Winterfield Estate , Ballarat").
POSTCODE_SUFFIX = re.compile(r"\s+\d{4}\s*$")

# Prose blocks (disclaimer, SMSF explainer) also contain commas, so comma
# alone cannot identify a section header. They are multi-line and start with
# recognisable prose; real headers are a single short line.
MAX_HEADER_LEN = 80


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
    m = re.search(r"\d+", s)
    return int(m.group(0)) if m else None


def _clean_float(value) -> Optional[float]:
    s = _clean_str(value)
    if not s:
        return None
    try:
        return float(re.sub(r"[^\d.\-]", "", s))
    except ValueError:
        return None


def _parse_section_header(text: str) -> Optional[tuple[str, str]]:
    """Return (estate, suburb) from a section header line, or None.

    "Toolern Waters , Melton South 3338"          -> ("Toolern Waters", "Melton South")
    "Grandview Estate, Truganina 3029 (5% ...)"   -> ("Grandview Estate", "Truganina")
    "Five Farms Estate, Clyde North (5% deposit)" -> ("Five Farms Estate", "Clyde North")
    "Coridale Estate , Lara, Geelong (10% ...)"   -> ("Coridale Estate", "Lara")

    That last case is the one to be careful with: the trailing ", Geelong" is
    the wider district, not the suburb. Bolst routes on suburb, and Lara is
    what suburbs.yml knows, so we keep the FIRST field after the estate.
    """
    s = (text or "").strip()
    if not s or "\n" in s or len(s) > MAX_HEADER_LEN:
        return None
    if "," not in s:
        return None
    if REGION_LINE.match(s):
        return None

    estate, _, rest = s.partition(",")
    estate = estate.strip()

    rest = DEPOSIT_SUFFIX.sub("", rest).strip()
    # District suffix ("Lara, Geelong") — take the suburb, drop the district.
    suburb = rest.split(",")[0].strip()
    suburb = POSTCODE_SUFFIX.sub("", suburb).strip()

    if not estate or not suburb:
        return None
    return estate, suburb


def _populated(row: list) -> int:
    return sum(1 for c in row if c not in (None, "") and str(c).strip())


def _is_column_header(row: list) -> bool:
    return _clean_str(row[0]) == COLUMN_HEADER_FIRST_CELL


def _check_header(row: list, source_file: str) -> None:
    """Raise if Goldstate reorders or renames columns, so a layout change is
    loud rather than silently misaligning every field. The header row repeats
    above each estate section, so this is checked on every occurrence."""
    actual = [(_clean_str(c) or "") for c in row[:N_COLUMNS]]
    if actual != EXPECTED_HEADER:
        raise ValueError(
            f"Goldstate column header mismatch in {source_file}. "
            f"Expected {EXPECTED_HEADER}, got {actual}."
        )


def _land_dimensions(width, depth) -> Optional[str]:
    w, d = _clean_str(width), _clean_str(depth)
    if w and d:
        return f"{w} x {d}"
    return w or d


def _row_to_stocklist_row(
    row: list,
    *,
    estate: Optional[str],
    suburb: Optional[str],
    source_file: str,
    source_region: Optional[str],
    source_row_index: int,
) -> StocklistRow:
    meta = {}
    orientation = _clean_str(row[3])
    storey = _clean_str(row[11])
    if orientation:
        meta["orientation"] = orientation
    if storey:
        meta["storey"] = storey

    return StocklistRow(
        builder="goldstate",
        suburb=suburb or "",
        estate=estate,
        lot=_clean_str(row[1]),
        street=_clean_str(row[2]),
        titles=_clean_str(row[0]),
        land_m2=_clean_int(row[6]),
        land_dimensions=_land_dimensions(row[4], row[5]),
        land_price=_clean_money(row[7]),
        home_design=_clean_str(row[8]),
        facade=_clean_str(row[9]),
        house_m2=_clean_float(row[12]),
        bed=_clean_int(row[10]),
        bath=None,   # absent from source
        car=None,    # absent from source
        build_price=_clean_money(row[13]),
        total_price=_clean_money(row[14]),
        status=_clean_str(row[15]),
        is_one_part=False,
        source_file=source_file,
        source_region=source_region,
        source_row_index=source_row_index,
        meta=meta,
    )


def parse(file_path: Path) -> list[StocklistRow]:
    """Parse a Goldstate Homes stocklist PDF into canonical rows."""
    file_path = Path(file_path)
    rows: list[StocklistRow] = []
    row_index = 0

    current_region: Optional[str] = None
    current_estate: Optional[str] = None
    current_suburb: Optional[str] = None

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            for table in page.find_tables() or []:
                for raw in table.extract() or []:
                    if not raw:
                        continue
                    raw = list(raw) + [None] * (N_COLUMNS - len(raw))

                    if _is_column_header(raw):
                        _check_header(raw, file_path.name)
                        continue

                    n = _populated(raw)

                    # Single-cell rows carry region labels, section headers,
                    # the page title, and the prose blocks.
                    if n == 1:
                        text = _clean_str(raw[0]) or ""
                        if REGION_LINE.match(text):
                            current_region = text.upper()
                            continue
                        section = _parse_section_header(text)
                        if section is not None:
                            current_estate, current_suburb = section
                        continue

                    # A data row has every column filled. Requiring most of
                    # them filters stray artefacts without being brittle about
                    # a single blank cell.
                    if n < 10:
                        continue

                    rows.append(
                        _row_to_stocklist_row(
                            raw,
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
        print("Usage: python -m lib.parsers.goldstate <path-to-pdf>", file=sys.stderr)
        sys.exit(1)
    parsed = parse(Path(sys.argv[1]))
    print(f"Parsed {len(parsed)} rows from {sys.argv[1]}")
    for row in parsed[:3]:
        print(row)
    if len(parsed) > 3:
        print("...")
        print(parsed[-1])
