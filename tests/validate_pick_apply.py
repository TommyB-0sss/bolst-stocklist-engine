"""
Validation script for Stage 9.4 (apply_picks → routing precedence).

Verifies that promoting Specialised rows to is_one_part=True actually flows
them into the One Part tab via the existing Stage 7 routing precedence.

Drift-tolerant: uses whatever the live fixture happens to contain.

Usage (from bundle root, with venv active):
    python tests/validate_pick_apply.py

Scenarios:
  1. apply_picks([], picks=[]) → 0 applied
  2. apply_picks(rows, [pick]) → 1 applied; that row now is_one_part=True
  3. After apply, routing puts the picked row in 'one-part-contracts'
  4. Non-Specialised rows are never touched, even if (lot, suburb, estate) collide
  5. A pick that doesn't match any parsed row → 0 applied (caller logs drift)
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.one_part_candidates import get_specialised_candidates  # noqa: E402
from lib.parsers.specialised import parse as parse_specialised  # noqa: E402
from lib.parsers.types import StocklistRow  # noqa: E402
from lib.pick_apply import apply_picks  # noqa: E402
from lib.routing import ONE_PART_REGION_ID, load_config, route  # noqa: E402

SAMPLE = (
    BUNDLE_ROOT.parent
    / "bolst-property-group-data"
    / "nlimbo@specialisedhomeconstructions.com.au"
    / "Stocklist 28.04.26.pdf"
)


def main() -> int:
    if not SAMPLE.exists():
        print(f"ERROR: missing sample {SAMPLE}", file=sys.stderr)
        return 1

    cfg = load_config(BUNDLE_ROOT / "config" / "suburbs.yml")
    candidates = get_specialised_candidates(SAMPLE)
    one_pick = candidates[0].rows[0]
    print(f"Pick under test: Lot {one_pick.lot} {one_pick.suburb} / {one_pick.estate}")

    fails = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal fails
        marker = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"[{marker}] {name}" + (f"  ({detail})" if detail else ""))

    # Scenario 1
    fresh = parse_specialised(SAMPLE)
    n = apply_picks(fresh, [])
    check("1. Empty picks list -> 0 applied", n == 0)

    # Scenario 2
    fresh = parse_specialised(SAMPLE)
    n = apply_picks(fresh, [one_pick])
    promoted = [r for r in fresh if r.is_one_part]
    check(
        f"2. Single pick -> 1 applied, row promoted to is_one_part=True",
        n == 1 and len(promoted) == 1
        and promoted[0].lot == one_pick.lot and promoted[0].suburb == one_pick.suburb,
        f"applied={n}, promoted={len(promoted)}",
    )

    # Scenario 3 — routing precedence
    routed = route(fresh, cfg)
    promoted_routed = [r for r in routed if r.row.is_one_part]
    check(
        "3. Promoted row routes to 'one-part-contracts'",
        len(promoted_routed) == 1
        and promoted_routed[0].region_id == ONE_PART_REGION_ID,
        f"region={promoted_routed[0].region_id if promoted_routed else 'none'}",
    )

    # Scenario 4 — non-Specialised immune
    decoy = StocklistRow(
        builder="aldrich",
        suburb=one_pick.suburb,
        estate=one_pick.estate,
        lot=one_pick.lot,
    )
    fresh = parse_specialised(SAMPLE) + [decoy]
    n = apply_picks(fresh, [one_pick])
    check(
        "4. Non-Specialised row with same (lot,suburb,estate) is NOT promoted",
        decoy.is_one_part is False and n == 1,
        f"decoy.is_one_part={decoy.is_one_part}, applied={n}",
    )

    # Scenario 5 — pick that doesn't exist in this week's data
    ghost = deepcopy(one_pick)
    ghost.lot = "999999"
    fresh = parse_specialised(SAMPLE)
    n = apply_picks(fresh, [ghost])
    check(
        "5. Pick referencing non-existent lot -> 0 applied (drift signal)",
        n == 0,
    )

    print(f"\n--- Scenarios run; failures: {fails} ---")
    return 0 if fails == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
