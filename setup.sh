#!/usr/bin/env bash
# setup.sh — provision a fresh VM (Claude Cloud Routine) to run the
# bolst-stocklist-engine. Idempotent: safe to re-run.
#
# Steps:
#   1. Create a venv and install the pinned dependencies.
#   2. Reconstruct the MSAL OAuth token cache from the injected secret.
#
# The token cache (.credentials/token.json) is gitignored and never in the
# repo. Locally it lives on disk; on the cloud VM it is injected as the
# BOLST_GRAPH_TOKEN_JSON Routine secret and written here at setup time.
#
# NOTE (auth caveat — see RUNBOOK.md "OAuth in a headless VM"): MSAL may
# rotate the refresh token on each run and write a new token.json, which is
# DISCARDED when the stateless VM shuts down. The next fire therefore replays
# the ORIGINAL secret. This works within Azure AD's ~90-day refresh window
# but must be smoke-tested, and the secret re-captured before expiry.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
echo "[setup] python: $($PY --version)"

$PY -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ -n "${BOLST_GRAPH_TOKEN_JSON:-}" ]; then
  mkdir -p .credentials
  printf '%s' "$BOLST_GRAPH_TOKEN_JSON" > .credentials/token.json
  echo "[setup] wrote .credentials/token.json from BOLST_GRAPH_TOKEN_JSON"
else
  echo "[setup] WARNING: BOLST_GRAPH_TOKEN_JSON not set — Graph auth will" \
       "fail in headless mode (device-code flow cannot run without a browser)."
fi

echo "[setup] done"
