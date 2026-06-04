"""
REA Ignite CSV parser — Bolst Listings tab.

Source: Tom configures Ignite to email a daily scheduled "Active Listings"
CSV report to his own Outlook (Bolst_Phase1_Plan.md line 79 — "no Ignite
credentials, no scraping"). We read the CSV from Outlook each morning and
feed it through this parser.

Output: List[ListingRow] populating the dedicated "Bolst Listings" page of
the morning PDF. 7 rendered columns are locked in Bolst_Phase1_Plan.md
line 77: Lot, Address, Suburb, Price, Title Status, Listing URL, Listing
Agent.

Expected CSV columns (15, in this order — header-matched so reordering by
Ignite export config is detected loudly rather than silently misaligning):

  0  Property Id
  1  Street Address
  2  Suburb
  3  Address Hidden Y/N
  4  Property Type
  5  Price
  6  Price Display
  7  Title
  8  Description
  9  Listing Agent
  10 Vendor Name
  11 Vendor Phone
  12 Bedrooms
  13 Authority
  14 Auction Datetime

Encoding: the Ignite export is UTF-8 (sample 2026-05-01 has emoji ✔️ in
descriptions). Use utf-8-sig to also tolerate a BOM if Ignite ever adds one.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable, Optional

from .types import ListingRow

EXPECTED_HEADER = [
    "Property Id", "Street Address", "Suburb", "Address Hidden Y/N",
    "Property Type", "Price", "Price Display", "Title", "Description",
    "Listing Agent", "Vendor Name", "Vendor Phone", "Bedrooms",
    "Authority", "Auction Datetime",
]

LISTING_URL_TEMPLATE = (
    "https://agentadmin.realestate.com.au/agentdesktop"
    "#listings/{property_id}/edit/campaign"
)

# Lot prefix variants seen in Ignite data:
#   "Lot 251 Butters Rd."
#   "Lot.411 Roselldan Road"            (period instead of space)
#   "Lot - 1 Wedge Street"              (dash separator)
#   "LOT-1756. Blythen Road"            (no space at all)
# Matches: Lot followed by any combination of space/period/dash, then digits.
LOT_RE = re.compile(r"^\s*Lot[\s.\-]+(\d+\w?)\b", re.IGNORECASE)

# Estate name embedded in parentheses, e.g. "Lot 319 Fencepost Drive (Atkinson Place)"
ESTATE_RE = re.compile(r"\(([^)]+)\)")

# Title-status patterns. Order matters: most-specific first. Each pattern
# returns the matched substring as the displayed value.
TITLE_STATUS_PATTERNS = [
    # "titling Dec 2026", "titling mid 2026", "titling late 2026"
    re.compile(
        r"titling\s+"
        r"(?:early\s+|mid\s+|late\s+)?"
        r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
        r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
        r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
        r"early|mid|late)\s+\d{4}",
        re.IGNORECASE,
    ),
    # "Q3 2026"
    re.compile(r"Q[1-4]\s*\d{4}", re.IGNORECASE),
    # "Titled" — last because it's a substring of "titling"-prefixed text
    re.compile(r"\btitled\b", re.IGNORECASE),
]


def _extract_lot(street_address: str) -> Optional[str]:
    if not street_address:
        return None
    m = LOT_RE.match(street_address)
    return m.group(1) if m else None


def _strip_lot_and_estate(street_address: str) -> tuple[str, Optional[str]]:
    """Return (address-without-lot-prefix-or-estate-parens, estate-or-None).

    "Lot 319 Fencepost Drive (Atkinson Place)" -> ("Fencepost Drive", "Atkinson Place")
    "92 Grafton Street"                         -> ("92 Grafton Street", None)
    "Lot - 1  Wedge Street"                     -> ("Wedge Street", None)
    """
    if not street_address:
        return "", None
    s = street_address

    # 1. Extract estate (first parenthesised group), then remove it from the
    #    address.
    estate = None
    m = ESTATE_RE.search(s)
    if m:
        estate = m.group(1).strip()
        s = ESTATE_RE.sub("", s)

    # 2. Strip "Lot N" prefix (any of the variants LOT_RE matches).
    s = LOT_RE.sub("", s, count=1)

    # 3. Collapse whitespace + strip leading punctuation residue.
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return s, estate


def _parse_int_or_none(s: str) -> Optional[int]:
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def _extract_title_status(*texts: str) -> Optional[str]:
    blob = " ".join(t for t in texts if t)
    for pat in TITLE_STATUS_PATTERNS:
        m = pat.search(blob)
        if m:
            # Normalise whitespace + capitalise leading word for display
            value = re.sub(r"\s+", " ", m.group(0).strip())
            return value[:1].upper() + value[1:]
    return None


def _read_rows(csv_path: Path) -> Iterable[list[str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        yield from csv.reader(f)


def parse(csv_path: Path) -> list[ListingRow]:
    """Parse an Ignite Active Listings CSV → List[ListingRow]."""
    rows_iter = iter(_read_rows(csv_path))
    try:
        header = next(rows_iter)
    except StopIteration:
        return []

    # Header-match (case-insensitive, whitespace-trimmed) to catch the
    # day Tom's export config silently reorders columns.
    actual = [h.strip() for h in header]
    if actual != EXPECTED_HEADER:
        missing = set(EXPECTED_HEADER) - set(actual)
        extra = set(actual) - set(EXPECTED_HEADER)
        raise ValueError(
            f"REA Ignite CSV header mismatch in {csv_path.name}. "
            f"Missing: {sorted(missing)}. Extra: {sorted(extra)}."
        )

    out: list[ListingRow] = []
    for idx, row in enumerate(rows_iter, start=1):
        if len(row) != len(EXPECTED_HEADER):
            # Defensive: malformed row, skip with a flag
            continue
        (
            property_id, street, suburb, hidden, prop_type, price, price_display,
            title, description, listing_agent, vendor_name, vendor_phone,
            bedrooms, authority, auction_dt,
        ) = (cell.strip() for cell in row)

        if not property_id:
            continue

        address_clean, estate = _strip_lot_and_estate(street)
        listing = ListingRow(
            lot=_extract_lot(street),
            address=address_clean,
            raw_address=street,
            estate=estate,
            suburb=suburb,
            title_status=_extract_title_status(title, description),
            bed=_parse_int_or_none(bedrooms),
            price=price,
            price_int=_parse_int_or_none(price),
            listing_agent=listing_agent,
            listing_url=LISTING_URL_TEMPLATE.format(property_id=property_id),
            property_id=property_id,
            source_file=csv_path.name,
            source_row_index=idx,
            meta={
                "address_hidden": hidden,
                "property_type": prop_type,
                "price_display": price_display,
                "authority": authority,
                "auction_datetime": auction_dt,
                "vendor_name": vendor_name,
                "vendor_phone": vendor_phone,
                "title": title,
                "description": description,
            },
        )
        out.append(listing)
    return out
