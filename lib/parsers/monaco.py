"""
Monaco Built stocklist parser.

Monaco's weekly stocklist is a 36-page PDF reached via a "WEEKLY STOCKLIST
LINK" button in their campaign email (ingestion: html_link), not an
attachment.

THE DUPLICATION (the thing to know about this builder)
------------------------------------------------------
The PDF contains its entire stocklist THREE TIMES: 549 data rows that reduce
to 183 unique ones, every single row appearing exactly 3 times. Verified on
the 15/07/2026 sample — the multiplicity histogram is a clean {3: 183}, and
all 5 region blocks divide by 3 exactly (60/288/153/27/21 rows ->
20/96/51/9/7 unique).

The repetition happens WITHIN each region block, which is why each region
heading still appears only once. Critically, all 3 copies of a row always
carry the same region (checked: 0 rows disagree), so exact-tuple dedupe is
safe and cannot silently reassign a package to the wrong region.

WITHOUT DEDUPE, MONACO INFLATES THE REPORT AND THE COVER TOTAL BY 3x.

Column layout (zero-indexed, 12 columns):
  0  ESTATE        may wrap and absorb the suburb: "Ridgelea\\nEstate\\nPakenham\\nEast"
  1  SUBURB        may wrap: "Armstrong\\nCreek"
  2  ADDRESS       "<lot> <street>", e.g. "1005 Borthwick Parade"
  3  DESIGN        "Sofia 179" — the trailing number is the house m2
  4  HOUSE SIZE    IN SQUARES, e.g. "19.32sq" (every other builder gives m2)
  5  CONFIG        "4, 2, 2" = bed, bath, car
  6  LAND SIZE     "339m2", where the squared char arrives as U+FFFD
  7  YIELD         blank on 181 of 183 rows
  8  TITLES        "Titled" or "Estimated\\n31-03-2027"
  9  LAND PRICE
  10 BUILD PRICE
  11 TOTAL PRICE

Quirks handled
--------------
* Three TOTAL PRICE cells wrap mid-number AND carry cents:
  "$1,004,03\\n0", "$1,004,20\\n4.7", "$770,157.\\n4". A naive digit-strip
  would read the second as $10,042,047. _clean_money joins the wrap first,
  then truncates at the decimal point.
* HOUSE SIZE is converted squares -> m2 (x 9.2903) so it is comparable with
  the other builders. The DESIGN name corroborates it: "Sofia 179" against
  19.32sq -> 179.5 m2. Raw value kept in meta["house_size_sq"].
* ESTATE has the suburb appended when it wraps. The SUBURB column is
  authoritative, so the trailing suburb is stripped off the estate.
* Suburb casing is inconsistent at source ("Clyde north" vs "Clyde North").
  Left alone: routing uppercases for lookup and the renderer title-cases for
  display, so both already resolve correctly.

Status:
  Monaco publishes no STATUS column — the whole document is available stock.
  Rows are stamped "Available" so the rendered STATUS cell matches the other
  builders rather than sitting blank.

is_one_part:
  Always False. Monaco's one-part offering lives behind a login-gated stock
  portal, not as a per-row flag in this PDF.

Sample provenance: bolst_MonacoBuilt.pdf (15/07/2026), 183 unique rows.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .types import StocklistRow

N_COLUMNS = 12

EXPECTED_HEADER = [
    "ESTATE", "SUBURB", "ADDRESS", "DESIGN", "HOUSE SIZE",
    "CONFIG\n(BED, BATH, CAR)", "LAND\nSIZE", "YIELD", "TITLES",
    "LAND\nPRICE", "BUILD\nPRICE", "TOTAL\nPRICE",
]

COLUMN_HEADER_FIRST_CELL = "ESTATE"

REGION_LINE = re.compile(
    r"^(SOUTH EAST|WEST|NORTH|OTHER REGION|REGIONAL SOUTH EAST GIPPSLAND)$"
)

# "1005 Borthwick Parade" -> lot 1005, street "Borthwick Parade". These are
# lot numbers rather than street numbers: Goldstate lists the same Five Farms
# stock as "Lot 762 Truss Cres" where Monaco says "760 Truss Crescent".
ADDRESS_RE = re.compile(r"^\s*(\d+\w?)\s+(.*)$")

CONFIG_RE = re.compile(r"^\s*(\d+)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+)\s*$")

SQUARES_TO_M2 = 9.2903


def _flatten(value) -> Optional[str]:
    """Join a wrapped cell onto one line and collapse whitespace."""
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()
    return s or None


def _clean_money(value) -> Optional[int]:
    """Dollars as int. Handles cells that wrap mid-number and carry cents.

    "$1,004,03\\n0"  -> 1004030
    "$1,004,20\\n4.7"-> 1004204   (NOT 10042047)
    "$770,157.\\n4"  -> 770157
    """
    s = _flatten(value)
    if not s:
        return None
    s = s.replace(" ", "")
    s = s.split(".")[0]              # drop cents before stripping separators
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def _clean_int(value) -> Optional[int]:
    s = _flatten(value)
    if not s:
        return None
    m = re.search(r"\d+", s)
    return int(m.group(0)) if m else None


def _house_m2_from_squares(value) -> tuple[Optional[float], Optional[str]]:
    """"19.32sq" -> (179.5, "19.32sq"). Returns (m2, raw)."""
    raw = _flatten(value)
    if not raw:
        return None, None
    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    if not m:
        return None, raw
    return round(float(m.group(1)) * SQUARES_TO_M2, 1), raw


def _split_config(value) -> tuple[Optional[int], Optional[float], Optional[int]]:
    """"4, 2, 2" -> (4, 2.0, 2)."""
    s = _flatten(value)
    if not s:
        return None, None, None
    m = CONFIG_RE.match(s)
    if not m:
        return None, None, None
    return int(m.group(1)), float(m.group(2)), int(m.group(3))


def _split_address(value) -> tuple[Optional[str], Optional[str]]:
    """"1005 Borthwick Parade" -> ("1005", "Borthwick Parade")."""
    s = _flatten(value)
    if not s:
        return None, None
    m = ADDRESS_RE.match(s)
    if not m:
        return None, s
    return m.group(1), m.group(2).strip() or None


def _clean_estate(value, suburb: Optional[str]) -> Optional[str]:
    """Strip the suburb that wrapped cells append to the estate name.

    ("Ridgelea Estate Pakenham East", "Pakenham East") -> "Ridgelea Estate"
    ("Perch Estate Clyde North",      "Clyde North")   -> "Perch Estate"
    """
    estate = _flatten(value)
    if not estate:
        return None
    if suburb:
        trailing = re.compile(re.escape(suburb) + r"\s*$", re.IGNORECASE)
        estate = trailing.sub("", estate).strip(" ,-")
    return estate or None


def _check_header(row: list, source_file: str) -> None:
    """Raise if Monaco reorders or renames columns, rather than silently
    misaligning every field."""
    actual = [(c if c is not None else "") for c in row[:N_COLUMNS]]
    if actual != EXPECTED_HEADER:
        raise ValueError(
            f"Monaco column header mismatch in {source_file}. "
            f"Expected {EXPECTED_HEADER}, got {actual}."
        )


def _row_to_stocklist_row(
    cells: tuple[str, ...],
    *,
    source_file: str,
    source_region: Optional[str],
    source_row_index: int,
) -> StocklistRow:
    suburb = _flatten(cells[1]) or ""
    lot, street = _split_address(cells[2])
    bed, bath, car = _split_config(cells[5])
    house_m2, house_sq = _house_m2_from_squares(cells[4])

    meta = {}
    if house_sq:
        meta["house_size_sq"] = house_sq
    yield_pct = _flatten(cells[7])
    if yield_pct:
        meta["yield"] = yield_pct

    return StocklistRow(
        builder="monaco",
        suburb=suburb,
        estate=_clean_estate(cells[0], suburb),
        lot=lot,
        street=street,
        titles=_flatten(cells[8]),
        land_m2=_clean_int(cells[6]),
        land_price=_clean_money(cells[9]),
        home_design=_flatten(cells[3]),
        house_m2=house_m2,
        bed=bed,
        bath=bath,
        car=car,
        build_price=_clean_money(cells[10]),
        total_price=_clean_money(cells[11]),
        status="Available",   # no STATUS column; see module docstring
        is_one_part=False,
        source_file=source_file,
        source_region=source_region,
        source_row_index=source_row_index,
        meta=meta,
    )


def parse(file_path: Path) -> list[StocklistRow]:
    """Parse a Monaco Built stocklist PDF into canonical rows, deduplicated.

    Returns 183 rows from the 549 present in the 15/07/2026 sample. Dedupe is
    on the full raw cell tuple and keeps first occurrence, so document order
    and region attribution are preserved.
    """
    file_path = Path(file_path)
    rows: list[StocklistRow] = []
    seen: set[tuple[str, ...]] = set()
    current_region: Optional[str] = None
    row_index = 0

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            for table in page.find_tables() or []:
                for raw in table.extract() or []:
                    if not raw:
                        continue
                    raw = list(raw) + [None] * (N_COLUMNS - len(raw))
                    populated = [c for c in raw if c not in (None, "")]
                    first = (raw[0] or "").strip()

                    # Region headings and stray prose arrive as single-cell rows.
                    if len(populated) <= 1:
                        if REGION_LINE.match(first):
                            current_region = first
                        continue

                    if first == COLUMN_HEADER_FIRST_CELL:
                        _check_header(raw, file_path.name)
                        continue

                    cells = tuple((c or "").strip() for c in raw[:N_COLUMNS])
                    if cells in seen:
                        continue          # 2nd and 3rd copies
                    seen.add(cells)

                    rows.append(
                        _row_to_stocklist_row(
                            cells,
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
        print("Usage: python -m lib.parsers.monaco <path-to-pdf>", file=sys.stderr)
        sys.exit(1)
    parsed = parse(Path(sys.argv[1]))
    print(f"Parsed {len(parsed)} rows from {sys.argv[1]}")
    for row in parsed[:3]:
        print(row)
    if len(parsed) > 3:
        print("...")
        print(parsed[-1])
