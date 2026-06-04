"""
Smoke test for Stage 9.8.6 — live Luxton ingest via MailChimp -> Google Sheets.

Luxton's MailChimp newsletters carry "1 Part Sock List - Click" and
"2 Part Stock List - Click" buttons. Each is a MailChimp tracking URL
that 302-redirects to a public Google Sheet. We follow the redirect,
extract the sheet ID, and download via /export?format=xlsx.

Usage (from bundle root, with venv active):
    python tests/validate_graph_read_luxton.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from dotenv import load_dotenv

load_dotenv(BUNDLE_ROOT / ".env")

from lib.graph_read import IngestError, fetch_all_for_builder, load_builders_config  # noqa: E402
from lib.parsers.luxton import parse as parse_luxton  # noqa: E402


def main() -> int:
    builders_config = load_builders_config(BUNDLE_ROOT)

    print("Fetching all Luxton stocklists via MailChimp -> Google Sheets...")
    try:
        paths = fetch_all_for_builder(
            "luxton", builders_config, bundle_root=BUNDLE_ROOT,
        )
    except IngestError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"Got {len(paths)} XLSX file(s):")
    fails: list[str] = []

    for path in paths:
        size_kb = path.stat().st_size / 1024
        print(f"\n  - {path.name} ({size_kb:,.1f} KB)")
        rows = parse_luxton(path)
        print(f"    Parsed: {len(rows)} rows")
        print(f"    is_one_part rows: {sum(1 for r in rows if r.is_one_part)}")
        if len(rows) == 0:
            fails.append(f"{path.name}: 0 rows parsed")

    if len(paths) < 2:
        fails.append(f"expected 2 XLSX files (1 Part + 2 Part), got {len(paths)}")

    print("\n--- Live Luxton ingest checks ---")
    if fails:
        print(f"FAIL ({len(fails)} violation(s)):")
        for f in fails:
            print(f"  - {f}")
        return 2
    total_rows = sum(len(parse_luxton(p)) for p in paths)
    print(f"PASS - {len(paths)} Luxton XLSX ingested live, {total_rows} total rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
