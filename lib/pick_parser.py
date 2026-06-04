"""
Stage 9.3 - Parse Tom's reply to the 16:00 evening prompt.

Input:  the plain-text body of Tom's reply email + the candidate set we sent
        him (so we can disambiguate suggested-suburb against the actual
        candidate suburbs).

Output: PickResult with `picks` (list of StocklistRow that should land in
        the One Part tab) and `unresolved` (list of human-readable reasons
        for any "Lot X" mentions that we couldn't confidently match - these
        feed Stage 9.5's banner).

Reply format we ask Tom to use (set in the evening prompt body):

    Lot 17 Elliminyt, Lot 205 Thornhill Park

Why suburbs are required: lot numbers are NOT unique across the Specialised
stocklist. This week's data has 5 lot numbers that appear in two different
estates each (e.g. Lot 42 in both Benalla/Stablewood and Newborough/Narracan
Waters). A bare "Lot 42" can't be disambiguated.

Resolution rules:
  1. For each `Lot N` mention, look at the chars between it and the next
     `Lot N` (or end of message) - call this the "tail".
  2. Find candidates where row.lot == N. Three cases:
       a. zero candidates  → unresolved ("Lot N not in this week's stocklist")
       b. one candidate    → matched (suburb in tail is bonus, not required)
       c. >1 candidates    → must disambiguate by suburb name appearing in
                             tail (case-insensitive). If none / multiple
                             match → unresolved.
  3. The reply may include extra text (greetings, signatures, sales chatter).
     Anything that isn't a `Lot N` match is ignored.
  4. If Tom replies multiple times on the thread, the caller passes only the
     most recent reply (per locked architecture: most-recent-reply-wins).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .one_part_candidates import CandidateGroup
from .parsers.types import StocklistRow

LOT_RE = re.compile(r"\bLot\s+(\d+)\b", re.IGNORECASE)


@dataclass
class PickResult:
    picks: list[StocklistRow] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def parse_picks(reply_text: str, candidates: list[CandidateGroup]) -> PickResult:
    result = PickResult()
    if not reply_text or not reply_text.strip():
        return result

    by_lot: dict[str, list[StocklistRow]] = {}
    for group in candidates:
        for row in group.rows:
            if row.lot:
                by_lot.setdefault(row.lot, []).append(row)

    matches = list(LOT_RE.finditer(reply_text))
    if not matches:
        return result

    seen_keys: set[tuple[str, str]] = set()

    for i, m in enumerate(matches):
        lot = m.group(1)
        tail_start = m.end()
        tail_end = matches[i + 1].start() if i + 1 < len(matches) else len(reply_text)
        tail = reply_text[tail_start:tail_end].lower()

        rows = by_lot.get(lot, [])
        if not rows:
            result.unresolved.append(f"Lot {lot} not in this week's stocklist")
            continue

        if len(rows) == 1:
            row = rows[0]
            key = (row.lot or "", row.suburb or "")
            if key not in seen_keys:
                result.picks.append(row)
                seen_keys.add(key)
            continue

        suburb_hits = [r for r in rows if r.suburb and r.suburb.lower() in tail]
        if len(suburb_hits) == 1:
            row = suburb_hits[0]
            key = (row.lot or "", row.suburb or "")
            if key not in seen_keys:
                result.picks.append(row)
                seen_keys.add(key)
        elif len(suburb_hits) == 0:
            suburbs_in_play = ", ".join(sorted({r.suburb or "?" for r in rows}))
            result.unresolved.append(
                f"Lot {lot} is ambiguous - appears in {suburbs_in_play}; "
                f"reply with a suburb to disambiguate"
            )
        else:
            hit_suburbs = ", ".join(sorted({r.suburb or "?" for r in suburb_hits}))
            result.unresolved.append(
                f"Lot {lot} matched multiple suburbs in your reply ({hit_suburbs}) - "
                f"please send one Lot per pick"
            )

    return result
