#!/usr/bin/env bash
# pythia — publish dist/ to the gh-pages branch, served at
# https://gbasin.github.io/pythia/. Invoked at the end of daily_run.sh;
# safe to run manually.
#
# Builds the gh-pages commit with git plumbing (a temp index + commit-tree)
# so the main working tree and current branch are never touched.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$PROJECT_DIR/dist"
BRANCH="gh-pages"

cd "$PROJECT_DIR"

if [ ! -f "$DIST/index.html" ]; then
  echo "publish: $DIST/index.html missing; nothing to publish" >&2
  exit 1
fi

# Pages runs Jekyll by default, which drops files/dirs starting with _.
touch "$DIST/.nojekyll"

# `add -f` below bypasses ignore rules, so scrub Finder junk first.
find "$DIST" -name '.DS_Store' -delete

# A path only — git errors on a pre-existing zero-length index file.
TMP_DIR="$(mktemp -d)"
TMP_INDEX="$TMP_DIR/index"
trap 'rm -rf "$TMP_DIR"' EXIT

git fetch --quiet origin "$BRANCH" 2>/dev/null || true
PARENT=""
if git rev-parse --verify --quiet "refs/remotes/origin/$BRANCH" >/dev/null; then
  PARENT="$(git rev-parse "refs/remotes/origin/$BRANCH")"
fi

# Stage dist/ contents as the branch root. -f because ignore rules from the
# main checkout don't apply to this tree.
GIT_INDEX_FILE="$TMP_INDEX" git --work-tree="$DIST" add -Af .
TREE="$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)"

if [ -n "$PARENT" ] && [ "$TREE" = "$(git rev-parse "$PARENT^{tree}")" ]; then
  echo "publish: dashboard unchanged; skipping"
  exit 0
fi

MSG="publish $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
if [ -n "$PARENT" ]; then
  COMMIT="$(git commit-tree "$TREE" -p "$PARENT" -m "$MSG")"
else
  COMMIT="$(git commit-tree "$TREE" -m "$MSG")"
fi

git push --quiet origin "$COMMIT:refs/heads/$BRANCH"
echo "publish: pushed $COMMIT to $BRANCH"
