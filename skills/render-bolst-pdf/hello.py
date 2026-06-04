"""
hello.py — minimal PDF generator for Stage 1 plumbing test.

Thin CLI wrapper around lib.pdf_render.write_hello_pdf — the actual PDF
construction lives in lib/ so it can be reused by send_test.py and (later) by
the Stage 8 branded renderer.

Usage (from bundle root, with venv active):
    python skills/render-bolst-pdf/hello.py [output_path]

Default output: output/hello_bolst_{timestamp}.pdf
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.pdf_render import write_hello_pdf  # noqa: E402


def main() -> int:
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = BUNDLE_ROOT / "output" / f"hello_bolst_{ts}.pdf"

    written = write_hello_pdf(out)
    print(f"OK: wrote {written} ({written.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
