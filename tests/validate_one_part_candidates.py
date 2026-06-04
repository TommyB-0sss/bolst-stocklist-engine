"""
Smoke test for the Stage 9 candidate generator.

Usage (from bundle root, with venv active):
    python tests/validate_one_part_candidates.py

Tests STRUCTURAL invariants only — drift-tolerant so it stays green when
Specialised's stocklist changes week to week. We verify:
  - Generator returns a non-empty list of CandidateGroup
  - No row in the output has is_one_part=True (the filter worked)
  - Every group has a non-empty suburb + estate + at least one row
  - Lot order within each group is ascending (by leading numeric portion)
  - Row count out == row count in (no rows lost during grouping)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.one_part_candidates import get_specialised_candidates  # noqa: E402
from lib.parsers.specialised import parse as parse_specialised  # noqa: E402

SAMPLE = (
    BUNDLE_ROOT.parent
    / "bolst-property-group-data"
    / "nlimbo@specialisedhomeconstructions.com.au"
    / "Stocklist 28.04.26.pdf"
)


def _lot_num(lot: str | None) -> int:
    if not lot:
        return 10**9
    m = re.search(r"\d+", lot)
    return int(m.group()) if m else 10**9


def main() -> int:
    if not SAMPLE.exists():
        print(f"ERROR: missing sample {SAMPLE}", file=sys.stderr)
        return 1

    raw_rows = parse_specialised(SAMPLE)
    groups = get_specialised_candidates(SAMPLE)
    total_out = sum(len(g.rows) for g in groups)

    print(f"=== {SAMPLE.name} ===")
    print(f"  Parsed rows:           {len(raw_rows)}")
    print(f"  Candidate groups:      {len(groups)}")
    print(f"  Rows across groups:    {total_out}")
    print(f"  Distinct suburbs:      {len({g.suburb for g in groups})}")
    print(f"  Distinct estates:      {len({(g.suburb, g.estate) for g in groups})}")
    if groups:
        sample = groups[0]
        print(
            f"  First group: {sample.suburb} / {sample.estate} "
            f"({len(sample.rows)} row(s), lots: "
            f"{', '.join(r.lot or '?' for r in sample.rows)})"
        )

    fails: list[str] = []
    if len(groups) == 0:
        fails.append("zero candidate groups returned")
    if total_out != sum(1 for r in raw_rows if not r.is_one_part):
        fails.append(
            f"row count mismatch: out={total_out} != "
            f"in_eligible={sum(1 for r in raw_rows if not r.is_one_part)}"
        )
    for g in groups:
        if not g.suburb:
            fails.append(f"group with empty suburb (estate={g.estate!r})")
        if not g.estate:
            fails.append(f"group with empty estate (suburb={g.suburb!r})")
        if not g.rows:
            fails.append(f"group {g.suburb}/{g.estate} has zero rows")
        if any(r.is_one_part for r in g.rows):
            fails.append(f"group {g.suburb}/{g.estate} contains is_one_part=True row")
        nums = [_lot_num(r.lot) for r in g.rows]
        if nums != sorted(nums):
            fails.append(f"group {g.suburb}/{g.estate} lots not ascending: {nums}")

    print("\n--- Structural checks ---")
    if fails:
        print(f"FAIL ({len(fails)} violation(s)):")
        for f in fails:
            print(f"  - {f}")
        return 2
    print(f"PASS - {len(groups)} groups / {total_out} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
