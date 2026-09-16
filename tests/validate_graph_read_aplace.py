"""
Smoke test for Stage 9.8.5 — live Aplace ingest via html_link / button-extract.

Aplace ships TWO PDFs per email via Campaign Monitor (cmail19) tracking
links:
  - "Download – Victoria Stocklist"            (regional)
  - "Download – 100% Upfront commission stocklist" (Put-Call → one_part)

Exercises fetch_all_for_builder (returns list[Path]) and the new HTML
button-extract path in graph_read.

Usage (from bundle root, with venv active):
    python tests/validate_graph_read_aplace.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from dotenv import load_dotenv

load_dotenv(BUNDLE_ROOT / ".env")

from lib.graph_read import IngestError, fetch_all_for_builder, load_builders_config  # noqa: E402
from lib.parsers.aplace import parse as parse_aplace  # noqa: E402


def main() -> int:
    builders_config = load_builders_config(BUNDLE_ROOT)

    print("Fetching all Aplace stocklists via button-extract...")
    try:
        paths = fetch_all_for_builder(
            "aplace", builders_config, bundle_root=BUNDLE_ROOT,
        )
    except IngestError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"Got {len(paths)} file(s):")
    fails: list[str] = []

    for path in paths:
        size_kb = path.stat().st_size / 1024
        print(f"\n  - {path.name} ({size_kb:,.1f} KB)")
        rows = parse_aplace(path)
        print(f"    Parsed: {len(rows)} rows / "
              f"{len({r.suburb for r in rows})} suburbs / "
              f"{len({r.estate for r in rows})} estates")
        if len(rows) == 0:
            fails.append(f"{path.name}: 0 rows parsed")

    # 2026-09-16: the "100% Upfront commission" button is marked optional in
    # builders.yml (Aplace stopped publishing it in late July 2026), so one
    # PDF is a valid live result. Two means it has come back.
    if len(paths) < 1:
        fails.append(f"expected at least the Victoria Stocklist PDF, got {len(paths)}")
    victoria = [p for p in paths if "Victoria" in p.name]
    if not victoria:
        fails.append("Victoria Stocklist PDF (the required button) was not among the results")

    print("\n--- Live Aplace ingest checks ---")
    if fails:
        print(f"FAIL ({len(fails)} violation(s)):")
        for f in fails:
            print(f"  - {f}")
        return 2
    total_rows = sum(len(parse_aplace(p)) for p in paths)
    print(f"PASS - {len(paths)} Aplace PDF(s) ingested live, {total_rows} total rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
