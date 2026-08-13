"""
Pre-flight suburb audit (one-shot, run from bundle root).

Pulls today's live data from Tom's Outlook for:
  - Bolst REA listings (subject "REA CSV" -> "REA Listings.csv" attachment)
  - All 6 builder stocklists (via fetch_all_for_builder)
Then routes every unique suburb through config/suburbs.yml and reports
which ones do NOT resolve to one of the 10 canonical regions.

Why this exists: surfaces how many "bolst-extra" per-suburb sections the
upcoming A.1 layout change will produce, before we commit to the design.

Usage:
    .venv\\Scripts\\python.exe tests\\audit_suburbs.py
"""

from __future__ import annotations

import sys
import traceback
from collections import defaultdict
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from dotenv import load_dotenv

load_dotenv(BUNDLE_ROOT / ".env")

from lib.auth import get_access_token  # noqa: E402
from lib.graph_read import (  # noqa: E402
    _default_cache_dir, _try_sender_for_attachment, fetch_all_for_builder,
    load_builders_config,
)
from lib.builder_roster import PARSERS  # noqa: E402
from lib.parsers.rea_ignite import parse as parse_rea  # noqa: E402
from lib.routing import _normalise_suburb, load_config  # noqa: E402

# PARSERS comes from lib/builder_roster.py — this script used to keep its own
# copy, which drifted to 6 builders and reported "all suburbs map cleanly" for
# builders it had never loaded.


def _fetch_rea_csv() -> Path:
    """Download the latest 'REA Listings.csv' from Tom's own mailbox."""
    token = get_access_token()
    cache_dir = _default_cache_dir(BUNDLE_ROOT, "rea")
    path = _try_sender_for_attachment(
        token=token,
        sender="tom@bolstpropertygroup.com.au",
        patterns=["REA*.csv"],
        subject_filter="REA CSV",
        cache_dir=cache_dir,
        skip_cache=False,
    )
    if path is None:
        raise RuntimeError("REA Listings.csv not found in Tom's recent mail")
    return path


def _audit_one_source(
    name: str,
    suburbs: list[str],
    config,
) -> tuple[int, dict[str, int]]:
    """Return (mapped_count, unmapped_counter)."""
    mapped = 0
    unmapped: dict[str, int] = defaultdict(int)
    for raw in suburbs:
        norm = _normalise_suburb(raw)
        if not norm:
            unmapped["(empty)"] += 1
            continue
        canonical = config.suburb_aliases.get(norm, norm)
        region_id = config.suburb_to_region.get(canonical)
        if region_id:
            mapped += 1
        else:
            unmapped[raw] += 1
    return mapped, dict(unmapped)


def main() -> int:
    config = load_config(BUNDLE_ROOT / "config" / "suburbs.yml")
    print(f"Loaded suburbs.yml: {len(config.suburb_to_region)} suburbs across "
          f"{len(config.region_ids)} regions.\n")

    # ---- REA ----
    print("=" * 70)
    print("REA LISTINGS (Bolst's own REA Active Listings CSV)")
    print("=" * 70)
    try:
        rea_path = _fetch_rea_csv()
        print(f"Downloaded: {rea_path}")
        listings = parse_rea(rea_path)
        rea_suburbs = [L.suburb for L in listings]
        mapped, unmapped = _audit_one_source("rea", rea_suburbs, config)
        print(f"Rows: {len(listings)}  Mapped: {mapped}  "
              f"Unmapped: {sum(unmapped.values())}")
        if unmapped:
            print("Unmapped suburbs (raw -> count):")
            for s, c in sorted(unmapped.items(), key=lambda kv: -kv[1]):
                print(f"  {s!r:30s}  x {c}")
        else:
            print("All REA suburbs map cleanly.")
    except Exception:
        traceback.print_exc()
        print("REA fetch/parse failed - continuing with builders.")

    # ---- 6 builders ----
    builders_cfg = load_builders_config(BUNDLE_ROOT)
    builder_unmapped: dict[str, dict[str, int]] = {}
    for builder_id, parser in PARSERS.items():
        print()
        print("=" * 70)
        print(f"BUILDER: {builder_id}")
        print("=" * 70)
        try:
            paths = fetch_all_for_builder(builder_id, builders_cfg,
                                          bundle_root=BUNDLE_ROOT)
            all_rows = []
            for p in paths:
                all_rows.extend(parser(p))
            suburbs = [r.suburb for r in all_rows]
            mapped, unmapped = _audit_one_source(builder_id, suburbs, config)
            print(f"Files: {len(paths)}  Rows: {len(all_rows)}  "
                  f"Mapped: {mapped}  Unmapped: {sum(unmapped.values())}")
            if unmapped:
                builder_unmapped[builder_id] = unmapped
                print("Unmapped suburbs (raw -> count):")
                for s, c in sorted(unmapped.items(), key=lambda kv: -kv[1]):
                    print(f"  {s!r:30s}  x {c}")
            else:
                print("All suburbs map cleanly.")
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")

    # ---- Summary ----
    print()
    print("=" * 70)
    print("SUMMARY: distinct unmapped suburbs across all live sources")
    print("=" * 70)
    distinct = defaultdict(list)  # raw_suburb -> [source_ids]
    if 'unmapped' in locals():
        # REA case (last value of `unmapped` from REA block could be wrong if
        # REA succeeded; re-derive from per-source dicts)
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
