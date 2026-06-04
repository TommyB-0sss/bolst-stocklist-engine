"""
Microsoft Graph send helpers.

Reused by:
  - skills/compose-and-send/send_test.py    (Stage 1 plumbing)
  - skills/compose-and-send/send_report.py  (Stage 9, morning report)
  - skills/one-part-prompt/run.py           (Stage 9, evening One Part prompt to Tom)

The authenticated Graph identity is the SENDER. With our delegated permissions
(Mail.Send), `POST /me/sendMail` always sends as the signed-in user. The Phase 1
plan signs in as Tom, so all sends originate from tom@bolstpropertygroup.com.au.

Returning the requests.Response keeps callers in control of retry / error reporting.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Iterable

import requests

from lib.auth import get_access_token

GRAPH_SENDMAIL_ENDPOINT = "https://graph.microsoft.com/v1.0/me/sendMail"
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class Attachment:
    """A file attachment for a Graph email. Content is raw bytes; we base64-encode at send time."""
    filename: str
    content: bytes
    content_type: str = "application/pdf"

    def as_graph_payload(self) -> dict:
        return {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": self.filename,
            "contentType": self.content_type,
            "contentBytes": base64.b64encode(self.content).decode("ascii"),
        }


def send_mail(
    *,
    recipient: str,
    subject: str,
    body_text: str | None = None,
    body_html: str | None = None,
    attachments: Iterable[Attachment] = (),
    save_to_sent_items: bool = True,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> requests.Response:
    """
    Send an email via Microsoft Graph as the authenticated user.

    Pass either body_text (plain) or body_html (HTML). HTML wins if both supplied.

    Raises HTTPError on non-2xx responses. The expected success status is 202 Accepted —
    Graph queues the message for delivery and returns no body.
    """
    if body_html is None and body_text is None:
        raise ValueError("send_mail requires body_text or body_html")
    if body_html is not None:
        body_payload = {"contentType": "HTML", "content": body_html}
    else:
        body_payload = {"contentType": "Text", "content": body_text}

    token = get_access_token()
    payload = {
        "message": {
            "subject": subject,
            "body": body_payload,
            "toRecipients": [{"emailAddress": {"address": recipient}}],
            "attachments": [a.as_graph_payload() for a in attachments],
        },
        "saveToSentItems": save_to_sent_items,
    }
    response = requests.post(
        GRAPH_SENDMAIL_ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout_seconds,
    )
    return response
