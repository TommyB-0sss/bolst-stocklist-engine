"""Dry-run preview of the One Part evening prompt.

Renders exactly the HTML body that send_evening_prompt.py would send,
but writes it to output/ instead of calling Microsoft Graph send. Use
this to review the email before Inam forwards / sends himself to Tom.

Usage:
    .venv\\Scripts\\python.exe tests\\preview_evening_prompt.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

# Import the prompt helpers directly from the sender script so we render
# byte-identical HTML.
from importlib.util import module_from_spec, spec_from_file_location

prompt_path = BUNDLE_ROOT / "skills" / "one-part-prompt" / "send_evening_prompt.py"
spec = spec_from_file_location("send_evening_prompt", prompt_path)
mod = module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)

from lib.graph_read import fetch_latest_for_builder, load_builders_config  # noqa: E402
from lib.one_part_candidates import get_specialised_candidates  # noqa: E402

MELBOURNE = ZoneInfo("Australia/Melbourne")


def main() -> int:
    builders_cfg = load_builders_config(BUNDLE_ROOT)
    pdf_path = fetch_latest_for_builder(
        "specialised", builders_cfg, bundle_root=BUNDLE_ROOT,
    )
    print(f"Using Specialised PDF: {pdf_path.name}")

    groups = get_specialised_candidates(pdf_path)
    total_rows = sum(len(g.rows) for g in groups)
    print(f"  {total_rows} candidate rows in {len(groups)} (suburb, estate) groups")

    now_mel = datetime.now(MELBOURNE)
    report_date = (now_mel + timedelta(days=1)).strftime("%Y-%m-%d")
    subject = f"[Bolst One Part — {report_date}]"
    html = mod._build_html_body(groups, report_date, total_rows)

    out_dir = BUNDLE_ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    html_path = out_dir / f"evening-prompt-{report_date}.html"
    html_path.write_text(html, encoding="utf-8")
    txt_path = out_dir / f"evening-prompt-{report_date}.subject.txt"
    txt_path.write_text(f"Subject: {subject}\nTo: tom@bolstpropertygroup.com.au\n"
                        f"From: tom@bolstpropertygroup.com.au\n"
                        f"Candidates: {total_rows} rows in {len(groups)} groups\n",
                        encoding="utf-8")

    print()
    print(f"  Subject:  {subject}")
    print(f"  HTML:     {html_path}")
    print(f"  Header:   {txt_path}")
    print()
    print("Open the .html in a browser to preview. Inam to forward / send himself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
