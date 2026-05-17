#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Classify the sentiment of $TICKER mentions in captured responses.

For each unclassified mention (sentiment_hint IS NULL), asks claude-haiku
to read the parent response and label the writer's stance on each ticker
as one of: bullish, bearish, neutral, context.

Idempotent — only touches mentions where sentiment_hint IS NULL unless
--reclassify is passed. Chained after run_panel.py in daily_run.sh.

    uv run scripts/classify_mentions.py
    uv run scripts/classify_mentions.py --reclassify    # nuke + redo
    uv run scripts/classify_mentions.py --limit 5
"""

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "panel.sqlite"
NEUTRAL_CWD = "/tmp"

CLASSIFIER_MODEL = "haiku"
VALID_STANCES = {"bullish", "bearish", "neutral", "context"}

CLASSIFIER_PROMPT = """\
You classify investment recommendations. Below is a response from an AI
assistant about stocks. Identify every ticker prefixed with $ and judge
the assistant's STANCE on each one.

Stance values:
  bullish  - assistant recommends BUYING / OWNING / OVERWEIGHTING the name
  bearish  - assistant recommends AVOIDING / SELLING / UNDERWEIGHTING it
  neutral  - mentioned without a clear recommendation either way
  context  - mentioned only as a comparison, benchmark, or example — not
             as a pick (e.g. "the next NVDA-style winner" or "vs SPY")

Output exactly one row per UNIQUE ticker. The "ticker" field is the
symbol without the $ prefix.

If the assistant is hedged but tilts one direction, classify by the tilt
— not "neutral". Only use "neutral" when there's truly no recommendation.

Response to analyze:
─── BEGIN RESPONSE ───
{response_text}
─── END RESPONSE ───

Output ONLY a JSON array. No prose, no markdown, no code fences. Schema:
[{{"ticker": "NVDA", "stance": "bullish"}}, {{"ticker": "TLT", "stance": "context"}}]
"""


def call_classifier(response_text: str, timeout: int) -> tuple[list[dict], str | None]:
    """Run claude haiku as classifier. Returns (labels, error_msg)."""
    prompt = CLASSIFIER_PROMPT.format(response_text=response_text)
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--model", CLASSIFIER_MODEL,
        "--setting-sources", "project",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--tools", "",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            cwd=NEUTRAL_CWD,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], "timeout"
    if proc.returncode != 0:
        return [], f"exit {proc.returncode}: {proc.stderr[:200]!r}"

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return [], f"outer json: {e}"

    text = (payload.get("result") or "").strip()
    # strip ```json ... ``` fences if the classifier wrapped its output
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        labels = json.loads(text)
    except json.JSONDecodeError as e:
        return [], f"inner json: {e}; head={text[:120]!r}"

    if not isinstance(labels, list):
        return [], f"not a list: {type(labels).__name__}"
    return labels, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--reclassify", action="store_true",
        help="Re-classify ALL mentions, not just unclassified ones (sets sentiment_hint=NULL first).",
    )
    ap.add_argument("--limit", type=int, default=None, help="Process at most N responses.")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"db missing: {DB_PATH}", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    if args.reclassify:
        n = con.execute("UPDATE mentions SET sentiment_hint = NULL").rowcount
        con.commit()
        print(f"[classify] --reclassify: cleared {n} sentiment_hint values")

    targets = con.execute(
        """
        SELECT DISTINCT r.id AS resp_id, r.raw_text
        FROM responses r
        JOIN mentions m ON m.response_id = r.id
        WHERE m.sentiment_hint IS NULL AND r.raw_text IS NOT NULL
        ORDER BY r.id
        """
    ).fetchall()
    if args.limit:
        targets = targets[: args.limit]

    print(f"[classify] {len(targets)} response(s) with unclassified mentions")
    if not targets:
        con.close()
        return 0

    total_labeled = 0
    for i, row in enumerate(targets, start=1):
        rid = row["resp_id"]
        text = row["raw_text"]
        pending = {
            t["ticker"]: t["id"]
            for t in con.execute(
                "SELECT id, ticker FROM mentions WHERE response_id = ? AND sentiment_hint IS NULL",
                (rid,),
            )
        }
        if not pending:
            continue

        print(f"[{i:>3}/{len(targets)}] resp #{rid}  ({len(pending)} tickers) ...", flush=True)
        t0 = time.monotonic()
        labels, err = call_classifier(text, timeout=args.timeout)
        dt = int((time.monotonic() - t0) * 1000)

        if err:
            print(f"        classifier error ({dt}ms): {err}")
            # Default the unclassified tickers to 'neutral' so we don't loop forever.
            for ticker, mid in pending.items():
                con.execute(
                    "UPDATE mentions SET sentiment_hint = 'neutral' WHERE id = ?",
                    (mid,),
                )
            con.commit()
            continue

        labeled_now: set[str] = set()
        for lab in labels:
            ticker = (lab.get("ticker") or "").upper().lstrip("$")
            stance = (lab.get("stance") or "").lower()
            if ticker not in pending:
                continue
            if stance not in VALID_STANCES:
                stance = "neutral"
            con.execute(
                "UPDATE mentions SET sentiment_hint = ? WHERE id = ?",
                (stance, pending[ticker]),
            )
            labeled_now.add(ticker)
            total_labeled += 1
        # Anything the classifier didn't return → default to neutral.
        for ticker, mid in pending.items():
            if ticker not in labeled_now:
                con.execute(
                    "UPDATE mentions SET sentiment_hint = 'neutral' WHERE id = ?",
                    (mid,),
                )
        con.commit()
        print(
            f"        labeled {len(labeled_now)}/{len(pending)} from classifier output  ({dt}ms)"
        )

    con.close()
    print(f"[classify] done. {total_labeled} mentions classified (others defaulted to 'neutral').")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
