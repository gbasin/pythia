#!/usr/bin/env bash
# pythia — daily panel run.
# Invoked by launchd via com.pythia.daily. Also safe to run manually.
set -euo pipefail

# launchd starts with a near-empty env. Restore a PATH that covers the
# common install locations of the CLI binaries the orchestrator shells out
# to (claude, codex, uv). Harmless entries for dirs that don't exist.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
  # health_check.py at the end is the stage that notices and alerts, so it
  # must run even when every earlier stage failed.
  uv run scripts/run_panel.py || true
  echo "=== panel run finished $(date -u +'%Y-%m-%dT%H:%M:%SZ') ==="
  echo "--- classifying sentiment ---"
  uv run scripts/classify_mentions.py || true
  echo "--- benchmarking alpha ---"
  uv run scripts/benchmark_alpha.py --rebuild-signals || true
  echo "--- rendering dashboard ---"
  uv run scripts/render_page.py || true
  echo "--- publishing dashboard ---"
  # Pushes dist/ to the gh-pages branch, then triggers the Pages deploy
  # workflow (deploy-pages.yml) that serves gbasin.github.io/pythia.
  ./scripts/publish_pages.sh || true
  echo "--- health check ---"
  # Inspects this run, pushes critical issues to ntfy + files GitHub issues.
  # `|| true` so a transport hiccup never fails the pipeline.
  uv run scripts/health_check.py || true
} >> "$LOG" 2>&1
