# Bolst Stocklist Engine — Deployment & Operations Runbook

How to run the engine, deploy it to Claude Cloud Routines, manage its
secrets, and recover from the common failure modes. Pair with `BUILD_LOG.md`
(build history) and `../Bolst_Hosting_Options.md` (why Routines).

---

## 1. What it does

Each weekday the engine:

| Time (Australia/Melbourne) | Day | Routine | Action |
|---|---|---|---|
| ~~16:00~~ | ~~Mon–Fri~~ | ~~`bolst-one-part-evening`~~ | **RETIRED 2026-09-11 at Tom's request.** Tom deletes it at claude.ai/code/routines. The morning report still carries the auto-flagged One Part rows; only the reply-driven picks stop. |
| **07:00** | Tue–Sat | `bolst-morning-report` | Fetch every roster builder (`lib/builder_roster.py`, 8 as of 2026-08) + REA live, read Tom's overnight reply **inline** (no-op once the evening routine is gone), apply his picks, render the branded PDF (clickable cover), send it. |

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
| `BOLST_AZURE_CLIENT_ID` | Entra app registration in Bolst's tenant |
| `BOLST_AZURE_TENANT_ID` | Bolst tenant |
| `BOLST_AZURE_AUTHORITY` | `https://login.microsoftonline.com/<tenant-id>` — must be tenant-specific, never `/common` (app-only requires it) |
| `BOLST_AZURE_SCOPES` | `Mail.Read Mail.Send Mail.ReadWrite` — delegated (legacy) mode only; app-only uses `.default` |
| `BOLST_AZURE_CLIENT_SECRET` (+ `_EXPIRES`) | **App-only credential — the form chosen 2026-09-11.** Client secret (portal max 24 months) + its portal expiry date `YYYY-MM-DD` so every run logs the countdown. See §9. |
| `BOLST_AZURE_CLIENT_CERT_PEM_B64` | App-only alternative (deferred): base64, one line, of a PEM bundle = private key + certificate. Thumbprint and expiry derived from it. Wins over the secret if both set. See §9. |
| `BOLST_AZURE_CLIENT_CERT_PEM_PATH` | Local-dev form of the certificate alternative: path to the same PEM bundle. |
| `BOLST_MAILBOX` | Mailbox to read from / send as in app-only mode. Defaults to `BOLST_REPORT_SENDER`; normally unset. |
| `BOLST_AUTH_MODE` | `auto` (default) / `app` / `delegated` — debugging override only. |
| `BOLST_REPORT_SENDER` | Report sent FROM (Tom's Outlook) |
| `BOLST_REPORT_RECIPIENT` | Report sent TO — single address or comma-separated list. **Source of truth for the recipient — NOT delivery.yml.** Live = Tom (+ reps Aaron Wilson / Howard Rock once their addresses are confirmed). |
| `BOLST_ONE_PART_RECIPIENT` | Evening prompt recipient (Tom) |
| `BOLST_GRAPH_TOKEN_JSON_B64` / `BOLST_GRAPH_TOKEN_JSON` | **LEGACY delegated mode, cloud only.** Base64 (or raw) of `.credentials/token.json`. `setup.sh` writes it to disk on the VM. Dies on every Tom password reset — superseded by the app-only credential above (§9). Remove once app-only is live. |

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

## 5. OAuth in a headless VM (LEGACY — superseded by §9 app-only auth)

> **Read §9 first.** Everything below describes the delegated (device-code)
> design that failed three times in 2026 (10 Jul ageing, 4 Aug and Sep
> password resets). It is kept only as the fallback until the app-only
> credential is live in the cloud.

In delegated mode `lib/auth.py` uses **device-code flow** — interactive sign-in, impossible on
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
| `[auth] ... credential expires ... WARNING` / `EXPIRED` in the run log | App certificate or secret nearing/past its end date | Rotate per §9 (add the new credential in Entra BEFORE removing the old one → zero downtime) |
| `AADSTS7000215` invalid client secret / `AADSTS700027` certificate | Wrong or stale `BOLST_AZURE_CLIENT_SECRET` / PEM bundle, or cert not uploaded to the app | Compare the thumbprint `python lib/auth.py` prints with the one in Entra → Certificates & secrets |
| `401`/`403` on `/users/<mailbox>/...` in app-only mode | Admin consent missing for the APPLICATION permissions, or the Exchange application access policy excludes the mailbox | Entra → API permissions: green ticks on **Application** `Mail.Read` + `Mail.Send`; `Test-ApplicationAccessPolicy` must say Granted; policy changes take up to an hour |
| `invalid_grant` / auth fails on the VM (delegated mode) | Refresh token expired, replay-rejected or revoked by a password reset | Migrate to app-only (§9). Stop-gap: re-capture token (§5), update `BOLST_GRAPH_TOKEN_JSON_B64` |
| Report ships but a builder is missing | That builder's email/format changed | Check the run log's `SKIP:` line; report is per-builder tolerant (still ships) |
| `ModuleNotFoundError` on the VM | Dep missing from `requirements.txt` | Add + pin it; re-verify against the venv |
| One Part tab shows no picks though Tom replied | Subject prefix mismatch or reply not found | Confirm Tom replied on the `[Bolst One Part — <date>]` thread; run `skills/one-part-collect/run.py` to inspect |
| Report HELD — "REA listings are mandatory and none were found" | No REA CSV anywhere in Tom's mail | REA is MANDATORY + weekly. Tom emails himself the CSV (subject `REA CSV`, attachment `REA*.csv`) each Monday; the report reuses it all week. Have Tom send/re-send it, then re-run. The lookup is subject-scoped so volume of other mail doesn't matter |

---

## 8. Phase / recipient transitions

- **Build phase (done):** report went to `inam@meetapex.ai` for review.
- **Live (now):** `BOLST_REPORT_RECIPIENT=tom@bolstpropertygroup.com.au`.
  Evening prompt → Tom.
- **Reps:** the var takes a comma-separated list — append Aaron Wilson +
  Howard Rock once their addresses are confirmed. Update the secret in the
  cloud environment; no code change.

---

## 9. App-only Graph auth (client credentials) — the permanent fix

**Why (2026-09-11).** The delegated design froze a *user* refresh token into a
static cloud secret. It died three times in 2026: ~1-month ageing (10 Jul), Tom's
password reset (4 Aug), and the hack-attempt reset (Sep). Client credentials hold
no refresh token — every run mints a fresh ~1-hour access token from the app's
own certificate — so password resets and ageing cannot revoke it. The only
maintenance left is the credential's own expiry, a known date the engine logs on
every run (`[auth] ... credential expires YYYY-MM-DD (N days)`, WARNING ≤ 60).

**Not literally permanent — what can still break it:** the certificate/secret
expiring (planned, logged), someone deleting the app registration or its consent
(deliberate), Tom's M365 licence lapsing. Nothing accidental.

**How it works in code.** `lib/auth.py` picks app-only automatically when
`BOLST_AZURE_CLIENT_CERT_PEM_B64` (or `_PEM_PATH`, or `BOLST_AZURE_CLIENT_SECRET`)
is set, requests `https://graph.microsoft.com/.default`, and every mailbox call
goes to `/users/<BOLST_MAILBOX>/...` instead of `/me/...`
(`graph_user_base()`). Without those vars it falls back to the legacy device flow
(§5), so the change is dormant until the tenant work below is done.

**One-time tenant setup (Tom or his tenant admin; full click-path in
`../Bolst_Tom_Call_2026-09-14_AppOnly_Cutover.md`):**

1. **Application permissions + admin consent.** Entra → App registrations → the
   engine's app (client id in `.env`) → API permissions → Add → Microsoft Graph →
   **Application** permissions `Mail.Read` + `Mail.Send` → **Grant admin consent**.
   Green ticks on both.
2. **Credential — client secret.** Decision 2026-09-11 (Inam): Microsoft's
   24-month maximum is enough for now; the certificate is deferred. Entra →
   Certificates & secrets → Client secrets → New client secret → description
   `bolst-engine-cloud-<yyyy-mm>`, Expires **24 months** (730 days — the portal
   maximum; longer is possible only via PowerShell/Graph and Microsoft advises
   against it) → Add → copy the **Value** at once (shown only once; the Secret
   ID is not it). It goes into exactly two places: Inam's local `.env` (for the
   verify run) and the `bolst` cloud environment, as `BOLST_AZURE_CLIENT_SECRET`
   plus `BOLST_AZURE_CLIENT_SECRET_EXPIRES=YYYY-MM-DD` (the date the portal
   shows). Never into chat, email or a document.
   *Alternative, kept in code — use if the tenant's app management policy
   refuses to create a secret, or when a longer-lived credential is wanted:*
   certificate. On Inam's machine (Git Bash, bundle root; `.credentials/` is
   gitignored):
   `openssl req -x509 -newkey rsa:2048 -sha256 -days 1095 -nodes -subj "/CN=bolst-stocklist-engine" -keyout .credentials/bolst-engine.key -out .credentials/bolst-engine.cer`
   then `cat .credentials/bolst-engine.key .credentials/bolst-engine.cer > .credentials/bolst-engine.pem`
   and `base64 -w0 .credentials/bolst-engine.pem > .credentials/bolst-engine.pem.b64`
   → `BOLST_AZURE_CLIENT_CERT_PEM_B64`. Upload **only `bolst-engine.cer`**
   (public half) under Certificates. The engine derives thumbprint + expiry
   from the bundle. Certificate wins if both forms are set.
