---
name: one-part-prompt
description: At 16:00 AEST, emails Tom tomorrow's Specialised Home Constructions stocklist as candidate One Part Contract picks. Tom replies with the lot numbers he wants promoted to the One Part tab; the morning poll routine reads his reply at 06:30 AEST. Use when the 16:00 evening routine fires, or when manually triggered to dry-run the One Part editorial flow.
---

# one-part-prompt

Sub-skill of `bolst-stocklist-engine`. Sends the **16:00 AEST evening prompt** that drives the One Part Contracts tab.

## Why this exists

Per Tom Bolst's directive (2026-05-01 followup, confirmed 2026-05-09): which Specialised lots appear on the One Part tab is editorial, not rule-based. We email Tom every afternoon with the candidates; he replies with picks; the next morning's report includes them.

## What it does

1. Loads today's Specialised stocklist PDF (default: live fixture; CLI flag overrides).
2. Calls `lib/one_part_candidates.get_specialised_candidates()` to filter + group rows.
3. Renders an HTML email body — one table per (suburb, estate) group, with Lot, Address, Titles, Floorplan, Bed-Bath-Car, Price columns.
4. Sends via Microsoft Graph (Tom's Outlook → `inam@meetapex.ai` during build phase) with subject `[Bolst One Part — YYYY-MM-DD]` where `YYYY-MM-DD` is **tomorrow's** report date in Australia/Melbourne timezone.
5. Returns 0 on Graph 202 Accepted; non-zero on send failure.

## Subject line is load-bearing

The morning poll skill (`one-part-collect`) finds Tom's reply by literal subject search on the `[Bolst One Part — YYYY-MM-DD]` prefix. Do **not** change the subject format without also updating `one-part-collect`.

## Usage

```
python skills/one-part-prompt/send_evening_prompt.py            # default fixture
python skills/one-part-prompt/send_evening_prompt.py path/to.pdf  # explicit file
```

## Replaced when

Stage 9.8 will introduce `lib/graph_read.py` — at that point this skill will pull the Specialised PDF live from Tom's Outlook instead of the fixture path. The candidate generator + email rendering logic stays unchanged.
