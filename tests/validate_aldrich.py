"""
Validation script for the Aldrich parser.

Usage (from bundle root, with venv active):
    python tests/validate_aldrich.py

Tests STRUCTURAL invariants. Fixture should be refreshed by saving Corey's
latest "ALDRICH HOMES STOCKLIST" attachment.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.aldrich import parse  # noqa: E402

SAMPLE = (
    BUNDLE_ROOT.parent
    / "bolst-property-group-data"
    / "Corey.b@aldrichhomes.com.au"
    / "Stocklist C44.pdf"
)

# Aldrich's PDF prints these region headers at the top of each page;
# they're a stable structural property of the file format, unlike row counts.
VALID_REGIONS = {
    None,
    "Exclusive Packages",
    "West",
    "North",
    "South-East",
    "Geelong",
}

CRITICAL_FIELDS = ("suburb", "lot", "estate", "total_price", "home_design", "status")
ARITHMETIC_TOLERANCE = 5


def main() -> int:
    if not SAMPLE.exists():
        print(f"ERROR: missing sample {SAMPLE}", file=sys.stderr)
        return 1

    rows = parse(SAMPLE)
    print(f"=== {SAMPLE.name}: {len(rows)} rows ===")
    print(f"  Regions: {dict(Counter(r.source_region for r in rows))}")
    print(f"  Statuses: {dict(Counter(r.status for r in rows))}")
    print(f"  Distinct estates: {len(set(r.estate for r in rows))}")
    rebates = sum(1 for r in rows if r.meta.get("land_rebate"))
    print(f"  Rows with land_rebate: {rebates}")
    if rows:
        prices = [r.total_price for r in rows if r.total_price]
        if prices:
            print(f"  Package price range: ${min(prices):,} - ${max(prices):,}")

    # --- Arithmetic (informational) ---
    arith_issues = []
    for i, r in enumerate(rows):
        if r.land_price is None or r.build_price is None or r.total_price is None:
            continue
        delta = (r.land_price + r.build_price) - r.total_price
        if abs(delta) > ARITHMETIC_TOLERANCE:
            arith_issues.append((i, r, delta))
    if arith_issues:
        print(f"\n  WARN {len(arith_issues)} arithmetic mismatch(es):")
        for i, r, d in arith_issues[:5]:
            print(f"    Row {i}: lot {r.lot} {r.estate} off by ${d:+,}")
    else:
        print("  All rows: land_price + build_price == total_price.")

    # --- Structural invariants ---
    fails: list[str] = []
    if len(rows) == 0:
        fails.append("zero rows parsed")
    if not all(r.builder == "aldrich" for r in rows):
        fails.append("not all rows have builder='aldrich'")
    if not all(r.source_file == SAMPLE.name for r in rows):
        fails.append("source_file mismatch on some rows")
    for fld in CRITICAL_FIELDS:
        miss = sum(1 for r in rows if not getattr(r, fld))
        if miss > 0:
            fails.append(f"{miss} row(s) missing {fld}")

    bad_regions = {r.source_region for r in rows} - VALID_REGIONS
    if bad_regions:
        fails.append(f"unexpected source_region value(s): {bad_regions}")

    # Aldrich source has no ONE PART CONTRACT marker — every row should have
    # is_one_part=False (orchestrator may flip this later via builders.yml).
    leaked = sum(1 for r in rows if r.is_one_part)
    if leaked:
        fails.append(f"{leaked} row(s) unexpectedly have is_one_part=True")

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
