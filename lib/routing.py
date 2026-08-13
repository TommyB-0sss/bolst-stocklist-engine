"""
Region routing layer.

Takes a parsed StocklistRow and assigns it to one of Bolst's 10 canonical
regions (or to the special "uncategorised" bucket if its suburb isn't in
the map). Routing is driven by config/suburbs.yml.

Two precedence rules:

  1. row.is_one_part=True  → region_id="one-part-contracts" (always)
     (One-part contracts get their own dedicated tab regardless of suburb.)

  2. otherwise → suburb pre-normalisation → alias lookup → suburb_to_region
     If no match: region_id="uncategorised", routing_reason explains why.

Pre-normalisation (in order, in `_normalise_suburb`):
  - Strip trailing parens block:  "Bonshaw (Ballarat)" → "Bonshaw"
  - If comma present, take last part:
      "Penndale Street, Tarneit" → "Tarneit"   (Australian "<street>, <suburb>")
  - Trim whitespace, uppercase

Featured-section markers (Hermitage's "PACKAGES OF THE WEEK", Aldrich's
"Exclusive Packages") flow through as meta["featured"]=True on the
RoutedRow. Stage 8 (PDF render) decides how to display them; this layer
doesn't promote them to a separate region.

This module does NOT mutate StocklistRow. RoutedRow wraps the original
row plus routing metadata. Parsers stay pure; routing is composable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from lib.parsers.types import StocklistRow

ONE_PART_REGION_ID = "one-part-contracts"
UNCATEGORISED_REGION_ID = "uncategorised"

# Source-region values that flag a row as featured. These currently come
# from Hermitage and Aldrich; both flow through to the row's normal
# geographic region but get meta["featured"]=True for downstream rendering.
FEATURED_SOURCE_REGIONS = {
    "PACKAGES OF THE WEEK",   # Hermitage
    "Exclusive Packages",     # Aldrich
}


@dataclass
class RoutedRow:
    row: StocklistRow
    region_id: str
    routing_reason: str
    meta: dict = field(default_factory=dict)

    @property
    def is_uncategorised(self) -> bool:
        return self.region_id == UNCATEGORISED_REGION_ID


@dataclass
class RoutingConfig:
    """Loaded view of config/suburbs.yml. Keys are uppercased for lookup."""
    region_ids: set[str]               # known region ids (sanity check)
    region_names: dict[str, str]       # id → display name
    region_banners: dict[str, Optional[str]]
    suburb_aliases: dict[str, str]     # UPPERCASE → UPPERCASE
    suburb_to_region: dict[str, str]   # UPPERCASE → region_id


def load_config(path: Path) -> RoutingConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    region_ids = {r["id"] for r in raw.get("regions", [])}
    region_names = {r["id"]: r["name"] for r in raw.get("regions", [])}
    region_banners = raw.get("region_banner", {}) or {}

    suburb_aliases = {
        k.upper(): v.upper()
        for k, v in (raw.get("suburb_aliases") or {}).items()
    }
    suburb_to_region = {
        k.upper(): v
        for k, v in (raw.get("suburb_to_region") or {}).items()
    }

    # Sanity: every value in suburb_to_region must reference a known region_id.
    bad = {sub: rid for sub, rid in suburb_to_region.items()
           if rid not in region_ids}
    if bad:
        raise ValueError(
            f"suburb_to_region references unknown region_id(s): {bad}"
        )
    # Aliases must point at a key that's in the suburb map (otherwise the
    # alias is a dead-end).
    bad_aliases = {k: v for k, v in suburb_aliases.items()
                   if v not in suburb_to_region}
    if bad_aliases:
        raise ValueError(
            f"suburb_aliases point to unmapped target(s): {bad_aliases}"
        )

    return RoutingConfig(
        region_ids=region_ids,
        region_names=region_names,
        region_banners=region_banners,
        suburb_aliases=suburb_aliases,
        suburb_to_region=suburb_to_region,
    )


_PARENS_TAIL = re.compile(r"\s*\([^)]*\)\s*$")

# Some senders append a state and/or country to the suburb — Hermitage emits
# "Winter Valley VIC, Australia". This MUST be stripped BEFORE the comma rule
# below, because rsplit(",")[-1] would otherwise reduce that to "Australia"
# and send every such row to uncategorised (added 2026-08-06, 3 live rows).
#
# Deliberately anchored on AUSTRALIA: the state name alone is only stripped as
# part of a country-terminated tail, so a suburb whose final word merely looks
# like a state abbreviation is never touched. A ", VIC" tail with no country
# is NOT handled — it would fail visibly in the uncategorised warning rather
# than route somewhere wrong, which is the safer failure for an unseen format.
_STATE_COUNTRY_TAIL = re.compile(
    r"[,\s]+(?:VIC|VICTORIA|NSW|QLD|SA|WA|TAS|NT|ACT)?[,\s]*AUSTRALIA\s*$",
    re.IGNORECASE,
)


def _normalise_suburb(raw: Optional[str]) -> str:
    """Apply the pre-normalisation rules documented in suburbs.yml."""
    if not raw:
        return ""
    s = str(raw).strip()
    s = _PARENS_TAIL.sub("", s)
    s = _STATE_COUNTRY_TAIL.sub("", s)
    if "," in s:
        s = s.rsplit(",", 1)[-1]
    return s.strip().upper()


def route_row(row: StocklistRow, config: RoutingConfig) -> RoutedRow:
    """Route a single StocklistRow to a Bolst region."""
    meta: dict = {}

    # Featured marker (Hermitage Packages, Aldrich Exclusive). Doesn't
    # change region — just annotates for Stage 8.
    if row.source_region in FEATURED_SOURCE_REGIONS:
        meta["featured"] = True
        meta["featured_source"] = row.source_region

    # Precedence rule 1: One Part Contracts overrides suburb routing.
    if row.is_one_part:
        return RoutedRow(
            row=row,
            region_id=ONE_PART_REGION_ID,
            routing_reason="is_one_part",
            meta=meta,
        )

    # Precedence rule 2: suburb lookup with pre-normalisation + alias.
    norm = _normalise_suburb(row.suburb)
    if not norm:
        return RoutedRow(
            row=row,
            region_id=UNCATEGORISED_REGION_ID,
            routing_reason="suburb_empty",
            meta=meta,
        )

    canonical = config.suburb_aliases.get(norm, norm)
    region_id = config.suburb_to_region.get(canonical)
    if region_id is None:
        return RoutedRow(
            row=row,
            region_id=UNCATEGORISED_REGION_ID,
            routing_reason=f"suburb_unmapped:{row.suburb!r}",
            meta=meta,
        )

    reason = f"suburb:{canonical}->{region_id}"
    if canonical != norm:
        reason = f"suburb:{norm}=>{canonical}->{region_id}"  # alias path
    return RoutedRow(
        row=row,
        region_id=region_id,
        routing_reason=reason,
        meta=meta,
    )


def route(rows: list[StocklistRow], config: RoutingConfig) -> list[RoutedRow]:
    return [route_row(r, config) for r in rows]


if __name__ == "__main__":
    import sys
    from collections import Counter
    from pathlib import Path as _P

    BUNDLE_ROOT = _P(__file__).resolve().parent.parent
    sys.path.insert(0, str(BUNDLE_ROOT))

    cfg = load_config(BUNDLE_ROOT / "config" / "suburbs.yml")
    print(f"Loaded {len(cfg.region_ids)} regions, "
          f"{len(cfg.suburb_aliases)} aliases, "
          f"{len(cfg.suburb_to_region)} suburb mappings.")
