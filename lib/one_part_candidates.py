"""
Stage 9 — Specialised One Part candidate generator.

Produces the list of rows the 16:00 AEST evening prompt shows to Tom so he
can pick which lots to promote to the One Part Contracts tab.

Why this module exists
----------------------
Per the locked plan (`Bolst_Phase1_Plan.md` line 81), the One Part Specialised
flow is editorial, not rule-based. Tom replies with the lots he wants. The
candidate set is "every Specialised row that the parser hasn't already flagged
as `is_one_part=True`" — today that's all rows (the Specialised parser flags
nothing), but the filter future-proofs us if Specialised ever starts shipping
explicit one-part markers like Hermitage does.

What it returns
---------------
A list of `CandidateGroup`s, each one a (suburb, estate) bucket with its
rows sorted by lot number. Grouping matches how Tom thinks about lots when
picking ("two from Elliminyt, one from Thornhill Park"). The downstream
email composer (Stage 9.2) renders one table per group.

Public API
----------
    get_specialised_candidates(file_path: Path) -> list[CandidateGroup]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .parsers.specialised import parse as parse_specialised
from .parsers.types import StocklistRow


@dataclass
class CandidateGroup:
    suburb: str
    estate: str
    rows: list[StocklistRow] = field(default_factory=list)


def _lot_sort_key(lot: str | None) -> tuple[int, str]:
    if not lot:
        return (10**9, "")
    m = re.search(r"\d+", lot)
    return (int(m.group()) if m else 10**9, lot)


def get_specialised_candidates(file_path: Path) -> list[CandidateGroup]:
    rows = parse_specialised(file_path)
    eligible = [r for r in rows if not r.is_one_part]

    grouped: dict[tuple[str, str], list[StocklistRow]] = {}
    for r in eligible:
        key = (r.suburb or "", r.estate or "")
        grouped.setdefault(key, []).append(r)

    groups: list[CandidateGroup] = []
    for (suburb, estate) in sorted(grouped.keys(), key=lambda k: (k[0].lower(), k[1].lower())):
        bucket = sorted(grouped[(suburb, estate)], key=lambda r: _lot_sort_key(r.lot))
        groups.append(CandidateGroup(suburb=suburb, estate=estate, rows=bucket))
    return groups
