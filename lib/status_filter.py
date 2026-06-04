"""
Status filter — decides which rows make it into the morning report.

Loads a DROP-list from config/status-filter.yml. Matching is case-
insensitive against the parsed StocklistRow.status:
  - Empty / None  → KEEP  (treated as implicit Available)
  - In drop list  → DROP
  - Anything else → KEEP  (forward-compatible default)

Parsers preserve raw status casing on the row; this layer only normalises
at lookup, so the original string survives for downstream display.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


def load_drop_list(path: Path) -> set[str]:
    """Read config/status-filter.yml and return drop-list as uppercase set."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    drops = raw.get("drop_if_status_in") or []
    return {str(s).strip().upper() for s in drops if s and str(s).strip()}


def should_keep(status: Optional[str], drop_list: set[str]) -> bool:
    """Return True if a row with this status should appear in the report."""
    if status is None:
        return True
    s = str(status).strip()
    if not s:
        return True
    return s.upper() not in drop_list


if __name__ == "__main__":
    import sys
    from pathlib import Path as _P
    BUNDLE_ROOT = _P(__file__).resolve().parent.parent
    sys.path.insert(0, str(BUNDLE_ROOT))
    drops = load_drop_list(BUNDLE_ROOT / "config" / "status-filter.yml")
    print(f"Drop list ({len(drops)}): {sorted(drops)}")
