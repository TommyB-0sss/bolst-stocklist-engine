"""
Validation script for the Stage 9.3 pick parser.

Runs through 8 reply scenarios against the live Specialised candidate set
and asserts the parser handles each correctly. Drift-tolerant: scenarios
are described in terms of the parser's behavior, not absolute row counts.

Usage (from bundle root, with venv active):
    python tests/validate_pick_parser.py

Each scenario prints PASS / FAIL with details. Exit code 0 = all pass,
2 = at least one failure.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.one_part_candidates import get_specialised_candidates  # noqa: E402
from lib.pick_parser import parse_picks  # noqa: E402

SAMPLE = (
    BUNDLE_ROOT.parent
    / "bolst-property-group-data"
    / "nlimbo@specialisedhomeconstructions.com.au"
    / "Stocklist 28.04.26.pdf"
)


def _find_two_unique_lots(candidates) -> list[tuple[str, str]]:
    """Return [(lot, suburb), (lot, suburb)] for two distinct lots that each appear in exactly one row."""
    counts = Counter()
    sample = {}
    for g in candidates:
        for r in g.rows:
            if r.lot:
                counts[r.lot] += 1
                sample[r.lot] = (r.lot, r.suburb)
    uniq = [sample[lot] for lot, n in counts.items() if n == 1]
    if len(uniq) < 2:
        raise RuntimeError("need at least two unique-lot rows in fixture")
    return uniq[:2]


def _find_dup_lot(candidates) -> tuple[str, list[str]]:
    """Return (lot, [suburb1, suburb2, ...]) for a lot that appears in multiple rows."""
    by_lot: dict[str, list[str]] = {}
    for g in candidates:
        for r in g.rows:
            if r.lot and r.suburb:
                by_lot.setdefault(r.lot, []).append(r.suburb)
    for lot, subs in by_lot.items():
        if len(set(subs)) > 1:
            return lot, sorted(set(subs))
    raise RuntimeError("no ambiguous-lot row in fixture")


def main() -> int:
    if not SAMPLE.exists():
        print(f"ERROR: missing sample {SAMPLE}", file=sys.stderr)
        return 1

    candidates = get_specialised_candidates(SAMPLE)
    two_uniques = _find_two_unique_lots(candidates)
    uniq_lot, uniq_suburb = two_uniques[0]
    other_uniq_lot, other_uniq_suburb = two_uniques[1]
    dup_lot, dup_suburbs = _find_dup_lot(candidates)

    scenarios = [
        (
            "1. Empty reply -> 0 picks, 0 unresolved",
            "",
            lambda r: len(r.picks) == 0 and len(r.unresolved) == 0,
        ),
        (
            "2. Whitespace-only reply -> 0 picks, 0 unresolved",
            "   \n\n  ",
            lambda r: len(r.picks) == 0 and len(r.unresolved) == 0,
        ),
        (
            "3. No 'Lot N' tokens -> 0 picks, 0 unresolved",
            "Hi Inam, just confirming you got my message yesterday.",
            lambda r: len(r.picks) == 0 and len(r.unresolved) == 0,
        ),
        (
            f"4. Single unique lot bare ('Lot {uniq_lot}') -> 1 pick",
            f"Lot {uniq_lot}",
            lambda r: len(r.picks) == 1
            and r.picks[0].lot == uniq_lot
            and len(r.unresolved) == 0,
        ),
        (
            f"5. Two unique lots with suburbs ('Lot {uniq_lot} {uniq_suburb}, "
            f"Lot {other_uniq_lot} {other_uniq_suburb}') -> 2 picks",
            f"Lot {uniq_lot} {uniq_suburb}, Lot {other_uniq_lot} {other_uniq_suburb}",
            lambda r: len(r.picks) == 2
            and {p.lot for p in r.picks} == {uniq_lot, other_uniq_lot}
            and len(r.unresolved) == 0,
        ),
        (
            f"6. Ambiguous lot bare ('Lot {dup_lot}') -> 0 picks, 1 unresolved (ambiguity)",
            f"Lot {dup_lot}",
            lambda r: len(r.picks) == 0
            and len(r.unresolved) == 1
            and "ambiguous" in r.unresolved[0].lower(),
        ),
        (
            f"7. Ambiguous lot disambiguated by suburb ('Lot {dup_lot} {dup_suburbs[0]}') -> 1 pick",
            f"Lot {dup_lot} {dup_suburbs[0]}",
            lambda r: len(r.picks) == 1
            and r.picks[0].lot == dup_lot
            and r.picks[0].suburb == dup_suburbs[0]
            and len(r.unresolved) == 0,
        ),
        (
            "8. Lot not in stocklist -> 0 picks, 1 unresolved",
            "Lot 99999 Atlantis",
            lambda r: len(r.picks) == 0
            and len(r.unresolved) == 1
            and "not in this week" in r.unresolved[0].lower(),
        ),
        (
            f"9. Greeting + signature noise around real picks ('Lot {uniq_lot} {uniq_suburb}') -> 1 pick",
            f"Hi Inam,\n\nLet's go with Lot {uniq_lot} {uniq_suburb} for tomorrow.\n\nThanks,\nTom\n--\nTom Bolst | Director",
            lambda r: len(r.picks) == 1
            and r.picks[0].lot == uniq_lot
            and len(r.unresolved) == 0,
        ),
        (
            f"10. Same lot mentioned twice -> deduped to 1 pick",
            f"Lot {uniq_lot} {uniq_suburb}, Lot {uniq_lot} {uniq_suburb}",
            lambda r: len(r.picks) == 1 and len(r.unresolved) == 0,
        ),
    ]

    fails = 0
    print(f"=== Pick parser scenarios ({len(scenarios)} total) ===\n")
    print(f"  Fixture: {SAMPLE.name}")
    print(f"  Unique-lot probe:    Lot {uniq_lot} ({uniq_suburb})")
    print(f"  Other-unique probe:  Lot {other_uniq_lot} ({other_uniq_suburb})")
    print(f"  Ambiguous-lot probe: Lot {dup_lot} (in {dup_suburbs})\n")

    for name, reply, check in scenarios:
        result = parse_picks(reply, candidates)
        ok = check(result)
        marker = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"[{marker}] {name}")
        if not ok:
            print(f"        reply={reply!r}")
            print(f"        picks={[(p.lot, p.suburb) for p in result.picks]}")
            print(f"        unresolved={result.unresolved}")

    print(f"\n--- {len(scenarios) - fails}/{len(scenarios)} pass ---")
    return 0 if fails == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
