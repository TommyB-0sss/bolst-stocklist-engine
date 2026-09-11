# Bolst Stocklist Engine — Build Log

Granular substep-level tracker. **Read this first when resuming a session** to know exactly where we paused.

Format: `[status] N.N — name (date) — short note`. Status: `[ ]` pending, `[~]` in progress, `[x]` done, `[!]` blocked.

---

## Stage 1 — Skill scaffold + MCP wiring + end-to-end PDF delivery

- [x] 1.1 — Folder skeleton created (2026-05-06) — empty bundle structure: skills/, config/, assets/headers/, routines/
- [x] 1.2 — SKILL.md written (2026-05-06) — entry point declaring what bolst-stocklist-engine does + when Claude should invoke it
- [x] 1.3 — Config YAMLs stubbed (2026-05-06) — builders.yml, suburbs.yml, status-filter.yml, reps.yml, delivery.yml (with full comments + dev/prod routing notes)
- [x] 1.4 — Brand assets copied in (2026-05-06) — 10 banners (Green-01..09 + Green_One Part Cont) + footer.jpg, total ~14 MB. Region→banner mapping TODO during Stage 8.
- [x] 1.5 — Hello-world PDF generator (2026-05-06) — fpdf2 script at skills/render-bolst-pdf/hello.py, outputs to bundle output/. Latin-1 limitation noted (Stage 8 will add DejaVuSans for unicode).
- [x] 1.6 — Microsoft Graph send wiring (DONE 2026-05-08; end-to-end verified, Inam received test email)
         1.6a — [x] App registered in Bolst tenant (single-tenant). Client ID + Tenant ID stored in .env.
         1.6b — [x] Mail.Read + Mail.Send + Mail.ReadWrite delegated; admin consent granted by Inam-as-Tom.
                Public client flows enabled (required for device-code flow).
         1.6c — [x] Fresh venv at .venv/ (Python 3.10.0). Installed msal 1.36.0 + python-dotenv 1.2.2 +
                fpdf2 2.8.7. Pinned in requirements.txt.
         1.6d — [x] lib/auth.py written — device-code flow + SerializableTokenCache → .credentials/token.json.
                Single get_access_token() function used by all skills.
         1.6e — [x] First-run sign-in complete. Inam signed in as Tom via login.microsoft.com/device.
                Refresh token cached (~90 days valid).
         1.6f — [x] skills/compose-and-send/send_test.py — thin orchestrator using lib/pdf_render.py
                + lib/graph_send.py. Returns 202 Accepted from Graph. Hello PDF (1,231 bytes) confirmed
                received at inam@meetapex.ai 2026-05-08.

       Architecture decision 2026-05-08 (during refactor): created proper lib/ package for shared
       Python code so skill folders stay thin. lib/pdf_render.py owns PDF generation; lib/graph_send.py
       owns Graph sending; future lib/graph_read.py for ingest. Skill scripts (.py inside skills/<name>/)
       are CLI orchestrators that import from lib/. Bundle root added to sys.path at script entry —
       standard pattern. This avoids hyphen-vs-underscore folder name conflicts and keeps lib reusable.
       hello.py also refactored to import from lib.pdf_render (no duplicate PDF code).
- [x] 1.7 — Read test against Tom's live Outlook (2026-05-08) — done via MCP connector, not Python/Graph.
       Confirmed Tom's mailbox is alive, top result was Aaron Wilson reply to Tom on a price reduction.
       Surfaced the 6 builder senders + cadences. Re-do via Python/Graph token after 1.6e completes.
