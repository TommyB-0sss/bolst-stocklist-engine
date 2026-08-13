"""
PDF generation for the Bolst Stocklist Engine.

Phase 1 (Stage 1 plumbing): build_hello_pdf_bytes() — minimal hello-world PDF
used by send_test.py and skills/render-bolst-pdf/hello.py to prove the pipeline.

Phase 1 (Stage 8): build_report_pdf() — branded morning report with the 10
region banners, footer, and routed stocklist rows.

Cover page: assets/Front Cover.pdf (Tom's branded design) is rendered as
page 1 of the same document — full-bleed PNG background + masked dynamic
overlays for the date/total/per-region counts. Each "AVAILABLE BY REGION"
row is also a clickable internal link that jumps to that region's page
(fpdf2 native GoTo links; see _render_cover_onto + build_report_pdf).

Returning bytes (rather than writing to disk) keeps the API symmetric for both
file-output use cases (hello.py CLI) and in-memory use cases (Graph attachment).
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

import pypdfium2 as pdfium
from fpdf import FPDF

from lib.parsers.types import ListingRow
from lib.routing import RoutedRow, RoutingConfig, _normalise_suburb


# ============================================================================
# Stage 1 plumbing — hello PDF
# ============================================================================

def build_hello_pdf_bytes(label: str = "system online") -> bytes:
    """Minimal one-page PDF used for plumbing tests. Returns the PDF as bytes."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=24)
    pdf.cell(0, 20, "Hello Bolst", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 10, label, new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.ln(10)
    pdf.set_font("Helvetica", size=10)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pdf.cell(0, 8, f"Generated: {timestamp}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 8, "bolst-stocklist-engine - Stage 1 plumbing test",
             new_x="LMARGIN", new_y="NEXT", align="C")

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def write_hello_pdf(output_path: Path, label: str = "system online") -> Path:
    """Convenience wrapper for the CLI: writes the hello PDF to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_hello_pdf_bytes(label))
    return output_path


# ============================================================================
# Stage 8 — branded morning report
# ============================================================================

# Bolst brand palette (sampled from the banner JPGs).
COLOR_BRAND_GREEN = (13, 56, 35)      # #0D3823 — banner background
COLOR_BRAND_GOLD = (201, 162, 74)     # #C9A24A — banner accent
COLOR_COVER_BG = (24, 47, 43)         # #182F2B — exact cover-page bg
                                      # (sampled from rendered Front Cover.pdf;
                                      # used to mask static numbers seamlessly)
COLOR_ALT_ROW = (224, 224, 224)       # #E0E0E0 — alt row background.
                                      # Inverted zebra: even rows (0,2,4)
                                      # get this darker shade; odd rows
                                      # stay white. Was #F8F8F8 on odd rows.
COLOR_BORDER = (204, 204, 204)        # #CCCCCC — table cell borders
COLOR_DIM = (102, 102, 102)           # #666666 — subtitle / muted text

# Landscape A4 dimensions
PAGE_WIDTH_MM = 297
PAGE_HEIGHT_MM = 210
MARGIN_MM = 10
USABLE_WIDTH_MM = PAGE_WIDTH_MM - 2 * MARGIN_MM   # 277

# Banner dimensions: source aspect ratio is roughly 6.83:1 (4843×709). At
# 277mm width that's ~40mm height. Subtle, not overwhelming.
BANNER_HEIGHT_MM = 40
BANNER_GAP_MM = 4   # space between banner and subtitle

# 8-column widths in mm. Sum: 257mm; centred within the 277mm usable
# width with 10mm extra margin on each side.
COL_WIDTHS = {
    "suburb":  32,
    "lot":     14,
    "address": 50,
    "estate":  50,
    "titles":  25,
    "bbc":     24,
    "total":   32,
    "status":  30,
}

COL_HEADERS = {
    "suburb":  "SUBURB",
    "lot":     "LOT NO",
    "address": "ADDRESS",
    "estate":  "ESTATE",
    "titles":  "TITLES",
    "bbc":     "BED/Bath/Car",
    "total":   "TOTAL $",
    "status":  "STATUS",
}

ROW_HEIGHT_MM = 5
HEADER_HEIGHT_MM = 7
# Bottom-margin reservation for the page-break check. Must be at least
# FOOTER_HEIGHT_MM (40mm full-bleed footer) plus a small gap so rows
# never overlap the gold contact band. Pre-2026-05-25 this was 12mm,
# allowing rows to extend to y=198 — well into the footer at y=170+.
BOTTOM_MARGIN_MM = 45


# ----- formatting helpers -------------------------------------------------

def _fmt_date(d: date) -> str:
    """'8 May 2026' — matches Tom's template subtitle format."""
    # %-d is POSIX, not Windows. Strip leading zero manually.
    return f"{d.day} {d.strftime('%B %Y')}"


def _fmt_currency(v: Optional[int]) -> str:
    if v is None:
        return "-"
    return f"${v:,}"


def _fmt_bbc(bed, bath, car) -> str:
    """Render bed/bath/car. Question marks dropped per Tom 2026-05-25.

    - All three present:       '4-2-2'
    - Bed only (Hermitage/REA): '4'      (Tom: just show the bedroom)
    - Nothing:                  '-'
    - Bed missing, others known: '-2-2'  (Inam: '-' placeholder for bed
                                          slot to preserve column position
                                          and avoid 2-2 ambiguity)
    - Partial cases:            slots stay positional, missing = '-'
    """
    bed_known = bed is not None
    bath_known = bath is not None
    car_known = car is not None

    if not (bed_known or bath_known or car_known):
        return "-"

    # Tom's primary case: bed only, no bath/car -> just the bedroom number.
    if bed_known and not bath_known and not car_known:
        return str(int(bed))

    bed_s = str(int(bed)) if bed_known else "-"
    if bath_known:
        bath_s = str(int(bath)) if float(bath).is_integer() else str(bath)
    else:
        bath_s = "-"
    car_s = str(int(car)) if car_known else "-"

    return f"{bed_s}-{bath_s}-{car_s}"


def _fmt_status(s: Optional[str]) -> str:
    """Title-case the status. Source data is mixed: 'AVAILABLE' / 'HOLD' /
    'CONTRACT SIGNED' co-exist with 'Available' / 'On Hold' / 'Reserved'.
    Apply at render so status_filter (drop-list match) still sees raw."""
    if not s or not str(s).strip():
        return "Available"
    return " ".join(w.capitalize() for w in str(s).split())


@dataclass
class SectionRow:
    """Source-agnostic row shape used by _render_region + _draw_section_row.

    Both builder StocklistRows (via RoutedRow) and Bolst REA ListingRows
    convert to this before rendering, so a single region's table can mix
    sources transparently. price_int carries the numeric value used for
    the suburb-grouped ascending price sort; rows without a price sort
    last in their group.
    """
    suburb: str
    lot: str
    address: str
    estate: str
    titles: str
    bbc: str
    total: str
    status: str
    price_int: Optional[int]


def _section_row_from_routed(routed: RoutedRow) -> SectionRow:
    r = routed.row
    return SectionRow(
        suburb=r.suburb or "",
        lot=r.lot or "",
        address=r.street or "",
        estate=r.estate or "",
        titles=r.titles or "",
        bbc=_fmt_bbc(r.bed, r.bath, r.car),
        total=_fmt_currency(r.total_price),
        status=_fmt_status(r.status),
        price_int=r.total_price,
    )


def _section_row_from_listing(L: ListingRow) -> SectionRow:
    """REA Active Listings have no bath/car columns and no status field
    (every listed property is, by definition, Active = Available). BBC
    column follows Tom's 2026-05-25 rule: just the bedroom number when
    bath + car are unavailable (no question marks)."""
    bbc = _fmt_bbc(L.bed, None, None)
    return SectionRow(
        suburb=L.suburb or "",
        lot=_safe_latin1(L.lot or ""),
        address=_safe_latin1(L.address or ""),
        estate=_safe_latin1(L.estate or ""),
        titles=_safe_latin1(L.title_status or ""),
        bbc=bbc,
        total=_safe_latin1(L.price or ""),
        status="Available",
        price_int=L.price_int,
    )


def _truncate_to_width(pdf: FPDF, text: str, max_width_mm: float) -> str:
    """Truncate with ellipsis if string exceeds max_width at the active font."""
    if not text:
        return ""
    if pdf.get_string_width(text) <= max_width_mm:
        return text
    while text and pdf.get_string_width(text + "...") > max_width_mm:
        text = text[:-1]
    return (text + "...") if text else ""


# ----- region rendering ----------------------------------------------------

def _draw_banner(pdf: FPDF, banner_path: Optional[Path]) -> None:
    """Place region banner image at the top of the current page.

    Full-bleed (x=0, y=0, w=PAGE_WIDTH) so the branded green band runs
    edge-to-edge. Tom flagged 2026-05-25 that the prior inset (10mm white
    strips on the sides + top) looked unfinished. The cover page is
    already full-bleed; this matches it.
    """
    if banner_path and banner_path.exists():
        pdf.image(str(banner_path),
                  x=0, y=0,
                  w=PAGE_WIDTH_MM, h=BANNER_HEIGHT_MM)
    # Content cursor still respects MARGIN_MM left/right + the prior
    # vertical position (banner-bottom + gap) so the table layout doesn't
    # shift relative to the page.
    pdf.set_y(BANNER_HEIGHT_MM + BANNER_GAP_MM + MARGIN_MM)


def _draw_subtitle(pdf: FPDF, report_date: date, n_packages: int,
                   continued: bool = False,
                   section_title: Optional[str] = None) -> None:
    """'<Region> — Stocklist as at 8 May 2026 | 4 packages' — left-aligned.

    `section_title` (e.g. region name "Geelong & Colac" or extra-suburb
    label "BENDIGO") is prefixed when provided. Tom 2026-05-25 flagged
    that continuation pages with no region context made it hard to tell
    where one section ends and the next begins."""
    pdf.set_font("Helvetica", style="B", size=10)
    pdf.set_text_color(*COLOR_BRAND_GREEN)
    suffix = " (continued)" if continued else ""
    prefix = f"{section_title} — " if section_title else ""
    label = (f"{prefix}Stocklist as at {_fmt_date(report_date)} | "
             f"{n_packages} package{'s' if n_packages != 1 else ''}{suffix}")
    pdf.set_x(MARGIN_MM)
    pdf.cell(0, 6, _safe_latin1(label), new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.ln(2)


def _draw_table_header(pdf: FPDF,
                       headers: Optional[dict] = None) -> None:
    """Render the 8-col table header. Pass `headers` to override default
    labels — used by Bolst Listings to swap STATUS -> AGENT."""
    headers = headers or COL_HEADERS
    pdf.set_x(MARGIN_MM + (USABLE_WIDTH_MM - sum(COL_WIDTHS.values())) / 2)
    pdf.set_font("Helvetica", style="B", size=8)
    pdf.set_text_color(255, 255, 255)
    pdf.set_fill_color(*COLOR_BRAND_GREEN)
    pdf.set_draw_color(*COLOR_BRAND_GREEN)
    for key in COL_WIDTHS:
        pdf.cell(COL_WIDTHS[key], HEADER_HEIGHT_MM, headers.get(key, ""),
                 border=0, align="C", fill=True)
    pdf.ln(HEADER_HEIGHT_MM)


def _titlecase_suburb(s: Optional[str]) -> str:
    """Normalise builder/REA suburb strings to consistent Title Case.

    Source data is inconsistent: 'WARRNAMBOOL' / 'Warrnambool' / 'shepparton
    north'. Apply at render layer (parsers keep raw values for audit, same
    pattern routing uses)."""
    if not s:
        return ""
    return " ".join(w.capitalize() for w in s.split())


def _data_row_align(key: str) -> str:
    """Per-column alignment policy."""
    if key == "total":
        return "R"
    if key in ("lot", "bbc", "status", "titles"):
        return "C"
    return "L"


def _draw_section_row(pdf: FPDF, row: SectionRow, alt_row: bool) -> None:
    """Render one row across the 8 columns from a SectionRow adapter.

    Source-agnostic: builder StocklistRows and REA ListingRows both arrive
    here through their respective `_section_row_from_*` adapters.

    Inverted zebra: alt rows (even-indexed) get the darker grey fill;
    odd rows stay white. Per Inam 2026-05-09 the previous gold-tint
    'featured' highlight has been removed — Aldrich Exclusive and
    Hermitage PACKAGES rows render the same as any other row.
    """
    pdf.set_x(MARGIN_MM + (USABLE_WIDTH_MM - sum(COL_WIDTHS.values())) / 2)
    pdf.set_font("Helvetica", size=8)
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(*COLOR_BORDER)

    if alt_row:
        pdf.set_fill_color(*COLOR_ALT_ROW)
        fill = True
    else:
        fill = False

    cells = {
        "suburb":  _titlecase_suburb(row.suburb),
        "lot":     row.lot,
        "address": row.address,
        "estate":  row.estate,
        "titles":  row.titles,
        "bbc":     row.bbc,
        "total":   row.total,
        "status":  row.status,
    }
    for key in COL_WIDTHS:
        text = _truncate_to_width(pdf, cells[key], COL_WIDTHS[key] - 2)
        pdf.cell(COL_WIDTHS[key], ROW_HEIGHT_MM, text,
                 border=1, align=_data_row_align(key), fill=fill)
    pdf.ln(ROW_HEIGHT_MM)


def _section_sort_key(sr: SectionRow):
    """Group by suburb (alphabetical, Title-cased), then ASCENDING by price
    within each suburb. Rows with no price sort last in their group."""
    return (
        _titlecase_suburb(sr.suburb),
        0 if sr.price_int is not None else 1,
        sr.price_int or 0,
    )


def _render_sorted_section_rows(pdf: FPDF, rows: list[SectionRow],
                                report_date: date,
                                section_title: Optional[str] = None) -> None:
    """Sort rows by suburb A-Z + price ASC and render them, inserting
    continuation pages (subtitle + table header repeated, banner not)
    whenever the next row would overflow the page. `section_title` is
    surfaced in the continuation subtitle so the reader can tell which
    region the page belongs to."""
    sorted_rows = sorted(rows, key=_section_sort_key)
    for i, sr in enumerate(sorted_rows):
        if pdf.get_y() + ROW_HEIGHT_MM > PAGE_HEIGHT_MM - BOTTOM_MARGIN_MM:
            pdf.add_page()
            pdf.set_y(MARGIN_MM)
            _draw_subtitle(pdf, report_date, len(sorted_rows),
                           continued=True, section_title=section_title)
            _draw_table_header(pdf)
        _draw_section_row(pdf, sr, alt_row=(i % 2 == 0))


def _draw_empty_region_message(pdf: FPDF) -> None:
    pdf.set_font("Helvetica", style="I", size=10)
    pdf.set_text_color(*COLOR_DIM)
    pdf.cell(0, 8, "No packages this week.",
             new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_text_color(0, 0, 0)


# Light-gold tint for the notice banner — visible but doesn't fight the
# brand-green banner above it. Picked from the same gold family as the
# previously-removed featured highlight.
COLOR_NOTICE_BG = (245, 230, 211)        # #F5E6D3 background fill
COLOR_NOTICE_BORDER = (201, 162, 74)     # brand gold border
NOTICE_PAD_X_MM = 6
NOTICE_PAD_Y_MM = 3
NOTICE_LINE_HEIGHT_MM = 5


def _draw_notice_banner(pdf: FPDF, message: str) -> None:
    """Render a callout-style notice across the full table width.

    Used for the One Part tab when Tom didn't reply to the evening prompt
    (or replied with ambiguous lots that couldn't be resolved). Sits between
    the region subtitle and the data table so it's visible without
    disrupting the row layout.
    """
    table_x = MARGIN_MM + (USABLE_WIDTH_MM - sum(COL_WIDTHS.values())) / 2
    table_w = sum(COL_WIDTHS.values())
    pdf.set_x(table_x)
    pdf.set_font("Helvetica", style="I", size=9)
    pdf.set_fill_color(*COLOR_NOTICE_BG)
    pdf.set_draw_color(*COLOR_NOTICE_BORDER)
    pdf.set_text_color(*COLOR_DIM)
    pdf.multi_cell(
        w=table_w,
        h=NOTICE_LINE_HEIGHT_MM,
        text=message,
        border=1,
        align="C",
        fill=True,
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)


def _render_region(pdf: FPDF, region_id: str, region_name: str,
                   banner_path: Optional[Path], rows: list[SectionRow],
                   report_date: date, notice: Optional[str] = None) -> None:
    """Render one of the 10 canonical Bolst regions. Rows are pre-merged
    by the caller — builder StocklistRows + Bolst REA ListingRows for
    suburbs that map to this region. Sort + table layout are uniform.
    """
    pdf.add_page()
    _draw_banner(pdf, banner_path)
    _draw_subtitle(pdf, report_date, len(rows), section_title=region_name)

    if notice:
        _draw_notice_banner(pdf, notice)

    if not rows:
        _draw_empty_region_message(pdf)
        return

    _draw_table_header(pdf)
    _render_sorted_section_rows(pdf, rows, report_date,
                                section_title=region_name)


# ----- Bolst REA listings: routing + extra-section fallback -----------------
#
# 2026-05-25 layout change (Inam): the previous standalone "BOLST LISTINGS"
# page is gone. REA listings now fold into the 10 regional sections by
# suburb, sharing the same 8-col table layout as the senders. The AGENT
# column (which was the only field distinguishing the listings page) is
# dropped; listing rows render with status="Available" in that slot.
#
# Listings whose suburb doesn't map to any of the 10 canonical regions go
# into per-suburb fallback sections rendered after the 10 regions, each
# titled with just the suburb name. The audit on 2026-05-25 confirms zero
# listings need this path against the current REA feed, but it's defensive
# against future Mallee / far-east-Gippsland properties appearing.

BOLST_EXTRA_PREFIX = "bolst-extra:"
EXTRA_TITLE_BAR_HEIGHT_MM = 14


_LATIN1_FALLBACKS = str.maketrans({
    "—": "-",   # em dash
    "–": "-",   # en dash
    "‘": "'", "’": "'",    # curly single quotes
    "“": '"', "”": '"',    # curly double quotes
    "…": "...", # ellipsis
})


def _safe_latin1(s: str) -> str:
    """Map common unicode punctuation to latin-1 equivalents; drop the rest.
    Helvetica is a core PDF font (latin-1 only). REA descriptions / agent
    names occasionally contain curly quotes that would otherwise raise."""
    if not s:
        return ""
    s = s.translate(_LATIN1_FALLBACKS)
    return s.encode("latin-1", "replace").decode("latin-1")


def _route_listings(listings: list[ListingRow],
                    config: RoutingConfig) -> dict[str, list[ListingRow]]:
    """Bucket REA ListingRows by region_id using suburbs.yml (same lookup
    rules as builder rows in lib/routing). Unmapped suburbs land in their
    own per-suburb bucket keyed by 'bolst-extra:<RAW_SUBURB>'.

    Empty suburbs would normally route to 'uncategorised' upstream — Inam
    confirmed 2026-05-25 that REA listings never carry an empty suburb, so
    we skip those rows silently rather than synthesising a section.
    """
    buckets: dict[str, list[ListingRow]] = defaultdict(list)
    for L in listings:
        norm = _normalise_suburb(L.suburb)
        if not norm:
            continue
        canonical = config.suburb_aliases.get(norm, norm)
        region_id = config.suburb_to_region.get(canonical)
        if region_id:
            buckets[region_id].append(L)
        else:
            buckets[f"{BOLST_EXTRA_PREFIX}{L.suburb}"].append(L)
    return dict(buckets)


def _draw_extra_title_bar(pdf: FPDF, suburb_label: str) -> None:
    """Brand-green title bar for an unmapped-suburb fallback section.
    Same visual weight as the old Bolst Listings page header, but shows
    the suburb name only (Inam 2026-05-25)."""
    pdf.set_xy(MARGIN_MM, MARGIN_MM)
    pdf.set_fill_color(*COLOR_BRAND_GREEN)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", style="B", size=18)
    pdf.cell(USABLE_WIDTH_MM, EXTRA_TITLE_BAR_HEIGHT_MM,
             _safe_latin1(suburb_label.upper()),
             border=0, align="C", fill=True)
    pdf.ln(EXTRA_TITLE_BAR_HEIGHT_MM + BANNER_GAP_MM)
    pdf.set_text_color(0, 0, 0)


def _render_bolst_extra_section(pdf: FPDF, suburb_label: str,
                                rows: list[SectionRow],
                                report_date: date) -> None:
    """Render a single per-suburb fallback section for listings whose
    suburb didn't match any of the 10 canonical regions."""
    pdf.add_page()
    _draw_extra_title_bar(pdf, suburb_label)
    _draw_subtitle(pdf, report_date, len(rows), section_title=suburb_label)
    if not rows:
        _draw_empty_region_message(pdf)
        return
    _draw_table_header(pdf)
    _render_sorted_section_rows(pdf, rows, report_date,
                                section_title=suburb_label)


FOOTER_HEIGHT_MM = 40        # footer.jpg is 4843×709, ~40mm at PAGE_WIDTH


def _draw_footer(pdf: FPDF, footer_path: Path) -> None:
    """Place footer image flush to the bottom + sides of the page (full
    bleed). Tom flagged 2026-05-25 that the prior 5mm bottom gap + 10mm
    side margins looked unfinished. If the last data row left less than
    FOOTER_HEIGHT of vertical space, add a new page first and pin the
    footer to its bottom — never to the centre."""
    if not footer_path.exists():
        return
    y_pos = PAGE_HEIGHT_MM - FOOTER_HEIGHT_MM
    if pdf.get_y() + FOOTER_HEIGHT_MM > PAGE_HEIGHT_MM:
        pdf.add_page()
    pdf.image(str(footer_path),
              x=0, y=y_pos,
              w=PAGE_WIDTH_MM, h=FOOTER_HEIGHT_MM)


# ----- public API ---------------------------------------------------------

def build_report_pdf(
    routed_rows: list[RoutedRow],
    config: RoutingConfig,
    *,
    bundle_root: Path,
    report_date: Optional[date] = None,
    one_part_notice: Optional[str] = None,
    listings: Optional[list[ListingRow]] = None,
) -> bytes:
    """
    Render the branded Bolst stocklist morning report.

    routed_rows      Rows that have been through Stage 7 routing+filter pipeline.
                     Caller is responsible for status filtering (lib/status_filter).
    config           Loaded RoutingConfig (region IDs, names, banner mapping).
    bundle_root      Path to bundle root (used to resolve banner + footer paths).
    report_date      Defaults to today.
    one_part_notice  If set, renders a callout banner on the One Part Contracts
                     page between subtitle and table. Used by the morning poll
                     (Stage 9) to surface "no Specialised picks received" or
                     "Lot N ambiguous — please specify suburb" messages.

    Returns the PDF as bytes.
    """
    if report_date is None:
        report_date = date.today()

    # Bucket every row (builders + REA listings) by region_id. Listings
    # whose suburb doesn't map to a canonical region get parked in
    # `extra_buckets` keyed by 'bolst-extra:<suburb>'.
    by_region: dict[str, list[SectionRow]] = defaultdict(list)
    for rr in routed_rows:
        by_region[rr.region_id].append(_section_row_from_routed(rr))

    extra_buckets: dict[str, list[SectionRow]] = defaultdict(list)
    if listings:
        for region_id, listings_for_region in _route_listings(listings, config).items():
            target = (extra_buckets if region_id.startswith(BOLST_EXTRA_PREFIX)
                      else by_region)
            for L in listings_for_region:
                target[region_id].append(_section_row_from_listing(L))

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)  # we manage breaks manually

    # Cover page (page 1): Tom's branded Front Cover.pdf with live values
    # overlaid + clickable region links. Built INLINE on the same document
    # as the content (rather than merged afterwards via pypdfium2) so fpdf2
    # emits native internal GoTo links that resolve to the region pages
    # rendered below. The cover is full-bleed, so margins are zeroed for it
    # and restored to the content margin straight after.
    cover_path = bundle_root / "assets" / "Front Cover.pdf"
    region_links: dict[str, int] = {}
    if cover_path.exists():
        pdf.set_margins(0, 0, 0)
        region_links = _render_cover_onto(
            pdf, routed_rows, config, cover_path=cover_path,
            report_date=report_date, listings=listings,
        )
        pdf.set_margins(MARGIN_MM, MARGIN_MM, MARGIN_MM)

    headers_dir = bundle_root / "assets" / "headers"
    footer_path = bundle_root / "assets" / "footer.jpg"

    # Render in declared order (suburbs.yml regions: list preserves order).
    # Footer is pinned to the bottom of the last page of every section.
    # _render_region opens with add_page(), so a region's first page is
    # always the page after whatever is current — captured here so the
    # cover links can target it.
    region_start_page: dict[str, int] = {}
    for region_id, region_name in config.region_names.items():
        banner_filename = config.region_banners.get(region_id)
        banner_path = (headers_dir / banner_filename) if banner_filename else None
        rows = by_region.get(region_id, [])
        notice = one_part_notice if region_id == "one-part-contracts" else None
        region_start_page[region_id] = pdf.page_no() + 1
        _render_region(pdf, region_id, region_name, banner_path, rows, report_date, notice=notice)
        _draw_footer(pdf, footer_path)

    # Bolst extra sections (defensive — REA listings whose suburb is
    # genuinely outside Bolst's 10 regions). Sorted alphabetically by
    # suburb so the order is stable across runs.
    for region_id in sorted(extra_buckets.keys()):
        suburb_label = region_id[len(BOLST_EXTRA_PREFIX):]
        _render_bolst_extra_section(pdf, suburb_label,
                                    extra_buckets[region_id], report_date)
        _draw_footer(pdf, footer_path)

    # Resolve each cover region link to the top of its region's first page.
    # set_link is applied after all pages exist; fpdf2 emits the GoTo
    # destinations at output() time.
    for region_id, link in region_links.items():
        start = region_start_page.get(region_id)
        if start is not None:
            pdf.set_link(link, page=start)

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()


# ----- dynamic cover overlay ----------------------------------------------

# Tom's `Front Cover.pdf` is designed at Letter landscape (792 x 612 pt =
# 279.4 x 215.9 mm) but has ~9mm of WHITE padding at top + bottom inside
# the page — leftover from the design being authored portrait then
# rotated. The actual green design only occupies ~197.6mm of vertical
# space, leaving an effective design aspect of 1.4137 (essentially A4
# landscape).
#
# To eliminate the white margins on the cover (Inam 2026-05-25), we:
#  (1) render the Letter cover to PNG as before,
#  (2) crop the white top/bottom borders (left/right are already flush),
#  (3) embed the cropped image filling a full A4 landscape page.
#
# Stretch is ~6.3% horizontal + virtually nothing vertical (the crop +
# stretch produces no visible distortion because the design IS A4-aspect
# once the white padding is removed).
#
# Overlay coordinates were calibrated against the ORIGINAL Letter PDF
# coordinate system (0..215.9mm y, 0..279.4mm x). _scaled_y() subtracts
# the top-margin offset before scaling so the dynamic values stay locked
# to the cropped design.

COVER_LETTER_W_MM = 279.4
COVER_LETTER_H_MM = 215.9
COVER_A4_W_MM = 297.0
COVER_A4_H_MM = 210.0
# Measured 2026-05-25 from rendered cover PNG: green design occupies
# y=103..2343 out of 2448px tall (scale=4 render).
COVER_LETTER_TOP_PAD_MM = 9.08    # 103/2448 * 215.9
COVER_LETTER_DESIGN_H_MM = 197.62  # 2241/2448 * 215.9
COVER_X_SCALE = COVER_A4_W_MM / COVER_LETTER_W_MM         # ~1.063
COVER_Y_SCALE = COVER_A4_H_MM / COVER_LETTER_DESIGN_H_MM  # ~1.063 (matches X — design is A4-aspect once cropped)


def _scaled_x(x: float) -> float:
    """Letter-cover x coord -> A4-cover x coord."""
    return x * COVER_X_SCALE


def _scaled_y(y: float) -> float:
    """Letter-cover y coord -> A4-cover y coord. Accounts for the white
    top padding cropped out of the source PNG."""
    return (y - COVER_LETTER_TOP_PAD_MM) * COVER_Y_SCALE


def _scaled(d: dict) -> dict:
    """Scale a calibration dict (x, y, w, h, ...) from Letter to A4 space."""
    return {
        **d,
        "x": _scaled_x(d["x"]),
        "y": _scaled_y(d["y"]),
        "w": d["w"] * COVER_X_SCALE,
        "h": d["h"] * COVER_Y_SCALE,
    }

# Calibrated positions for each dynamic field. (x, y, w, h) in mm define
# the mask rectangle (also where the new value is written, with the
# given alignment). All coordinates measured from the rendered 2x cover
# at 1584x1224 px (1 px = 0.1764 mm).
COVER_FIELDS = {
    # Date "8 May 2026" — bottom-left, white bold.
    # Real digit bbox: y=99.31..106.02 (incl descender). Tight mask with
    # 0.5mm padding; sits between "WEEK ENDING" label (ends y=94.73) and
    # "PRICING AS AT THIS DATE" label (starts y=108.31).
    "date": dict(x=16.5, y=98.8, w=47.5, h=7.7,
                 font_size=22, style="B", color=(255, 255, 255), align="L"),
    # Total "484" — middle, gold bold large.
    # Real digit bbox: y=100.20..108.84. Sits between "TOTAL PACKAGES"
    # label (ends y=94.73) and "ACROSS ALL REGIONS" label (starts y=113.07).
    "total": dict(x=87.3, y=99.7, w=33.3, h=9.7,
                  font_size=38, style="B", color=(201, 162, 74), align="L"),
}

# Region counts: list of (region_id, y_mm). All right-aligned at
# x_right = 263 mm. y values measured from rendered cover (each row's
# top scanned where digit pixels first appear, minus small padding).
# Order matches the order the design printed them in — DO NOT reorder.
COVER_REGION_COUNTS = [
    ("one-part-contracts",  83.0),  # original digit y=84.14..86.26
    ("geelong-colac",       89.2),  # 90.32..92.43
    ("gippsland",           95.4),  # 96.49..98.61
    ("horsham",            101.7),  # 102.84..104.96
    ("metro-north",        107.9),  # 109.02..111.13
    ("metro-south-east",   114.1),  # 115.19..117.31
    ("metro-west",         120.4),  # 121.54..123.66
    ("regional-north-east", 126.6),  # 127.71..129.83
    ("regional-west",      132.8),  # 133.89..136.00
    ("warrnambool",        139.1),  # 140.24..142.18
]
COVER_COUNT_X = 253.0
COVER_COUNT_W = 10.0
COVER_COUNT_H = 4.5
COVER_COUNT_FONT_SIZE = 9
COVER_COUNT_COLOR = (201, 162, 74)  # gold

# Clickable link band per region row (A4-landscape mm). Each "AVAILABLE BY
# REGION" row becomes a clickable area that jumps to that region's first
# page. Measured 2026-06-02 from the rendered cover: the list text spans
# x=176..289mm; the band is widened slightly (172mm + 120mm = 292mm) so the
# whole row is clickable. Each row's vertical centre is DERIVED from the
# COVER_REGION_COUNTS calibration (centre of the count cell), so the links
# stay locked to the artwork if the cover is ever re-tuned. Height 6.2mm is
# under the ~6.6mm row pitch, so adjacent rows never overlap.
COVER_LINK_X_MM = 172.0
COVER_LINK_W_MM = 120.0
COVER_LINK_ROW_H_MM = 6.2


def _render_cover_background(cover_path: Path) -> BytesIO:
    """Render Front Cover.pdf rotated +90deg as a high-res PNG, crop the
    built-in white top/bottom padding, return as BytesIO for embedding."""
    src = pdfium.PdfDocument(str(cover_path))
    rot = pdfium.PdfDocument.new()
    rot.import_pages(src)
    rot[0].set_rotation(90)
    img = rot[0].render(scale=4).to_pil().convert("RGB")
    src.close()
    rot.close()
    img = _crop_white_borders(img)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "cover_bg.png"  # fpdf2 sniffs format from name
    return buf


def _crop_white_borders(img):
    """Trim solid-white borders (any combination of top/bottom/left/right)
    from a PIL image. Tolerant of slight off-white (>=250 per channel)."""
    w, h = img.size

    def is_white(rgb):
        return all(c >= 250 for c in rgb)

    # Scan a center column / row to find non-white bounds.
    top = next((y for y in range(h) if not is_white(img.getpixel((w // 2, y)))), 0)
    bottom = next(
        (y for y in range(h - 1, -1, -1) if not is_white(img.getpixel((w // 2, y)))),
        h - 1,
    )
    left = next((x for x in range(w) if not is_white(img.getpixel((x, h // 2)))), 0)
    right = next(
        (x for x in range(w - 1, -1, -1) if not is_white(img.getpixel((x, h // 2)))),
        w - 1,
    )
    return img.crop((left, top, right + 1, bottom + 1))


def _mask_and_write(pdf: FPDF, x: float, y: float, w: float, h: float,
                    text: str, *, font_size: int, style: str,
                    color: tuple, align: str) -> None:
    """Cover the static value with a rectangle matching the cover bg,
    then write the live value on top."""
    pdf.set_fill_color(*COLOR_COVER_BG)
    pdf.set_draw_color(*COLOR_COVER_BG)
    pdf.rect(x, y, w, h, style="F")
    pdf.set_xy(x, y)
    pdf.set_font("Helvetica", style=style, size=font_size)
    pdf.set_text_color(*color)
    pdf.cell(w, h, text, align=align)


def _render_cover_onto(pdf: FPDF,
                       routed_rows: list[RoutedRow],
                       config: RoutingConfig,
                       *, cover_path: Path,
                       report_date: date,
                       listings: Optional[list[ListingRow]] = None,
                       ) -> dict[str, int]:
    """Draw the dynamic cover as a new page on `pdf`; return {region_id:
    link_id} for the clickable region rows.

    Steps: render Front Cover.pdf rotated +90deg as PNG, embed as
    full-bleed background, mask the baked-in static values, write today's
    live values on top, then add a clickable link band over each region row.

    The caller must set margins to 0 before calling (the cover is
    full-bleed) and restore them afterwards. Link destinations are left
    unresolved here — the caller wires them with pdf.set_link() once the
    region pages have been rendered and their page numbers are known.

    `listings` is included in the per-region counts so the cover totals
    match the table page subtitles after the 2026-05-25 A.1 layout
    reshape that folded REA listings into the regions. bolst-extra
    buckets (unmapped suburbs) are not counted on the cover since they
    sit outside the 10 canonical regions.
    """
    bg_buf = _render_cover_background(cover_path)

    # A4 landscape so the cover matches the rest of the document. The
    # Letter-aspect design is stretched to fill A4 (minor 6% horizontal
    # + 3% vertical compression — barely visible on the symmetric brand
    # layout). Zero margins so no white space anywhere.
    pdf.add_page()
    pdf.image(bg_buf, x=0, y=0,
              w=COVER_A4_W_MM, h=COVER_A4_H_MM)

    # Per-region row counts (live) — builders + REA listings folded in.
    per_region: dict[str, int] = defaultdict(int)
    for rr in routed_rows:
        per_region[rr.region_id] += 1
    extra_counts: dict[str, int] = {}
    if listings:
        listing_buckets = _route_listings(listings, config)
        for region_id, ls in listing_buckets.items():
            if region_id.startswith(BOLST_EXTRA_PREFIX):
                # bolst-extra sections sit outside the 10 cover regions: they
                # render as their own per-suburb sections but the branded
                # artwork has no line for them, so they cannot be counted here
                # without breaking headline == sum(region lines).
                extra_counts[region_id[len(BOLST_EXTRA_PREFIX):]] = len(ls)
                continue
            per_region[region_id] += len(ls)

    # The headline TOTAL PACKAGES must equal the sum of the per-region counts
    # printed directly beneath it. Summing per_region wholesale breaks that
    # promise the moment a row routes somewhere the cover has no line for —
    # in practice 'uncategorised', which happens whenever a builder ships a
    # suburb missing from config/suburbs.yml. Such a row is counted here but
    # renders on no page at all (the body loop iterates config.region_names,
    # which excludes it), so the headline silently overstates. That regressed
    # on 2026-06-16 and was patched by mapping the suburbs of the day rather
    # than by removing the mechanism, so it re-arms with every new builder.
    #
    # Summing over the cover's OWN region list makes headline and region
    # lines reconcile by construction, and anything excluded gets shouted
    # about instead of absorbed.
    cover_region_ids = [rid for rid, _y in COVER_REGION_COUNTS]
    total = sum(per_region.get(rid, 0) for rid in cover_region_ids)

    unrendered = {rid: n for rid, n in sorted(per_region.items())
                  if n and rid not in cover_region_ids
                  and not rid.startswith(BOLST_EXTRA_PREFIX)}
    if unrendered:
        print(
            f"WARNING: {sum(unrendered.values())} row(s) routed outside the "
            f"cover's regions and will not appear on any page: {unrendered}. "
            f"Excluded from the TOTAL PACKAGES headline. Fix by mapping the "
            f"suburb in config/suburbs.yml, or by adding the region to both "
            f"the regions: list and COVER_REGION_COUNTS.",
            file=sys.stderr,
        )

    # The mirror-image problem: bolst-extra rows DO render, but have no cover
    # line, so the headline understates the document by exactly their count.
    # The fallback is meant to be empty (it was on 2026-05-25 when it was
    # built); a non-empty one means an REA suburb needs mapping. Warn rather
    # than fold them into the total, because folding would leave the headline
    # disagreeing with the sum of the region lines printed under it.
    if extra_counts:
        print(
            f"WARNING: {sum(extra_counts.values())} REA listing(s) rendered in "
            f"bolst-extra fallback sections: {extra_counts}. These have no "
            f"cover line, so TOTAL PACKAGES understates the document by that "
            f"many. Fix by mapping the suburb(s) in config/suburbs.yml.",
            file=sys.stderr,
        )

    # Mask + overlay date.
    _mask_and_write(pdf, **_scaled(COVER_FIELDS["date"]),
                    text=_fmt_date(report_date))

    # Mask + overlay total.
    _mask_and_write(pdf, **_scaled(COVER_FIELDS["total"]), text=str(total))

    # Mask + overlay each region count, and lay a clickable link band over
    # the whole row (region name through count).
    region_links: dict[str, int] = {}
    for region_id, y in COVER_REGION_COUNTS:
        _mask_and_write(
            pdf,
            x=_scaled_x(COVER_COUNT_X), y=_scaled_y(y),
            w=COVER_COUNT_W * COVER_X_SCALE,
            h=COVER_COUNT_H * COVER_Y_SCALE,
            text=str(per_region.get(region_id, 0)),
            font_size=COVER_COUNT_FONT_SIZE,
            style="",
            color=COVER_COUNT_COLOR,
            align="R",
        )
        link = pdf.add_link()
        region_links[region_id] = link
        center_y = _scaled_y(y) + (COVER_COUNT_H * COVER_Y_SCALE) / 2.0
        pdf.link(
            x=COVER_LINK_X_MM,
            y=center_y - COVER_LINK_ROW_H_MM / 2.0,
            w=COVER_LINK_W_MM,
            h=COVER_LINK_ROW_H_MM,
            link=link,
        )

    return region_links


def build_cover_page_bytes(routed_rows: list[RoutedRow],
                           config: RoutingConfig,
                           *, cover_path: Path,
                           report_date: date,
                           listings: Optional[list[ListingRow]] = None) -> bytes:
    """Standalone single-page cover preview (used by tests / ad-hoc renders).

    The production report builds the cover inline via _render_cover_onto so
    the region links resolve to real region pages. Here there are no region
    pages, so every link is parked on the cover itself (page 1) to keep the
    annotations valid.
    """
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(0, 0, 0)
    region_links = _render_cover_onto(
        pdf, routed_rows, config, cover_path=cover_path,
        report_date=report_date, listings=listings,
    )
    for link in region_links.values():
        pdf.set_link(link, page=1)

    out = BytesIO()
    pdf.output(out)
    return out.getvalue()
