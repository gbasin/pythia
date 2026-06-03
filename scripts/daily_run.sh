#!/usr/bin/env bash
# pythia — daily panel run.
# Invoked by launchd via com.pythia.daily. Also safe to run manually.
set -euo pipefail

# launchd starts with a near-empty env. Restore PATH to include the CLI
# binaries the orchestrator shells out to (claude, codex, uv).
export PATH="/Users/garybasin/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

PROJECT_DIR="/Users/garybasin/Code/pythia"
LOG_DIR="$PROJECT_DIR/logs"
LOG="$LOG_DIR/panel-$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

# Load secrets (GEMINI_API_KEY etc.) so subprocess CLIs/scripts inherit them.
# `.env` is in .gitignore and chmod 600.
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

{
  echo
  echo "=== panel run started $(date -u +'%Y-%m-%dT%H:%M:%SZ') ($(date +'%H:%M %Z')) ==="
  echo "PATH=$PATH"
  # `|| true` so partial failures don't abort the chain — failures are
  # recorded as error rows in the DB and the run row gets status='partial'.
  /opt/homebrew/bin/uv run scripts/run_panel.py || true
  echo "=== panel run finished $(date -u +'%Y-%m-%dT%H:%M:%SZ') ==="
  echo "--- classifying sentiment ---"
  /opt/homebrew/bin/uv run scripts/classify_mentions.py || true
  echo "--- rendering dashboard ---"
  /opt/homebrew/bin/uv run scripts/render_page.py
  echo "--- health check ---"
  # Inspects this run, pushes critical issues to ntfy + files GitHub issues.
  # `|| true` so a transport hiccup never fails the pipeline.
  /opt/homebrew/bin/uv run scripts/health_check.py || true
} >> "$LOG" 2>&1
