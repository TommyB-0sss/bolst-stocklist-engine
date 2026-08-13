"""
Single source of truth for the builder roster.

WHY THIS MODULE EXISTS: this dict used to be hand-copied into three separate
files — skills/compose-and-send/send_report.py, tests/audit_suburbs.py and
skills/render-bolst-pdf/render_local.py. Adding a builder meant remembering all
three, and forgetting one failed SILENTLY: on 2026-08-06 the audit script was
still on 6 builders and cheerfully reported "all suburbs map cleanly" for two
builders it had never loaded, while the production report had already ingested
them. Import PARSERS from here instead of rebuilding it.

`rea` is deliberately NOT in this roster. It is Bolst's own REA Ignite export,
not builder stock, and it is ingested on a separate path that folds listings
into the regional sections at render time. Callers import
lib.parsers.rea_ignite.parse directly.

Adding a builder is three edits, none of them here-and-there:
  1. lib/parsers/<builder>.py      — the parser
  2. config/builders.yml           — sender, ingestion mode, link strategy
  3. this file                     — one line in PARSERS
"""

from __future__ import annotations

from typing import Callable

from .parsers.aldrich import parse as parse_aldrich
from .parsers.aplace import parse as parse_aplace
from .parsers.goldstate import parse as parse_goldstate
from .parsers.hermitage import parse as parse_hermitage
from .parsers.luxton import parse as parse_luxton
from .parsers.monaco import parse as parse_monaco
from .parsers.specialised import parse as parse_specialised
from .parsers.urbane import parse as parse_urbane
from .parsers.types import StocklistRow

# builder_id -> parser. The builder_id must match a key under `builders:` in
# config/builders.yml; that is how the ingest layer finds the sender and
# ingestion mode. len(PARSERS) is the authoritative builder count — never
# hard-code it, or adding a builder produces nonsense like "8/6 builders".
PARSERS: dict[str, Callable[..., list[StocklistRow]]] = {
    "specialised": parse_specialised,
    "aldrich":     parse_aldrich,
    "urbane":      parse_urbane,
    "hermitage":   parse_hermitage,
    "aplace":      parse_aplace,
    "luxton":      parse_luxton,
    "goldstate":   parse_goldstate,   # added 2026-08-06 (paid 2026-08 scope)
    "monaco":      parse_monaco,      # added 2026-08-06 (paid 2026-08 scope)
}
