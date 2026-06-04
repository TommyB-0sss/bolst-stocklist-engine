"""
Smoke test for Stage 9.8.1 — live Specialised ingest from Tom's Outlook.

Exercises the full live path:
  1. Authenticate as Tom (cached refresh token from .credentials/)
  2. Search Tom's mailbox for the latest Specialised email
  3. Download the PDF attachment to .cache/builder-downloads/specialised/
  4. Run the existing Specialised parser against the live file
  5. Sanity-check parser output (>0 rows, plausible suburb/lot/price coverage)

Usage (from bundle root, with venv active):
    python tests/validate_graph_read_specialised.py

This is the FIRST end-to-end test against Tom's PRODUCTION mailbox. If
Specialised's PDF format has drifted since the April fixture, the parser
will surface errors against today's data. Drift is signal, not failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from dotenv import load_dotenv

load_dotenv(BUNDLE_ROOT / ".env")

from lib.graph_read import IngestError, fetch_latest_for_builder, load_builders_config  # noqa: E402
from lib.parsers.specialised import parse as parse_specialised  # noqa: E402


def main() -> int:
    print("Loading builders.yml...")
    builders_config = load_builders_config(BUNDLE_ROOT)

    print("Fetching latest Specialised stocklist from Tom's Outlook...")
    try:
        pdf_path = fetch_latest_for_builder(
            "specialised", builders_config, bundle_root=BUNDLE_ROOT,
        )
    except IngestError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    size_kb = pdf_path.stat().st_size / 1024
    print(f"  Downloaded: {pdf_path.name} ({size_kb:,.1f} KB)")
    print(f"  Cache path: {pdf_path}")

    print("\nParsing live PDF...")
    rows = parse_specialised(pdf_path)
    print(f"  Parsed: {len(rows)} rows")
    print(f"  Distinct suburbs: {len({r.suburb for r in rows})}")
    print(f"  Distinct estates: {len({r.estate for r in rows})}")
    if rows:
        prices = [r.total_price for r in rows if r.total_price]
        if prices:
            print(f"  Price range: ${min(prices):,} - ${max(prices):,}")

    fails = []
    if len(rows) == 0:
        fails.append("zero rows parsed from live PDF")
    if not any(r.lot for r in rows):
        fails.append("no rows have a lot number")
    if not any(r.suburb for r in rows):
        fails.append("no rows have a suburb")
    if not any(r.total_price for r in rows):
        fails.append("no rows have a total_price")

    print("\n--- Live ingest checks ---")
    if fails:
        print(f"FAIL ({len(fails)} violation(s)):")
        for f in fails:
            print(f"  - {f}")
        return 2
    print(f"PASS - live Specialised ingest works end-to-end ({len(rows)} rows).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
