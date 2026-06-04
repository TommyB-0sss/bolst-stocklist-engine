"""
Validation script for the Aplace parser.

Usage (from bundle root, with venv active):
    python tests/validate_aplace.py

Tests STRUCTURAL invariants only — does not assert specific row counts,
status values, or estate names that drift as Aplace updates their weekly
PDFs. Fixtures should be refreshed periodically by re-downloading from
the cmail19 tracking links (see builders.yml).
"""

from __future__ import annotations

import sys
import re
from collections import Counter
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.aplace import parse  # noqa: E402

SAMPLES_DIR = BUNDLE_ROOT.parent / "bolst-property-group-data" / "aplacevic@aplace.com.au"
GENERAL_FILE = SAMPLES_DIR / "Aplace-GENERAL-Stock-List.pdf"
PUTCALL_FILE = SAMPLES_DIR / "Aplace-Put-Call-Stock-List.pdf"

CRITICAL_FIELDS = ("suburb", "lot", "total_price", "home_design")
REGION_PATTERN = re.compile(r"^Victoria(?:\s*-\s*[\w &,]+)?$")


def _summarise(label: str, rows: list) -> None:
    print(f"\n=== {label}: {len(rows)} rows ===")
    print(f"  Regions: {dict(Counter(r.source_region for r in rows))}")
    print(f"  Statuses: {dict(Counter(r.status for r in rows))}")
    print(f"  Distinct estates: {len(set(r.estate for r in rows))}")
    bbc = sum(1 for r in rows if r.bed and r.bath is not None and r.car is not None)
    print(f"  bed/bath/car parsed: {bbc}/{len(rows)}")
    if rows:
        prices = [r.total_price for r in rows if r.total_price]
        if prices:
            print(f"  Total price range: ${min(prices):,} - ${max(prices):,}")


def _check_invariants(label: str, rows: list, source_file: str) -> list[str]:
    """Return list of structural-invariant violations (empty list = pass)."""
    fails = []
    if len(rows) == 0:
        fails.append(f"{label}: zero rows parsed")
        return fails

    if not all(r.builder == "aplace" for r in rows):
        fails.append(f"{label}: not all rows have builder='aplace'")
    if not all(r.source_file == source_file for r in rows):
        fails.append(f"{label}: source_file mismatch on some rows")

    for fld in CRITICAL_FIELDS:
        miss = sum(1 for r in rows if not getattr(r, fld))
        if miss > 0:
            fails.append(f"{label}: {miss} row(s) missing {fld}")

    # Region label, when present, must match Aplace's "Victoria - <area>" pattern.
    bad_regions = [r.source_region for r in rows
                   if r.source_region and not REGION_PATTERN.match(r.source_region)]
    if bad_regions:
        fails.append(f"{label}: {len(bad_regions)} region label(s) don't match "
                     f"'Victoria - <area>' pattern (samples: {set(bad_regions[:3])})")

    return fails


def main() -> int:
    fails: list[str] = []
    for f in (GENERAL_FILE, PUTCALL_FILE):
        if not f.exists():
            print(f"ERROR: missing sample {f}", file=sys.stderr)
            return 1

    general = parse(GENERAL_FILE)
    putcall = parse(PUTCALL_FILE)
    _summarise("GENERAL", general)
    _summarise("Put-Call", putcall)

    fails.extend(_check_invariants("GENERAL", general, GENERAL_FILE.name))
    fails.extend(_check_invariants("Put-Call", putcall, PUTCALL_FILE.name))

    print("\n--- Structural checks ---")
    if fails:
        print(f"FAIL ({len(fails)} violation(s)):")
        for f in fails:
            print(f"  - {f}")
        return 2
    print(f"PASS - {len(general) + len(putcall)} rows parse cleanly across both files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
