"""
Luxton stocklist parser.

Luxton is the only XLSX-based builder. Stefan sends three weekly XLSX files
plus one PDF. The PDF is a print-export of one of the XLSX files and is
redundant — it's not parsed (the XLSX equivalent has the same rows in clean
form). The three XLSX files have related-but-different schemas; this module
exposes a single `parse(file_path)` entry point that dispatches on the title
cell in row 0:

  - "House & Land Packages"      → Mode A — main weekly stocklist
  - "One Part Contracts"         → Mode B — sets is_one_part=True on every row
  - "THORNHILL GARDENS - …"      → Mode C — agent-specific super-lot file
                                    (B.L.B.G. single-cell bed/living/bath/garage)

All three produce canonical StocklistRow objects.

Source-defect preservation:
  Stefan's data carries known typos that must NOT be silently normalised
  (the validator affirmatively checks they survive):
    - "Contact signed" (sic, House & Land status)
    - "Thorrnhill Gardens" (sic, One Part estate; same estate also appears
      correctly as "Thornhill Gardens")
    - "Pearl " (trailing whitespace, One Part estate — collapsed by
      _clean_str so this DOES get fixed; track via meta if needed)

  Status casing also varies wildly (AVAILABLE / Available / Hold / HOLD /
  SOLD / EOI / CONTRACT SIGNED / Contract). The parser preserves raw
  casing; Stage 7 status-filter.yml does case-insensitive matching.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import openpyxl

from .types import StocklistRow

MODE_HOUSE_AND_LAND = "house_and_land"
MODE_ONE_PART = "one_part"
MODE_SUPERLOTS = "superlots"

BLBG_PATTERN = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)\.(\d+)\s*$")


def _clean_str(value) -> Optional[str]:
    """Coerce any cell value to a stripped string, collapsing whitespace.
    Excel returns floats for integer-looking cells (e.g. 526.0, 4.0); strip
    trailing .0 from numerics so 'lot' fields read as '526' not '526.0'.
    Datetime cells (Stefan sometimes types real dates instead of strings
    like "Sept 2025" — surfaces as `datetime(2025,10,1,0,0)`) format as
    short month-year, e.g. 'Oct 2025'."""
    if value is None:
        return None
    # Local imports to avoid pulling datetime module in non-Excel parsers.
    from datetime import datetime, date as _date
    if isinstance(value, datetime):
        s = value.strftime("%b %Y")
    elif isinstance(value, _date):
        s = value.strftime("%b %Y")
    elif isinstance(value, float) and value.is_integer():
        s = str(int(value))
    else:
        s = str(value)
    s = " ".join(s.split())
    return s if s else None


def _clean_money(value) -> Optional[int]:
    """Handles both '$405,000' (string) and 681350 (int/float) cells."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = _clean_str(value)
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def _clean_int(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = _clean_str(value)
    if not s:
        return None
    match = re.search(r"\d+", s)
    return int(match.group(0)) if match else None


def _clean_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = _clean_str(value)
    if not s:
        return None
    try:
        return float(re.sub(r"[^\d.\-]", "", s))
    except ValueError:
        return None


def _parse_blbg(value) -> tuple[Optional[int], Optional[int], Optional[float], Optional[int]]:
    """Parse Superlots' B.L.B.G. format: '3.1.1.2' → (bed, living, bath, car)."""
    s = _clean_str(value)
    if not s:
        return None, None, None, None
    match = BLBG_PATTERN.match(s)
    if not match:
        return None, None, None, None
    return (
        int(match.group(1)),
        int(match.group(2)),
        float(match.group(3)),
        int(match.group(4)),
    )


def _detect_mode(row0: tuple) -> Optional[str]:
    """Identify the file type from the title cell at A1."""
    if not row0:
        return None
    title = _clean_str(row0[0]) or ""
    # Mode A's row 0 col 0 is "1.0" (a sequence number); the title is in col 1.
    title_b = _clean_str(row0[1] if len(row0) > 1 else None) or ""
    combined = title.upper() + " " + title_b.upper()
    if "HOUSE & LAND PACKAGES" in combined:
        return MODE_HOUSE_AND_LAND
    if "ONE PART CONTRACTS" in combined:
        return MODE_ONE_PART
    if combined.startswith("THORNHILL GARDENS"):
        return MODE_SUPERLOTS
    return None


def _walk_data_rows(rows: list[tuple], header_row: int, key_col: int) -> list[tuple]:
    """Walk rows after the header, collecting non-empty rows where the key
    column is set. Tolerates blank separator rows but stops after >5 in a row
    to avoid scanning thousands of empty trailing rows that openpyxl reports."""
    data = []
    blank_streak = 0
    for row in rows[header_row + 1:]:
        v = row[key_col] if key_col < len(row) else None
        if v is None or str(v).strip() == "":
            blank_streak += 1
            if blank_streak > 5:
                break
            continue
        blank_streak = 0
        data.append(row)
    return data


_NUMERIC_LAND_PRICE = re.compile(r"^[\d,.\s$]+$")


def _is_shifted_hnl_row(row: tuple) -> bool:
    """Detect Stefan's H&L column-shift defect.

    When LAND $ (col 6) is left blank in Stefan's source, the row visually
    shifts: he types HOUSE into col 6, FACADE into col 7, Bed into col 8,
    etc. — everything from cols 6..11 is offset by -1 vs canonical. HOUSE
    m2 / HOUSE $ at cols 13/14 stay aligned. PACKAGE $ ends up missing.

    Detected when col 6 holds non-empty, non-numeric content (a string with
    letters — typically the HOUSE design name like 'LX 18E').

    Known affected: Thornhill Park lots 313, 318 in the 2026-05-08 H&L
    sample. Real source defect, not parser bug.
    """
    val = row[6] if len(row) > 6 else None
    if val is None or isinstance(val, (int, float)):
        return False
    s = str(val).strip()
    if not s:
        return False
    return not _NUMERIC_LAND_PRICE.match(s)


def _parse_house_and_land(rows: list[tuple], source_file: str) -> list[StocklistRow]:
    # Canonical column layout (Google Sheets export, what production will see):
    #   0=ESTATE, 1=REGION, 2=LOT, 3=SUBURB, 4=TITLES, 5=LAND M2, 6=LAND $,
    #   7=HOUSE, 8=FACADE, 9=Bed, 10=Living, 11=Bath, 12=Car,
    #   13=HOUSE m2, 14=HOUSE $, 15=PACKAGE $, 16=STATUS, 17=DOWNLOAD, 18=NOTES
    out: list[StocklistRow] = []
    for i, row in enumerate(_walk_data_rows(rows, header_row=1, key_col=0)):
        meta: dict = {}
        shifted = _is_shifted_hnl_row(row)

        if shifted:
            # Cols 6..11 shifted left by 1; HOUSE m2 / HOUSE $ still at 13/14.
            # PACKAGE $ and STATUS lost — total_price falls back to HOUSE $.
            land_price = None
            home_design = _clean_str(row[6])
            facade = _clean_str(row[7])
            bed = _clean_int(row[8])
            living = _clean_int(row[9])
            bath = _clean_float(row[10])
            car = _clean_int(row[11])
            build_price = _clean_money(row[14]) if len(row) > 14 else None
            total_price = build_price
            status = None
            download = _clean_str(row[15]) if len(row) > 15 else None
            notes = None
            meta["data_defect"] = "shifted_columns_land_price_blank"
        else:
            land_price = _clean_money(row[6])
            home_design = _clean_str(row[7])
            facade = _clean_str(row[8])
            bed = _clean_int(row[9])
            living = _clean_int(row[10])
            bath = _clean_float(row[11])
            car = _clean_int(row[12])
            build_price = _clean_money(row[14])
            total_price = _clean_money(row[15])
            status = _clean_str(row[16]) if len(row) > 16 else None
            download = _clean_str(row[17]) if len(row) > 17 else None
            notes = _clean_str(row[18]) if len(row) > 18 else None

        if living is not None:
            meta["living"] = living
        if download:
            meta["download"] = download
        if notes:
            meta["notes"] = notes

        out.append(StocklistRow(
            builder="luxton",
            suburb=_clean_str(row[3]) or "",
            estate=_clean_str(row[0]),
            lot=_clean_str(row[2]),
            street=None,
            titles=_clean_str(row[4]),
            land_m2=_clean_int(row[5]),
            land_price=land_price,
            home_design=home_design,
            facade=facade,
            house_m2=_clean_float(row[13]),
            bed=bed,
            bath=bath,
            car=car,
            build_price=build_price,
            total_price=total_price,
            status=status,
            is_one_part=False,
            source_file=source_file,
            source_region=_clean_str(row[1]),
            source_row_index=i,
            meta=meta,
        ))
    return out


def _parse_one_part(rows: list[tuple], source_file: str) -> list[StocklistRow]:
    # cols: 0=ESTATE, 1=REGION, 2=LOT, 3=SUBURB, 4=ETA SETTLEMENT, 5=LAND M2,
    # 6=HOUSE, 7=FACADE, 8=BEDS, 9=LIVING, 10=BATH, 11=GARAGE, 12=HOUSE m2,
    # 13=PACKAGE $, 14=STATUS, 15=DOWNLOAD, 16=NOTES, 17=SALES BROCHURE, 18=POS
    out: list[StocklistRow] = []
    for i, row in enumerate(_walk_data_rows(rows, header_row=1, key_col=0)):
        meta: dict = {}
        if (living := _clean_int(row[9])) is not None:
            meta["living"] = living
        for k, idx in (("download", 15), ("notes", 16),
                       ("sales_brochure", 17), ("pos", 18)):
            if idx < len(row) and (v := _clean_str(row[idx])):
                meta[k] = v
        out.append(StocklistRow(
            builder="luxton",
            suburb=_clean_str(row[3]) or "",
            estate=_clean_str(row[0]),
            lot=_clean_str(row[2]),
            street=None,
            titles=_clean_str(row[4]),  # ETA SETTLEMENT — different field, same role
            land_m2=_clean_int(row[5]),
            land_price=None,
            home_design=_clean_str(row[6]),
            facade=_clean_str(row[7]),
            house_m2=_clean_float(row[12]),
            bed=_clean_int(row[8]),
            bath=_clean_float(row[10]),
            car=_clean_int(row[11]),
            build_price=None,
            total_price=_clean_money(row[13]),
            status=_clean_str(row[14]),
            is_one_part=True,
            source_file=source_file,
            source_region=_clean_str(row[1]),
            source_row_index=i,
            meta=meta,
        ))
    return out


def _parse_superlots(rows: list[tuple], source_file: str) -> list[StocklistRow]:
    # cols: 0=ESTATE, 1=REGION, 2=LOT, 3=SUBURB, 4=TITLES, 5=LAND M2, 6=LAND $,
    # 7=HOUSE, 8=FACADE, 9=B.L.B.G., 10=HOUSE m2, 11=HOUSE $, 12=PACKAGE $,
    # 13=STATUS, 14=DOWNLOAD, 15=NOTES
    out: list[StocklistRow] = []
    for i, row in enumerate(_walk_data_rows(rows, header_row=1, key_col=0)):
        bed, living, bath, car = _parse_blbg(row[9])
        meta: dict = {"superlot": True}
        if living is not None:
            meta["living"] = living
        if (download := _clean_str(row[14])):
            meta["download"] = download
        if (notes := _clean_str(row[15])):
            meta["notes"] = notes
        out.append(StocklistRow(
            builder="luxton",
            suburb=_clean_str(row[3]) or "",
            estate=_clean_str(row[0]),
            lot=_clean_str(row[2]),
            street=None,
            titles=_clean_str(row[4]),
            land_m2=_clean_int(row[5]),
            land_price=_clean_money(row[6]),
            home_design=_clean_str(row[7]),
            facade=_clean_str(row[8]),
            house_m2=_clean_float(row[10]),
            bed=bed,
            bath=bath,
            car=car,
            build_price=_clean_money(row[11]),
            total_price=_clean_money(row[12]),
            status=_clean_str(row[13]),
            is_one_part=False,
            source_file=source_file,
            source_region=_clean_str(row[1]),
            source_row_index=i,
            meta=meta,
        ))
    return out


def parse(file_path: Path) -> list[StocklistRow]:
    """Parse any of Luxton's three XLSX file types into canonical rows."""
    file_path = Path(file_path)
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    mode = _detect_mode(rows[0])
    if mode == MODE_HOUSE_AND_LAND:
        return _parse_house_and_land(rows, file_path.name)
    if mode == MODE_ONE_PART:
        return _parse_one_part(rows, file_path.name)
    if mode == MODE_SUPERLOTS:
        return _parse_superlots(rows, file_path.name)
    raise ValueError(
        f"Unknown Luxton file format. Row 0 starts with: {rows[0][:3]!r}. "
        f"Expected one of: 'House & Land Packages', 'One Part Contracts', "
        f"'THORNHILL GARDENS - ...'"
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m lib.parsers.luxton <path-to-xlsx>", file=sys.stderr)
        sys.exit(1)
    parsed = parse(Path(sys.argv[1]))
    print(f"Parsed {len(parsed)} rows from {sys.argv[1]}")
    for row in parsed[:3]:
        print(row)
    if len(parsed) > 3:
        print("...")
        print(parsed[-1])
