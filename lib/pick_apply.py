"""
Stage 9.4 — Promote Tom's One Part picks to is_one_part=True before routing.

Once the morning poll (9.3) has parsed Tom's reply into a list of picks,
this module mutates the freshly-parsed Specialised rows so they carry
`is_one_part=True`. From there, the existing Stage 7 routing precedence
(one_part overrides suburb routing) flows them into the One Part Contracts
tab without any changes to routing.py.

Why match strictly on (lot, suburb, estate)
-------------------------------------------
The picks coming out of pick_parser.parse_picks() are StocklistRow objects
from the SAME PDF file the morning report just parsed — but they're a
DIFFERENT parse pass (one for the prompt at 16:00 yesterday, one for the
report at 06:50 today). So object identity doesn't hold; we have to match
on stable fields.

Lot alone is not unique (this week has 5 lot numbers shared across two
estates). Lot + suburb is sufficient today, but (lot, suburb, estate) is
the safest 3-field key — if Specialised ever ships the same lot in
multiple estates within the same suburb, we still pick the right one.

Caller is responsible for logging the returned count vs len(picks). A
mismatch means the stocklist Tom replied against has changed since the
prompt was sent (e.g., Specialised pushed an updated PDF overnight) —
worth a banner in the report.
"""

from __future__ import annotations

from .parsers.types import StocklistRow


def apply_picks(rows: list[StocklistRow], picks: list[StocklistRow]) -> int:
    if not picks:
        return 0

    pick_keys = {(p.lot, p.suburb, p.estate) for p in picks if p.lot and p.suburb}

    applied = 0
    for row in rows:
        if row.builder != "specialised":
            continue
        if (row.lot, row.suburb, row.estate) in pick_keys:
            row.is_one_part = True
            applied += 1
    return applied
