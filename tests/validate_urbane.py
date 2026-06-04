"""
Validation script for the Urbane parser.

Usage (from bundle root, with venv active):
    python tests/validate_urbane.py

Tests STRUCTURAL invariants. Fixture should be refreshed from Tyana
Troise's latest direct attachment ("Urbane Homes | Latest Stock List
Update - DD/MM/YYYY - vNNN").
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.urbane import parse  # noqa: E402

# Look up the Urbane sample wherever it landed (folder is sender-named).
SAMPLES_DIR = BUNDLE_ROOT.parent / "bolst-property-group-data"
URBANE_FOLDER = next(
    (d for d in SAMPLES_DIR.iterdir() if d.is_dir() and "orbithomes" in d.name.lower()),
    None,
)

# Urbane's PDF uses these inline region markers (`/// METRO NORTH \\\` etc.);
# they're a stable structural property of the file format.
VALID_REGIONS = {
    None,
    "METRO NORTH",
    "METRO WEST",
    "METRO SOUTHEAST",
    "GEELONG",
}

CRITICAL_FIELDS = ("suburb", "lot", "street", "estate", "total_price", "home_design")
ARITHMETIC_TOLERANCE = 5


def main() -> int:
    if URBANE_FOLDER is None:
        print(f"ERROR: no Urbane sample folder under {SAMPLES_DIR}", file=sys.stderr)
        return 1
    pdfs = sorted(URBANE_FOLDER.glob("*.pdf"))
    if not pdfs:
        print(f"ERROR: no Urbane PDF in {URBANE_FOLDER}", file=sys.stderr)
        return 1
    sample = pdfs[-1]

    rows = parse(sample)
    print(f"=== {sample.name}: {len(rows)} rows ===")
    print(f"  Regions: {dict(Counter(r.source_region for r in rows))}")
    print(f"  Statuses: {dict(Counter(r.status for r in rows))}")
    print(f"  Distinct estates: {len(set(r.estate for r in rows))}")
    print(f"  Distinct facades: {dict(Counter(r.facade for r in rows))}")
    notes_count = sum(1 for r in rows if r.meta.get("notes"))
    print(f"  Rows with notes: {notes_count}")
    bbc = sum(1 for r in rows if r.bed and r.bath is not None and r.car is not None)
    print(f"  bed/bath/car parsed: {bbc}/{len(rows)}")
    if rows:
        prices = [r.total_price for r in rows if r.total_price]
        if prices:
            print(f"  Total price range: ${min(prices):,} - ${max(prices):,}")

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
            print(f"    Row {i}: lot {r.lot} {r.street} off by ${d:+,}")
    else:
        print("  All rows: land_price + build_price == total_price.")

    # --- Structural invariants ---
    fails: list[str] = []
    if len(rows) == 0:
        fails.append("zero rows parsed")
    if not all(r.builder == "urbane" for r in rows):
        fails.append("not all rows have builder='urbane'")
    if not all(r.source_file == sample.name for r in rows):
        fails.append("source_file mismatch on some rows")
    for fld in CRITICAL_FIELDS:
        miss = sum(1 for r in rows if not getattr(r, fld))
        if miss > 0:
            fails.append(f"{miss} row(s) missing {fld}")

    bad_regions = {r.source_region for r in rows} - VALID_REGIONS
    if bad_regions:
        fails.append(f"unexpected source_region value(s): {bad_regions}")

    # Urbane has no Status column — parser hardcodes "Available".
    if rows and not all(r.status == "Available" for r in rows):
        fails.append("expected status='Available' on all rows (Urbane has no status column)")

    # Urbane's BED-BATH-CAR cells follow a regular dash-separated format;
    # parse rate should be 100%.
    if bbc != len(rows):
        fails.append(f"bed/bath/car parse rate {bbc}/{len(rows)} != 100%")

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
