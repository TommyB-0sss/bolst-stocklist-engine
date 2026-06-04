"""
Validation script for the Hermitage parser.

Usage (from bundle root, with venv active):
    python tests/validate_hermitage.py

Tests STRUCTURAL invariants. The fixture is a snapshot of Hermitage's
public CDN PDF (URL pattern: hs-6368574.f.hubspotstarter.net/hubfs/6368574/
{DDMMYY}.pdf) and should be refreshed periodically. Row counts and
estate names drift weekly; do not assert on them.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.hermitage import parse  # noqa: E402

# Pick whichever Hermitage PDF is present in the data folder. Filenames
# follow the DDMMYY pattern of the source CDN.
SAMPLES_DIR = BUNDLE_ROOT.parent / "bolst-property-group-data" / "houseandland@hermitagehomes.com.au"

VALID_REGIONS = {
    None,  # rare — only if region detection fails for an early row
    "PACKAGES OF THE WEEK",
    "NORTHERN REGION",
    "SOUTH-EASTERN REGION",
    "WESTERN REGION",
    "REGIONAL",
}

CRITICAL_FIELDS = ("suburb", "lot", "estate", "total_price", "home_design", "status")
ARITHMETIC_TOLERANCE = 5  # dollars


def main() -> int:
    pdfs = sorted(SAMPLES_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"ERROR: no Hermitage sample PDF in {SAMPLES_DIR}", file=sys.stderr)
        return 1
    sample = pdfs[-1]  # most recently named (DDMMYY sorts mostly by date)

    rows = parse(sample)
    print(f"=== {sample.name}: {len(rows)} rows ===")
    print(f"  Regions: {dict(Counter(r.source_region for r in rows))}")
    print(f"  Statuses: {dict(Counter(r.status for r in rows))}")
    print(f"  Distinct estates: {len(set(r.estate for r in rows))}")
    print(f"  is_one_part rows: {sum(1 for r in rows if r.is_one_part)}")
    if rows:
        prices = [r.total_price for r in rows if r.total_price]
        if prices:
            print(f"  Total price range: ${min(prices):,} - ${max(prices):,}")

    # --- Arithmetic integrity (informational; does not fail) ---
    arith_issues = []
    for i, r in enumerate(rows):
        if r.land_price is None or r.build_price is None or r.total_price is None:
            continue
        delta = (r.land_price + r.build_price) - r.total_price
        if abs(delta) > ARITHMETIC_TOLERANCE:
            arith_issues.append((i, r, delta))
    if arith_issues:
        print(f"\n  WARN {len(arith_issues)} arithmetic mismatch(es) (likely source typos):")
        for i, r, d in arith_issues[:5]:
            print(f"    Row {i}: lot {r.lot} {r.street} land+build vs total off by ${d:+,}")
    else:
        print("  All rows: land_price + build_price == total_price.")

    # --- Structural invariants ---
    fails: list[str] = []
    if len(rows) == 0:
        fails.append("zero rows parsed")
    if not all(r.builder == "hermitage" for r in rows):
        fails.append("not all rows have builder='hermitage'")
    if not all(r.source_file == sample.name for r in rows):
        fails.append("source_file mismatch on some rows")
    for fld in CRITICAL_FIELDS:
        miss = sum(1 for r in rows if not getattr(r, fld))
        if miss > 0:
            fails.append(f"{miss} row(s) missing {fld}")

    bad_regions = {r.source_region for r in rows} - VALID_REGIONS
    if bad_regions:
        fails.append(f"unexpected source_region value(s): {bad_regions}")

    # is_one_part must mirror the Street-cell convention exactly.
    for i, r in enumerate(rows):
        expected = (r.street or "").upper() == "ONE PART CONTRACT"
        if r.is_one_part != expected:
            fails.append(f"row {i} is_one_part={r.is_one_part} mismatches "
                         f"street={r.street!r}")
            break  # one example is enough

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
