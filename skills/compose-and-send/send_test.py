"""
send_test.py — substep 1.6f Stage 1 plumbing test.

Sends a hello PDF from Tom's Outlook to the Phase 1 recipient (inam@meetapex.ai)
via Microsoft Graph. Proves the full OAuth + Graph send pipeline works end to end.

Replaced by send_report.py once Stage 8 (branded PDF render) is done.

Usage (from bundle root, with venv active):
    python skills/compose-and-send/send_test.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BUNDLE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

from lib.graph_send import Attachment, send_mail  # noqa: E402
from lib.pdf_render import build_hello_pdf_bytes  # noqa: E402

load_dotenv(BUNDLE_ROOT / ".env")


def main() -> int:
    recipient = os.environ["BOLST_REPORT_RECIPIENT"]
    sender = os.environ["BOLST_REPORT_SENDER"]

    print("Generating hello PDF...", file=sys.stderr)
    pdf_bytes = build_hello_pdf_bytes(label="system online - send test")
    print(f"  PDF size: {len(pdf_bytes):,} bytes", file=sys.stderr)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = (
        "This is an automated send test from substep 1.6f of the Bolst "
        "Stocklist Engine build.\n\n"
        f"Sender: {sender}\n"
        f"Recipient: {recipient}\n"
        f"Timestamp: {timestamp}\n\n"
        "If you can read this and the attached PDF opens, the OAuth + Graph "
        "send pipeline is working end to end."
    )

    print(f"Sending to {recipient} as {sender}...", file=sys.stderr)
    response = send_mail(
        recipient=recipient,
        subject=f"Bolst Stocklist Engine - send test ({timestamp})",
        body_text=body,
        attachments=[Attachment(filename="hello-bolst.pdf", content=pdf_bytes)],
    )

    if response.status_code == 202:
        print("OK - 202 Accepted. Email queued by Microsoft Graph.", file=sys.stderr)
        return 0
    print(f"FAILED - HTTP {response.status_code}", file=sys.stderr)
    print(f"Response body:\n{response.text}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