3. **Restrict the app to Tom's mailbox** (application permissions are tenant-wide
   by default). Exchange Online PowerShell as an Exchange admin:
   `New-DistributionGroup -Name "Bolst Stocklist Engine Scope" -Alias bolst-engine-scope -Type Security -Members tom@bolstpropertygroup.com.au`
   then `New-ApplicationAccessPolicy -AppId <client-id> -PolicyScopeGroupId bolst-engine-scope@bolstpropertygroup.com.au -AccessRight RestrictAccess -Description "Bolst stocklist engine: Tom's mailbox only"`
   and verify with `Test-ApplicationAccessPolicy -Identity tom@bolstpropertygroup.com.au -AppId <client-id>` → `Granted`.
   Takes up to an hour to apply to live Graph calls. If Tom cannot run
   PowerShell, Inam runs it with `Connect-ExchangeOnline -Device` and Tom enters
   the device code himself — no password ever changes hands.
4. **Cloud environment** (`claude.ai/code` → Environments → `bolst`): add
   `BOLST_AZURE_CLIENT_SECRET` + `BOLST_AZURE_CLIENT_SECRET_EXPIRES` (or
   `BOLST_AZURE_CLIENT_CERT_PEM_B64` if the certificate path was used).
   Keep everything else. Remove
   `BOLST_GRAPH_TOKEN_JSON_B64` once step 5 passes. The routine prompt needs no
   change — `setup.sh` recognises the new vars.
5. **Verify, in this order:** locally `python lib/auth.py --verify` (read-only
   GET of the inbox; 401/403 = consent or access policy not applied yet) →
   locally `send_report.py --no-send` → merge to `main` → "Run now" on the
   routine → Tom receives the report.
6. **Harden after cutover:** Authentication → "Allow public client flows" → No;
   remove the delegated Mail.* permissions; delete local `.credentials/token*.json`.

**Rotation (before the credential's end date, zero downtime):** create the new
secret (or certificate) in Entra *alongside* the old one, update the env var(s)
in the cloud environment and local `.env`, run `python lib/auth.py --verify`,
then delete the old credential in Entra. Two can be valid at once. A 24-month
secret created mid-Sep 2026 ends mid-Sep 2028 → calendar reminder ~mid-Jun 2028;
the run log warns at 60 days regardless.

**No failure alerting exists (decision 2026-09-11):** the routine platform
has no notification hooks and an external heartbeat monitor was built and
then dropped as not wanted. A missing report is noticed by Tom or by checking
the run log at claude.ai/code/routines; the `[auth]` line there names the
cause.

**Insurance if consent is delayed:** the §5 device-code renewal still works
(~2 min with Tom entering the code). It is a stop-gap only — it will die on
his next password reset.
