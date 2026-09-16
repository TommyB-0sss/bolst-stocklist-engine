"""
Offline checks for lib.graph_read._resolve_buttons — the layered newsletter
button resolver added 2026-09-16 (latest email -> older emails within a
window -> configured live sheet -> optional/missing, plus the unknown-sheet
tripwire). No network and no Graph: the redirect follower and the cache
downloader are stubbed.

Usage (from bundle root, venv active):
    python tests/validate_button_resolver.py
"""
from __future__ import annotations

import contextlib
import io
import sys
from datetime import date, timedelta
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BUNDLE_ROOT))

import lib.graph_read as gr  # noqa: E402

TODAY = date.today()
SHEET_A = "AAAA1111aaaa"
SHEET_B = "BBBB2222bbbb"
SHEET_NEW = "NEWNEW9999new"
TRACK = {   # Mailchimp-style tracking href -> sheet id it redirects to
    "https://us.list-manage.com/trkA": SHEET_A,
    "https://us.list-manage.com/trkB": SHEET_B,
    "https://us.list-manage.com/trkNew": SHEET_NEW,
}
BTN_ONE = {"text_contains": "1 Part Sock List", "filename": "L-One.xlsx",
           "format": "google_sheets_xlsx", "fallback_sheet_id": SHEET_A}
BTN_TWO = {"text_contains": "2 Part Stock List", "filename": "L-HL.xlsx",
           "format": "google_sheets_xlsx", "fallback_sheet_id": SHEET_B}
BTN_TWO_NOFALLBACK = {k: v for k, v in BTN_TWO.items() if k != "fallback_sheet_id"}
BTN_VIC = {"text_contains": "Victoria Stocklist", "filename": "A-Vic.pdf"}
BTN_UPFRONT_OPT = {"text_contains": "100% Upfront commission",
                   "filename": "A-Up.pdf", "optional": True}


def msg(days_ago: int, html: str) -> dict:
    d = TODAY - timedelta(days=days_ago)
    return {"receivedDateTime": f"{d.isoformat()}T04:00:00Z",
            "body": {"content": html}}


def link(text: str, href: str) -> str:
    return f'<p><a href="{href}">{text}</a></p>'


ONE = link("1 Part Sock List - Click", "https://us.list-manage.com/trkA")
TWO = link("2 Part Stock List - Click", "https://us.list-manage.com/trkB")
NEW = link("Sub $600K House & Land", "https://us.list-manage.com/trkNew")
FOOTER = (link("why did I get this?", "https://x.us4.list-manage.com/about?u=1")
          + link("update subscription preferences", "https://x.us4.list-manage.com/profile?u=1"))
VIC = link("Download – Victoria Stocklist", "https://cdn.aplace.com.au/vic.pdf")
UPF = link("Download – 100% Upfront commission stocklist", "https://cdn.aplace.com.au/up.pdf")


class Stub:
    def __init__(self) -> None:
        self.downloads: list[tuple[str, str, date]] = []
        self.fail_urls: set[str] = set()

    def resolve(self, href: str) -> str:
        if href in TRACK:
            return TRACK[href]
        raise gr.IngestError(f"not a sheet: {href}")

    def download(self, url, cache_dir, filename, when, skip_cache,
                 expected_content_types=()):
        if url in self.fail_urls:
            raise gr.IngestError(f"boom {url}")
        self.downloads.append((url, filename, when))
        return cache_dir / f"{when.strftime('%Y%m%d')}-{filename}"


def run(buttons, messages, strategy=None, stub=None):
    stub = stub or Stub()
    gr._resolve_google_sheet_id = stub.resolve
    gr._download_to_cache = stub.download
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        paths = gr._resolve_buttons("testb", strategy or {}, buttons, messages,
                                    Path("cache-stub"), False)
    return paths, err.getvalue(), stub


def sheet_url(sheet_id: str) -> str:
    return gr._sheet_xlsx_url(sheet_id)


results: list[tuple[bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))


