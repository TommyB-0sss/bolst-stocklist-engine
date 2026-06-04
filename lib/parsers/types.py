"""
Canonical row schema produced by every builder parser.

All 6 parsers (aplace, luxton, specialised, aldrich, hermitage, urbane) emit
List[StocklistRow] regardless of source format. Downstream code (region routing,
status filter, dedup, PDF render) operates only on this shape.

Fields are Optional because builders vary in what they include. Required fields
that we'd expect every row to have: builder, lot, suburb, status, source_file.

Add fields here as new builders surface new data — but keep this single source of
truth for the row shape across the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StocklistRow:
    builder: str

    # Location
    suburb: str
    estate: Optional[str] = None
    lot: Optional[str] = None
    street: Optional[str] = None

    # Land
    titles: Optional[str] = None              # "Titled" / "Mar-27" / "Q4 2026"
    land_m2: Optional[int] = None
    land_dimensions: Optional[str] = None     # "10.5 x 28" — kept raw
    land_price: Optional[int] = None          # dollars

    # Home
    home_design: Optional[str] = None
    facade: Optional[str] = None
    house_m2: Optional[float] = None
    bed: Optional[int] = None
    bath: Optional[float] = None              # fractional like 2.5
    car: Optional[int] = None

    # Pricing
    build_price: Optional[int] = None         # dollars
    total_price: Optional[int] = None         # dollars

    # Release / status
    release_type: Optional[str] = None        # builder-specific concept
    status: Optional[str] = None              # "Available" / "Reserved" / "EOI" / etc
    is_one_part: bool = False                 # True for one-part contracts

    # Traceability — set by the parser, used for audit and dedup
    source_file: Optional[str] = None
    source_region: Optional[str] = None       # raw region label from source (page header etc)
    source_row_index: Optional[int] = None

    # Builder-specific fields that don't fit the canonical shape go here
    meta: dict = field(default_factory=dict)


@dataclass
class ListingRow:
    """
    Row shape emitted by the REA Ignite CSV parser.

    Separate from StocklistRow because the REA Ignite export is fundamentally
    different data: it describes Bolst's OWN active listings on realestate.com.au,
    not builder stock available to sell. The PDF renders these in a dedicated
    "Bolst Listings" section (Bolst_Phase1_Plan.md line 77) whose 7 columns map
    directly to the fields below.
    """

    # Identifiers / rendered fields (Bolst Listings page mirrors senders' 8-col
    # layout — Bolst_Phase1_Plan.md line 77 originally specified 7 cols, but
    # Inam 2026-05-23 widened to 8 cols for visual parity with regional pages:
    # SUBURB | LOT | ADDRESS | ESTATE | TITLES | BED/Bath/Car | TOTAL $ | AGENT.
    # LISTING URL column dropped; URL retained on the row for future use.)
    lot: Optional[str]            # extracted from Street Address ("Lot 251 ..." -> "251")
    address: str                  # Street Address with "Lot N" prefix + "(estate)" stripped
    raw_address: str              # original Street Address as supplied by Ignite
    estate: Optional[str]         # extracted from "(...)" in Street Address
    suburb: str
    title_status: Optional[str]   # "Titled" / "Titling Dec 2026" — regex over Title+Description
    bed: Optional[int]            # from "Bedrooms" CSV column
    price: str                    # formatted "$631,343" — for display
    price_int: Optional[int]      # numeric for sorting (price-desc within suburb)
    listing_agent: str            # "Sammy Swayn" / "Howard Rock" / "Aaron Wilson"
    listing_url: str              # kept for future use even though dropped from PDF

    # Traceability
    property_id: str
    source_file: Optional[str] = None
    source_row_index: Optional[int] = None

    # Fields we don't render but keep for audit/debug
    meta: dict = field(default_factory=dict)
