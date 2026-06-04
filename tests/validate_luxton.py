"""
Validation script for the Luxton parser.

Usage (from bundle root, with venv active):
    python tests/validate_luxton.py

Tests STRUCTURAL invariants across all 3 Luxton XLSX modes (House & Land,
One Part Contracts, Superlots). Fixtures are snapshots of Stefan's live
Google Sheets and should be refreshed periodically by re-downloading via
the export?format=xlsx URL pattern. Stefan can clean up status casing,
typos, and row counts at any time — those things are not asserted here.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.luxton import parse  # noqa: E402

SAMPLES_DIR = BUNDLE_ROOT.parent / "bolst-property-group-data" / "stefanc@luxtonhomes.com.au"
HL_FILE = SAMPLES_DIR / "Luxton Homes - HOUSE & LAND STOCKLIST.xlsx"
OP_FILE = SAMPLES_DIR / "Luxton Homes - One Part Contracts.xlsx"
SL_FILE = SAMPLES_DIR / "AGENT - Thornhill Gardens - Superlots.xlsx"

CRITICAL_HL = ("suburb", "lot", "estate", "home_design", "status")  # total_price may be missing if Stefan leaves cells blank
CRITICAL_OP = ("suburb", "lot", "estate", "home_design", "total_price")  # status may be None occasionally
CRITICAL_SL = ("suburb", "lot", "estate", "home_design", "total_price", "status")
ARITHMETIC_TOLERANCE = 5


def _summarise(label: str, rows: list) -> None:
    print(f"\n=== {label}: {len(rows)} rows ===")
    print(f"  Statuses: {dict(Counter(r.status for r in rows))}")
    print(f"  Regions: {dict(Counter(r.source_region for r in rows))}")
    print(f"  Distinct estates: {len(set(r.estate for r in rows))}")
    print(f"  is_one_part rows: {sum(1 for r in rows if r.is_one_part)}")
    if rows:
        prices = [r.total_price for r in rows if r.total_price]
        if prices:
            print(f"  Total price range: ${min(prices):,} - ${max(prices):,}")


def _check_critical(label: str, rows: list, fields: tuple) -> list[str]:
    fails = []
    for fld in fields:
        miss = sum(1 for r in rows if not getattr(r, fld))
        if miss > 0:
            fails.append(f"{label}: {miss} row(s) missing {fld}")
    return fails


def main() -> int:
    for f in (HL_FILE, OP_FILE, SL_FILE):
        if not f.exists():
            print(f"ERROR: missing sample {f}", file=sys.stderr)
            return 1

    hl = parse(HL_FILE)
    op = parse(OP_FILE)
    sl = parse(SL_FILE)
    _summarise("House & Land", hl)
    _summarise("One Part Contracts", op)
    _summarise("Superlots", sl)

    fails: list[str] = []

    # --- Cross-file invariants ---
    if not all(r.builder == "luxton" for r in hl + op + sl):
        fails.append("not all rows have builder='luxton'")

    # Per-file structural invariants
    if len(hl) == 0:
        fails.append("House & Land: zero rows parsed")
    if any(r.is_one_part for r in hl):
        fails.append("House & Land: is_one_part=True leaked from this file")
    if any(r.source_file != HL_FILE.name for r in hl):
        fails.append("House & Land: source_file mismatch on some rows")
    fails.extend(_check_critical("House & Land", hl, CRITICAL_HL))

    if len(op) == 0:
        fails.append("One Part: zero rows parsed")
    if not all(r.is_one_part for r in op):
        n = sum(1 for r in op if not r.is_one_part)
        fails.append(f"One Part: {n} row(s) missing is_one_part=True")
    if any(r.land_price for r in op):
        fails.append("One Part: land_price unexpectedly populated (file has no LAND $ column)")
    if any(r.build_price for r in op):
        fails.append("One Part: build_price unexpectedly populated")
    if any(r.source_file != OP_FILE.name for r in op):
        fails.append("One Part: source_file mismatch on some rows")
    fails.extend(_check_critical("One Part", op, CRITICAL_OP))

    if len(sl) == 0:
        fails.append("Superlots: zero rows parsed")
    if not all(r.meta.get("superlot") is True for r in sl):
        fails.append("Superlots: meta['superlot']=True missing on some rows")
    if any(r.is_one_part for r in sl):
        fails.append("Superlots: is_one_part=True leaked from this file")
    if any(r.source_file != SL_FILE.name for r in sl):
        fails.append("Superlots: source_file mismatch on some rows")
    fails.extend(_check_critical("Superlots", sl, CRITICAL_SL))
    sl_bbc = sum(1 for r in sl if r.bed and r.bath is not None and r.car is not None)
    if sl_bbc != len(sl):
        fails.append(f"Superlots: B.L.B.G. parse rate {sl_bbc}/{len(sl)} != 100%")

    # --- House & Land arithmetic (informational) ---
    arith_issues = []
    for i, r in enumerate(hl):
        if r.land_price is None or r.build_price is None or r.total_price is None:
            continue
        delta = (r.land_price + r.build_price) - r.total_price
        if abs(delta) > ARITHMETIC_TOLERANCE:
            arith_issues.append((i, r, delta))
    if arith_issues:
        print(f"\n  WARN House & Land: {len(arith_issues)} arithmetic mismatch(es):")
        for i, r, d in arith_issues[:5]:
            print(f"    Row {i}: lot {r.lot} {r.estate} off by ${d:+,}")
    else:
        print("\n  House & Land: all populated rows have land + build == total.")

    # Surface H&L rows missing total_price (data quality, not failure)
    hl_no_total = sum(1 for r in hl if r.total_price is None)
    if hl_no_total:
        print(f"  WARN House & Land: {hl_no_total} row(s) missing total_price (Stefan source).")

    print("\n--- Structural checks ---")
    if fails:
        print(f"FAIL ({len(fails)} violation(s)):")
        for f in fails:
            print(f"  - {f}")
        return 2
    print(f"PASS - {len(hl) + len(op) + len(sl)} rows parse cleanly across 3 files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
