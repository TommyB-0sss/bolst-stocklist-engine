#!/usr/bin/env bash
# setup.sh — provision a fresh VM (Claude Cloud Routine) to run the
# bolst-stocklist-engine. Idempotent: safe to re-run.
#
# Steps:
#   1. Create a venv and install the pinned dependencies.
#   2. Make the Graph credential available (see RUNBOOK §9):
#        APP-ONLY (preferred): BOLST_AZURE_CLIENT_CERT_PEM_B64 or
#          BOLST_AZURE_CLIENT_SECRET is read by lib/auth.py straight from the
#          environment. Nothing to write to disk.
#        DELEGATED (legacy): reconstruct the MSAL token cache
#          (.credentials/token.json) from BOLST_GRAPH_TOKEN_JSON(_B64).
#          That cache is a frozen user refresh token: it dies on every mailbox
#          password reset and can age out (~1 month observed). Kept only as
#          the fallback until app-only is live.
#
# The token cache is gitignored and never in the repo.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
echo "[setup] python: $($PY --version)"

$PY -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ -n "${BOLST_AZURE_CLIENT_CERT_PEM_B64:-}" ] || [ -n "${BOLST_AZURE_CLIENT_CERT_PEM_PATH:-}" ] || [ -n "${BOLST_AZURE_CLIENT_SECRET:-}" ]; then
  echo "[setup] app-only Graph credential present — lib/auth.py will use client credentials (no token cache needed)"
fi

# Legacy delegated cache. Written whenever the secret is present so a
# BOLST_AUTH_MODE=delegated override still works during the cutover window.
if [ -n "${BOLST_GRAPH_TOKEN_JSON_B64:-}" ]; then
  mkdir -p .credentials
  printf '%s' "$BOLST_GRAPH_TOKEN_JSON_B64" | base64 -d > .credentials/token.json
  echo "[setup] wrote .credentials/token.json from BOLST_GRAPH_TOKEN_JSON_B64 (legacy delegated mode)"
elif [ -n "${BOLST_GRAPH_TOKEN_JSON:-}" ]; then
  mkdir -p .credentials
  printf '%s' "$BOLST_GRAPH_TOKEN_JSON" > .credentials/token.json
  echo "[setup] wrote .credentials/token.json from BOLST_GRAPH_TOKEN_JSON (legacy delegated mode)"
elif [ -z "${BOLST_AZURE_CLIENT_CERT_PEM_B64:-}${BOLST_AZURE_CLIENT_CERT_PEM_PATH:-}${BOLST_AZURE_CLIENT_SECRET:-}" ]; then
  echo "[setup] WARNING: no Graph credential set (BOLST_AZURE_CLIENT_CERT_PEM_B64 /"        "BOLST_AZURE_CLIENT_SECRET / BOLST_GRAPH_TOKEN_JSON_B64) — Graph auth will fail"        "in headless mode (device-code flow cannot run without a browser)."
fi

echo "[setup] done"
