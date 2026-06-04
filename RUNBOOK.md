# Bolst Stocklist Engine — Deployment & Operations Runbook

How to run the engine, deploy it to Claude Cloud Routines, manage its
secrets, and recover from the common failure modes. Pair with `BUILD_LOG.md`
(build history) and `../Bolst_Hosting_Options.md` (why Routines).

---

## 1. What it does

Each weekday the engine:

| Time (Australia/Melbourne) | Day | Routine | Action |
|---|---|---|---|
| **16:00** | Mon–Fri | `bolst-one-part-evening` | Email Tom the day's Specialised One Part *candidates*. He replies with the lots he wants on the One Part tab. |
| **07:00** | Tue–Sat | `bolst-morning-report` | Fetch all 6 builders + REA live, read Tom's overnight reply **inline**, apply his picks, render the branded PDF (clickable cover), send it. |

> **Two routines only.** The old 06:30 poll was folded into the 07:00 report
> (2026-06-02) — Routines are stateless, so the report reads Tom's reply
> itself rather than via a cached file. Do **not** create a morning-poll
> routine (`routines/one-part-morning-poll-0630.yml` is deprecated).

Each morning covers the previous weekday's data (Mon prompt → Tue report …
Fri prompt → Sat report). Quiet inbox Sun + Mon.

---

## 2. Secrets / environment variables

All config is environment-driven (`lib/auth.py`, `send_report.py`,
`send_evening_prompt.py` read `os.environ`). See `.env.example` for the full
list. Locally these live in `.env` (gitignored). In the cloud they are
**Routine secrets** — never commit them.