def main() -> int:
    orig_resolve, orig_download = gr._resolve_google_sheet_id, gr._download_to_cache
    try:
        # 1. Latest email carries both sheet buttons: layer 1, cached under TODAY.
        paths, err, stub = run([BTN_ONE, BTN_TWO], [msg(0, ONE + TWO + FOOTER)])
        check("latest email: both sheets resolved", len(paths) == 2)
        check("latest email: sheet downloads use export URLs A and B",
              [d[0] for d in stub.downloads] == [sheet_url(SHEET_A), sheet_url(SHEET_B)],
              str(stub.downloads))
        check("latest email: live sheets cached under today's date",
              all(d[2] == TODAY for d in stub.downloads))
        check("latest email: no fallback chatter", "resolved it from" not in err and "fetched the configured" not in err, err)

        # 2. Latest email has no buttons; an older email inside the window has both.
        paths, err, stub = run([BTN_ONE, BTN_TWO],
                               [msg(0, "<p>Dual key promo</p>" + FOOTER), msg(30, ONE + TWO)],
                               {"search_older_emails_days": 120})
        check("older email in window: both resolved", len(paths) == 2)
        check("older email in window: two info lines name the older email",
              err.count("resolved it from the") == 2, err)
        check("older email in window: still cached under today", all(d[2] == TODAY for d in stub.downloads))

        # 3. Only email with buttons is OUTSIDE the window -> configured sheet ids.
        paths, err, stub = run([BTN_ONE, BTN_TWO],
                               [msg(0, "<p>promo</p>"), msg(200, ONE + TWO)],
                               {"search_older_emails_days": 120})
        check("outside window: fallback sheets used for both", len(paths) == 2 and err.count("fetched the configured sheet") == 2, err)
        check("outside window: downloads hit the configured ids",
              sorted(d[0] for d in stub.downloads) == sorted([sheet_url(SHEET_A), sheet_url(SHEET_B)]))

        # 4. Window 0, no fallback, button only in an older email -> nothing resolved.
        raised = False
        try:
            run([BTN_TWO_NOFALLBACK], [msg(0, "<p>promo</p>"), msg(1, TWO)])
        except gr.IngestError as e:
            raised = "no buttons resolved" in str(e)
        check("window 0 + no fallback + nothing in latest: IngestError", raised)

        # 5. PDF button: older email allowed only inside the window; keeps the email's date.
        raised = False
        try:
            run([BTN_VIC], [msg(0, "<p>package of the week</p>"), msg(7, VIC)])
        except gr.IngestError:
            raised = True
        check("pdf: window 0 ignores the 7-day-old email", raised)
        paths, err, stub = run([BTN_VIC], [msg(0, "<p>package of the week</p>"), msg(7, VIC)],
                               {"search_older_emails_days": 14})
        check("pdf: window 14 resolves from the 7-day-old email", len(paths) == 1 and "resolved it from" in err)
        check("pdf: snapshot keeps the email's received date, not today",
              stub.downloads and stub.downloads[0][2] == TODAY - timedelta(days=7), str(stub.downloads))

        # 6. Optional button missing: info line, no WARNING, no raise.
        paths, err, _ = run([BTN_VIC, BTN_UPFRONT_OPT], [msg(0, VIC)])
        check("optional missing: one pdf returned", len(paths) == 1)
        check("optional missing: info line, not a WARNING",
              "optional list(s)" in err and "WARNING" not in err, err)

        # 7. Required button missing with no fallback: WARNING names it.
        paths, err, _ = run([BTN_ONE, BTN_TWO_NOFALLBACK], [msg(0, ONE)])
        check("required missing: partial result", len(paths) == 1)
        check("required missing: WARNING 'only 1 of 2' names the button",
              "WARNING: testb: only 1 of 2" in err and "2 Part Stock List" in err, err)

        # 8. Tripwire: an unknown sheet linked from the latest email is reported;
        #    footer/admin links are not followed.
        paths, err, _ = run([BTN_ONE, BTN_TWO], [msg(0, ONE + TWO + NEW + FOOTER)])
        check("tripwire: unknown sheet reported with its id",
              f"does not know ({SHEET_NEW}" in err and "Sub $600K" in err, err)
        check("tripwire: known sheets not reported", SHEET_A not in err and SHEET_B not in err, err)
        check("tripwire: footer links produce no warning", "about" not in err and "profile" not in err, err)

        # 9. Download failure on a sheet falls through the layers and ends as WARNING.
        stub = Stub()
        stub.fail_urls.add(sheet_url(SHEET_B))
        paths, err, _ = run([BTN_ONE, BTN_TWO], [msg(0, ONE + TWO), msg(10, ONE + TWO)],
                            {"search_older_emails_days": 30}, stub)
        check("download failure: other sheet still returned", len(paths) == 1)
        check("download failure: WARNING carries the error text",
              "WARNING" in err and "boom" in err, err)

        # 10. Both missing and both optional -> still an error (nothing to ingest).
        raised = False
        try:
            run([dict(BTN_VIC, optional=True), BTN_UPFRONT_OPT], [msg(0, "<p>nothing</p>")])
        except gr.IngestError:
            raised = True
        check("all optional, none found: IngestError (builder skipped, not silently empty)", raised)
    finally:
        gr._resolve_google_sheet_id, gr._download_to_cache = orig_resolve, orig_download

    failed = [n for ok, n in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
    if failed:
        print("FAILED: " + "; ".join(failed))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