- [x] 1.8 — Inbox survey + builder sender mapping (2026-05-08) — searched Tom's inbox per builder.
       Confirmed all 6 stocklist senders + format + cadence. Discovered:
         - `bolst-property-group-data\` is organized by SENDER EMAIL — Tom did the mapping for us
         - Hermitage emails have NO PDF attachments; data lives behind a CTA link → CDN PDF
         - Hermitage PDF URL is predictable: `hubfs/6368574/{DDMMYY}.pdf` on hs-6368574.f.hubspotstarter.net
         - Hermitage redirect chain verified end-to-end: tracking URL → JS interstitial → 307 → PDF
         - Hermitage PDF is publicly fetchable (no auth/cookies); 5 pages of clean tabular data;
           region routing baked into section headers; "ONE PART CONTRACT" flagged in Street column
         - Urbane confirmed: Tyana Troise primary canonical sender; HubSpot/Mikayla as secondary
         - Aldrich's Corey sends both canonical stocklists AND per-package emails — need subject filter
         - Luxton's Stefan emails come via two channels: MailChimp (no attachment, link-only) +
           direct Outlook with XLSX/PDF attachments; filename-pattern naturally skips MailChimp
         - Aplace canonical sender is `aplacevic`; Stephanie's per-package PDFs are noise (Phase 1.5)
- [x] 1.9 — builders.yml updated with live data (2026-05-08) — replaced 2026-05-06 stub.
       Added: `ingestion: html_link` mode for Hermitage with primary URL template + fallback
       button-text strategy; `subject_filter` for Aldrich; `secondary_senders` for Urbane;
       routing-order fix for Aplace (Put-Call before GENERAL).

---

## Test-then-integrate strategy (for Stage 1.6f and beyond)

Until reports are mature, the daily PDF goes to **Inam**, not Tom. This protects Tom's live inbox from buggy / wrong reports during dev.

| Phase | Recipient of report | When to flip |
| --- | --- | --- |
| Build phase | inam@meetapex.ai | Default for all dev sends |
| Mature phase | Tom's inbox | Once 2–3 consecutive days of reports look correct manually reviewed by Inam |
| Phase 1.5 | Tom + Aaron + Howard | After Tom approves rep fan-out and signatures arrive |

`delivery.yml` recipient field will update at each transition. No code change required.

## Stage 2 — Ignite REA parser + Bolst Listings tab

Resolution path locked 2026-05-23: **Option B — Tom configures REA Ignite to email
daily Active Listings CSV to his own Outlook.** Domain.com.au path dropped (commercial
team stalled). See memory: project_bolst_phase1_locked.md, project_bolst_listings_layout.md.

- [x] 2.1 — Sample CSV survey + parser design (DONE 2026-05-23). 15-column Ignite export
       (`HomeLandPkg_Active_All_Agents_20260501.csv`, 132 rows). Confirmed UTF-8 encoding
       (early cp1252 attempt was wrong — Windows console display was the source of mojibake,
       not the file). Discovered: bath/car NOT in CSV (Title/Description marketing copy only,
       60/132); STATUS not a column (Active Listings export → implicit Active); Authority
       column empty for all rows; Bedrooms IS a column (2-6).
- [x] 2.2 — ListingRow dataclass (DONE 2026-05-23). Separate from StocklistRow because
       REA Active Listings ≠ builder stock. Added `lib/parsers/types.py::ListingRow` with
       lot/address/raw_address/estate/suburb/title_status/bed/price/price_int/listing_agent/
       listing_url/property_id + meta dict for audit.
- [x] 2.3 — REA Ignite parser (DONE 2026-05-23). `lib/parsers/rea_ignite.py`. Header-validated
       (raises loudly if Tom's export config reorders columns). Lot regex widened to catch
       128/132: `Lot N`, `Lot.N`, `Lot - N`, `LOT-N` variants. Estate extracted from
       `(...)` in address. Lot prefix stripped from address column at parse time. Title-status
       regex catches 56/132 (rest = `-`; deferred regex tuning).
- [x] 2.4 — Bolst Listings PDF page (DONE 2026-05-23). `lib/pdf_render.py::_render_bolst_listings`.
       8-col parity with senders (Inam decision — override of original 7-col spec in
       Bolst_Phase1_Plan.md line 77). AGENT replaces STATUS in the last slot. Brand-green
       title bar in place of region banner. Reuses `_draw_table_header` (new optional
       `headers` arg), `_truncate_to_width`, `_draw_footer`. New page inserted into
       `build_report_pdf` between cover and regional pages via optional `listings=` kwarg.
- [x] 2.5 — Render-layer normalisations (DONE 2026-05-23). Applied to BOTH sender + Bolst
       Listings pages: suburb → Title Case (`_titlecase_suburb`), status → Title Case
       (`_fmt_status` updated). **Critical:** stays at render only — `lib/status_filter.py`
       must see raw status to match its drop-list. Sort policy changed on both pages from
       suburb+price-ASC to suburb+price-DESC (price-null rows last). Latin-1 safety helper
       (`_safe_latin1`) for unicode punctuation in REA descriptions / agent names.
- [x] 2.6 — Local orchestrator (DONE 2026-05-23). `skills/render-bolst-pdf/render_local.py`
       mirrors `send_report.py` but: 6 builders from Outlook via existing `fetch_all_for_builder`,
       REA from local CSV (default = sample, `--rea-csv` to override), no Graph send. Writes
       to `output/bolst-local-YYYY-MM-DD.pdf`.
- [x] 2.7 — Sample render against live data (DONE 2026-05-23). 526 rows from 6/6 builders,
       498 kept after status filter, 132 REA listings → 30-page PDF, 14.5 MB. Verified:
       column header parity, sort order (suburb alpha + price desc), suburb title-casing,
       status title-casing, "Lot N" prefix stripped from address, estate extracted from
       parens where present. Output: `output/bolst-local-2026-05-23.pdf`.
- [x] 2.8 — Live REA CSV ingest wired (2026-05-25). Tom now emails himself daily
       "REA CSV" with attachment "REA Listings.csv"; `config/builders.yml` got a
       `rea` entry (sender=Tom, subject_filter, filename pattern). Orchestrator
       (`skills/compose-and-send/send_report.py`) calls `_ingest_rea_listings()`
       after the 6 builder ingest. Non-fatal — missing export logs a warning,
       report still ships builder-only. End-to-end verified 2026-05-25: 121 REA
       listings + 526 builder rows → 29-page PDF, 14.5 MB.

       Same-day layout reshape (Substep A.1, Inam): REA listings no longer get
       their own page. They fold into the 10 regional sections by suburb (same
       suburbs.yml lookup as builder rows). AGENT column dropped; REA rows use
       STATUS="Available". Sort within suburb flipped to price ASCENDING.
       Defensive `bolst-extra:<suburb>` fallback sections after the 10 regions
       (zero this run — audit confirms 100% suburb coverage).

       Pre-flight audit work (`tests/audit_suburbs.py`) found 22 unmapped Vic
       suburbs (mostly Gippsland + Goulburn Valley + Warrnambool itself missing
       its self-mapping). All added to `config/suburbs.yml` — now 87 entries.
       Borderline calls: Bunyip→gippsland, Kilmore→metro-north, Swan Hill→
       regional-north-east (Murray-corridor extension; Mallee isn't really
       Bolst's catchment).

       Specialised parser bug fixed (`lib/parsers/specialised.py`): section
       headers like "SWAN HILL - HEIRLOOM ESTATE" kept the generic " ESTATE"
       suffix in `estate_word_count`, misaligning data rows by one token
       (showed "Ave Swan" suburb, "Coronation" street). New SECTION_ESTATE_SUFFIX
       regex strips it before counting. Two Swan Hill rows now correct.

       Output sample: `output/bolst-stocklist-2026-05-25.pdf` (production
       orchestrator) and `output/bolst-local-2026-05-25.pdf` (local renderer
       equivalent). Per [[feedback-preview-client-emails]] the morning report
       is not auto-sent during build phase; Inam reviews each output before
       it goes to Tom.

## Stage 3 — Aplace parser

- [x] 3.1 — Inspect samples + define column mapping (2026-05-08). Both Aplace files share
       the same 16-column layout: SUBURB, LOT NO, ADDRESS, ESTATE, TITLES, LAND SIZE (m2),
       LAND DIMENSIONS, LAND PRICE, HOUSE TYPE, FAÇADE TYPE, HOUSE SIZE (m2), BED BATH CAR,
       HOUSE PRICE, TOTAL PACKAGE PRICE, RELEASE TYPE, STATUS. GENERAL is 8 pages (one
       region per page); Put-Call is 4 pages, header reads "STATUS STATUS" (duplicate label,
       but content is release_type + status — handled via positional indexing).
- [x] 3.2 — pdfplumber 0.11.9 installed; pinned in requirements.txt. Created
       lib/parsers/__init__.py and lib/parsers/types.py (canonical StocklistRow dataclass —
       single source of truth for row shape, reused by all 6 parsers).
- [x] 3.3 — lib/parsers/aplace.py written. Uses pdfplumber.extract_tables() per page;
       header-row detection via SUBURB cell content; helper functions for money / int /
       float / bed-bath-car cleaning; page region extracted from "Victoria - <foo>" header
       line. ~150 lines.
- [x] 3.4 — tests/validate_aplace.py written. Runs parser against both samples, reports
       row counts by region/status/release_type, flags rows with missing critical fields
       and suspiciously low land prices (typo detection).
- [x] 3.5 — validated. GENERAL: 66 rows / 8 regions / 3 statuses (incl "Reverved" typo
       passed through); Put-Call: 25 rows / 4 regions / 2 statuses (incl EOI). 91 rows
       total. Zero rows with missing critical fields. $448 land-price anomaly flagged.

Architectural decisions for parsers (set 2026-05-08, applies to all 6):
  - Parsers live at lib/parsers/<builder>.py. They expose `parse(file_path) -> list[StocklistRow]`.
  - Parser stays dumb: produces clean rows, no Bolst-tab semantics. is_one_part is set
    by the ingest orchestrator based on builders.yml routing rules (file-glob OR row-content).
  - Each parser has a sibling validator at tests/validate_<builder>.py with row-count and
    field-coverage assertions.
  - Builder-specific quirks (e.g. Aplace's "STATUS STATUS" duplicate header) handled via
    positional indexing rather than column names.

## Stage 4 — Luxton parser (XLSX-based, 3 file types)

- [x] 4.1 — Inspect samples (2026-05-08). 4 files on disk; 3 unique
       data sources. Decision: **skip the PDF** ("Luxton Homes - One Part
       Contracts - Sheet1.pdf") because it's a print-export of the One
       Part XLSX with mangled table boundaries (pdfplumber returns 1-col
       garbage). Same rows live cleanly in the XLSX. Three XLSX modes
       to handle:
         A. "House & Land Packages"   — main weekly (13 real data rows)
         B. "One Part Contracts"      — weekly one-part (20 real rows)
         C. "THORNHILL GARDENS - ..." — agent superlot (11 real rows)
       Per Inam's direction (Tom wants ALL Luxton data), all three are
       in scope. openpyxl 3.1.5 + et-xmlfile 2.0.0 added to
       requirements.txt.

       Stefan's data has known typos that must be preserved:
         - "Contact signed" (sic) status in House & Land
         - "Thorrnhill Gardens" (sic) estate in One Part (same estate
           also appears correctly as "Thornhill Gardens" — both must
           coexist after parsing)
         - "Pearl " trailing-space estate — judged invisible whitespace,
           collapsed by _clean_str (visible typos are preserved; invisible
           ones are not)
       Status casing is wildly inconsistent across files (AVAILABLE /
       Available / Hold / HOLD / SOLD / EOI / CONTRACT SIGNED / Contract).
       Parser preserves raw casing; Stage 7 status-filter.yml does
       case-insensitive matching.

- [x] 4.2 — lib/parsers/luxton.py written (2026-05-08). Single
       `parse(file_path)` entry point dispatches on the title cell at row
       0 to one of three mode handlers. Mode A reads col 0 = sequence
       number (skipped) and shifts all data by +1. Mode B has no LAND $
       column (one-part = lump sum) and uses ETA SETTLEMENT in place of
       TITLES. Mode C parses B.L.B.G. format ("3.1.1.2") into bed +
       living + bath + car via a single regex helper.

       Excel quirks handled: integer-looking cells return as 4.0 not 4
       (float coerced via `value.is_integer()` check); money columns are
       sometimes string ("$405,000") and sometimes raw int (681350) in
       the same file — _clean_money handles both. A 5-row blank-streak
       tolerance walks past the blank separator row in Mode A and stops
       before openpyxl's inflated max_row trailing padding.

       is_one_part is automatically True for every Mode B row, False for
       Modes A and C. meta carries living count, download flag, notes,
       sales_brochure, pos, and (for Mode C) superlot=True.

- [x] 4.3 — tests/validate_luxton.py written (2026-05-08). Runs all 3
       files through one `parse()` call, checks per-mode expectations
       (row counts, is_one_part flag, presence/absence of land_price,
       Mode C all-Thornhill-Gardens), arithmetic integrity for Mode A,
       and source-defect preservation regression checks for both typos.

- [x] 4.4 — validated (2026-05-08). 13 + 20 + 11 = 44 rows across 3
       files. All checks pass: "Contact signed" (sic) preserved, both
       spellings of Thornhill/Thorrnhill coexist, all 20 One Part rows
       carry is_one_part=True with land_price=None and build_price=None,
       all 11 Superlots rows have meta['superlot']=True and Thornhill
       Gardens E/F estates, B.L.B.G. parse rate 100%, House & Land
       arithmetic 100% clean.

Stage 4 lessons learned (set 2026-05-08):
  - **Skip the PDF.** When a builder sends both XLSX and PDF, prefer
    XLSX every time. PDFs of XLSX data are print-exports with mangled
    table extraction; the same rows live cleanly in the source XLSX.
  - **Multi-mode parsers via a row-0 dispatch.** When one builder sends
    multiple file types with related schemas, single `parse()` entry +
    title-cell dispatch keeps builders.yml simpler than registering
    multiple per-file parsers.
  - **openpyxl quirks worth knowing**: max_row is inflated by formatted
    empty trailing rows (One Part reports 883, real is 20). Walk with a
    blank-streak tolerance and a key-column check. Integer cells return
    as floats (4.0) — handle in _clean_int via `value.is_integer()`.
  - **Source-defect preservation has a sensible boundary**: visible typos
    ("Contact signed", "Thorrnhill Gardens") preserved via raw-string
    pass-through; invisible typos (trailing whitespace) not preserved
    because they're typing accidents, not semantic.

## Stage 5 — Specialised parser

- [x] 5.1 — Inspect sample (2026-05-08). 5 pages, ~32 sections (one per estate),
       9 columns: LOT NO. / ADDRESS / SUBURB / ESTATE / TITLES / AREA / FLOORPLAN /
       BED-BATH-CAR (icons header) / PACKAGE PRICE. Section headers like "BENALLA -
       LIVINGSTON" precede each section. No STATUS column (parser defaults Available).
       Bed-bath-car uses dashes "4 - 2 - 2" (Aplace used spaces). Date format "Sept-26"
       seen alongside standard "Dec-26".
- [x] 5.2 — First attempt with pdfplumber.extract_tables() returned 36/52 rows —
       alternating-row striping caused the line-based table detection to split each
       section into multiple sub-tables and drop shaded rows.
- [x] 5.3 — Pivoted to text-based parsing using pdfplumber.extract_text(). State
       machine: track current section context (suburb_word_count + estate_word_count
       from header), regex-match data row tail (price/bed-bath-car/floorplan/area/titles
       from the right), then deterministically slice the leading "<lot> <address...>
       <suburb...> <estate...>" using section's word counts. lib/parsers/specialised.py
       written.
- [x] 5.4 — tests/validate_specialised.py written.
- [x] 5.5 — validated. 52 rows / 26 suburbs / 31 estates / 5 home designs (Forbes 17
       dominates with 32 rows). Multi-word suburbs (Melton South, Smythes Creek,
       Thornhill Park, Winter Valley) and estates (Narracan Waters, One Mile Creek,
       McMahons Place, The Reserve / Lookout / Outlook / Willows) handled correctly.
       No rows missing critical fields. Price range $576K–$776K.

Pattern divergence noted (applies to remaining parsers): pdfplumber's table extraction
is brittle on visually-styled PDFs. When extract_tables() drops rows, fall back to
extract_text() + line-by-line regex with a state machine. Aplace parser uses tables;
Specialised uses text. Stage 6 (Hermitage) will likely use tables again since the
Hermitage PDF we already inspected is well-structured.

## Stage 6 — Aldrich + Hermitage + Urbane parsers

Order chosen: Hermitage → Aldrich → Urbane. Hermitage first because it
validates the `ingestion: html_link` mode end-to-end and was the riskiest
parser of the three.

### Hermitage

- [x] 6.1 — Inspect sample (2026-05-08). 5 pages, single repeating 13-column
       layout (Lot No / Street / Land m2 / Titles / Land Price / Home Design /
       Facade / Bed / Storey / House m2 / Build Price / Total Price / Status).
       4 region headers (NORTHERN / SOUTH-EASTERN / WESTERN / REGIONAL) plus
       a leading "PACKAGES OF THE WEEK" section that has no region label of
       its own. Section headers split on first comma into (estate, suburb)
       after stripping postcodes / energy-rating / "% Deposit" suffixes.
       Multi-token Home Design values ("Nexus 25 (Dual Key)", "Leon 22 GE -
       1B") rule out text-based regex slicing without significant care.
       Sample has zero ONE PART CONTRACT rows and only "Available" status —
       both edge cases untestable from this file.
- [x] 6.2 — lib/parsers/hermitage.py written (2026-05-08). Initial strategy:
       extract_tables() per page + Y-position correlation between table
       bboxes and section header text. **Smoke test failed silently** — only
       5 distinct (region, estate, suburb) tuples vs. 44 expected, because
       pdfplumber returns ONE giant table per page (no horizontal rule lines
       between sub-sections), so every row inherited the last-seen header
       above the table's top.
       Refactored to per-row Y correlation: each `table.rows[i].bbox[1]` is
       pushed onto the same timeline as header events, giving each row its
       correct estate/suburb context. `_row_is_data` also tightened to
       require non-empty Street and Land m2 (filters page-header date
       sweeping into the giant table as cell 0 of row 0).
- [x] 6.3 — tests/validate_hermitage.py written (2026-05-08). Standard
       row-count + field-coverage checks plus two Hermitage-specific guards:
       (a) arithmetic integrity (land_price + build_price ≈ total_price
       within $5 — Hermitage is the first builder where totals are exact
       arithmetic), (b) frozen-reference regression check on per-region row
       and estate counts (returns exit code 2 if anything drifts).
- [x] 6.4 — validated (2026-05-08). 149 rows / 5 regions / 44 distinct
       (region,estate,suburb) tuples. Breakdown: PACKAGES 9/1, NORTHERN 19/8,
       SOUTH-EASTERN 18/6, WESTERN 29/11, REGIONAL 74/18. All field coverage
       passes. Arithmetic check flagged 1 anomaly: row 128 lot 517 Moore St,
       build_price `$34,900` (almost certainly a dropped leading "3" — should
       be `$349,000`, since 239k + 349k = 588k exactly). Genuine source-PDF
       defect, not a parser bug — worth surfacing to Tom.

Lessons learned for future parsers (set 2026-05-08, applies to remaining 3):

  - For any builder where multiple sub-sections share a page, **smoke-test
    table grouping before writing the validator**. Run the parser, count
    distinct (region, estate, suburb) tuples, compare against your inspection
    estimate. If they don't match, pdfplumber is bundling sub-sections — pivot
    to per-row Y correlation BEFORE writing tests against bad output.
  - Per-row Y correlation pattern: build a single timeline of (Y, kind, payload)
    events on each page, where data rows use `table.rows[i].bbox[1]` and
    header text uses `extract_text_lines()` line tops. Sort by Y, walk in
    document order, maintain (region, estate, suburb) state, emit each data
    row tagged with current state. This pattern will likely apply to Aldrich
    and Urbane if their PDFs have similar styling.
  - Add an arithmetic-integrity validator check whenever the source includes
    explicit summed totals — costs ~10 lines, catches real source defects.

### Aldrich

- [x] 6.5 — Inspect sample (2026-05-08). Single sample `Stocklist C44.pdf`,
       6 pages, 19 columns. Structurally simpler than Hermitage: every row
       carries its own Estate Name + Suburb + Status as cells, so no
       Y-correlation needed. Region label sits at the top of each page
       (`Exclusive Packages` / `West` / `North` / `South-East` / `Geelong`).
       New fields beyond the canonical StocklistRow shape: Orientation,
       Garage (string, not int — distinct from `car`), Land Rebate /
       Discount, Storeys. No Street column, no Facade column. Status
       vocabulary richer than other builders: 6 values (Available, Exclusive,
       On Hold, Not Available, Sold, Resale).
- [x] 6.6 — lib/parsers/aldrich.py written (2026-05-08). One pass per page:
       lift region from first text line, extract_tables() for cells, build
       StocklistRow per row with overflow fields → meta. Defensive
       `_clean_str` collapses internal whitespace including newlines, so
       wrapped estate names (e.g. "Cloverton Midtown Estate" splits across
       two visual lines on page 4) come through as one clean string.
       land_dimensions composed as "WIDTH x LENGTH" to match Aplace's format.
- [x] 6.7 — tests/validate_aldrich.py written (2026-05-08). Standard checks
       plus three Aldrich-specific guards: status vocabulary completeness
       (all 6 expected statuses present), Cloverton wrap regression (3 rows
       with full "Cloverton Midtown Estate" preserved), and the same
       arithmetic-integrity check used for Hermitage.
- [x] 6.8 — validated (2026-05-08). 134 rows / 5 regions (Exclusive
       Packages 14, West 51, North 19, South-East 12, Geelong 38). All 6
       statuses present. Zero missing-field rows. Zero arithmetic
       mismatches — Aldrich's source data is clean. 32 rows (24%) carry a
       land_rebate value. Cloverton wrap preserved correctly on all 3 rows.
       Aldrich was a one-shot parser — smoke test passed without any
       refactor, validating the prediction that builders with row-self-context
       are dramatically simpler than those with section-header context.

### Urbane

- [x] 6.9 — Inspect sample (2026-05-08). Single sample
       "Urbane Homes H&L Package Stocklist - April 2026 (24-04) - v001.pdf",
       3 pages (page 3 is empty footer notice). 15 logical columns of data
       (LOT NO / STREET NAME / SUBURB / ESTATE / LAND SIZE / LAND DIMENSIONS /
       ORIENTATION / TITLES / HOUSE TYPE / BED BATH CAR / FACADE / BUILD
       PRICE / LAND PRICE / HOUSE & LAND TOTAL / NOTES). Worst-of-both
       structure: row-self-context like Aldrich (estate + suburb in cells)
       AND inline `/// METRO NORTH \\\` style region markers like Hermitage.
       Quirks: land size has unit suffix ("349m2"), house type sometimes
       spaceless ("Brampton192"), bed-bath-car uses dashes ("4-2-2") not
       spaces, no Status column (every listed row is implicitly Available),
       facade typo "Sevile" (sic) on lot 315 Perons Road (preserved as-is),
       Mambourin Green estate wraps over two visual lines on lot 502.
       Folder-name confusion: data folder is `mikayla...@orbithomes.com.au`
       (Mikayla works for Orbit, distributing Urbane via HubSpot); per
       Inam's direction, parser is sender-agnostic — Tyana Troise's direct
       attachment route uses the same parser.
- [x] 6.10 — lib/parsers/urbane.py written (2026-05-08). Per-row Y
       correlation timeline (from Hermitage) for region tracking, plus
       direct cell extraction for estate/suburb (from Aldrich). Initial
       smoke test returned 0 rows because **pdfplumber emits 16 cells per
       row, not 15** — an empty leading column for the left page margin
       sits at index 0, shifting every data column by +1. Fixed by bumping
       all column indices and updating column-count check to >= 15. Second
       smoke-test attempt exposed a **second issue: page 2 region markers
       have trailing junk** ("/// GEELONG \\\ o" with stray "o" leaked from
       adjacent column-header letter-spacing fragments). Fixed by removing
       the `$` anchor from `REGION_LINE` regex so trailing characters are
       ignored.
- [x] 6.11 — tests/validate_urbane.py written (2026-05-08). Standard checks
       plus: status all-Available regression, 100% bed/bath/car parse rate,
       arithmetic integrity, Sevile (sic) source-defect preservation,
       Mambourin Green wrap regression.