| Var | Purpose |
|---|---|
| `BOLST_AZURE_CLIENT_ID` | Entra app (public client) |
| `BOLST_AZURE_TENANT_ID` | Bolst tenant |
| `BOLST_AZURE_AUTHORITY` | `https://login.microsoftonline.com/<tenant-id>` |
| `BOLST_AZURE_SCOPES` | `Mail.Read Mail.Send Mail.ReadWrite` |
| `BOLST_REPORT_SENDER` | Report sent FROM (Tom's Outlook) |
| `BOLST_REPORT_RECIPIENT` | Report sent TO. **Source of truth for the recipient — NOT delivery.yml.** Build phase = `inam@meetapex.ai`; flip to Tom at sign-off. |
| `BOLST_ONE_PART_RECIPIENT` | Evening prompt recipient (Tom) |
| `BOLST_GRAPH_TOKEN_JSON` | **Cloud only.** Full contents of `.credentials/token.json` (the MSAL token cache). `setup.sh` writes it to disk on the VM. See §5. |

---

## 3. Run it locally (manual / pilot)

From the bundle root (`bolst-stocklist-engine/`), with the venv active:

```bash
# Morning report — render only, no send (safe; writes output/*.pdf)
python skills/compose-and-send/send_report.py --no-send

# Morning report — live send to BOLST_REPORT_RECIPIENT
python skills/compose-and-send/send_report.py

# Evening One Part prompt
python skills/one-part-prompt/send_evening_prompt.py

# Inspect what the report would collect from Tom's reply (debug only)
python skills/one-part-collect/run.py --report-date YYYY-MM-DD
```

Per the client-comms rule, generate to disk and review before any send to
Tom (see the project's preview-before-send preference).

---

## 4. Deploy to Claude Cloud Routines (Phase C)

Mechanism confirmed by research 2026-06-02 (docs: code.claude.com/docs
routines + claude-code-on-the-web). A Routine is a **full Claude Code cloud
session** (Ubuntu 24.04; Python/git/pip preinstalled; network; shell). Each
run **re-clones the repo fresh** (stateless — why the One Part poll was
folded in). A per-environment **setup script is cached ~7 days** (good place
for `pip install`); env vars inject in `.env` format and never enter the
repo. Cron + Australia/Melbourne timezone supported; Pro = 5 runs/day (our 2
weekday routines fit; min interval 1 hour).

Prereqs: pre-flight test (§4a) passed; Tom's sign-off on a sample; Tom's
Claude login for one-time setup.

1. **Repo.** `git init` at the **bundle root** (`bolst-stocklist-engine/`),
   NOT the parent (it holds proprietary builder samples + planning docs).
   Confirm `.gitignore` excludes `.env`, `.credentials/`, `.cache/`,
   `.venv/`, `output/`. Push to a **private** GitHub repo in Tom's account.
2. **GitHub access for the cloud agent.** Private-repo cloning via the
   default OAuth integration is documented-flaky (Anthropic issues #64130,
   #60101). Use the **Claude GitHub App** installed on this specific repo.
   Robust fallback: store a fine-grained read-only **GitHub PAT** as an env
   var and clone via
   `https://x-access-token:$GITHUB_PAT@github.com/<owner>/<repo>`.
3. **Cloud environment + secrets.** Create/assign a cloud environment. Add
   every var from §2 in `.env` format, including `BOLST_GRAPH_TOKEN_JSON`.
   Set the environment **setup script** to
   `pip install -r requirements.txt` (cached → fast subsequent fires).
   NOTE: env vars are visible to anyone who can edit this environment — fine
   for Tom's own account; he rotates his password after handover.
4. **Token reconstruction each run.** Because the repo is re-cloned fresh per
   fire, the routine prompt must (re)write the token before running: run
   `bash setup.sh` (writes `.credentials/token.json` from
   `BOLST_GRAPH_TOKEN_JSON`) then the script. Keep this in the per-run
   prompt, not only the cached setup script.
5. **Routines.** Create exactly two (web UI claude.ai/code/routines or
   `/schedule`; custom cron via `/schedule update`):
   - `bolst-one-part-evening` — cron `0 16 * * 1-5`, `Australia/Melbourne`
     — runs `skills/one-part-prompt/send_evening_prompt.py`
   - `bolst-morning-report` — cron `0 7 * * 2-6`, `Australia/Melbourne`
     — runs `skills/compose-and-send/send_report.py`
6. **Smoke test.** Fire one of each manually; confirm the evening email
   arrives and the morning report renders + sends (to Inam during build
   phase). The first 1–2 real morning fires double as the OAuth go/no-go
   (§6).

### 4a. Pre-flight test (do BEFORE the Tom session)

Routines is a research preview and private-repo auth is the riskiest link.
On your *own* Claude account with a throwaway private repo, prove three
mechanics in ~30 min so the client session is pure execution:
  (a) the cloud agent can **clone the private repo**,
  (b) **env-var secrets inject** and are readable by the script,
  (c) `pip install` + a trivial `python` run succeed on a fired routine.
If private cloning misbehaves → switch to the PAT method (step 2) or the
Vercel fallback (`../Bolst_Hosting_Options.md`) — decided before, not during.

---

## 5. OAuth in a headless VM (the critical caveat)

`lib/auth.py` uses **device-code flow** — interactive sign-in, impossible on
an unattended VM. So the cloud never signs in; it reuses a **pre-captured
refresh token**.

**Capture (one-time, on a machine with a browser):**
```bash
python -m lib.auth          # completes device-code sign-in as Tom
# then copy the file contents into the BOLST_GRAPH_TOKEN_JSON secret:
cat .credentials/token.json
```

**The risk to validate (Phase B):** MSAL rotates the refresh token on use and
writes a new `token.json`. A stateless VM **discards** that rotated token when
it shuts down, so the next fire replays the **original** secret. This usually
works within Azure AD's ~90-day refresh window, but must be proven (run twice
from a clean inject — see Phase B). If AAD replay-protection rejects the
reused token, options are: (a) persist the rotated cache back to a secret
each run, or (b) move the schedule to a host with storage (Vercel + Blob).

**Expiry:** the refresh token's window is ~90 days of inactivity. Daily fires
keep it alive, but **re-capture and update the secret if the engine is ever
idle for weeks** (e.g. after a long pause), and watch for `invalid_grant`
errors (see §7).

---

## 6. Phase B — OAuth go/no-go (validated in the cloud)

**Decision (2026-06-02): validate in the cloud with a freshly-captured
token, NOT on the dev machine.** The dev simulation (replay the original
token after discarding the rotated one) can invalidate the working dev
token if Azure rejects the replayed refresh token — not worth the risk to
the pilot setup. Instead:

1. Capture a **fresh** token for the cloud (§5) immediately before Phase C.
2. Deploy and let the **first 1–2 real Routine fires be the test**.
3. PASS = two consecutive fires (e.g. Tue + Wed report) authenticate with no
   `invalid_grant`. FAIL = the refresh token didn't survive a stateless
   fire → pursue a token-persistence workaround (write the rotated cache
   back to a secret each run) or move to a host with storage (Vercel +
   Blob). Either way the only cost is re-capturing a token — the dev
   environment is untouched.

> Optional dev simulation (only if you want an early signal and have Tom's
> MS login on standby to re-auth): back up `.credentials/token.json`, run
> the report `--no-send` twice while restoring the *original* token between
> runs, and watch for `invalid_grant`. Skip unless you accept the
> token-invalidation risk.

---

## 7. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `invalid_grant` / auth fails on the VM | Refresh token expired or replay-rejected | Re-capture token (§5), update `BOLST_GRAPH_TOKEN_JSON`; revisit Phase B |
| Report ships but a builder is missing | That builder's email/format changed | Check the run log's `SKIP:` line; report is per-builder tolerant (still ships) |
| `ModuleNotFoundError` on the VM | Dep missing from `requirements.txt` | Add + pin it; re-verify against the venv |
| One Part tab shows no picks though Tom replied | Subject prefix mismatch or reply not found | Confirm Tom replied on the `[Bolst One Part — <date>]` thread; run `skills/one-part-collect/run.py` to inspect |
| Report HELD — "REA listings are mandatory and none were found" | No REA CSV anywhere in Tom's mail | REA is MANDATORY + weekly. Tom emails himself the CSV (subject `REA CSV`, attachment `REA*.csv`) each Monday; the report reuses it all week. Have Tom send/re-send it, then re-run. The lookup is subject-scoped so volume of other mail doesn't matter |

---

## 8. Phase / recipient transitions

- **Build phase (now):** report → `inam@meetapex.ai` (review). Evening
  prompt → Tom.
- **Mature phase:** set `BOLST_REPORT_RECIPIENT` secret to Tom. No code
  change.
- **Phase 1.5:** add Aaron Wilson + Howard Rock (reps) — `reps.yml` +
  per-rep send. Needs rep signatures + Howard's email.
