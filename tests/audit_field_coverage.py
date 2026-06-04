"""
Field-coverage audit across all 6 builder parsers.

Inam asked (2026-05-09): does every row in every sender's data carry an
Address and a complete Bed/Bath/Car? If not, where are the gaps?

This script runs each parser against the live fixtures in
bolst-property-group-data/ and reports per-builder coverage. Read-only.

Usage (from bundle root):
    python tests/audit_field_coverage.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.aplace import parse as parse_aplace          # noqa: E402
from lib.parsers.aldrich import parse as parse_aldrich        # noqa: E402
from lib.parsers.hermitage import parse as parse_hermitage    # noqa: E402
from lib.parsers.luxton import parse as parse_luxton          # noqa: E402
from lib.parsers.specialised import parse as parse_specialised  # noqa: E402
from lib.parsers.urbane import parse as parse_urbane          # noqa: E402

DATA_DIR = BUNDLE_ROOT.parent / "bolst-property-group-data"

SOURCES = [
    ("Aplace",       parse_aplace,      DATA_DIR / "aplacevic@aplace.com.au" / "Aplace-GENERAL-Stock-List.pdf"),
    ("Aplace",       parse_aplace,      DATA_DIR / "aplacevic@aplace.com.au" / "Aplace-Put-Call-Stock-List.pdf"),
    ("Aldrich",      parse_aldrich,     DATA_DIR / "Corey.b@aldrichhomes.com.au" / "Stocklist C44.pdf"),
    ("Hermitage",    parse_hermitage,   DATA_DIR / "houseandland@hermitagehomes.com.au" / "080526.pdf"),
    ("Luxton",       parse_luxton,      DATA_DIR / "stefanc@luxtonhomes.com.au" / "Luxton Homes - HOUSE & LAND STOCKLIST.xlsx"),
    ("Luxton",       parse_luxton,      DATA_DIR / "stefanc@luxtonhomes.com.au" / "Luxton Homes - One Part Contracts.xlsx"),
    ("Luxton",       parse_luxton,      DATA_DIR / "stefanc@luxtonhomes.com.au" / "AGENT - Thornhill Gardens - Superlots.xlsx"),
    ("Specialised",  parse_specialised, DATA_DIR / "nlimbo@specialisedhomeconstructions.com.au" / "Stocklist 28.04.26.pdf"),
    ("Urbane",       parse_urbane,      DATA_DIR / "mikayla+2Esalva=orbithomes.com.au@hubspotfree.hs-send.com" / "Urbane Homes H&L Package Stocklist - April 2026 (24-04) - v001.pdf"),
]


def _has_addr(r) -> bool:
    return bool(r.street and str(r.street).strip())


def _has_bbc(r) -> bool:
    return r.bed is not None and r.bath is not None and r.car is not None


def _row_label(r) -> str:
    src = Path(r.source_file).name if r.source_file else "?"
    return f"lot {r.lot or '?'} | {r.suburb or '?'} | {r.estate or '?'} | {src}"


def main() -> None:
    print("=" * 78)
    print("FIELD-COVERAGE AUDIT — Address (street) + Bed/Bath/Car")
    print("=" * 78)

    by_builder: dict[str, list] = {}
    for builder, parser, path in SOURCES:
        if not path.exists():
            print(f"\n[!] MISSING FIXTURE: {path}")
            continue
        rows = parser(str(path))
        by_builder.setdefault(builder, []).extend(rows)

    print(f"\nTotal rows parsed: {sum(len(v) for v in by_builder.values())}")

    grand_addr_missing = 0
    grand_bbc_missing = 0
    grand_total = 0

    for builder, rows in sorted(by_builder.items()):
        n = len(rows)
        addr_ok = sum(1 for r in rows if _has_addr(r))
        bbc_ok = sum(1 for r in rows if _has_bbc(r))
        addr_miss = [r for r in rows if not _has_addr(r)]
        bbc_miss = [r for r in rows if not _has_bbc(r)]

        grand_addr_missing += len(addr_miss)
        grand_bbc_missing += len(bbc_miss)
        grand_total += n

        print(f"\n--- {builder} ({n} rows) ---")
        print(f"  Address present : {addr_ok}/{n}  ({addr_ok/n:.0%})")
        print(f"  Bed/Bath/Car all: {bbc_ok}/{n}  ({bbc_ok/n:.0%})")

        if addr_miss:
            sources = Counter(Path(r.source_file).name for r in addr_miss if r.source_file)
            print(f"  Address MISSING: {len(addr_miss)} rows, by file: {dict(sources)}")
            for r in addr_miss[:5]:
                print(f"     - {_row_label(r)}")
            if len(addr_miss) > 5:
                print(f"     ... and {len(addr_miss) - 5} more")

        if bbc_miss:
            sources = Counter(Path(r.source_file).name for r in bbc_miss if r.source_file)
            print(f"  Bed/Bath/Car MISSING: {len(bbc_miss)} rows, by file: {dict(sources)}")
            for r in bbc_miss[:5]:
                print(f"     - {_row_label(r)} | bed={r.bed} bath={r.bath} car={r.car}")
            if len(bbc_miss) > 5:
                print(f"     ... and {len(bbc_miss) - 5} more")

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  Total rows               : {grand_total}")
    print(f"  Rows missing Address     : {grand_addr_missing} ({grand_addr_missing/grand_total:.0%})")
    print(f"  Rows missing Bed/Bath/Car: {grand_bbc_missing} ({grand_bbc_missing/grand_total:.0%})")


if __name__ == "__main__":
    main()
