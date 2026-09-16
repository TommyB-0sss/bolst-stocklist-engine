"""
Diagnostic: show every row that would NOT land in a cover region today.

Runs the same ingest + route pipeline as the morning report (cached
downloads are reused, so this is cheap after a report run) and prints:

  * builder rows routed to 'uncategorised', with builder, raw suburb,
    normalised suburb and the routing reason;
  * REA listings whose suburb has no region mapping (the 'bolst-extra'
    fallback), grouped by suburb.

Read-only. Nothing is rendered or sent.

Usage (from bundle root, venv active, working Graph auth):
    python tests/dump_routing.py
"""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter, defaultdict
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.routing import load_config, route, _normalise_suburb  # noqa: E402
from lib.status_filter import load_drop_list, should_keep     # noqa: E402


def _load_send_report():
    """Import skills/compose-and-send/send_report.py (hyphenated dir)."""
    path = BUNDLE_ROOT / "skills" / "compose-and-send" / "send_report.py"
    spec = importlib.util.spec_from_file_location("send_report", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    sr = _load_send_report()
    cfg = load_config(BUNDLE_ROOT / "config" / "suburbs.yml")
    drops = load_drop_list(BUNDLE_ROOT / "config" / "status-filter.yml")

    print("Ingesting builders (cache reused where present)...")
    all_rows, failed = sr._ingest_all_builders()
    print(f"  {len(all_rows)} rows; failed builders: {failed or 'none'}")

    routed = route(all_rows, cfg)
    kept = [r for r in routed if should_keep(r.row.status, drops)]
    unc = [r for r in kept if r.region_id == "uncategorised"]
    print(f"\n=== Builder rows uncategorised (after status filter): {len(unc)} ===")
    for r in unc:
        row = r.row
        print(f"  builder={row.builder!r:14} suburb={row.suburb!r:32} "
              f"norm={_normalise_suburb(row.suburb)!r:24} "
              f"estate={getattr(row, 'estate', '')!r:28} lot={getattr(row, 'lot', '')!r} "
              f"reason={r.routing_reason}")

    print("\nIngesting REA listings...")
    listings, rea_err = sr._ingest_rea_listings()
    print(f"  {len(listings)} listings; error: {rea_err or 'none'}")
    extra: dict[str, list] = defaultdict(list)
    for L in listings:
        norm = _normalise_suburb(L.suburb)
        canonical = cfg.suburb_aliases.get(norm, norm)
        if norm and canonical not in cfg.suburb_to_region:
            extra[L.suburb].append(L)
    print(f"\n=== REA listings with no region mapping: "
          f"{sum(len(v) for v in extra.values())} in {len(extra)} suburb(s) ===")
    for suburb, ls in sorted(extra.items()):
        print(f"  {suburb!r:20} x{len(ls)}  e.g. {ls[0].address!r}")

    print("\nRegion tally (builder rows kept):",
          dict(Counter(r.region_id for r in kept)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