- [x] 6.12 — validated (2026-05-08). 42 rows / 4 regions (METRO NORTH 3,
       METRO WEST 24, GEELONG 7, METRO SOUTHEAST 8). Zero missing critical
       fields. Zero arithmetic mismatches. 100% bed/bath/car parsed.
       14 rows carry notes ("$25K Land Rebate Applicable", "*Within 50m of
       Overhead Transmission Lines"). Sevile typo preserved on the one
       expected row. Mambourin Green wrap merged correctly.

Stage 6 lessons learned (set 2026-05-08):

  - **pdfplumber empty-margin column is real**. Urbane added an empty
    leading cell to every row (left margin). Whenever a future builder's
    smoke test returns 0 rows or has off-by-one column readings, dump
    `extract()[0]` first to confirm cell count and re-anchor indices.
    Don't trust visual column count from rendered output — always verify.
  - **Inline section markers can carry trailing junk**. Page-spanning
    column-header artifacts sometimes leak letter-spacing fragments onto
    region-marker text lines. Avoid `$` anchors in marker-detection regex
    when the styled cell uses character-by-character rendering.
  - **Source-defect preservation is a feature, not a bug**. Urbane's
    "Sevile" (sic) typo and Hermitage's $34,900 missing-digit are the
    builder's data, not ours to silently fix. Validators should
    affirmatively check that we passed them through unchanged so future
    parser refactors don't accidentally normalise them.

## Stage 7 — Region routing + suburb map + Uncategorised tab

- [x] 7.1 — Inventory suburbs across all 6 live datasets (2026-05-08).
       67 distinct suburb keys across 514 rows. Strong cross-builder
       agreement on most metro suburbs; 6 borderline cases needed rulings.

- [x] 7.2 — Confirmed Bolst's 10 canonical regions from existing
       config/suburbs.yml stub: One Part Contracts, Geelong & Colac,
       Gippsland, Horsham, Metro North, Metro South East, Metro West,
       Regional North East, Regional West, Warrnambool. 9 numbered
       banner images + 1 One-Part banner in assets/headers/. Banner-to-
       region mapping deferred to Stage 8 (filenames are
       Green-01..Green-09, non-descriptive).

- [x] 7.3 — config/suburbs.yml fully populated (2026-05-08). 62 suburb
       mappings covering every distinct suburb in live data, plus 2
       aliases (Frasers Rise→Fraser Rise, Mt Duneed→Mount Duneed) and
       3 source-defect cases handled via routing-layer pre-normalisation
       (parens-strip for "Bonshaw (Ballarat)", comma-split for "Penndale
       Street, Tarneit" / "Tarnala Road, Tarneit"). Echuca intentionally
       unmapped — routes to Uncategorised on first run for Tom's
       confirmation (single-builder Specialised, no adjacency signal).
       Borderline rulings extracted from live data: Wallan/Woodstock→
       Metro North (adjacency to Beveridge/Donnybrook); Nar Nar Goon→
       Metro South East (Aplace tagging consistent with Officer);
       Winchelsea/Elliminyt→Geelong & Colac (adjacent to Colac).

- [x] 7.4 — lib/routing.py written (2026-05-08). Single entry point
       `route(rows, config) -> list[RoutedRow]`. RoutedRow wraps original
       StocklistRow with region_id + routing_reason + meta. Two
       precedence rules: (1) is_one_part=True overrides suburb routing
       to "one-part-contracts"; (2) suburb pre-normalise → alias →
       suburb_to_region lookup; uncategorised fallback. Featured marker
       (Hermitage PACKAGES, Aldrich Exclusive) flows through as
       meta["featured"]=True without changing region — Stage 8 decides
       presentation. PyYAML 6.0.3 added to requirements.

- [x] 7.5 — config/status-filter.yml + lib/status_filter.py
       (2026-05-08). Drop list per Inam's directive: only Sold + Contract
       Signed (case-insensitive). Forward-compatible drop-list (not
       allow-list) — new status values default to keep. Stefan's
       "Contact signed" typo explicitly kept per Inam, documented in
       YAML comment for future Tom review.

- [x] 7.6 — Featured-section policy resolved (2026-05-08). Decision: no
       separate region. Featured rows route by suburb to their
       geographic region with meta["featured"]=True flag. Stage 8 PDF
       render decides whether to highlight or promote to top of section.
       Composes correctly with is_one_part: Hermitage Wallan rows that
       are BOTH featured AND one-part route to one-part-contracts and
       still carry the featured flag.

- [x] 7.7 — tests/validate_routing.py (2026-05-08). End-to-end Stage 7
       validator covering parsers → routing → status filter pipeline.
       Tests STRUCTURAL invariants only: row count preservation,
       region_id validity, is_one_part precedence + corollary, featured-
       flag bidirectional consistency, status-filter case-insensitivity,
       Stefan typo explicitly kept by design.

Live-data routing distribution (514 rows in, 484 kept after status filter):
  metro-west             151      gippsland               47
  geelong-colac           96      metro-south-east        37
  metro-north             83      regional-west           31
  regional-north-east     23      one-part-contracts      13
  uncategorised            2      warrnambool              1
  (Horsham: 0 — no stock this week, region kept for future)

  Status-dropped: 30 rows (CONTRACT SIGNED 17 + Sold 12 + SOLD 1).
  Featured: 25 rows (Aldrich Exclusive 14 + Hermitage PACKAGES 11).
  Uncategorised: 2 Echuca rows (intentional — Tom's call on first review).

Stage 7 lessons learned:
  - **Adjacency-driven routing extracts well from live data** — 5 of 6
    borderline suburbs got high-confidence rulings from neighbour evidence
    + cross-builder consistency. Only 1 (Echuca) had no signal and was
    deferred to Uncategorised — exactly what Uncategorised is for.
  - **Source-defect normalisation belongs in routing, not parsers**.
    Parsers stay pure pass-through; routing's `_normalise_suburb` strips
    parens / takes last comma-segment / uppercases / applies aliases.
    Tested via 5 known defects all resolving correctly without parser
    changes.
  - **Featured flag composes with is_one_part.** Hermitage's Wallan
    one-part rows are BOTH featured (PACKAGES OF THE WEEK) AND one-part.
    Routing puts them in one-part-contracts (precedence) and keeps
    featured=True. Stage 8 can decide both visual treatments
    independently.
  - **Forward-compatible status drop list.** Only 2 entries (Sold,
    Contract Signed). New status values from any builder default to KEEP
    rather than silently disappearing. Tom adds to drop list as needed.

## Stage 8 — Branded PDF render

- [x] 8.1 — Layout decisions locked with Inam (2026-05-08).
       Landscape A4. Show all 10 regions (empty regions render banner +
       "No packages this week" message). Page break per region with
       "(continued)" subtitle on overflow pages. Footer image on last
       page only. 8-column table widths sum to 257mm centred in 277mm
       usable width.

- [x] 8.2 — Verified Latin-1 sufficiency (2026-05-08). Probed all 484
       kept rows across 8 string fields; zero non-Latin-1 characters.
       Default Helvetica is sufficient — no DejaVuSans bundling needed,
       saves ~700KB and reduces install complexity. Builder data is all
       Latin script.

- [x] 8.3 — lib/pdf_render.py build_report_pdf() implemented
       (2026-05-08). Bolst brand palette extracted from banner JPGs:
       dark green #0D3823 + gold #C9A24A. Per-region rendering: banner
       at top → subtitle "Stocklist as at <date> | N packages" →
       8-column table (header bg dark green / white text; alternate row
       stripe #F8F8F8 for legibility). Manual page-break management
       with continuation-page support (no banner repeat to save space,
       but subtitle + table header redraw).

- [x] 8.4 — Format helpers: _fmt_date ("8 May 2026" — strips POSIX %-d
       for Windows compat), _fmt_currency ("$XXX,XXX" or "-" if None),
       _fmt_bbc ("4-2-2" or "-" if any cell missing), _fmt_status
       (default "Available" for None/blank). _truncate_to_width adds
       ellipsis for cells that would overflow column width.

- [x] 8.5 — Featured row highlighting (2026-05-08). 25 rows flagged
       this week (Aldrich Exclusive 14 + Hermitage PACKAGES 11) get a
       light-gold background tint #F5E6D3 that overrides the alt-row
       stripe. Subtle, matches Bolst's gold accent, scannable without
       disrupting table flow. Per Inam directive "if actual design is
       ambiguous then do in best way possible".

- [x] 8.6 — End-to-end pipeline run (2026-05-08). 514 parsed → 514
       routed → 484 kept (status filter dropped 30) → 23-page PDF
       (14.2MB). Page distribution: 1 (One Part 13 rows) + 4 (Geelong
       96 rows) + 2 (Gippsland 47) + 1 (Horsham empty placeholder) +
       3 (Metro N 83) + 2 (Metro SE 37) + 5 (Metro W 151) + 1 (RNE 25) +
       2 (Regional W 31) + 1 (Warrnambool 1) + 1 (Footer) = 23.
       Output: output/bolst-stocklist-2026-05-08.pdf.

- [x] 8.7 — tests/validate_report_pdf.py written (2026-05-08).
       Structural-invariant checks: PDF magic-bytes valid, page count
       >= 11 (10 regions + footer), Landscape A4 dimensions, every
       region produces a subtitle, empty regions show placeholder,
       column-header line appears for every non-empty region. Drift-
       tolerant — no specific row-count assertions.

Stage 8 v1 lessons learned:
  - **PDF size is large** (14MB). Driven by 4843×709 px banner JPGs
    embedded at full resolution × 10 regions. Acceptable for email
    attachment (Outlook 25MB limit) but worth optimizing in Stage 8.x
    if Tom flags it. Quick fix: resize banners to ~1500px wide before
    embedding (saves ~75% size with no visible quality loss at 277mm
    landscape width).
  - **Manual page-break management beats auto_page_break** when the
    table needs context-redraw on overflow. fpdf2's auto break doesn't
    redraw column headers; doing it manually with explicit y-position
    checks gives clean continuation pages.
  - **Latin-1 sufficiency was a real check, not paranoia.** All 484
    rows verified clean — saves bundling DejaVuSans. If a future
    builder ever sends Unicode (em-dash in estate name, smart quotes
    in notes), the parser will preserve it but render will fail; that's
    the right time to add DejaVuSans, not preemptively.

- [x] 8.8 — Footer placement fixed (2026-05-08, end of session). Initial
       implementation rendered footer at vertical centre of a dedicated
       final page (looked wrong — empty page with floating footer).
       Reworked `_draw_footer` to pin the footer to the bottom of the
       current page (5mm from page edge) and only add a new page when
       the last region's data left less than 45mm of vertical space.
       Page count went 23 → 22 with the fix; validator still passes.

## Stage 8.x — Polish pass (2026-05-09 session with Inam)

Inam reviewed the 2026-05-08 PDF and gave 8 directives. All landed plus
an additional cover-design overlay and a late-session datetime fix.
Pipeline now produces a 24-page PDF (cover + 10 regions w/
footer-per-section). Live row counts after the new "Contract Issue"
filter: 514 parsed → 482 kept (was 484 — 2 more dropped).

- [x] 8.x.1 — Field-coverage audit across all 6 senders (2026-05-09).
       New script `tests/audit_field_coverage.py` runs every parser and
       reports per-builder Address (street) + Bed/Bath/Car coverage.
       Findings:
         • Aplace, Specialised, Urbane: 100% on both fields ✓
         • Aldrich: 0% Address (source has no Street column) +
           0% car (parser stored Garage in meta but set car=None)
         • Hermitage: 100% Address + 0% bath/car (source has Bed +
           Storey only, no bath/car columns at all)
         • Luxton: 0% Address (XLSX has ESTATE/REGION/LOT/SUBURB
           but no street column), 100% bed/bath/car
       Live Outlook spot-check confirmed Urbane fixture stale (Tyana
       2026-05-08 vs our April Mikayla) and Aldrich fixture stale (C44
       vs Corey 2026-05-05). Other 4 senders fresh.

- [x] 8.x.2 — Aldrich parser: Garage → car mapping (2026-05-09).
       Added `_garage_to_car` helper: Single=1, Double=2, Triple=3,
       Quad/Quadruple=4 (case-insensitive). Recovered car field for
       all 134 Aldrich rows. Raw garage string still preserved in
       meta["garage"] for traceability.

- [x] 8.x.3 — Luxton parser: Thornhill Park column-shift recovery
       (2026-05-09). Stefan's H&L sheet has a known defect where
       blank LAND $ in lots 313 + 318 shifted cols 6..11 left by 1
       (HOUSE name landed in LAND $ cell, etc — flagged in
       2026-05-08 verification milestone, BUILD_LOG line 619).
       Parser now detects via `_is_shifted_hnl_row` (col 6 is
       non-empty AND non-numeric → shifted), re-maps the row, and
       sets `total_price = HOUSE $` so these rows display with
       pricing. meta["data_defect"] = "shifted_columns_land_price_blank"
       flags the rows for traceability. Result: lots 313/318
       Thornhill Park now show $643,500 / $657,000 (recovered from
       HOUSE $ when LAND $ + PACKAGE $ are missing).

- [x] 8.x.4 — Hermitage parser: blank "ONE PART CONTRACT" street
       (2026-05-09). Source PDF writes "ONE PART CONTRACT" in the
       Street column for one-part rows as a marker. Parser already
       set `is_one_part=True` based on this; now ALSO nulls
       `street` so renderer leaves the address column blank rather
       than printing the marker text. Affects 4 Wallan rows in the
       2026-05-08 sample.

- [x] 8.x.5 — Status filter: drop "Contract Issue" / "Contract Issued"
       (2026-05-09). Added both variants to config/status-filter.yml.
       Reverses the 2026-05-08 stance which had explicitly kept
       "CONTRACT ISSUED". Inam's call: these are no longer counted as
       available stock. 2 rows newly dropped → 482 kept (was 484).

- [x] 8.x.6 — pdf_render.py: BBC "?" rule for Hermitage (2026-05-09).
       _fmt_bbc updated: when bed is set but bath/car are None
       (Hermitage's case — source genuinely lacks the columns),
       render as "4-?-?" instead of "-". Honest about what we know
       vs don't.

- [x] 8.x.7 — pdf_render.py: sort + group rows per region (2026-05-09).
       Within each region's `_render_region`, rows are now grouped by
       suburb (alphabetical) then sorted ascending by total price
       within each suburb. Rows with no total_price sort last in their
       group. Easier scanning for Tom.

- [x] 8.x.8 — pdf_render.py: inverted darker zebra + featured highlight
       removed (2026-05-09). COLOR_LIGHT_GRAY (#F8F8F8 on odd rows)
       replaced with COLOR_ALT_ROW (#E0E0E0 on even rows). The 2026-05-08
       gold-tint "featured" highlight (Aldrich Exclusive + Hermitage
       PACKAGES rows) is gone — Inam reversed the 2026-05-08 decision.
       All rows now render uniformly with the inverted zebra only.

- [x] 8.x.9 — pdf_render.py: footer per section (2026-05-09). `_draw_footer`
       now called after every region in `build_report_pdf`, not just at
       end of doc. Footer pins to bottom of each region's last page.

- [x] 8.x.10 — Cover page: branded design + dynamic overlay
       (2026-05-09). Replaced the code-built summary cover with Tom's
       branded `assets/Front Cover.pdf`. Two-step technique:
         (a) pypdfium2 imports Front Cover.pdf as page 1 with
             `set_rotation(90)` (the design is laid out landscape but
             stored in a portrait page, so viewers without rotation
             show it sideways).
         (b) Programmatic overlay of 12 dynamic values (date, total,
             10 region counts) on top of the baked-in static numbers.
             pypdfium2 renders the rotated cover to a high-res PNG;
             fpdf2 embeds as full-bleed background; per-field mask
             rectangles match cover bg #182F2B (NOT brand green
             #0D3823 — sampled from rendered cover); live values
             written on top in matched fonts.
       Calibrated coordinates live in `COVER_FIELDS` and
       `COVER_REGION_COUNTS` constants. If Tom's design is ever
       swapped, those constants are the only thing to re-tune.

       New helper functions: `_render_cover_background`,
       `_mask_and_write`, `build_cover_page_bytes`,
       `_merge_cover_with_content`. New dependency: pypdfium2
       (already available in venv).

       Validator updated — page 0 is now the merged cover (Letter
       portrait stored size, displays landscape via rotation), page 1+
       is content (A4 landscape).

- [x] 8.x.11 — Luxton datetime title cells (2026-05-09, late session).
       Stefan's One Part XLSX has some ETA SETTLEMENT cells typed as
       real dates (not strings like "Sept 2025"). openpyxl returns
       Python `datetime` objects; `_clean_str` was str()-ing them as
       "2025-10-01 00:00:00" which then displayed in the TITLES
       column. Fixed by detecting datetime/date in `_clean_str` and
       formatting as "Oct 2025" (matches the month-year convention
       used by other entries in the same column). 12 rows affected.

Stage 8.x lessons learned (set 2026-05-09):

  - **Cover-bg color must be sampled from the actual rendered PNG, not
    assumed from brand palette.** Front Cover.pdf uses #182F2B for the
    page background, NOT the banner-derived #0D3823. Visible rectangles
    appeared on first overlay attempt because the mask shade didn't
    match. Always sample from the rendered artifact when masking-based
    overlay is in play.
  - **Bbox scans must distinguish stacked elements.** First measurement
    of "484" gave y=95.26..115.89 (20mm tall) — wrong, because the scan
    captured "TOTAL PACKAGES" label + thin "|" separator + the digit
    stack as one bbox. Real "484" is y=100.20..108.84 (8.6mm). Always
    scan with per-row pixel-count to identify discrete elements before
    assuming a single bbox.
  - **fpdf2 + tuple format flips orientation unexpectedly.** `FPDF(orientation="L", format=(279.4, 215.9))` produced a portrait page
    (215.9 × 279.4). Use named formats (`format="Letter"`) with
    orientation, not tuples. Lesson worth remembering for any future
    custom-sized pages.
  - **pypdfium2 page-merging works; native-pdf overlay does not.**
    pypdfium2 imports pages cleanly via `PdfDocument.import_pages`,
    but for ON-TOP overlay (a separate transparent overlay PDF
    composited on the imported page) you'd need pikepdf or reportlab.
    Workaround used: render the imported page as PNG, embed as
    background in fpdf2, draw on top. Slightly higher byte count
    (~14.5MB → 14.7MB) but works without new deps.
  - **Hermitage's "ONE PART CONTRACT" marker is data, not address.**
    Source-defect-preservation has limits — when a marker string
    coincides with semantic flagging (is_one_part), the marker should
    NOT bleed into other fields like `street`. Parsers should null
    out marker fields after lifting their semantic content.

## Stage 9 — One Part evening prompt + morning poll

Architecture (locked 2026-05-09 with Inam):
  - 16:00 AEST evening prompt (was 17:00 in plan; Tom requested 4 PM).
  - Candidate scope: Specialised only. Other builders' One Part rows come
    via parser-set `is_one_part=True` (Hermitage's "ONE PART CONTRACT"
    Street markers, Luxton's Mode B One Part XLSX).
  - Dev recipient: inam@meetapex.ai. Flips to Tom at handover.
  - Reply handling: most-recent reply on the prompt thread wins.
  - 06:30 AEST morning poll → 06:45 cutoff → 06:50 send.

- [x] 9.1 — Candidate generator (2026-05-09). lib/one_part_candidates.py
       exposes `get_specialised_candidates(file_path) -> list[CandidateGroup]`.
       Reuses lib/parsers/specialised.py (single source of truth — no
       duplicate parsing). Filters `is_one_part=False` (no-op today since
       Specialised parser flags nothing, but future-proofs against parser
       changes). Groups rows by (suburb, estate); both groups and rows
       within them sorted alphabetically/by lot number. Validator
       tests/validate_one_part_candidates.py passes against the live
       fixture: **52 rows → 31 groups across 26 suburbs**, zero is_one_part
       leakage, row count preserved, lot order ascending within each
       group.
- [x] 9.2 — Evening prompt composer + sender (2026-05-09).
       skills/one-part-prompt/send_evening_prompt.py + SKILL.md.
       Renders 31 candidate groups (52 rows from this week's Specialised
       fixture) as one HTML table per (suburb, estate) — columns: Lot,
       Address, Titles, Floorplan, Bed-Bath-Car, Price. Brand green
       headers + zebra striping. Subject is `[Bolst One Part — YYYY-MM-DD]`
       with TOMORROW's date in Australia/Melbourne (the date of the report
       this prompt feeds, not the send date). Graph send succeeded
       (202 Accepted). End-to-end verified: Outlook OAuth → Graph
       sendMail with HTML body → email queued for inam@meetapex.ai.

       Side changes:
         - lib/graph_send.py: send_mail() gained body_html parameter
           (additive — body_text path unchanged, body_text/body_html
           validation added). Existing send_test.py still works.
         - config/delivery.yml: one_part_evening_prompt 17:00 → 16:00
           per Tom's 2026-05-09 directive.
         - requirements.txt: added tzdata==2026.2 (zoneinfo on Windows
           needs the IANA tz database from this pure-Python wheel).
       Subject prefix is load-bearing — the morning poll (9.3) finds
       Tom's reply by literal subject search on `[Bolst One Part —`.
- [x] 9.3 — Pick parser written (2026-05-09).
       lib/pick_parser.py exposes `parse_picks(reply_text, candidates) ->
       PickResult(picks, unresolved)`. Pure function, no I/O — Outlook
       read wiring deferred to Stage 9.8 (lib/graph_read.py).
       Resolution rules:
         (a) `Lot N` regex (case-insensitive) finds candidates
         (b) zero matches in stocklist → unresolved with reason
         (c) one match → picked (suburb optional)
         (d) >1 matches → must disambiguate by suburb name in tail text
       Lot-number ambiguity is REAL: this week's data has 5 lots that
       appear in multiple suburbs (Lot 42 in Benalla AND Newborough,
       etc.) — the email body now instructs Tom on the
       `Lot &lt;number&gt; &lt;suburb&gt;` format.
       Validator tests/validate_pick_parser.py: 10/10 scenarios pass —
       empty/whitespace replies, bare unique lots, ambiguous lots
       (with + without suburb), off-list lots (Lot 99999 Atlantis),
       greeting+signature noise around real picks, duplicate-mention
       dedup. Drift-tolerant: probes use whatever unique/ambiguous
       lots happen to be in the fixture this week.
- [x] 9.4 — Pick application module (2026-05-09).
       lib/pick_apply.py exposes `apply_picks(rows, picks) -> int`.
       Mutates matching Specialised rows in-place: sets
       is_one_part=True, returns applied count.
       Match key is the strict 4-field (builder='specialised', lot,
       suburb, estate). Lot alone insufficient (5 dupes this week);
       (lot, suburb) sufficient today but estate is the safety net for
       future weeks where Specialised could ship the same lot in
       multiple estates within the same suburb.
       Validator tests/validate_pick_apply.py: 5/5 pass — empty picks,
       single pick promoted (and routed to one-part-contracts via the
       existing Stage 7 precedence), non-Specialised decoy with same
       key is NOT promoted, ghost lot returns 0 applied (drift signal
       for caller to surface in banner).
       NOT touching the orchestrator (validate_report_pdf.py) yet —
       that integration belongs to Stage 9.7 end-to-end dry run.
- [x] 9.5 — One Part notice banner (2026-05-09).
       lib/pdf_render.py: build_report_pdf() gained an optional
       `one_part_notice: str | None = None` parameter (additive — all
       existing callers unaffected). When set, _render_region for
       region_id="one-part-contracts" injects a callout banner between
       subtitle and table: light gold background (#F5E6D3), brand gold
       border (#C9A24A), italic dim-grey text, multi_cell wraps long
       messages.
       Generic `notice` rather than hardcoded "no picks" string — caller
       picks the message: "No Specialised picks received - reply to
       yesterday's prompt to add." for empty replies, or unresolved-lot
       descriptions ("Lot 42 ambiguous - please specify suburb") from
       Stage 9.3's PickResult.unresolved.
       Banner gates on poll outcome, NOT on tab emptiness — Hermitage's
       4 + Luxton's 9 auto-flagged One Part rows can still be present
       and the Specialised editorial-gap notice still belongs there.
       Validator tests/validate_one_part_notice.py: 3/3 pass — notice
       absent without arg, present with arg, appears exactly once
       (no bleed to other regions). Stage 8 regression test still
       passes (24 pages / 482 rows / 14.5MB unchanged).
- [x] 9.6 — Routine YAMLs (2026-05-09).
       routines/one-part-evening-1600.yml + one-part-morning-poll-0630.yml.
       Schema set (was empty folder before): name + description + cron +
       timezone + skill + sub_skill + prompt + on_success/on_failure + notes.
       The YAMLs serve dual-purpose:
         (a) human spec for whoever creates the Claude.ai Schedule manually
         (b) machine-readable spec for the `/schedule` skill if/when we
             automate routine creation
       Cron: "0 16 * * *" (evening) and "30 6 * * *" (morning), both
       Australia/Melbourne (DST handled automatically).
       Morning poll explicitly documents the 06:45 cutoff and the
       "no-picks-is-not-a-failure" semantics — if Tom didn't reply, the
       report still ships with the Stage 9.5 empty-reply banner.
       Subject prefix `[Bolst One Part —` flagged as load-bearing in both
       YAMLs (matched between the evening sender and morning reader).
- [x] 9.8.7 — Morning report orchestrator + 07:00 send + routines
       (2026-05-09). Three components landed:

       (a) Picks persistence — lib/picks_store.py:
           Single JSON at .cache/last_morning_picks.json with schema
           {report_date, reply_subject, polled_at, picks[], unresolved[]}.
           write_picks() / read_picks_for(report_date). Stale picks
           (yesterday's file still on disk) ignored: read_picks_for
           returns None unless report_date matches today.

       (b) Morning poll runner — skills/one-part-collect/run.py:
           Searches Tom's Outlook via $search "subject:Bolst One Part",
           filters client-side by report_date string (avoids em-dash vs
           hyphen brittleness in Graph search). Strips Tom's own sent
           message; takes most recent reply. Extracts plaintext via
           BeautifulSoup, runs pick_parser, persists via picks_store.
           Smoke-tested with --report-date 2026-05-10: found 3 thread
           messages (today's evening prompts), filtered out 3 as "from
           Tom" (sent messages), 0 replies => empty picks JSON written.

       (c) Morning report orchestrator — skills/compose-and-send/send_report.py:
           Live end-to-end: ingest all 6 builders via fetch_all_for_builder
           in a loop, read picks via picks_store, apply_picks, route +
           filter, build_report_pdf with one_part_notice, send via Graph.
           Per-builder try/except so transient failures don't abort the
           report. Subject "Bolst Stocklist - Sun 10 May" format.
           --no-send flag for testing without actual delivery.

           Live verification: full pipeline ran end-to-end against Tom's
           production mailbox. 6/6 builders ingested, 513 rows, 486 kept
           after status filter, 11 One Part rows (all auto-flagged from
           Hermitage + Luxton; 0 from picks since no reply). 14.5 MB PDF
           sent to inam@meetapex.ai. Graph 202 Accepted.

       Schedule changes (per Tom's 2026-05-09 directive):
         - delivery.yml daily_build_send 06:50 -> 07:00
         - routines/one-part-evening-1600.yml: cron daily -> Mon-Fri (1-5)
         - routines/one-part-morning-poll-0630.yml: cron daily -> Tue-Sat (2-6)
         - routines/morning-report-0700.yml: NEW, Tue-Sat 07:00

       Weekly cycle: Mon-Fri 16:00 evening prompt; Tue-Sat 06:30 morning
       poll + 07:00 morning send. 5 reports per week. Tom gets a quiet
       inbox Sun + Mon morning. Each morning's report covers the previous
       weekday's data:
         Mon prompt -> Tue 7AM report
         Tue prompt -> Wed 7AM report
         Wed prompt -> Thu 7AM report
         Thu prompt -> Fri 7AM report
         Fri prompt -> Sat 7AM report

       *** STAGE 9 COMPLETE END-TO-END. Engine self-drives from Outlook
           ingest -> editorial pick layer -> branded morning send. ***

- [x] 9.8.6 — Luxton html_link mode (MailChimp -> Google Sheets) (2026-05-09).
       Discovered from live mailbox inspection:
         - Every Luxton MailChimp email (incl promo) carries the standard
           footer with "1 Part Sock List - Click" and "2 Part Stock List -
           Click" buttons. No subject filter needed — latest email
           always works.
         - MailChimp tracking URL (luxtonhomes.us4.list-manage.com) does
           ONE 302 redirect to a public Google Sheets URL.
         - Two URL flavours observed in the wild:
             /spreadsheets/d/{ID}/edit?gid=0    (1 Part button)
             /spreadsheets/u/0/d/{ID}/htmlview   (2 Part button)
           First regex was too strict (matched only /d/{ID}); fixed with
           optional /u/N/ prefix in GOOGLE_SHEETS_ID_RE.

       config/builders.yml luxton: ingestion attachment -> html_link.
       Added link_strategy.buttons with format=google_sheets_xlsx per
       button, plus filename aliases in filename_patterns + routing for
       the new live-mode filenames.

       lib/graph_read.py:
         - Added _resolve_google_sheets_xlsx_url(button_url) helper
         - Added GOOGLE_SHEETS_ID_RE regex (supports /u/N/ flavour)
         - Added GOOGLE_SHEETS_XLSX_CONTENT_TYPE constant
         - buttons loop now dispatches by btn['format'] in {pdf,
           google_sheets_xlsx}; expected_content_types passed through
           to _download_to_cache so format-mismatch fails loudly.

       Smoke test tests/validate_graph_read_luxton.py PASS:
         One Part XLSX:    20 rows / 20 is_one_part=True
         House & Land:     13 rows
       Note: Stefan's Thornhill Gardens Superlots file is NOT in the
       MailChimp emails (used to come via direct Outlook attachment in
       our April fixture). Not currently ingested — tom can flag if
       needed.

       *** ALL 6 BUILDERS NOW LIVE. ***
       Specialised + Aldrich + Urbane (attachment) + Hermitage
       (url_template) + Aplace + Luxton (button-extract). Morning
       report orchestrator (9.8.7) is unblocked.

- [x] 9.8.5 — Aplace html_link mode + multi-file API (2026-05-09).
       Discoveries from live mailbox inspection:
         - Aplace stocklist subject is "Aplace - House & Land Opportunities"
           (weekly Mon/Tue). Other Aplace mail is promo ("Package of the
           Week", "100% commission") — needs subject_filter.
         - Aplace ships TWO PDFs in ONE email via Campaign Monitor (cmail19):
           "Download - Victoria Stocklist" (regional) AND
           "Download - 100% Upfront commission stocklist" (one_part).

       config/builders.yml updated: aplace `ingestion: attachment` ->
       `html_link`, added subject_filter, added link_strategy.buttons
       (text_contains -> filename mapping for each download).

       lib/graph_read.py refactor:
         - Added `_extract_button_href(html, text)` using BeautifulSoup
         - Added `_list_recent_messages_with_body` (selects body field)
         - Added `link_strategy.buttons` handler in _fetch_html_link_mode
         - Mode handlers now return list[Path] (multi-file possible)
         - Public API split: fetch_all_for_builder() -> list[Path] for
           comprehensive ingest; fetch_latest_for_builder() -> Path is
           a thin wrapper returning first[0] for single-file callers
           (preserves the One Part flow's single-Path expectation).

       Dependency: beautifulsoup4 4.14.3 + lxml 6.1.0 added.

       Smoke test tests/validate_graph_read_aplace.py PASS:
         Victoria Stocklist:  72 rows / 24 sub / 38 est
         Upfront Commission:  24 rows / 7 sub / 7 est
         Both PDFs cached at .cache/builder-downloads/aplace/.

       5 of 6 builders now live. Last one: Luxton (MailChimp -> Google
       Sheets via /export?format=xlsx).

- [x] 9.8.4 — Hermitage html_link mode (URL template) (2026-05-09).
       lib/graph_read.py gained `_fetch_html_link_mode()` +
       `_format_url_template()` + `_download_to_cache()` helpers.
       url_template path: list latest Hermitage email -> use its
       receivedDateTime to substitute {ddmmyy} -> public HTTP GET to
       hubfs CDN -> cache as YYYYMMDD-{filename}.pdf -> return Path.
       Fallback (parse email HTML for "CLICK HERE" button + follow
       redirect chain) deferred to 9.8.4b — only needed if HubSpot
       ever drifts from the predictable filename pattern.

       Date-token substitution supports {ddmmyy}, {ddmmyyyy},
       {yyyymmdd} (case-insensitive variants too) — covers all 3
       link-mode builders if they each use a different pattern.

       Smoke test tests/validate_graph_read_hermitage.py PASS:
         Latest email 2026-05-08 -> URL hubfs/6368574/080526.pdf
         Downloaded 129 KB, parsed 146 rows / 31 sub / 42 est /
         4 auto-flagged is_one_part=True rows (the "ONE PART CONTRACT"
         Wallan markers).

       4 of 6 builders now live (Specialised, Aldrich, Urbane,
       Hermitage). Two link-mode builders remaining: Aplace
       (Campaign Monitor), Luxton (MailChimp -> Google Sheets).

- [x] 9.8.3 — Aldrich + Urbane attachment-mode (2026-05-09).
       lib/graph_read.py: refactored _fetch_attachment_mode to walk
       primary + secondary_senders in order via new
       _try_sender_for_attachment helper. subject_filter was already
       supported in 9.8.1.
       Smoke test tests/validate_graph_read_attachment.py runs all 3
       attachment builders end-to-end against Tom's mailbox: 3/3 PASS.
         Specialised:  48 rows / 21 sub / 25 est (May 5 vs Apr 28)
         Aldrich:     145 rows / 23 sub / 41 est (May 5 vs Apr xx
                                                  — subject_filter
                                                  skipped per-package
                                                  emails)
         Urbane:       45 rows / 15 sub / 24 est (May 8, from Tyana
                                                  primary — secondary
                                                  fallback not needed
                                                  this week)
       Half the morning report (3 of 6 builders) now reads live.
       Remaining 3: Aplace, Luxton, Hermitage — all html_link mode,
       coming in 9.8.4-9.8.6.

- [x] 9.8.2 — Wire live Specialised into evening prompt + dry run
       (2026-05-09). 5-line edit each:
         skills/one-part-prompt/send_evening_prompt.py — DEFAULT_FIXTURE
           constant removed; default is now fetch_latest_for_builder().
           CLI override (argv[1]) preserved.
         tests/dry_run_one_part.py — added _live_specialised_path()
           helper; _gather_all_rows() now takes specialised_path arg.

       End-to-end verified with live data:
         - Evening prompt: 48 rows / 25 groups from
           Stocklist 05.05.26.pdf, sent to inam@meetapex.ai (was 52/31
           with April fixture)
         - Dry run with reply "Lot 42, Lot 42 Benalla, Lot 99999 Atlantis":
           Lot 42 Benalla still exists this week (price $679,620 vs
           $676,720 last week - Specialised re-priced same lot).
           Lot 42 also still ambiguous with Newborough this week.
           1 pick applied, 2 unresolved, 12 rows in One Part region.
           PDF written to output/dry_run_one_part-20260509-124546.pdf.

       The April → May data drift confirms the parsers are stable
       across weeks and the ambiguity problem is structural not
       fluke. Ready for 9.8.3.

- [x] 9.8.1 — graph_read.py + Specialised attachment-mode (2026-05-09).
       lib/graph_read.py exposes `fetch_latest_for_builder(builder_id,
       builders_config, *, bundle_root, cache_dir=None,
       skip_cache=False) -> Path`. Dispatches by builders.yml `ingestion`
       mode; only attachment-mode implemented in 9.8.1 (html_link mode
       raises IngestError, scheduled for 9.8.4-9.8.6).

       Two Graph-API gotchas fixed during build:
         (a) `$filter from/emailAddress/address eq '...'` + `$orderby
             receivedDateTime desc` returns 400 InefficientFilter even
             with ConsistencyLevel: eventual + $count=true. Workaround:
             use `$search="from:<addr>"` (Graph indexes this for sender
             lookup) and sort client-side by receivedDateTime.
         (b) Attachments fetched via inline contentBytes (base64) in the
             /attachments JSON response, decoded before write — no
             separate /$value GET needed.

       Cache: `.cache/builder-downloads/<builder>/<YYYYMMDD>-<filename>`
       to keep same-day reruns cheap. The One Part flow runs both 16:00
       evening + 06:30 morning — both hit the same cached file unless
       skip_cache=True. .gitignore updated to exclude .cache/.

       Smoke test tests/validate_graph_read_specialised.py PASS:
         Downloaded Stocklist 05.05.26.pdf (244 KB) - Tom's actual most
         recent Specialised email, received 2026-05-05.
         Parsed: 48 rows / 21 suburbs / 25 estates / $575K-$749K range.
         (April fixture had 52 rows — natural week-to-week drift,
         parser handles both with no code change.)

       FIRST LIVE END-TO-END RUN against Tom's production mailbox.

- [x] 9.7 — End-to-end dry run (2026-05-09).
       tests/dry_run_one_part.py is a CLI script that takes a synthetic
       reply text on argv[1] and runs the full chain:
         reply -> parse_picks -> apply_picks -> route -> filter ->
         build_report_pdf(one_part_notice=...)
       Writes timestamped PDF to output/dry_run_one_part-YYYYMMDD-HHMMSS.pdf.
       Includes _build_notice() helper that combines (pick_count,
       unresolved) into the right banner text:
         clean reply        -> no notice
         picks + unresolved -> "Some entries could not be applied: ..."
         no picks at all    -> "No Specialised picks received - ..."

       Live exercise with reply "Lot 42, Lot 42 Benalla, Lot 99999 Atlantis":
         - 1 pick: Lot 42 Benalla / Stablewood ($676,720) -> One Part tab
         - 2 unresolved: bare Lot 42 ambiguity + Lot 99999 not in stocklist
         - 12 rows in One Part region (1 Specialised pick + 11 auto-flagged
           from Hermitage's "ONE PART CONTRACT" markers + Luxton's One Part
           XLSX rows)
         - notice banner rendered listing both unresolved entries
         - PDF: 14.5 MB, structurally identical to morning report + One
           Part region now contains Tom's pick

       Side fix: lib/pick_parser.py em-dash -> hyphen-minus in unresolved
       message strings. fpdf2's default Helvetica is Latin-1 only (per
       Stage 8.x lessons); em-dash crashed multi_cell. All 10 pick_parser
       scenarios still pass post-fix.

## Stage 10 — Approval watcher
- [ ] (substeps to be defined when Stage 10 starts)

## Stage 11 — Handover docs (stretch)
- [ ] (substeps to be defined when Stage 11 starts)

---

## Scope changes

- **2026-05-06** — REA Ignite CSV ingestion deferred. Focus stages 1–onwards on email-only ingestion. Stage 2 (REA parser) moves to AFTER the 6 email parsers are working. Email pipeline gets validated end-to-end first, then we layer the REA piece in.

- **2026-05-06** — Send mechanism changed from Gmail API → **Microsoft Graph API**. Single OAuth grant covers Mail.Read + Mail.Send. Avoids throwaway Gmail OAuth setup. Dev code path = prod code path.

- **2026-05-06 (evening)** — **PIVOT: skip the dev-simulation Outlook (`inam700@outlook.com`) entirely. Connect directly to Tom's Outlook from the start.** Reasoning: Inam meeting Tom 2026-05-07 to confirm builder senders + recipient + OAuth admin path. Trade-off: can't test reads until Tom OAuths; mitigated by building parsers against on-disk samples in parallel. Test send goes to Inam first (NOT Tom) until reports are mature, then we flip recipient to Tom. Filename-based dev routing is no longer needed — Tom's inbox has real builder senders preserved.

- **2026-05-08** — **Build-time read access connected via MCP, ahead of schedule.** Inam got direct access to Tom's MS account and re-authed the Claude.ai Microsoft 365 connector against Tom's mailbox (was inam700@outlook.com). All `mcp__claude_ai_Microsoft_365__*` calls now hit `tom@bolstpropertygroup.com.au`. Production runtime auth (Entra app + Python msal, substep 1.6) is still pending and unaffected — the MCP connector is read-only.

- **2026-05-08** — **Hermitage ingestion mode = html_link (new).** Hermitage's HubSpot newsletter emails carry NO PDF attachment. Master stocklist lives behind a "CLICK HERE FOR WEEKLY STOCKLIST" CTA → HubSpot tracking URL → JS interstitial → 307 → final PDF on `hs-6368574.f.hubspotstarter.net/hubfs/6368574/{DDMMYY}.pdf`. PDF is publicly fetchable. Builders.yml now models this with `ingestion: html_link` + `link_strategy.url_template` (primary) + `fallback_button_text` (fallback).

## Open questions / blockers (kill when resolved)

- ~~Inam to forward 6 builder sample emails from his Gmail to inam700@outlook.com~~ — obsoleted 2026-05-08; we read from Tom's live mailbox directly.
- Tom (or his admin) to consent to the Entra app once it's registered — gates substep 1.6e (production runtime auth).
- Email signatures for Aaron Wilson + Howard Rock still needed from Tom — Phase 1.5 only, not blocking.
- Howard Rock's email address not yet verified from the live mailbox — only Aaron's confirmed in builder thread.

## Live-data verification milestone (2026-05-08, late)

After parser layer completed, did a deep live-mailbox sweep + ingestion-path
verification before Stage 7. Findings reshaped the architecture and kept
parsers honest.

**Three of six builders had wrong `ingestion` mode** (we'd assumed attachment):
  - **Aplace** sends Campaign Monitor newsletters with no attachment.
    Download buttons resolve cmail19 tracking URL → public PDF on
    aplace.com.au CDN. Confirmed `Content-Type: application/pdf`, no auth.
  - **Luxton** sends MailChimp newsletters with "1 Part / 2 Part Sock List
    - Click" buttons. They resolve to **public Google Sheets**, downloadable
    as XLSX via `docs.google.com/spreadsheets/d/{ID}/export?format=xlsx`.
    Stefan's also said he's migrating to Dropbox — watch for changes.
  - **Hermitage** already known to be html_link via HubSpot CDN.

  Three remain attachment-based: Aldrich, Specialised, Urbane (Tyana Troise
  is canonical, not Mikayla — Mikayla's HubSpot is promo-only with no
  attachments).

**Microsoft account safety check** (Inam asked): no risk at our usage profile.
Microsoft Graph API quotas are 10,000 req/10min per app per mailbox; we use
~10 calls per session and ~6-10 calls per day in production. Read-only
OAuth-delegated activity. Worst case is HTTP 429 throttling, never account
suspension. Production is well inside the safe envelope.

**Test fixtures refreshed to live data**:
  - `aplacevic@aplace.com.au/Aplace-GENERAL-Stock-List.pdf` (LIVE)
  - `aplacevic@aplace.com.au/Aplace-Put-Call-Stock-List.pdf` (LIVE)
  - `houseandland@hermitagehomes.com.au/080526.pdf` (LIVE — today's)
  - `stefanc@luxtonhomes.com.au/Luxton Homes - HOUSE & LAND STOCKLIST.xlsx` (LIVE Google Sheets export)
  - `stefanc@luxtonhomes.com.au/Luxton Homes - One Part Contracts.xlsx` (LIVE)
  - Old dated/cached versions deleted.

**Luxton parser simplified** — removed dual-format detection that handled
the Tom-forwarded snapshot variant. Live Google Sheets format is canonical;
that's the only thing production will see. Cleaner, fewer code paths.

**All 6 validators rewritten as drift-tolerant**. Removed every hardcoded
`EXPECTED_TOTAL_ROWS = N`, `EXPECTED_REGION_BREAKDOWN`, source-defect-
preservation assertion ("Sevile must exist", "Cloverton wrap"), etc. Now
they test STRUCTURAL invariants only: parser doesn't crash, `builder` field
correct, critical fields populated, `source_region` matches the file
format's known set, `is_one_part` correctness, arithmetic warnings (printed,
not failures). Status vocabulary, row counts, estate names, source typos all
become observations rather than assertions — Stefan (or any builder) can
clean their data without breaking our tests.

**Two production-data findings the validators surfaced**:
  - **Hermitage live (today's PDF) has 4 ONE PART CONTRACT rows** —
    first time we've exercised the is_one_part detection against real data
    (cached 240726 had zero). Each one has `land + build ≠ total` because
    Hermitage prices one-parts as a single lump sum without the breakdown
    populated. **The arithmetic check should skip is_one_part rows in
    Stage 7** (or the parser should null land/build for one-part rows).
  - **Stefan's H&L sheet has 2 rows with shifted columns** (lots 313, 318
    Thornhill Gardens). LAND $ blank caused everything from col 6 onward to
    appear in the wrong cell. Real source defect, not parser bug. Tom can
    flag to Stefan.

## Notes for the next session

- **Where we paused:** end of 2026-05-09 (Stage 8.x polish pass complete).
  **Stages 1, 3, 4, 5, 6, 7, 8 + 8.x done. Live pipeline + branded cover
  with dynamic overlay all working.** Cumulative current row counts
  (drift weekly): 514 parsed → 514 routed → **482 kept** after status
  filter (32 dropped: Sold + Contract Signed + Contract Issue + Contract
  Issued). Output: 24-page PDF, ~14.5 MB. Stage 2 (REA) still deferred.

- **2026-05-09 session deliverables (sent to Tom for review):**
  - Field-coverage audit completed across all 6 senders. Confirmed
    Aldrich + Luxton genuinely have no Street column in source;
    Hermitage genuinely has no Bath/Car columns. Email drafted asking
    Tom to confirm whether these fields go by alternate names in any
    builder's format.
  - All 8 of Inam's review points landed (address-blank, sort/group,
    inverted zebra, footer per section, Contract Issue filter,
    Hermitage BBC "?" rule, Thornhill Park pricing recovery, cover
    summary).
  - Cover page now uses Tom's branded `assets/Front Cover.pdf` with
    live values overlaid via pypdfium2 + fpdf2 (see Stage 8.x.10).

- **Awaiting from Tom:**
  - Sign-off on the 2026-05-09 PDF (sent for review).
  - Whether BED/Bath/Car go by alternate names in any builder format
    (so we can re-search the missing rows). Currently 134 Aldrich rows
    have no Street, 44 Luxton rows have no Street, 146 Hermitage rows
    have no Bath/Car — believed to be source-side limits.
  - Substep 1.6 Entra app consent (gates production runtime auth).

- **Stage 7 closeout decisions (locked 2026-05-08 with Inam):**
  - **Region → banner mapping confirmed** by visual inspection of the 10
    JPGs. Each banner has the region name in cursive on the right, no
    ambiguity. Mapping written into config/suburbs.yml `region_banner`:
      Green-01=geelong-colac, Green-02=gippsland,
      Green-03=regional-west, Green-04=regional-north-east,
      Green-05=warrnambool, Green-06=horsham,
      Green-07=metro-north, Green-08=metro-south-east,
      Green-09=metro-west, Green_One Part Cont=one-part-contracts.
  - **Echuca → regional-north-east**. Goulburn-Murray corridor with
    Shepparton/Mooroopna; Specialised's other regional listings all fall
    in regional-north-east. Removed from Uncategorised.
  - **Featured visual treatment = highlight.** Stage 8 should highlight
    the 25 featured rows (Aldrich Exclusive + Hermitage PACKAGES) within
    their geographic regions, not promote to a separate section.

- **Stage 8 + 8.x done.** Branded morning report renders end-to-end
  with Tom's cover as page 1 + dynamic overlay. Output at
  output/bolst-stocklist-validator.pdf. DejaVuSans not needed — all
  482 kept rows are Latin-1 clean.

- **Natural next moves:**
  - **Stage 9 — One Part evening prompt + morning poll routines.** Tom
    needs the editorial One-Part flow: 17:00 evening prompt → Tom
    replies with one-part highlights → 06:30 morning poll → 06:45
    cutoff → 06:50 send. Routines = Claude.ai schedules; skill code
    handles the prompt/poll mechanics. 13 one-part rows would surface
    this week (Hermitage 4 + Luxton 9 active).
  - **Stage 10 — Approval watcher + hold/retry logic.** Defensive —
    detects when an upstream parse run produces unexpectedly different
    counts (e.g., a builder's PDF format changed) and holds the report
    for manual review.
  - **Fixture refresh (low priority):** Urbane fixture is stale (April
    Mikayla on disk; Tyana sent fresh 2026-05-08). Aldrich C44 is also
    stale (Corey sent fresher 2026-05-05). Same format both — doesn't
    affect parser correctness but keeps fixtures in sync with prod.
- **First-review confirmations still deferred to Tom (not blocking):**
  - Whether Reserved/Hold/Not Available/Resale/Exclusive/EOI should
    join the status drop list (currently kept; Contract Issue + Issued
    were added 2026-05-09).
  - PDF size ~14.5MB — acceptable under Outlook 25MB limit but worth
    resizing banner JPGs to ~1500px wide if Tom flags it.
- **Stage 2 (Ignite REA parser)** still deferred per 2026-05-06 lock —
  email parsers were the priority and now they're done. Pick up only if
  Tom's CRM feed becomes blocking.
- **Parser pattern (proven on Aplace + Specialised):**
  1. Read sample(s) to understand layout
  2. Try pdfplumber.extract_tables() first; if rows are dropped due to alternating styling, pivot to extract_text() + line-by-line regex with state machine
  3. Write `lib/parsers/<builder>.py` with `parse(file_path) -> list[StocklistRow]`
  4. Write `tests/validate_<builder>.py` for row counts + field coverage
  5. Run validator, eyeball edge cases, mark stage done
- **Subtle helper bug to avoid:** `_clean_int(value)` should match leading digits only (`re.search(r"\d+", s)`), not all digits (`re.sub(r"[^\d]", "", s)`). The latter turns "506m2" into 5062. Aplace uses raw integers in source so isn't affected, but Specialised's "506m²" exposed it.
- Send mechanism is **Microsoft Graph**, NOT Gmail. Sender = Tom's Outlook (post-OAuth in 1.6). Recipient = Inam during build phase, flips to Tom once reports mature, flips again at Phase 1.5 (Tom + reps).
- Working mode: step-by-step with explanations (see `..\CLAUDE.md`). Don't batch substeps.
- **CLAUDE.md line 30 is stale:** "Microsoft 365 MCP for Outlook (read), Gmail MCP for sending." Sending is via Microsoft Graph (msal in Python), not Gmail MCP. Worth cleaning up next session.
- Self-ingestion guard still applies: ingest-builder-stocklist must skip emails where subject starts with "Bolst Stocklist —" (so the engine doesn't try to parse its own outgoing reports if recipient = sender at handover).
- Builder identification key insights from 2026-05-08:
  - Sender is primary; filename + subject filters are defensive layers
  - Hermitage uses `ingestion: html_link` (the others use attachment)
  - Aldrich needs `subject_filter` (Corey sends both canonical stocklists and per-package emails)
  - Urbane has primary + secondary_senders (Tyana primary, HubSpot/Mikayla fallback)
  - Tom's `bolst-property-group-data\` folder is organized by sender email — that's the on-disk sample mapping
- **Hermitage PDF URL pattern (load-bearing):** `https://hs-6368574.f.hubspotstarter.net/hubfs/6368574/{DDMMYY}.pdf`. Publicly fetchable, no auth. Filename derived from email's receivedDateTime.

---

## Closeout — 2026-05-09 end of session (Stage 9 complete end-to-end live)

**Stages 1, 3-9 fully complete. Engine self-drives Outlook → editorial pick layer → branded morning send against Tom's PRODUCTION mailbox.** Manual orchestration only — no scheduler firing the scripts on cron yet (see Production Hosting section below).

### What works end-to-end live

```
16:00 Mon-Fri AEST  evening prompt
                    skills/one-part-prompt/send_evening_prompt.py
                    └─ live Specialised PDF from Tom's Outlook
                    └─ HTML candidate table → Graph send → Tom's inbox

(overnight)         Tom replies on the thread

06:30 Tue-Sat       morning poll
                    skills/one-part-collect/run.py
                    └─ search Tom's mailbox for the thread
                    └─ pick_parser → write picks JSON

06:45 Tue-Sat       (soft cutoff — no separate routine)

07:00 Tue-Sat       morning report
                    skills/compose-and-send/send_report.py
                    └─ fetch all 6 builders LIVE (graph_read.py)
                    └─ apply Tom's picks → route → status filter
                    └─ render branded PDF (24 pages, ~14.5 MB)
                    └─ Graph send to inam@meetapex.ai (build phase)
```

Live row tally for the week of 2026-05-05/08 (drift weekly):
- Specialised 48 + Aldrich 145 + Urbane 45 + Hermitage 146 + Aplace (Vic 72 + Upfront 24 = 96) + Luxton (One Part 20 + H&L 13 = 33) = **513 parsed → 486 kept** after status filter.
- One Part Contracts tab: 11 auto-flagged rows (Hermitage 4 Wallan markers + Luxton 7 active One Part rows) + however many Tom picks via the editorial flow.

Compares to April fixtures' 514 rows → 482 kept. Drift of <1% across 6 builders proves the parser layer is stable.

### Email recipient routing (per .env)

```
BOLST_REPORT_RECIPIENT=inam@meetapex.ai          # Morning report — still build phase
BOLST_REPORT_SENDER=tom@bolstpropertygroup.com.au
BOLST_ONE_PART_RECIPIENT=tom@bolstpropertygroup.com.au   # Flipped 2026-05-09 per Tom
```

So today: One Part evening prompt goes to Tom directly (he replies on the thread); morning report still goes to Inam during pilot review. Flip morning report when Tom signs off.

### Substep summary for Stage 9

| # | What | Status |
|---|---|---|
| 9.1 | Candidate generator (`lib/one_part_candidates.py`) | DONE |
| 9.2 | Evening prompt composer + sender | DONE |
| 9.3 | Pick parser (regex + suburb disambiguation) | DONE |
| 9.4 | Apply picks (mutate is_one_part=True) | DONE |
| 9.5 | One Part notice banner | DONE |
| 9.6 | Routine YAMLs (spec only) | DONE |
| 9.7 | End-to-end dry run | DONE |
| 9.8.1-6 | Live ingest for all 6 builders via `lib/graph_read.py` | DONE |
| 9.8.7 | Morning report orchestrator + 07:00 send + Tue-Sat cron | DONE |

### Production hosting — OPEN (next session)

Engine works manually but **routine YAMLs are documentation, not active schedules**. Nothing fires automatically. Two options on the table for Tom (full description in `..\Bolst_Hosting_Options.md`):

1. **Claude Code Routines** (locked architecture from 2026-05-07) — runs on Anthropic-managed Ubuntu cloud VMs, machine-independent, included in Tom's Pro/Max subscription. ~3-4 hrs migration: commit code to private GitHub repo, setup script for pip installs, OAuth refresh token + Azure IDs as Routine env vars, 3 routine specs.
2. **Vercel Cron Functions** — fallback. Free tier covers the 15 fires/week. ~3-4 hrs setup: project + function entrypoints + env vars + vercel.json crons + Vercel Blob for picks JSON.

Inam will discuss with Tom before next session. Migration starts when Tom picks an option.

### Known gaps / open items

- **Stefan's Thornhill Gardens Superlots file** (Luxton) is NOT in MailChimp emails — used to come via direct Outlook attachment in April fixture. ~11 Superlot rows missing in live ingest. Tom can flag if he wants those back.
- **Howard Rock email address** still TBC — Phase 1.5 only.
- **Aldrich/Luxton no Address column** + Hermitage no Bath/Car — confirmed permanent source limits, render gracefully.
- **Tom's reply UX:** Subject line uses em-dash; if Tom's email client treats em-dash differently in replies, the morning poll's date-substring filter still works (it doesn't care about punctuation).
- **CLAUDE.md line 30 still stale** ("Gmail MCP for sending"). Should clean up at handover.
- **Substep 1.6** Entra app consent — done 2026-05-08 (Tom granted Mail.Read + Mail.Send + Mail.ReadWrite via device-code flow).

### Lessons from Stage 9 worth preserving

- **Lot numbers are NOT unique** in Specialised data. Always require suburb disambiguation in editorial replies. This week 5 lots collide; structural property, not fluke.
- **Graph $filter on derived properties + $orderby = InefficientFilter.** Use $search instead and sort client-side.
- **Subject search across Unicode punctuation (em-dash) is unreliable.** Search punctuation-free anchor, filter by date string substring client-side.
- **Multi-file builders break a single-Path API cleanly:** add `fetch_all_for_builder` returning list, keep `fetch_latest_for_builder` for single-file callers.
- **Live data fixture-replacement immediately surfaces drift:** running parsers against today's data (vs April) showed 5/6 builders with small row count changes — proves parsers stable, no overfitting.
- **HTML link mode comes in three flavours:** url_template (Hermitage, predictable), button-extract → direct URL (Aplace, Campaign Monitor → CDN), button-extract → Google Sheets export (Luxton, MailChimp → docs.google.com).
- **Picks JSON cache won't survive Routines (cloud) cleanly** — each fire = fresh VM. Either commit picks to git or re-run poll inline. Decide at hosting migration time.

---

## 2026-06-02 — Tom requests: One Part fallback + clickable cover regions

Two requests from Tom this session.

### Request 1 — One Part: unconfirmed listings go to their region (VERIFIED, no code change)

Scope decided with Inam: **only the editorial Specialised candidates** fall
back to suburb/region when Tom doesn't reply. Builder-flagged one-parts
(Hermitage "ONE PART CONTRACT" markers + Luxton One Part XLSX) STAY in the
One Part tab regardless — that's their source designation.

Traced the pipeline and confirmed this **already works**:
  - `send_report.py` ingests the FULL Specialised stocklist (not just picks).
  - `pick_apply.py` sets `is_one_part=True` ONLY on rows Tom names; everything
    else keeps `is_one_part=False`.
  - `routing.py` only forces `is_one_part=True` rows into one-part-contracts,
    so unpicked Specialised rows fall through to the normal suburb lookup and
    land in their geographic region.
So a Specialised listing Tom doesn't reply about already appears in its
region — nothing lost. Likely Tom read the empty-reply banner (+ the
auto-flagged Hermitage/Luxton rows still present) as "my stock vanished".
No change made.

### Request 2 — Clickable region links on the cover (DONE)

Each "AVAILABLE BY REGION" row on the branded cover is now a clickable
internal link that jumps to that region's first page.

**Architecture change:** cover is now built INLINE on the same `FPDF`
document as the regions, instead of being rendered separately and merged
via pypdfium2. Removed `_merge_cover_with_content` (the pypdfium2
`import_pages` merge dropped/garbled link annotations). New flow in
`build_report_pdf`:
  1. `_render_cover_onto(pdf, ...)` (refactored out of `build_cover_page_bytes`)
     draws the cover as page 1 (margins zeroed, restored to 10mm after) and
     lays a clickable link band per region row; returns `{region_id: link_id}`.
  2. While rendering regions, capture each region's first page via
     `pdf.page_no()+1` (every `_render_region` opens with `add_page()`).
  3. `pdf.set_link(link, page=N)` wires each cover link to its region; fpdf2
     emits native GoTo destinations at `output()`.
`build_cover_page_bytes` kept as a thin standalone-preview wrapper.

**Link geometry** (new constants in pdf_render.py, A4-landscape mm,
measured 2026-06-02 from the rendered cover): `COVER_LINK_X_MM=172`,
`COVER_LINK_W_MM=120` (band spans x 172..292mm = region name through count),
`COVER_LINK_ROW_H_MM=6.2` (< ~6.6mm row pitch → no overlap). Row vertical
centres DERIVED from `COVER_REGION_COUNTS` so they stay locked if the cover
is re-tuned.

**Verified:** `validate_report_pdf.py` + `validate_one_part_notice.py` pass
(26 pages, 482 rows). Annotation dump confirms 10 GoTo links, each resolving
to the correct region's first page (one-part→pg1, geelong→pg2, gippsland→pg6,
horsham→pg8, metro-north→pg9, metro-se→pg13, metro-west→pg15, rne→pg21,
regional-west→pg23, warrnambool→pg25), all targeting top-of-page. Cover
artwork unchanged (date/total/counts overlay intact).

Lessons:
  - **pypdfium2 `import_pages` does not preserve fpdf2 link annotations.**
    For clickable internal links, build the whole doc in one `FPDF` and use
    native `add_link`/`link`/`set_link` rather than rendering + merging.
  - **fpdf2 emits internal links as explicit `/Dest` arrays** ([page_ref
    /XYZ x y zoom]), NOT `/A /GoTo` — inspect via `data.get('Dest')` +
    `resolve_all`, not `/A/D`.
  - **`set_link` can be called after pages render** — create the link + draw
    the clickable rect on page 1 early, resolve the destination page once
    known; fpdf2 binds at output().

---

## 2026-06-02 — Deployment prep for Claude Cloud Routines (Phase A)

Hosting locked = Claude Cloud Routines on Tom's Pro plan (see
`../Bolst_Hosting_Options.md`). Engine works manually; making it self-driving
needs the prep below. Plan is phased: A = Apex-side code/repo prep (no Tom),
B = OAuth headless de-risk (go/no-go), C = repo + secrets + routines in Tom's
account, D = pilot → sign-off → flip recipient to Tom.

### A1 — Folded the One Part morning poll INTO the morning report (DONE)
Decision (Inam): unconfirmed Specialised picks already fall to region; the
remaining cloud blocker was the picks handoff. Routines are stateless (fresh
VM per fire), so the old `.cache/last_morning_picks.json` written by the 06:30
poll did NOT survive to the 07:00 report. Fix: the report reads Tom's reply
INLINE at send time.
  - New `lib/one_part_collect.py::collect_picks(report_date_str, *,
    bundle_root) -> CollectedPicks` — lifts `_search_thread` /
    `_extract_reply_text` / `_is_from_tom` out of the old poll into the lib;
    reads the latest non-Tom reply, fetches live Specialised candidates, runs
    `parse_picks`.
  - `skills/compose-and-send/send_report.py` now calls `collect_picks()`
    inline (wrapped in try/except — a Graph hiccup on the reply read no longer
    sinks the report; it ships with auto-flagged rows). Removed
    `read_picks_for` import + `_picks_to_rows` helper.
  - `skills/one-part-collect/run.py` slimmed to a thin debug wrapper over
    `collect_picks` + `write_picks` (kept for manual inspection; NOT on the
    cloud path). Fixed a latent `subject_anchor` NameError that would have hit
    any reply-found path (only the zero-reply path was ever smoke-tested).
  - **Consequence:** the 06:30 morning-poll routine is now OBSOLETE — do NOT
    create it in Phase C. Weekday fires drop 3 → 2 (evening prompt + morning
    report), comfortably under the Pro 5/day cap.
  - Verified live (`--no-send`, 2026-06-02): 6/6 builders (514 rows), inline
    reply read handled "no reply today" cleanly, 481 kept, 12 auto-flagged One
    Part, cover PDF rendered. (REA CSV absent in mailbox today — non-fatal.)

### A2 — .gitignore audit (DONE)
`.gitignore` correctly excludes `.env`, `.credentials/` (the refresh token),
`.venv/`, `.cache/`, `output/`. **`git init` must be at the BUNDLE root
(`bolst-stocklist-engine/`)**, not the parent `bolst-property-group/` (which
holds proprietary builder samples + planning docs). Brand assets in `assets/`
(~14MB banners + Front Cover.pdf) ARE committed — needed for rendering.

### A3 — requirements + setup script + env contract (DONE)
  - **requirements.txt was incomplete:** `beautifulsoup4` + `lxml` (imported
    by `one_part_collect` + `graph_read`) were installed locally but unpinned,
    so a fresh VM would crash. Added beautifulsoup4==4.14.3, lxml==6.1.0,
    soupsieve==2.8.3, and promoted requests to a direct dep. Verified: pinned
    set now exactly matches the working venv (no missing/extra packages).
  - `setup.sh` — idempotent VM provisioner: venv + `pip install -r
    requirements.txt`, then writes `.credentials/token.json` from the
    `BOLST_GRAPH_TOKEN_JSON` secret (headless auth injection point).
  - `.env.example` — documents the env contract (names only, no values),
    incl. the cloud-only `BOLST_GRAPH_TOKEN_JSON` secret. Notes that
    `BOLST_REPORT_RECIPIENT` (env), NOT delivery.yml, is the recipient source
    of truth — the routine YAMLs/docs claiming "flip delivery.yml" are wrong.

### A4 — RUNBOOK.md (DONE)
`RUNBOOK.md` written: what it does (2 routines), the env/secrets table,
local run commands, the Phase C deploy steps, the headless-OAuth caveat +
token capture/re-capture, the Phase B test procedure, and a troubleshooting
table. Source of truth for handover ops.

### A5 — config/doc reconcile (DONE)
  - `routines/one-part-morning-poll-0630.yml` replaced with a DEPRECATED
    stub (`deprecated: true`, `superseded_by: morning-report-0700.yml`) so
    it's never fed to /schedule.
  - `routines/morning-report-0700.yml` prompt fixed: reads the reply inline
    via collect_picks, not `.cache`; recipient note → env var (not delivery.yml).
  - `routines/one-part-evening-1600.yml`: recipient → `BOLST_ONE_PART_RECIPIENT`
    (was wrongly `BOLST_REPORT_RECIPIENT`); subject-match note → collect_picks.
  - `config/delivery.yml`: added "env var is source of truth" note; schedule
    now lists 2 weekday routines (06:30 poll + 06:45 cutoff commented out as
    folded into 07:00).

**PHASE A COMPLETE.** All Apex-side code/repo prep done + live-validated. No
Tom dependency consumed yet.

### Phase B (GO/NO-GO) — DECIDED 2026-06-02: validate in the cloud
Goal: prove the refresh token survives stateless headless fires. The
destructive dev replay test risks invalidating the live dev token (AAD may
reject a replayed RT) and acquire_token_silent can serve a cached ACCESS
token → false PASS. **Inam's call: don't test on dev.** Capture a FRESH
token for the cloud at Phase C, deploy, and let the first 1-2 real Routine
fires be the test (PASS = two consecutive fires auth with no invalid_grant;
FAIL = token-persistence workaround or Vercel+Blob). Only cost on failure =
re-capture a token; dev untouched. RUNBOOK.md §6 updated to match.

Phase B is now bundled into Phase C — both need Tom (GitHub repo + Claude
login). **Everything Apex-side that can be done without Tom is DONE.**

### REA ingest fix — weekly cadence + subject-scoped search + mandatory (2026-06-02)
Triggered by Tom: 2026-06-02 report had no REA listings. Root cause: REA is a
WEEKLY file (Tom emails himself the dashboard CSV each Monday, reused Tue-Sat),
but the ingest searched only Tom's 20 most-recent emails — his high daily
volume buried the CSV outside that window. Tom HAD in fact sent today's
("REA Listings 2.6.csv", 2026-06-02, 118 listings); the old window just
couldn't see it. (My earlier manual mailbox search also missed it — only
checked the first page of relevance-ranked results.)

Fixes:
  - `lib/graph_read.py`: new `_build_from_search(sender, subject)` injects the
    subject into the Graph `$search` (`from:Tom AND subject:"REA CSV"`), so the
    latest matching CSV is found regardless of how much other mail Tom sends.
    `_list_recent_messages_from` gained a `subject=` param (+ `sentDateTime` in
    $select); `_try_sender_for_attachment` passes the builder's subject_filter
    through. Helps Aldrich too (narrows its noisy window). No same-day/age
    restriction — take the most recent; reuse all week.
  - `skills/compose-and-send/send_report.py`: REA is now MANDATORY —
    `_ingest_rea_listings` empty → `main()` ABORTS before render/send (returns
    1). Reverses the prior "non-fatal, ship builder-only" stance.
    `_log_rea_freshness()` notes current-week vs prior-week (uses most recent
    either way).
  - Docs synced: builders.yml rea comment, morning-report-0700.yml prompt,
    RUNBOOK §7, Bolst_Handover_Brief.md (§3 prereq + troubleshooting).
  - Verified live (`--no-send`, 2026-06-02): found `REA Listings 2.6.csv`
    (current-week, 118 listings), 527 builder rows → 485 kept + 118 REA folded
    in, report rendered. output/bolst-stocklist-2026-06-02.pdf now INCLUDES
    REA listings.

### Routines capability research (2026-06-02) — VERDICT: viable, with caveats
Researched current Claude Code routines docs before the Tom handover session.
  - **Routines = full Claude Code cloud sessions** (Ubuntu 24.04, Python/git/
    pip preinstalled, shell, network). CAN clone repo + pip install + run the
    Python engine. Cron + Australia/Melbourne tz supported. Pro = 5 runs/day
    (our 2 weekday routines fit; min interval 1 hour).
  - **Stateless per run** (fresh repo clone) — confirms the poll-fold was
    necessary. Per-env **setup script cached ~7 days** (put pip install there);
    env vars inject in `.env` format, not in repo.
  - **RISK 1 — private-repo auth is flaky** (Anthropic issues #64130, #60101:
    OAuth integration can't reliably clone private repos in remote agents).
    Mitigation: Claude GitHub App on the repo, or clone via a GitHub PAT env
    var. This is the #1 thing to verify.
  - **RISK 2 — no secrets manager**: env vars visible to anyone who can edit
    the cloud environment. Fine for Tom's own account; rotate password after.
  - **RISK 3 — research preview**: limits/behaviour may change. Keep Vercel as
    documented fallback (`../Bolst_Hosting_Options.md`).
  - **Action: run a ~30-min pre-flight test routine on Inam's own account with
    a throwaway private repo BEFORE the Tom session** to prove clone + secrets
    + pip/python on a fired routine. RUNBOOK §4 + §4a rewritten with the
    confirmed mechanism + this pre-flight.

## 2026-08-06 — Graph token renewed; Goldstate + Monaco live; uncategorised driven to 0

Session picked up from the 2026-08-05 pause. The one blocker was Tom's Microsoft
sign-in; everything else followed from unblocking it.

**Token renewal (RESOLVED).** Both routines had been failing since Tue 4 Aug —
Tom's 3 Aug M365 password change revoked the frozen refresh token (AADSTS50173,
`TokensValidFrom 2026-08-03T08:22:55Z`). Renewed live on a call: `python -m
lib.auth` device flow as Tom, then the base64 cache pasted into
`BOLST_GRAPH_TOKEN_JSON_B64` in the `bolst` environment on Tom's claude.ai.
Local silent refresh confirmed working afterwards.
  - **Ordering lesson:** capture the `.b64` **AFTER** the `--no-send` verify, not
    before. MSAL rotates the refresh token on every successful run and rewrites
    `token.json`, so capturing last ships the newest token, already proven.
  - **Trap:** `env-file.md` (bundle root, gitignored, never committed) holds a
    full b64 token and is the paste-source for the env block. It must be updated
    at renewal or a later paste silently redeploys the DEAD token.
  - `Mail.Send` is still UNVERIFIED — every run this session used `--no-send`.

**Goldstate + Monaco wired for live ingest.** builders.yml entries written
against the REAL emails (the 2026-08-05 samples were Gmail screenshots with no
recoverable hrefs). Both use the existing `buttons` / `text_contains` strategy,
so NO new ingest code was needed.
  - **Goldstate** `sales@goldstate.com.au`, link text `GoldstateHomesStockList.pdf`,
    href = MailerLite click-tracker → storage.googleapis.com PDF.
    `subject_filter: "Stock List"` is **load-bearing**: that sender also blasts
    campaign mail with no stocklist link, which would be picked as `latest` and
    fail. BDMs deliberately NOT added as secondary_senders — `dbowen@` sends only
    personal correspondence, `dprendergast@` sends nothing.
  - **Monaco** `jacob.l@monacobuilt.com`, button `WEEKLY STOCKLIST LINK` (of 4).
    href is wrapped in `urldefense.proofpoint.com` by Bolst's OWN inbound mail
    security; verified requests follows it straight through to the MailChimp PDF,
    so no decoder needed. Decode recipe left in a builders.yml comment.

**Live 8-builder run:** 759 rows from 8/8 → 730 kept + 131 REA, 41 pages,
cover total reconciles. goldstate 62, monaco 213 unique (dedupe working — a
failure would have shown ~639).

**Uncategorised 9 → 13 → 0.** Three distinct causes, three distinct fixes:
  - config (`suburbs.yml`): `Officer South` + `Beaconsfield` → metro-south-east;
    new `Wangandary` → regional-north-east; aliases `Mickelham`→Mickleham and
    `Wagandary`→Wangandary.
  - code (`routing.py`): new `_STATE_COUNTRY_TAIL` strips a trailing
    state/country BEFORE the comma rule. Hermitage sends
    `Winter Valley VIC, Australia` and `rsplit(",")[-1]` was reducing it to
    `AUSTRALIA`. An alias could NOT fix this — an `AUSTRALIA` key would swallow
    every future such suburb. Rule list in suburbs.yml renumbered to 6 steps.
  - parser (`specialised.py`): new `_split_on_suburb_anchor`. The old code took
    the estate token count from the SECTION HEADER and applied it to every row,
    so a row whose own estate had a different word count shifted every field
    (`35 Quartz Street Wagandary One Mile Creek` under a `WAGANDARY - GRANITE
    PARK` header → suburb `One`, estate `Mile Creek`, street absorbed the
    suburb). Anchoring on the suburb makes estate word count irrelevant.
    **Subtlety:** some estates repeat the suburb (`Kilmore Kilmore Grounds`), so
    the anchor prefers the position whose trailing tokens exactly equal the
    section estate before falling back to position. Word-count path KEPT as
    fallback so nothing that parsed before stops parsing.

**Silent partial ingest — surfaced (`graph_read.py`).** `_fetch_html_link_mode`
raised only if NO buttons resolved; partial success returned silently and the
`missing` list was discarded. So the report had been quietly missing **Aplace's
"100% Upfront commission"** and **Luxton's "2 Part Stock List"** (~37 packages).
Now warns on stderr naming the missing lists and the source email date. Cause is
NOT ours: both senders' latest emails genuinely omit those buttons (Luxton's
6 Jul send was a 1-Part-only campaign, and he has sent nothing since).
NOTE: the warning lands in routine LOGS, not the report email — threading it
into the footer needs a `fetch_all_for_builder` signature change, deliberately
not bundled here.

**Roster centralised — new `lib/builder_roster.py`.** The PARSERS dict had been
hand-copied into three files; the audit script had drifted to 6 builders and
reported "all suburbs map cleanly" for builders it never loaded, and
`render_local.py` was also still on 6. All three now import the shared roster
(verified they reference the SAME object). Adding a builder = parser file +
builders.yml entry + one line in builder_roster.py.

**Verification.** Regression suite unchanged at **15 pass / 4 fail** before and
after. The 4 fails: `validate_hermitage` + `validate_luxton` (pre-existing, see
2026-08-05 notes) and `validate_graph_read_aplace` + `..._luxton`, which assert
2 files each and are red because of the missing-button issue above — all four
were already red before this session's changes. The Specialised change was
additionally proven by forcing the anchor to return None (which reproduces the
old path exactly) and diffing field-by-field over all 5 cached stocklists,
261 rows: **1 row changed, 0 rows lost.** Normalisation change covered by 27
assertions including every pre-existing case.

**NOT DONE / next session:**
  1. **COMMIT + PUSH — deferred by Inam until Tom replies.** Until then the cloud
     routine runs the 11 Jun commit and the 07:00 fire keeps sending the OLD
     6-builder report. 13 changed/new files in the tree.
  2. South Australia region — needs an 11th hand-calibrated
     `COVER_REGION_COUNTS` y-coordinate, not just a `regions:` entry, and Tom's
     REA export has ZERO SA stock today.
  3. Verify `Mail.Send` on the new token.
  4. Ask Tom: the week-old REA CSV (30 Jul), and whether Aplace/Luxton stopped
     sending those second stocklists on purpose.

---

## 2026-09-11 — Token outage #3 → app-only auth + external heartbeat (branch `app-only-auth-heartbeat`)

**Trigger.** Friday call with Tom (06:52 PKT, Gemini notes in the project root):
the 07:00 routine has produced nothing for weeks; the run log says
"Reauthenticate". Tom reset his password after a hack attempt. Third auth
outage of the year (10 Jul ageing, 4 Aug reset, now Sep). Tom also retired the
One Part evening routine, reported Luxton changed their newsletter, and REA
missing Warrnambool/Horsham. Decision: stop patching tokens; make auth
credential-based and make failures impossible to miss.

**Findings before coding.**
  - The routine platform has NO failure notification. The `on_failure: notify:`
    block in `routines/morning-report-0700.yml` was our own fiction — nothing
    ever read it. That is why a dead engine stayed silent for weeks.
  - Only two lines in the code assumed a signed-in user: the `/me/messages`
    and `/me/sendMail` endpoint constants.
  - Local `.credentials/token.json` was last refreshed 13 Aug and is the same
    delegated grant, so it is dead too. `render_local.py` still fetches
    builders via Graph — there is no "render from emailed files" mode.
  - REA: newest ingested CSV is `20260730-REA CSV 30 7.csv` even in the 13 Aug
    run. It has 2 Horsham + 4 Stawell rows and 0 Warrnambool (May/Jun files had
    5–6). The 13 Aug PDF rendered Horsham fine. Upstream question for Tom.
  - Luxton: `text_contains` button match on Stefan's MailChimp buttons
    (incl. his "Sock" typo). Last fetched Luxton file: 6 Jul, one-part only.
  - Repo has two `origin/claude/happy-goldberg-*` branches from Tom's own
    Claude sessions on 3 Sep (gitignore line). Harmless.

**Changes (all dormant until the new env vars exist — nothing breaks before consent).**
  - `lib/auth.py` REWRITTEN: two modes behind one `get_access_token()`.
    APP-ONLY (client credentials, `ConfidentialClientApplication`,
    `.default` scope) selected automatically when
    `BOLST_AZURE_CLIENT_CERT_PEM_B64` / `_PEM_PATH` / `BOLST_AZURE_CLIENT_SECRET`
    is set; DELEGATED device flow kept as fallback. Certificate thumbprint +
    expiry derived from the PEM bundle (cryptography). `graph_user_base()`
    returns `/me` or `/users/<BOLST_MAILBOX>` (default = report sender).
    `log_credential_expiry()` prints one line per run, WARNING ≤ 60 days,
    offline (no MSAL construction). `--verify` flag GETs the inbox read-only.
    Rejects `/common` authority up front. Never prints token material.
  - `lib/graph_read.py`, `lib/graph_send.py`, `lib/one_part_collect.py`:
    endpoint constants → `messages_endpoint()` / `sendmail_endpoint()`.
  - `lib/heartbeat.py` NEW: Healthchecks.io-compatible dead-man's switch.
    `start()` / `ok(summary)` / `fail(reason)`; no-op when
    `BOLST_HEARTBEAT_URL` unset; never raises; never prints the URL; body =
    counts + builder ids only (third-party service).
  - `skills/compose-and-send/send_report.py`: `main()` → `_run()` returning
    `(exit_code, summary)`; new `main()` pings start, then ok ONLY on Graph
    202, /fail on HELD / non-202 / any exception (re-raised unchanged).
    `--no-send` never pings. `log_credential_expiry()` at the top of every run.
  - `setup.sh`: recognises the app-only vars; token cache now legacy; notes
    when heartbeat is off. `.env.example`: full documentation of the new vars
    + openssl recipe. `routines/morning-report-0700.yml`: fictional notify
    block replaced by a note; 6→roster builders; heartbeat described.
  - `RUNBOOK.md`: §1 evening routine RETIRED, §2 new vars, §5 marked LEGACY,
    §7 new rows, §9 app-only procedure + rotation, §10 heartbeat.
  - Tests NEW (offline): `tests/validate_auth_mode.py` (mode selection, PEM
    parsing, thumbprint/expiry, error paths, endpoints follow mode),
    `tests/validate_heartbeat.py` (stubbed requests: ok/fail/start URLs,
    truncation, never-raise, URL never echoed).
  - Project root: `Bolst_Tom_Call_2026-09-14_AppOnly_Cutover.md` — everything
    needed from Tom and from his Entra app on Monday's call (permissions +
    consent, certificate, Exchange application access policy PowerShell,
    cloud env vars, verification order, device-code insurance path).

**NOT DONE / Monday.** Tom: admin consent for APPLICATION `Mail.Read` +
`Mail.Send`, certificate upload, Exchange access policy, env vars, delete the
evening routine. Inam: generate cert + Healthchecks check beforehand; merge to
main before the manual run; remove the legacy token secret; then Luxton fix and
REA CSV check from Tom's forwarded mail. Nothing committed yet.

**Verification (same session, offline — the dead token means no live Graph run).**
`tests/validate_auth_mode.py` 36/36 PASS (one test constant corrected: 2028 is a
leap year, 731 days). `tests/validate_heartbeat.py` 22/22 PASS. Wrapper
simulation with `_run` stubbed: success → start+OK ping; HELD → start+/fail;
crash → start+/fail then re-raised; `--no-send` success/crash → zero pings.
Existing offline suite unchanged: validate_routing, validate_pick_apply,
validate_one_part_notice, validate_report_pdf all PASS. `compileall` clean.
`routines/one-part-*.yml` + `delivery.yml` marked RETIRED. NOTHING COMMITTED.

**Decision (Inam, same day): client secret at Microsoft's 24-month portal
maximum; certificate deferred.** Research: Microsoft caps portal secrets at 24
months (Learn: how-to-add-credentials; M365 dev blog "client secret expiration
now limited to two years"); longer only via PowerShell/Graph and advised
against; tenant app-management policies can shorten or block secrets on newer
apps (fallback = the certificate path, already in code). Tom doc, RUNBOOK §9,
`.env.example` and the auth docstring reworded; code unchanged (both forms
supported, certificate wins if both set). Secret created mid-Sep 2026 → expires
mid-Sep 2028 → calendar reminder mid-Jun 2028; run log warns at 60 days.

**Late-session changes (Inam's answers, 2026-09-11 evening).**
  - **Heartbeat REMOVED entirely** — Inam: "remove heartbeat part, we don't need
    it, I will remember the expiry date". `lib/heartbeat.py` + its test deleted;
    `send_report.py` restored to main + only the `log_credential_expiry()` line
    and import added; setup.sh / .env.example / routine yml / RUNBOOK (§10 gone)
    cleaned. Consequence, recorded in RUNBOOK §9: there is NO failure alerting —
    a missing report is noticed by Tom or by reading the run log.
  - **Facts from Inam:** Tom IS the tenant admin; he still emails the REA CSV
    every Monday (so the 30 Jul staleness is OUR lookup's miss); he has already
    deleted the One Part evening routine; South Australia on hold; hack timing
    irrelevant.
  - **REA lookup broadened** (`config/builders.yml` rea.filename_patterns +=
    `*.csv`): sender + "REA CSV" subject already scope the match, so any .csv
    attachment (e.g. Ignite's native `HomeLandPkg_Active_All_Agents_<date>.csv`)
    is accepted. Cannot verify without auth — a OneDrive-link instead of an
    attachment, or a changed subject/sender, would still miss.
  - **New diagnostic `tests/dump_latest_emails.py`** (read-only, either auth
    mode): per recent email prints subject, date, from, attachments, every link
    (text → href → `--resolve` final URL + content-type). Built for Monday:
    `--builder rea` (why the CSV is missed) and `--builder luxton --resolve`
    (Stefan's new newsletter). Luxton goal per Inam: "detect changes and extract
    listing by any means" — design the format-agnostic extractor from the real
    email once auth is back; no forwarding from Tom needed.
  - Exchange application access policy stays in the Tom doc as OPTIONAL with a
    plain explanation (application permissions are tenant-wide; the policy
    narrows the app to Tom's mailbox; no functional effect).
