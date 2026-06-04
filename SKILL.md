---
name: bolst-stocklist-engine
description: Builds Bolst Property Group's daily morning stocklist report. Reads builder stock-list emails from Outlook, parses 6 builders' PDFs/XLSX, pulls REA listings from a scheduled Ignite CSV, applies routing/filtering rules, renders the Bolst-branded PDF, and emails it to the configured recipient. Use when the daily 06:50 AEST routine fires, or when the user asks to "run the morning report", "generate today's stocklist", "rebuild the report", or troubleshoot any part of the daily flow.
---

# Bolst Stocklist Engine

Daily morning report engine for Bolst Property Group. Replaces Tom Bolst's manual workflow of opening 6 builder emails, copying lots into his branded Excel template, and PDF-emailing it.

## What it does

Every morning at 06:50 AEST:

1. **Reads Tom's Outlook** for the latest builder stocklist emails (6 senders) and the scheduled Ignite REA CSV.
2. **Parses each source** into a unified row format: `{lot, address, suburb, estate, titles, beds_baths_cars, price, status, source_builder}`.
3. **Routes each row** to one of 10 regional tabs based on the suburb map. New suburbs land on an `Uncategorised` tab.
4. **Drops rows** with status `Contract Sign(ed)` or `Sold`. Keeps everything else (incl. Hold, Not Available).
5. **Pulls One Part Specialised picks** from Tom's reply to the previous evening's prompt (06:45 AEST cutoff).
6. **Renders the branded PDF** with 10 region banners + footer, plus the One Part Contracts tab + Bolst Listings tab.
7. **Emails the PDF** to `inam@meetapex.ai` (Phase 1) from `inam@meetapex.ai`'s Gmail.

Two side routines:

- **17:00 AEST evening prompt** — emails Tom tomorrow's Specialised stock so he can reply with One Part picks at his leisure.
- **Approval watcher** — if no `approved` reply lands by 11:00 AEST, holds and resends at 13:00.

## Sub-skills

| Sub-skill                         | When invoked                                                       |
| --------------------------------- | ------------------------------------------------------------------ |
| `skills/ingest-builder-stocklist` | For each new email matching one of the 6 builder filename patterns |
| `skills/ingest-rea-export`        | Once per morning, on the Ignite CSV email                          |
| `skills/route-to-region`          | After ingestion, before rendering                                  |
| `skills/apply-status-filter`      | After routing, drops Contract Sign/Sold rows                       |
| `skills/render-bolst-pdf`         | Once all data is collected and routed                              |
| `skills/one-part-prompt`          | Triggered by the 17:00 evening routine                             |
| `skills/one-part-collect`         | Triggered by the 06:30 morning poll routine                        |
| `skills/compose-and-send`         | Final step — packages PDF and sends                                |

## Orchestration — the daily 06:50 AEST flow

```
06:30  one-part-collect       → reads Tom's Outlook reply, parses lot numbers
06:45  cutoff                 → freeze One Part picks (banner if no reply)
06:50  daily-build:
       1. ingest-rea-export        (Ignite CSV from Outlook)
       2. ingest-builder-stocklist (×6, parallel)
       3. route-to-region          (apply suburbs.yml)
       4. apply-status-filter      (drop Sold + Contract Signed)
       5. render-bolst-pdf         (10 tabs + One Part + Listings)
       6. compose-and-send         (Gmail → inam@meetapex.ai)
11:00  approval-watcher       → if no "approved" reply, hold
13:00  approval-watcher       → resend
17:00  one-part-prompt        → email Tom tomorrow's Specialised stock
```

## Configuration (no code changes needed)

All operational knobs live in `config/`:

- `builders.yml` — sender/filename → builder → parser
- `suburbs.yml` — suburb → region map (10 regions)
- `status-filter.yml` — status values to drop
- `reps.yml` — sales reps for Phase 1.5 fan-out
- `delivery.yml` — recipient + send time

Tom edits these post-handover; no Python changes required.

## Architectural commitments

- **End-to-end OAuth.** Microsoft 365 MCP for Outlook reads; Gmail MCP for sends. No passwords, no scraping, no Playwright.
- **REA via Outlook.** Tom configures Ignite to email a daily scheduled CSV report to his own Outlook; we read it from there. No separate Ignite credentials.
- **Self-contained bundle.** Brand assets travel with the skill. Tom installs once in Claude Desktop; everything works.

## Dev mode (current)

During development, the Outlook connection points to Inam's `inam700@outlook.com` (he forwards builder samples from Gmail). Builder identification uses **attachment filename** because Gmail-forwarded mail has rewritten `From:` headers. At handover, the connection swaps to Tom's Outlook and sender-mapping is layered on top.

See `BUILD_LOG.md` for current build progress and `..\Bolst_Phase1_Plan.md` for the full plan.
