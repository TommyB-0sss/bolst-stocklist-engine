"""
Smoke test for Stage 9.8.4 — live Hermitage ingest via html_link / url_template.

Hermitage is the first builder to exercise html_link ingestion. Their
HubSpot newsletter has no attachment; the PDF lives at a predictable URL
on the hubfs CDN: hubfs/6368574/{DDMMYY}.pdf, where DDMMYY is the email's
receivedDateTime.

Usage (from bundle root, with venv active):
    python tests/validate_graph_read_hermitage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from dotenv import load_dotenv

load_dotenv(BUNDLE_ROOT / ".env")

from lib.graph_read import IngestError, fetch_latest_for_builder, load_builders_config  # noqa: E402
from lib.parsers.hermitage import parse as parse_hermitage  # noqa: E402


def main() -> int:
    builders_config = load_builders_config(BUNDLE_ROOT)

    print("Fetching latest Hermitage stocklist via url_template...")
    try:
        path = fetch_latest_for_builder(
            "hermitage", builders_config, bundle_root=BUNDLE_ROOT,
        )
    except IngestError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    size_kb = path.stat().st_size / 1024
    print(f"  Downloaded: {path.name} ({size_kb:,.1f} KB)")
    print(f"  Cache path: {path}")

    print("\nParsing live PDF...")
    rows = parse_hermitage(path)
    print(f"  Parsed: {len(rows)} rows")
    print(f"  Distinct suburbs: {len({r.suburb for r in rows})}")
    print(f"  Distinct estates: {len({r.estate for r in rows})}")
    one_part = sum(1 for r in rows if r.is_one_part)
    print(f"  Auto-flagged is_one_part=True rows: {one_part}")

    fails: list[str] = []
    if len(rows) == 0:
        fails.append("zero rows parsed from live Hermitage PDF")
    if not any(r.lot for r in rows):
        fails.append("no rows have a lot number")

    print("\n--- Live Hermitage ingest checks ---")
    if fails:
        print(f"FAIL ({len(fails)} violation(s)):")
        for f in fails:
            print(f"  - {f}")
        return 2
    print(f"PASS - live Hermitage ingest works end-to-end ({len(rows)} rows).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
