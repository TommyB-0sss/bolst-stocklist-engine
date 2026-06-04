"""
Validation script for the Specialised parser.

Usage (from bundle root, with venv active):
    python tests/validate_specialised.py

Tests STRUCTURAL invariants only. Specialised's PDF has no Status column;
parser defaults all rows to status="Available". No source_region either —
their PDF doesn't carry per-row regional grouping (Stage 7 will infer
region from suburb).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.specialised import parse  # noqa: E402

SAMPLE = (
    BUNDLE_ROOT.parent
    / "bolst-property-group-data"
    / "nlimbo@specialisedhomeconstructions.com.au"
    / "Stocklist 28.04.26.pdf"
)

CRITICAL_FIELDS = ("suburb", "lot", "estate", "total_price", "home_design")


def main() -> int:
    if not SAMPLE.exists():
        print(f"ERROR: missing sample {SAMPLE}", file=sys.stderr)
        return 1

    rows = parse(SAMPLE)
    print(f"=== {SAMPLE.name}: {len(rows)} rows ===")
    print(f"  Distinct suburbs: {len(set(r.suburb for r in rows))}")
    print(f"  Distinct estates: {len(set(r.estate for r in rows))}")
    print(f"  Distinct home designs: {len(set(r.home_design for r in rows))}")
    print(f"  Statuses: {dict(Counter(r.status for r in rows))}")
    titles = Counter(r.titles for r in rows)
    print(f"  Distinct titles values: {len(titles)}")
    bbc = sum(1 for r in rows if r.bed and r.bath is not None and r.car is not None)
    print(f"  bed/bath/car parsed: {bbc}/{len(rows)}")
    if rows:
        prices = [r.total_price for r in rows if r.total_price]
        if prices:
            print(f"  Total price range: ${min(prices):,} - ${max(prices):,}")

    fails: list[str] = []
    if len(rows) == 0:
        fails.append("zero rows parsed")
    if not all(r.builder == "specialised" for r in rows):
        fails.append("not all rows have builder='specialised'")
    if not all(r.source_file == SAMPLE.name for r in rows):
        fails.append("source_file mismatch on some rows")
    for fld in CRITICAL_FIELDS:
        miss = sum(1 for r in rows if not getattr(r, fld))
        if miss > 0:
            fails.append(f"{miss} row(s) missing {fld}")

    print("\n--- Structural checks ---")
    if fails:
        print(f"FAIL ({len(fails)} violation(s)):")
        for f in fails:
            print(f"  - {f}")
        return 2
    print(f"PASS - {len(rows)} rows parse cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
