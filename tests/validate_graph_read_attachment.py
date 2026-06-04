"""
Smoke test for Stage 9.8.3 — live ingest for all 3 attachment-mode builders.

Runs the full live path for Specialised + Aldrich + Urbane, exercising:
  - basic sender search (Specialised)
  - subject_filter (Aldrich — Corey sends per-package emails too)
  - secondary_senders fallback (Urbane — Tyana primary, Mikayla/HubSpot fallback)

Each builder fetches live from Tom's Outlook, parses the file, and prints
row counts. Fails on any builder that can't ingest or produces 0 rows.

Usage (from bundle root, with venv active):
    python tests/validate_graph_read_attachment.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from dotenv import load_dotenv

load_dotenv(BUNDLE_ROOT / ".env")

from lib.graph_read import IngestError, fetch_latest_for_builder, load_builders_config  # noqa: E402
from lib.parsers.aldrich import parse as parse_aldrich              # noqa: E402
from lib.parsers.specialised import parse as parse_specialised      # noqa: E402
from lib.parsers.urbane import parse as parse_urbane                # noqa: E402

PARSERS = {
    "specialised": parse_specialised,
    "aldrich": parse_aldrich,
    "urbane": parse_urbane,
}


def main() -> int:
    builders_config = load_builders_config(BUNDLE_ROOT)
    fails: list[str] = []

    for builder_id, parser in PARSERS.items():
        print(f"\n=== {builder_id.upper()} ===")
        try:
            path = fetch_latest_for_builder(
                builder_id, builders_config, bundle_root=BUNDLE_ROOT,
            )
        except IngestError as e:
            print(f"  FAIL: {e}")
            fails.append(f"{builder_id}: ingest failed - {e}")
            continue
        size_kb = path.stat().st_size / 1024
        print(f"  Downloaded: {path.name} ({size_kb:,.1f} KB)")
        rows = parser(path)
        print(f"  Parsed: {len(rows)} rows / "
              f"{len({r.suburb for r in rows})} suburbs / "
              f"{len({r.estate for r in rows})} estates")
        if len(rows) == 0:
            fails.append(f"{builder_id}: parser returned 0 rows from live file")

    print(f"\n--- {len(PARSERS) - len(fails)}/{len(PARSERS)} attachment builders OK ---")
    if fails:
        for f in fails:
            print(f"  - {f}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
