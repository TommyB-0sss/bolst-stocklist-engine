"""
Validation script for the Stage 9.5 One Part notice banner.

Renders the report twice — once with no notice, once with a sample notice —
and verifies the notice text appears in the PDF only when supplied. Also
spot-checks that the notice does NOT bleed into other regions' pages.

Usage (from bundle root, with venv active):
    python tests/validate_one_part_notice.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.parsers.aplace import parse as parse_aplace                # noqa: E402
from lib.parsers.aldrich import parse as parse_aldrich              # noqa: E402
from lib.parsers.hermitage import parse as parse_hermitage          # noqa: E402
from lib.parsers.urbane import parse as parse_urbane                # noqa: E402
from lib.parsers.specialised import parse as parse_specialised      # noqa: E402
from lib.parsers.luxton import parse as parse_luxton                # noqa: E402
from lib.routing import load_config, route                          # noqa: E402
from lib.status_filter import load_drop_list, should_keep           # noqa: E402
from lib.pdf_render import build_report_pdf                         # noqa: E402

DATA = BUNDLE_ROOT.parent / "bolst-property-group-data"
NOTICE_TEXT = "No Specialised picks received - reply to yesterday's prompt to add."


def _gather() -> list:
    rows = []
    for parser, paths in [
        (parse_aplace,      sorted((DATA / "aplacevic@aplace.com.au").glob("*.pdf"))),
        (parse_aldrich,     [DATA / "Corey.b@aldrichhomes.com.au" / "Stocklist C44.pdf"]),
        (parse_hermitage,   sorted((DATA / "houseandland@hermitagehomes.com.au").glob("*.pdf"))),
        (parse_urbane,      sorted((DATA / "mikayla+2Esalva=orbithomes.com.au@hubspotfree.hs-send.com").glob("*.pdf"))),
        (parse_specialised, [DATA / "nlimbo@specialisedhomeconstructions.com.au" / "Stocklist 28.04.26.pdf"]),
        (parse_luxton,      sorted((DATA / "stefanc@luxtonhomes.com.au").glob("*.xlsx"))),
    ]:
        for p in paths:
            if p.exists():
                rows.extend(parser(p))
    return rows


def _all_text(pdf_bytes: bytes) -> str:
    out = BUNDLE_ROOT / "output" / "_notice_test.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf_bytes)
    with pdfplumber.open(out) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def main() -> int:
    cfg = load_config(BUNDLE_ROOT / "config" / "suburbs.yml")
    drops = load_drop_list(BUNDLE_ROOT / "config" / "status-filter.yml")

    rows = _gather()
    routed = route(rows, cfg)
    kept = [r for r in routed if should_keep(r.row.status, drops)]
    print(f"Pipeline: {len(rows)} parsed -> {len(kept)} kept")

    fails = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal fails
        marker = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"[{marker}] {name}" + (f"  ({detail})" if detail else ""))

    # Without notice
    no_notice_pdf = build_report_pdf(kept, cfg, bundle_root=BUNDLE_ROOT)
    no_notice_text = _all_text(no_notice_pdf)
    check(
        "1. No notice argument -> notice text absent",
        NOTICE_TEXT not in no_notice_text,
    )

    # With notice
    with_notice_pdf = build_report_pdf(
        kept, cfg, bundle_root=BUNDLE_ROOT, one_part_notice=NOTICE_TEXT,
    )
    with_notice_text = _all_text(with_notice_pdf)
    check(
        "2. one_part_notice argument -> notice text present",
        NOTICE_TEXT in with_notice_text,
    )

    # Confirm the notice appears only ONCE (one One Part page, not bleeding)
    occurrences = with_notice_text.count(NOTICE_TEXT)
    check(
        "3. Notice appears exactly once (no bleed to other regions)",
        occurrences == 1,
        f"found {occurrences} occurrences",
    )

    print(f"\n--- {3 - fails}/3 pass ---")
    return 0 if fails == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
