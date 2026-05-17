#!/usr/bin/env bash
# Daily AI Recommendation Panel run.
# Invoked by launchd via com.ai-rec-panel.daily. Also safe to run manually.
set -euo pipefail

# launchd starts with a near-empty env. Restore PATH to include the CLI
# binaries the orchestrator shells out to (claude, codex, uv).
export PATH="/Users/garybasin/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

PROJECT_DIR="/Users/garybasin/Code/pythia"
LOG_DIR="$PROJECT_DIR/logs"
LOG="$LOG_DIR/panel-$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

{
  echo
  echo "=== panel run started $(date -u +'%Y-%m-%dT%H:%M:%SZ') ($(date +'%H:%M %Z')) ==="
  echo "PATH=$PATH"
  /opt/homebrew/bin/uv run scripts/run_panel.py
  echo "=== panel run finished $(date -u +'%Y-%m-%dT%H:%M:%SZ') ==="
  echo "--- rendering dashboard ---"
  /opt/homebrew/bin/uv run scripts/render_page.py
} >> "$LOG" 2>&1
