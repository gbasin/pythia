#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Render AI-Rec-Panel state to a static HTML page.

    uv run scripts/render_page.py            # write dist/index.html
    open dist/index.html                     # view in browser

Designed to be regenerated after every panel run (called by daily_run.sh).
Pure stdlib — no jinja, no framework. Output is a single static file built
for a reader with zero prior context: hero → why → findings → evidence →
how it works → operational.
"""

import html
import os
import random
import shutil
import sqlite3
import textwrap
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("PYTHIA_DB_PATH", ROOT / "db" / "panel.sqlite"))
# Shown in page footers as the pointer to the source code. Never render
# local filesystem paths into the public pages.
REPO_URL = "github.com/gbasin/pythia"
PROMPTS_YAML_PATH = ROOT / "prompts.yaml"
ASSETS_DIR = ROOT / "assets"
OUT_DIR = Path(os.environ.get("PYTHIA_DIST_DIR", ROOT / "dist"))
OUT_PATH = OUT_DIR / "index.html"
OUT_METHODOLOGY_PATH = OUT_DIR / "methodology.html"
OUT_TRENDS_PATH = OUT_DIR / "trends.html"
OUT_ALPHA_PATH = OUT_DIR / "alpha.html"
MODEL_CONFIGS_YAML_PATH = ROOT / "model_configs.yaml"
ET = ZoneInfo("America/New_York")

# Nights are bucketed by the ET calendar date of the run, matching
# benchmark_alpha.py's signal_date. SQLite has no timezone tables, so SQL
# uses DATE(started_at, '-5 hours') — the EST offset year-round. For the
# nightly 8 PM ET panel this yields the correct ET date in both EST and
# EDT; it only diverges from true ET in the 12am-1am EDT window, when no
# panel ever runs.

# Mirrors TOOLS_OFF_SUFFIX in scripts/run_panel.py — duplicated so the
# review page can show the exact text models see for tools_off runs.
TOOLS_OFF_SUFFIX = (
    "IMPORTANT: For this query, you may NOT use any web search, browser, "
    "or external lookup tools. Answer entirely from your training data. "
    "If your information is stale, say so and proceed anyway with the "
    "best answer you can give from what you know."
)

PROVIDER_ICONS = {
    "claude": ("Claude", "assets/icons/claude.svg"),
    "codex": ("GPT", "assets/icons/chatgpt.svg"),
    "gemini": ("Gemini", "assets/icons/gemini.svg"),
}


def load_preamble() -> str:
    try:
        lines = PROMPTS_YAML_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    for i, line in enumerate(lines):
        if line.strip() != "preamble: |":
            continue
        out = []
        for body_line in lines[i + 1:]:
            if body_line and not body_line.startswith(" "):
                break
            if body_line.startswith("  "):
                out.append(body_line[2:])
            else:
                out.append("")
        return "\n".join(out).strip()
    return ""


def load_model_configs_from_yaml() -> list[dict[str, str]]:
    """Small purpose-built parser for this repo's simple model_configs.yaml."""
    try:
        lines = MODEL_CONFIGS_YAML_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_configs = False
    for line in lines:
        stripped = line.strip()
        if stripped == "model_configs:":
            in_configs = True
            continue
        if not in_configs:
            continue
        if line.startswith("  - "):
            if current:
                rows.append(current)
            current = {}
            stripped = stripped[2:].strip()
        if current is None or ":" not in stripped or stripped.startswith("#"):
            continue
        key, value = stripped.split(":", 1)
        if key in {"id", "provider", "cli_command", "subcommand", "model_name", "trace_format"}:
            current[key] = value.strip().strip('"').strip("'")
    if current:
        rows.append(current)
    return rows


def assemble_example(persona_desc: str, prompt_text: str, preamble: str, tools_state: str) -> str:
    """Mirrors assemble_prompt() in run_panel.py — the literal string the CLI receives on stdin."""
    parts = [
        f"About me:\n{persona_desc.strip()}",
        preamble.strip(),
    ]
    if tools_state == "off":
        parts.append(TOOLS_OFF_SUFFIX)
    parts.append(f"Question:\n{prompt_text.strip()}")
    return "\n\n".join(parts) + "\n"


# ───────────────────────── narrative copy ─────────────────────────


TAGLINE = "what frontier AI models tell people to buy, captured daily"

CAPTION = """\
every night at 8 PM ET, pythia asks frontier coding-agent CLIs what
stocks to buy. 10 questions × 2 personas × configured models. each
$TICKER they name is labeled (bullish / bearish / neutral / context)
by a smaller LLM. the chart above is the net (bullish − bearish) per
ticker across this day's panel. scroll for the full breakdown."""

HERO = CAPTION  # legacy alias — render_main_page now uses CAPTION directly


EXPLAINER = """\
the chart above is the NET RECOMMENDATION FLOW for one day: bullish
mentions minus bearish mentions, per ticker, across the configured provider
surfaces answering 10 questions in 2 personas.

below it, three rolling/cumulative views:

  · FIRST SIGHTINGS — tickers ordered by their first appearance in clean
    runs, newest first. signals fresh names entering the recommendation flow.

  · CONSENSUS — tickers where multiple providers contributed bullish
    mentions. verdict flags 3/3, 2/3, and split-provider agreement.

  · TOP · LAST 7 DAYS — most-recommended tickers across the recent
    window, with `days` showing how many distinct days each appeared
    (a quick read on persistence vs flash-in-the-pan).

detail per day, full methodology, all panel runs, sample responses,
prompts, personas — all behind the links at the bottom of the page."""


WHY = """\
why bother?

  hundreds of millions of people now use ChatGPT and Claude as a
  first stop for investment ideas. the recommendations they receive
  — which names the model trusts, which it singles out as winners
  or losers, which it dismisses — quietly become a market force as
  retail follows.

  pythia mirrors the questions retail actually asks. some prompts
  deliberately name specific tickers ("is $NVDA a buy?"), because
  that's what real users type. the volume the model returns on
  those names is the point, not a bias to scrub — that is the
  flow.

  every $TICKER mention gets a stance label (bullish / bearish /
  neutral / context) from a separate smaller LLM, so the headline
  signal is "net recommendation" — not raw word count. no curation
  beyond that. the page rebuilds from the database on every run."""


INTRO_TOP_MENTIONS = """\
each ticker mention is classified as bullish, bearish, neutral, or
context. net is bullish minus bearish. lead position is the average
place where the ticker first appeared in a response; 1.0 means it
was usually a lead pick."""


INTRO_PERSONA_DELTA = """\
we ask the same questions as two different investors: a 28-year-old
speculator and a family-office allocator. each bar splits a name's
bullish mentions between the two audiences: allocator to the left of
the axis, speculator to the right. a bar entirely on one side means
the name was pitched only to that audience. treat thin bars with
caution."""


INTRO_SAMPLES = """\
these are recent response excerpts, shown as exhibits so you can
inspect the language behind the counts. full responses and traces are
preserved in the local data."""






FOOTER = """\
  not investment advice. not a recommendation. just an experiment.
  raw data lives in db/panel.sqlite. this page rebuilds on every
  panel run, from that database — no other source of truth."""


# ───────────────────────── data fetch ─────────────────────────


def fetch_trends(con) -> dict:
    """Aggregates across all clean days: rolling windows, new entrants,
    cross-provider consensus, and a day-by-day index."""
    con.row_factory = sqlite3.Row

    providers = [
        r["provider"]
        for r in con.execute(
        """
        SELECT DISTINCT mc.provider
        FROM responses r
        JOIN runs ru ON r.run_id = ru.id
        JOIN model_configs mc ON r.model_config_id = mc.id
        WHERE r.error IS NULL AND ru.is_clean = 1
        ORDER BY CASE mc.provider
                   WHEN 'claude' THEN 1
                   WHEN 'codex' THEN 2
                   WHEN 'gemini' THEN 3
                   ELSE 99
                 END, mc.provider
        """
        ).fetchall()
    ]
    provider_total = len(providers)

    def rolling_top(days_back: int, limit: int = 20):
        return [dict(r) for r in con.execute(
            """
            SELECT m.ticker,
                   SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1 ELSE 0 END) AS bull,
                   SUM(CASE WHEN m.sentiment_hint='bearish' THEN 1 ELSE 0 END) AS bear,
                   SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                            WHEN m.sentiment_hint='bearish' THEN -1
                            ELSE 0 END) AS net,
                   COUNT(*) AS n,
                   COUNT(DISTINCT DATE(ru.started_at, '-5 hours')) AS days_seen
            FROM mentions m
            JOIN responses r ON m.response_id = r.id
            JOIN runs ru ON r.run_id = ru.id
            WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0
              AND DATE(ru.started_at, '-5 hours') >= DATE('now', '-5 hours', ?)
            GROUP BY m.ticker
            ORDER BY net DESC, n DESC
            LIMIT ?
            """,
            (f"-{days_back} days", limit),
        ).fetchall()]

    top_7d = rolling_top(7, 20)
    top_30d = rolling_top(30, 20)
    top_all = rolling_top(3650, 20)  # effectively all-time

    first_sightings = [dict(r) for r in con.execute(
        """
        SELECT m.ticker, MIN(DATE(ru.started_at, '-5 hours')) AS first_seen,
               MAX(DATE(ru.started_at, '-5 hours')) AS last_seen,
               SUM(CASE WHEN mc.provider='claude' AND m.sentiment_hint='bullish' THEN 1 ELSE 0 END) AS claude_bull,
               SUM(CASE WHEN mc.provider='claude' AND m.sentiment_hint='bearish' THEN 1 ELSE 0 END) AS claude_bear,
               SUM(CASE WHEN mc.provider='codex'  AND m.sentiment_hint='bullish' THEN 1 ELSE 0 END) AS codex_bull,
               SUM(CASE WHEN mc.provider='codex'  AND m.sentiment_hint='bearish' THEN 1 ELSE 0 END) AS codex_bear,
               SUM(CASE WHEN mc.provider='gemini' AND m.sentiment_hint='bullish' THEN 1 ELSE 0 END) AS gemini_bull,
               SUM(CASE WHEN mc.provider='gemini' AND m.sentiment_hint='bearish' THEN 1 ELSE 0 END) AS gemini_bear,
               SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                        WHEN m.sentiment_hint='bearish' THEN -1
                        ELSE 0 END) AS net_since,
               COUNT(*) AS n,
               COUNT(DISTINCT DATE(ru.started_at, '-5 hours')) AS days_seen
        FROM mentions m
        JOIN responses r ON m.response_id = r.id
        JOIN model_configs mc ON r.model_config_id = mc.id
        JOIN runs ru ON r.run_id = ru.id
        WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0
        GROUP BY m.ticker
        ORDER BY first_seen DESC, net_since DESC, n DESC
        LIMIT 30
        """
    ).fetchall()]

    consensus = [dict(r) for r in con.execute(
        """
        SELECT m.ticker,
               SUM(CASE WHEN mc.provider='claude' AND m.sentiment_hint='bullish' THEN 1 ELSE 0 END) AS claude_bull,
               SUM(CASE WHEN mc.provider='claude' AND m.sentiment_hint='bearish' THEN 1 ELSE 0 END) AS claude_bear,
               SUM(CASE WHEN mc.provider='codex'  AND m.sentiment_hint='bullish' THEN 1 ELSE 0 END) AS codex_bull,
               SUM(CASE WHEN mc.provider='codex'  AND m.sentiment_hint='bearish' THEN 1 ELSE 0 END) AS codex_bear,
               SUM(CASE WHEN mc.provider='gemini' AND m.sentiment_hint='bullish' THEN 1 ELSE 0 END) AS gemini_bull,
               SUM(CASE WHEN mc.provider='gemini' AND m.sentiment_hint='bearish' THEN 1 ELSE 0 END) AS gemini_bear,
               SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1 ELSE 0 END) AS total_bull,
               SUM(CASE WHEN m.sentiment_hint='bearish' THEN 1 ELSE 0 END) AS total_bear,
               COUNT(DISTINCT CASE WHEN m.sentiment_hint='bullish' THEN mc.provider END) AS bullish_providers,
               COUNT(DISTINCT CASE WHEN m.sentiment_hint='bearish' THEN mc.provider END) AS bearish_providers
        FROM mentions m
        JOIN responses r ON m.response_id = r.id
        JOIN model_configs mc ON r.model_config_id = mc.id
        JOIN runs ru ON r.run_id = ru.id
        WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0
        GROUP BY m.ticker
        HAVING bullish_providers >= 2
        ORDER BY bullish_providers DESC, total_bull DESC, (total_bull - total_bear) DESC, m.ticker
        LIMIT 20
        """
    ).fetchall()]
    for r in consensus:
        r["provider_total"] = provider_total

    days_index = [dict(r) for r in con.execute(
        """
        SELECT DATE(ru.started_at, '-5 hours') AS day,
               COUNT(DISTINCT r.id) AS n_responses,
               COUNT(DISTINCT m.ticker) AS n_unique
        FROM runs ru
        LEFT JOIN responses r ON r.run_id = ru.id AND r.error IS NULL
        LEFT JOIN mentions m ON m.response_id = r.id
        WHERE ru.is_clean = 1
        GROUP BY day
        ORDER BY day DESC
        """
    ).fetchall()]

    # Per-day leading ticker
    leading_per_day = {}
    for r in con.execute(
        """
        SELECT day, ticker, net FROM (
            SELECT DATE(ru.started_at, '-5 hours') AS day, m.ticker,
                   SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                            WHEN m.sentiment_hint='bearish' THEN -1
                            ELSE 0 END) AS net,
                   ROW_NUMBER() OVER (PARTITION BY DATE(ru.started_at, '-5 hours')
                                       ORDER BY SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                                                          WHEN m.sentiment_hint='bearish' THEN -1
                                                          ELSE 0 END) DESC) AS rk
            FROM mentions m
            JOIN responses r ON m.response_id = r.id
            JOIN runs ru ON r.run_id = ru.id
            WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0
            GROUP BY day, m.ticker
        ) WHERE rk = 1
        """
    ).fetchall():
        leading_per_day[r["day"]] = (r["ticker"], r["net"])
    for d in days_index:
        lead = leading_per_day.get(d["day"])
        d["lead_ticker"] = lead[0] if lead else None
        d["lead_net"] = lead[1] if lead else None

    # Sparklines for the rolling-top tickers
    all_top_tickers = list({r["ticker"] for r in (top_7d + top_30d + top_all + consensus)})
    _, series = fetch_ticker_series(con, all_top_tickers, days_back=30)
    spark_max = max(
        (abs(v) for vs in series.values() for v in vs if v is not None),
        default=1,
    )
    for bucket in (top_7d, top_30d, top_all, consensus):
        for r in bucket:
            r["sparkline"] = sparkline(series.get(r["ticker"], []), max_abs=spark_max)
            r["spark_days"] = len(series.get(r["ticker"], []))

    return dict(
        top_7d=top_7d,
        top_30d=top_30d,
        top_all=top_all,
        first_sightings=first_sightings,
        consensus=consensus,
        providers=providers,
        days_index=days_index,
    )


def list_clean_days(con) -> list[str]:
    """Distinct calendar days (UTC) that have at least one clean run."""
    return [
        r[0]
        for r in con.execute(
            """
            SELECT DISTINCT DATE(started_at, '-5 hours') AS day
            FROM runs
            WHERE is_clean = 1 AND status IN ('completed', 'partial')
            ORDER BY day DESC
            """
        ).fetchall()
    ]


def fetch(con, day: str | None = None) -> dict:
    """Return all dashboard data. If `day` is given, scope per-day aggregates
    (counts, top_mentions, persona_delta, samples) to that date. Global panel
    definitions (prompts, personas, model_configs) and the recent-runs table
    are always cumulative across clean runs."""
    con.row_factory = sqlite3.Row

    # Day filter snippets — applied wherever we touch responses/mentions.
    if day:
        day_pred = "AND DATE(ru.started_at, '-5 hours') = ?"
        day_params = (day,)
    else:
        day_pred = ""
        day_params = ()

    counts = con.execute(
        f"""
        SELECT
            (SELECT COUNT(*) FROM runs ru
                WHERE ru.is_clean=1 {day_pred})                       AS n_runs,
            (SELECT COUNT(*) FROM responses r
                JOIN runs ru ON r.run_id = ru.id
                WHERE ru.is_clean=1 AND r.error IS NULL {day_pred})   AS n_responses_ok,
            (SELECT COUNT(*) FROM responses r
                JOIN runs ru ON r.run_id = ru.id
                WHERE ru.is_clean=1 AND r.error IS NOT NULL {day_pred}) AS n_responses_fail,
            (SELECT COUNT(*) FROM responses r
                JOIN runs ru ON r.run_id = ru.id
                WHERE ru.is_clean=1 AND r.refused=1 {day_pred})       AS n_refused,
            (SELECT COUNT(*) FROM mentions m
                JOIN responses r ON m.response_id = r.id
                JOIN runs ru ON r.run_id = ru.id
                WHERE ru.is_clean=1 {day_pred})                       AS n_mentions,
            (SELECT COUNT(DISTINCT m.ticker) FROM mentions m
                JOIN responses r ON m.response_id = r.id
                JOIN runs ru ON r.run_id = ru.id
                WHERE ru.is_clean=1 {day_pred})                       AS n_unique_tickers
        """,
        day_params * 6,
    ).fetchone()

    # Latest clean run for the freshness stamp (per-day or global).
    if day:
        latest_run = con.execute(
            "SELECT id, started_at, finished_at, status "
            "FROM runs WHERE is_clean=1 AND DATE(started_at, '-5 hours')=? "
            "ORDER BY id DESC LIMIT 1",
            (day,),
        ).fetchone()
    else:
        latest_run = con.execute(
            "SELECT id, started_at, finished_at, status "
            "FROM runs WHERE is_clean=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()

    # Recent runs table is always global (operational footer).
    runs = con.execute(
        """
        SELECT r.id, r.started_at, r.status, r.is_clean,
               (SELECT COUNT(*) FROM responses WHERE run_id=r.id) AS n_total,
               (SELECT COUNT(*) FROM responses WHERE run_id=r.id AND error IS NULL) AS n_ok,
               (SELECT COUNT(*) FROM responses WHERE run_id=r.id AND error IS NOT NULL) AS n_fail,
               (SELECT COUNT(*) FROM responses WHERE run_id=r.id AND refused=1) AS n_refused
        FROM runs r
        WHERE r.is_clean = 1
        ORDER BY r.id DESC LIMIT 10
        """
    ).fetchall()

    top_mentions = con.execute(
        f"""
        SELECT m.ticker,
               COUNT(*)                                                          AS n,
               SUM(CASE WHEN m.sentiment_hint = 'bullish' THEN 1 ELSE 0 END)     AS bull,
               SUM(CASE WHEN m.sentiment_hint = 'bearish' THEN 1 ELSE 0 END)     AS bear,
               SUM(CASE WHEN m.sentiment_hint = 'neutral' THEN 1 ELSE 0 END)     AS neut,
               SUM(CASE WHEN m.sentiment_hint = 'context' THEN 1 ELSE 0 END)     AS ctx,
               SUM(CASE WHEN m.sentiment_hint = 'bullish' THEN 1
                        WHEN m.sentiment_hint = 'bearish' THEN -1
                        ELSE 0 END)                                              AS net,
               AVG(m.position)                                                   AS avg_pos
        FROM mentions m
        JOIN responses r ON m.response_id = r.id
        JOIN runs ru ON r.run_id = ru.id
        WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0 {day_pred}
        GROUP BY m.ticker
        ORDER BY net DESC, n DESC, avg_pos ASC
        LIMIT 24
        """,
        day_params,
    ).fetchall()

    persona_delta = con.execute(
        f"""
        SELECT m.ticker,
               SUM(CASE WHEN r.persona_id='speculator' THEN 1 ELSE 0 END) AS spec_n,
               SUM(CASE WHEN r.persona_id='allocator'  THEN 1 ELSE 0 END) AS alloc_n
        FROM mentions m
        JOIN responses r ON m.response_id=r.id
        JOIN runs ru ON r.run_id = ru.id
        WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0
              AND m.sentiment_hint = 'bullish' {day_pred}
        GROUP BY m.ticker
        HAVING (spec_n + alloc_n) >= 1
        ORDER BY (spec_n - alloc_n) DESC, m.ticker
        """,
        day_params,
    ).fetchall()

    model_configs = con.execute(
        """
        SELECT id, provider, model_name, notes FROM model_configs ORDER BY id
        """
    ).fetchall()

    prompts = con.execute(
        """
        SELECT p.id, p.category, p.text
        FROM prompts p
        WHERE p.version_hash = (
            SELECT version_hash FROM prompts WHERE id = p.id ORDER BY rowid DESC LIMIT 1
        )
        ORDER BY CASE p.category
                   WHEN 'portfolio' THEN 0
                   WHEN 'single_name' THEN 1
                   WHEN 'sector_macro' THEN 2
                   ELSE 3 END,
                 p.id
        """
    ).fetchall()

    personas = con.execute(
        """
        SELECT p.id, p.label, p.description
        FROM personas p
        WHERE p.version_hash = (
            SELECT version_hash FROM personas WHERE id = p.id ORDER BY rowid DESC LIMIT 1
        )
        ORDER BY p.id
        """
    ).fetchall()

    day_pred2 = day_pred.replace("ru.", "ru2.")
    samples = con.execute(
        f"""
        SELECT r.id            AS resp_id,
               r.started_at    AS started_at,
               r.tools_state   AS tools_state,
               r.prompt_id     AS prompt_id,
               r.persona_id    AS persona_id,
               r.raw_text      AS raw_text,
               r.tokens_out    AS tokens_out,
               mc.provider     AS provider,
               mc.model_name   AS model_name,
               (SELECT text FROM prompts
                 WHERE id = r.prompt_id AND version_hash = r.prompt_version_hash) AS prompt_text
        FROM responses r
        JOIN model_configs mc ON r.model_config_id = mc.id
        JOIN runs ru ON r.run_id = ru.id
        WHERE r.error IS NULL AND r.raw_text IS NOT NULL AND LENGTH(r.raw_text) > 100
              AND ru.is_clean = 1 {day_pred}
              AND r.run_id = (
                  SELECT MAX(r2.run_id) FROM responses r2
                  JOIN runs ru2 ON r2.run_id = ru2.id
                  WHERE r2.error IS NULL AND ru2.is_clean = 1 {day_pred2}
              )
        ORDER BY r.id
        """,
        day_params + day_params,
    ).fetchall()

    # A stable pseudo-random spread across the run: shuffle with a seed
    # derived from the run, then prefer unseen prompts and balanced
    # providers so six exhibits show six different questions.
    samples = list(samples)
    if samples:
        rng = random.Random(f"{day or 'latest'}:{len(samples)}")
        rng.shuffle(samples)
        picked, seen_prompts, provider_counts = [], set(), {}
        for s in samples:
            if len(picked) >= 6:
                break
            if s["prompt_id"] in seen_prompts or provider_counts.get(s["provider"], 0) >= 2:
                continue
            picked.append(s)
            seen_prompts.add(s["prompt_id"])
            provider_counts[s["provider"]] = provider_counts.get(s["provider"], 0) + 1
        for s in samples:
            if len(picked) >= 6:
                break
            if s["prompt_id"] not in seen_prompts:
                picked.append(s)
                seen_prompts.add(s["prompt_id"])
        for s in samples:
            if len(picked) >= 6:
                break
            if all(p["resp_id"] != s["resp_id"] for p in picked):
                picked.append(s)
        samples = picked

    samples_enriched = []
    for s in samples:
        tickers = con.execute(
            "SELECT ticker FROM mentions WHERE response_id=? ORDER BY position LIMIT 10",
            (s["resp_id"],),
        ).fetchall()
        samples_enriched.append((s, [t["ticker"] for t in tickers]))

    # Attach 14-day sparklines to each top_mentions row.
    top_mentions = [dict(r) for r in top_mentions]
    if top_mentions:
        _, series = fetch_ticker_series(con, [r["ticker"] for r in top_mentions], days_back=14)
        spark_max = max(
            (abs(v) for vs in series.values() for v in vs if v is not None),
            default=1,
        )
        for r in top_mentions:
            r["sparkline"] = sparkline(series.get(r["ticker"], []), max_abs=spark_max)
            r["spark_days"] = len(series.get(r["ticker"], []))

    return dict(
        counts=counts,
        latest_run=latest_run,
        runs=runs,
        top_mentions=top_mentions,
        persona_delta=persona_delta,
        model_configs=model_configs,
        prompts=prompts,
        personas=personas,
        samples=samples_enriched,
    )


# ───────────────────────── helpers ─────────────────────────


def humanize_age(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    delta = datetime.now(timezone.utc) - ts
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[int | None], max_abs: int | None = None) -> str:
    """Render a series as a fixed-width sparkline. None = absent (·)."""
    if not values:
        return ""
    present = [abs(v) for v in values if v is not None and v != 0]
    if max_abs is None:
        max_abs = max(present) if present else 1
    out = []
    for v in values:
        if v is None:
            out.append("·")
        elif v == 0:
            out.append("▁")
        else:
            scaled = min(7, max(0, int(round(7 * abs(v) / max_abs))))
            out.append(SPARK_CHARS[scaled])
    return "".join(out)


def fetch_ticker_series(con, tickers: list[str], days_back: int = 14) -> tuple[list[str], dict[str, list[int | None]]]:
    """For each ticker, return (days, {ticker: [net_per_day]}) over the last
    `days_back` clean days. Missing days for a ticker → None."""
    if not tickers:
        return [], {}
    days = [
        r[0]
        for r in con.execute(
            """
            SELECT DISTINCT DATE(started_at, '-5 hours') AS day FROM runs
            WHERE is_clean = 1 AND DATE(started_at, '-5 hours') >= DATE('now', '-5 hours', ?)
            ORDER BY day ASC
            """,
            (f"-{days_back} days",),
        ).fetchall()
    ]
    if not days:
        return [], {t: [] for t in tickers}

    placeholders = ",".join("?" * len(tickers))
    rows = con.execute(
        f"""
        SELECT m.ticker, DATE(ru.started_at, '-5 hours') AS day,
               SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                        WHEN m.sentiment_hint='bearish' THEN -1
                        ELSE 0 END) AS net
        FROM mentions m
        JOIN responses r ON m.response_id = r.id
        JOIN runs ru ON r.run_id = ru.id
        WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0
          AND m.ticker IN ({placeholders})
          AND DATE(ru.started_at, '-5 hours') >= DATE('now', '-5 hours', ?)
        GROUP BY m.ticker, day
        """,
        list(tickers) + [f"-{days_back} days"],
    ).fetchall()

    by_ticker = {t: {} for t in tickers}
    for r in rows:
        by_ticker[r[0]][r[1]] = r[2]
    return days, {t: [by_ticker[t].get(d) for d in days] for t in tickers}


def table_exists(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def fetch_alpha(con, top_n: int = 20) -> dict:
    """Return the simple open→close benchmark from benchmark_alpha.py tables.

    render_page.py intentionally does not fetch prices or mutate the DB. The
    daily benchmark script owns data refresh; this renderer only visualizes
    whatever benchmark rows are already cached.
    """
    required = ("daily_signals", "forward_returns", "prices")
    if not all(table_exists(con, t) for t in required):
        return dict(available=False, rows=[], summary={}, top_n=top_n)

    rows = [
        dict(r)
        for r in con.execute(
            """
            WITH ranked AS (
              SELECT ds.*,
                     ROW_NUMBER() OVER (
                       PARTITION BY ds.signal_date
                       ORDER BY ds.net_score DESC, ds.mentions DESC, ds.ticker
                     ) AS rk
              FROM daily_signals ds
            ),
            day_baskets AS (
              SELECT r.signal_date,
                     fr.entry_date AS trade_date,
                     AVG(CASE WHEN r.rk <= ? THEN fr.return_pct END) AS top_return,
                     COUNT(CASE WHEN r.rk <= ? THEN 1 END) AS top_available
              FROM ranked r
              JOIN forward_returns fr
                ON fr.signal_date = r.signal_date
               AND fr.ticker = r.ticker
               AND fr.horizon_days = 1
              GROUP BY r.signal_date, fr.entry_date
            )
            SELECT db.signal_date,
                   db.trade_date,
                   db.top_return,
                   db.top_available,
                   CASE WHEN qqq.open IS NOT NULL AND qqq.open != 0
                        THEN qqq.close / qqq.open - 1 END AS qqq_return
            FROM day_baskets db
            LEFT JOIN prices qqq
              ON qqq.ticker='QQQ' AND qqq.source='yfinance' AND qqq.date=db.trade_date
            ORDER BY db.signal_date
            """,
            (top_n, top_n),
        ).fetchall()
    ]
    if not rows:
        return dict(available=False, rows=[], summary={}, top_n=top_n)

    # Two series the dashboard cares about: the raw (unhedged) top20 basket
    # return, and its excess over QQQ — the highlighted benchmark. Both are
    # accumulated additively across sessions.
    cum_top = 0.0
    cum_vs_qqq = 0.0
    for r in rows:
        top_return = r["top_return"] or 0.0
        qqq_return = r["qqq_return"] or 0.0
        r["excess_vs_qqq"] = top_return - qqq_return
        cum_top += top_return
        cum_vs_qqq += r["excess_vs_qqq"]
        r["cum_top"] = cum_top
        r["cum_top_vs_qqq"] = cum_vs_qqq

    def avg(key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    summary = dict(
        n_days=len(rows),
        top_avg=avg("top_return"),
        qqq_avg=avg("qqq_return"),
        vs_qqq_avg=avg("excess_vs_qqq"),
        cum_top=rows[-1]["cum_top"],
        cum_top_vs_qqq=rows[-1]["cum_top_vs_qqq"],
        latest_signal_date=rows[-1]["signal_date"],
        latest_trade_date=rows[-1]["trade_date"],
    )
    return dict(available=True, rows=rows, summary=summary, top_n=top_n)


def fmt_pct(value: float | None, width: int = 7) -> str:
    if value is None:
        return "n/a".rjust(width)
    return f"{value * 100:{width}.2f}%"


def fmt_signed_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.2f}%"


def signed_class(value: float | int | None) -> str:
    if value is None or value == 0:
        return "zero"
    return "up" if value > 0 else "down"


def signed_int_span(value: int | None) -> str:
    if value is None:
        return '<span class="zero">n/a</span>'
    return f'<span class="{signed_class(value)}">{value:+d}</span>'


def signed_pct_span(value: float | None) -> str:
    if value is None:
        return '<span class="zero">n/a</span>'
    return f'<span class="{signed_class(value)}">{html.escape(fmt_signed_pct(value))}</span>'


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def render_alpha_summary(alpha: dict) -> str:
    if not alpha.get("available"):
        return '<p class="dim">no scoreboard data yet; the first benchmark session lands after the next market open.</p>'
    s = alpha["summary"]
    n = alpha.get("top_n", 20)
    rows = [
        ("sessions", f"{s['n_days']}"),
        (f"top-{n} avg", signed_pct_span(s["top_avg"])),
        ("QQQ avg", signed_pct_span(s["qqq_avg"])),
        ("vs QQQ avg", signed_pct_span(s["vs_qqq_avg"])),
        (f"cumulative top-{n}", signed_pct_span(s["cum_top"])),
        ("cumulative excess vs QQQ", signed_pct_span(s["cum_top_vs_qqq"])),
        ("latest trade date", html.escape(s["latest_trade_date"] or "pending")),
    ]
    out = ['<table class="data-table"><thead><tr><th>measure</th><th class="num">value</th></tr></thead><tbody>']
    for label, value in rows:
        out.append(f'<tr><td>{html.escape(label)}</td><td class="num">{value}</td></tr>')
    out.append("</tbody></table>")
    return "".join(out)


def render_alpha_table(alpha: dict) -> str:
    rows = alpha.get("rows") or []
    if not rows:
        return '<p class="dim">no benchmarkable rows yet; the first scored session appears after prices settle.</p>'
    n = alpha.get("top_n", 20)
    out = [
        '<table class="data-table alpha-table">',
        "<thead><tr>",
        "<th>signal date</th><th>trade date</th><th class=\"num\">top available</th>",
        f"<th class=\"num\">top-{n} 1d</th><th class=\"num\">QQQ</th><th class=\"num\">vs QQQ</th>",
        f"<th class=\"num\">cum top-{n}</th><th class=\"num\">cum vs QQQ</th>",
        "</tr></thead><tbody>",
    ]
    for r in rows:
        out.append(
            "<tr>"
            f"<td>{html.escape(r['signal_date'])}</td>"
            f"<td>{html.escape(r['trade_date'])}</td>"
            f"<td class=\"num\">{r['top_available']}</td>"
            f"<td class=\"num\">{signed_pct_span(r['top_return'])}</td>"
            f"<td class=\"num\">{signed_pct_span(r['qqq_return'])}</td>"
            f"<td class=\"num\">{signed_pct_span(r['excess_vs_qqq'])}</td>"
            f"<td class=\"num\">{signed_pct_span(r['cum_top'])}</td>"
            f"<td class=\"num\">{signed_pct_span(r['cum_top_vs_qqq'])}</td>"
            "</tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


def render_alpha_svg(alpha: dict, width: int = 900, height: int = 220,
                     compact: bool = False) -> str:
    rows = alpha.get("rows") or []
    if not rows:
        return '<pre class="tbl">  (alpha benchmark not built yet)</pre>'

    n = alpha.get("top_n", 20)
    left, right, top, bottom = 12, 16, 20, 28
    chart_w = width - left - right
    chart_h = height - top - bottom
    model_values = [r["cum_top"] for r in rows]
    qqq_values = [r["cum_top"] - r["cum_top_vs_qqq"] for r in rows]
    values = model_values + qqq_values + [0.0]
    lo, hi = min(values), max(values)
    if lo == hi:
        lo -= 0.01
        hi += 0.01
    pad = (hi - lo) * 0.12
    lo -= pad
    hi += pad

    def x_at(i: int) -> float:
        if len(model_values) == 1:
            return left + chart_w
        return left + chart_w * i / (len(model_values) - 1)

    def y_at(v: float) -> float:
        return top + (hi - v) / (hi - lo) * chart_h

    model_points = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(model_values))
    qqq_points = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(qqq_values))
    latest_model = model_values[-1]
    latest_excess = rows[-1]["cum_top_vs_qqq"]
    zero_y = y_at(0.0)
    grid_values = [lo + (hi - lo) * i / 4 for i in range(5)]
    grid = []
    for v in grid_values:
        y = y_at(v)
        cls = "zero-line" if abs(v) < (hi - lo) / 1000 else "grid"
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" class="{cls}"/>')
        grid.append(f'<text x="{left}" y="{y - 4:.1f}" text-anchor="start">{v * 100:+.1f}%</text>')
    if all(abs(v) >= (hi - lo) / 1000 for v in grid_values):
        grid.append(f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width - right}" y2="{zero_y:.1f}" class="zero-line"/>')
        if all(abs(zero_y - y_at(v)) > 14 for v in grid_values):
            grid.append(f'<text x="{left}" y="{zero_y - 4:.1f}" text-anchor="start">0%</text>')
    aria = (
        f"cumulative top-{n} basket {fmt_signed_pct(latest_model)} and "
        f"cumulative excess versus QQQ {fmt_signed_pct(latest_excess)}"
    )
    return f"""<svg class="alpha-svg" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(aria)}">
  {"".join(grid)}
  <polyline points="{qqq_points}" fill="none" class="qqq-line"/>
  <polyline points="{model_points}" fill="none" class="models-line"/>
</svg>"""


def render_plot(alpha: dict, compact: bool = False) -> str:
    """Chart in a Qt-style sunken plot frame with a legend row. The models
    swatch and line take the up/down color of the latest cumulative value."""
    rows = alpha.get("rows") or []
    if not rows:
        return '<p class="dim">no scoreboard data yet; the first benchmark session lands after the next market open.</p>'
    color_var = "var(--up)" if rows[-1]["cum_top"] >= 0 else "var(--down)"
    return (
        f'<div class="plot" style="--chart-models: {color_var}">'
        '<div class="legend">'
        '<span><span class="swatch models"></span>models</span>'
        '<span><span class="swatch qqq"></span>QQQ</span></div>'
        f'{render_alpha_svg(alpha, compact=compact)}</div>'
    )


def indent2(text: str) -> str:
    return textwrap.indent(text, "  ")


def no_emdash(text: str) -> str:
    return (text or "").replace("\u2014", "-")


# ───────────────────────── section renderers ─────────────────────────


def render_top_mentions(d: dict) -> str:
    rows = d["top_mentions"]
    if not rows:
        return '<p class="dim">no ticker mentions were recorded for this night.</p>'
    max_abs_net = max((abs(r["net"] or 0) for r in rows), default=0) or 1
    out = [
        '<div class="scroll"><table class="data-table">',
        "<thead><tr>"
        "<th class=\"num\">rank</th><th>ticker</th>"
        "<th class=\"num\">bull</th><th class=\"num\">bear</th>"
        "<th class=\"num\">neut</th><th class=\"num\">ctx</th>"
        "<th class=\"num\">n</th>"
        "<th class=\"num\">lead position</th><th>net</th><th>14d sparkline</th>"
        "</tr></thead><tbody>",
    ]
    for i, r in enumerate(rows, start=1):
        net = r["net"] or 0
        out.append(
            "<tr>"
            f'<td class="num">{i}</td>'
            f'<td><strong>${html.escape(r["ticker"])}</strong></td>'
            f'<td class="num">{r["bull"] or 0}</td>'
            f'<td class="num">{r["bear"] or 0}</td>'
            f'<td class="num">{r["neut"] or 0}</td>'
            f'<td class="num">{r["ctx"] or 0}</td>'
            f'<td class="num">{r["n"] or 0}</td>'
            f'<td class="num">{(r["avg_pos"] or 0):.1f}</td>'
            f'<td>{pbar_html(net, max_abs_net)}</td>'
            f'<td class="spark">{html.escape(r.get("sparkline") or "")}</td>'
            "</tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def persona_split_cells(spec: int, alloc: int, max_count: int, half: int) -> str:
    """Two cells of a diverging widget bar: allocator grows left from the
    center axis, speculator grows right. Counts sit at the outer bar ends.
    The axis itself is the border between the cells. `half` is the full
    one-side bar length in units of 10px."""
    full_px = half * 10

    def seg(count: int, side: str) -> str:
        if not count or not max_count:
            return ""
        w = max(6, round(full_px * count / max_count))
        return f'<span class="seg {side}" style="width:{w}px"></span>'

    a_count = f'<span class="count{" zero" if alloc == 0 else ""}">{alloc}</span>'
    s_count = f'<span class="count{" zero" if spec == 0 else ""}">{spec}</span>'
    return (
        f'<td class="side-a">{a_count} {seg(alloc, "alloc")}</td>'
        f'<td class="side-s">{seg(spec, "spec")} {s_count}</td>'
    )


def render_persona_split(rows: list, half: int, limit: int) -> str:
    rows = [(r["ticker"], r["spec_n"] or 0, r["alloc_n"] or 0) for r in rows[:limit]]
    if not rows:
        return '<p class="dim">no persona split was recorded for this night.</p>'
    max_count = max((max(s, a) for _, s, a in rows), default=1) or 1
    out = [
        '<div class="scroll"><table class="data-table split-table">',
        '<thead><tr><th>ticker</th><th class="side-a">◂ allocator</th>'
        '<th class="side-s">speculator ▸</th></tr></thead><tbody>',
    ]
    for ticker, spec, alloc in rows:
        out.append(
            "<tr>"
            f'<td>${html.escape(ticker)}</td>'
            f'{persona_split_cells(spec, alloc, max_count, half)}'
            "</tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def render_persona_delta(d: dict) -> str:
    return render_persona_split(d["persona_delta"], half=16, limit=20)


def render_samples(d: dict) -> str:
    rows = d["samples"]
    if not rows:
        return '<p class="dim">no response excerpts are available for this night.</p>'
    parts = []
    for s, tickers in rows:
        age = humanize_age(s["started_at"])
        prompt_one = " ".join((s["prompt_text"] or "").split())
        if len(prompt_one) > 110:
            prompt_one = prompt_one[:107].rstrip() + "…"
        text = s["raw_text"] or ""
        snippet = text[:620].rstrip()
        if len(text) > 620:
            snippet = snippet.rstrip(" .,…") + "…"
        tool_label = "enabled" if s["tools_state"] == "on" else "disabled" if s["tools_state"] == "off" else "unknown"
        title = f"tool access: {tool_label}; output tokens: {s['tokens_out'] or 0}"
        parts.append(
            '<figure class="exhibit">'
            f'<figcaption class="label" title="{html.escape(title)}">'
            f'response #{s["resp_id"]} · {html.escape(age)} · '
            f'{html.escape(s["prompt_id"])} x {html.escape(s["persona_id"])} x '
            f'{html.escape(s["provider"])}'
            '</figcaption>'
            f'<p class="exhibit-question">{html.escape(no_emdash(prompt_one))}</p>'
            f'<pre class="exhibit-body">{html.escape(no_emdash(snippet))}</pre>'
            '</figure>'
        )
    return "".join(parts)


def render_prompts_html(d: dict) -> str:
    rows = d["prompts"]
    if not rows:
        return '<p class="dim">no questions are registered.</p>'
    cat_labels = {
        "portfolio": "portfolio construction",
        "single_name": "single-name views",
        "sector_macro": "sector and macro",
    }
    out = ['<div class="prompt-list">']
    current_cat = None
    for r in rows:
        if r["category"] != current_cat:
            current_cat = r["category"]
            out.append(f'<h3>{html.escape(cat_labels.get(current_cat, current_cat))}</h3>')
        text = " ".join(no_emdash(r["text"] or "").split())
        out.append(
            '<div class="prompt-item">'
            f'<div class="prompt-id">{html.escape(r["id"])}</div>'
            f'<p>{html.escape(text)}</p>'
            '</div>'
        )
    out.append("</div>")
    return "".join(out)


def render_personas(d: dict) -> str:
    rows = d["personas"]
    if not rows:
        return "  (no personas registered)"
    out = []
    for r in rows:
        out.append(f"  ▸ {r['label'].lower()}  [{r['id']}]")
        body = " ".join(no_emdash(r["description"] or "").split())
        wrapped = textwrap.fill(
            body, width=74, initial_indent="    ", subsequent_indent="    "
        )
        out.append(wrapped)
        out.append("")
    return "\n".join(out).rstrip()


def render_model_configs(d: dict) -> str:
    rows = load_model_configs_from_yaml() or [dict(r) for r in d["model_configs"]]
    if not rows:
        return '<p class="dim">no model surfaces are configured.</p>'
    out = [
        '<div class="scroll"><table class="data-table">',
        "<thead><tr><th>surface</th><th>provider</th><th>model</th><th>call path</th></tr></thead><tbody>",
    ]
    for r in rows:
        cmd = r.get("cli_command") or ""
        sub = r.get("subcommand") or ""
        call_path = " ".join(p for p in [cmd, sub] if p and p != "null")
        out.append(
            "<tr>"
            f'<td>{html.escape(r.get("id") or "")}</td>'
            f'<td>{html.escape(r.get("provider") or "")}</td>'
            f'<td>{html.escape(r.get("model_name") or "")}</td>'
            f'<td>{html.escape(call_path)}</td>'
            "</tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def render_rolling_top(rows: list[dict], window_label: str) -> str:
    if not rows:
        return f'<p class="dim">no recommendation flow in this {html.escape(window_label)} window yet.</p>'
    max_abs_net = max((abs(r.get("net") or 0) for r in rows), default=0) or 1
    spark_header = "30d sparkline"
    out = [
        '<div class="scroll"><table class="data-table">',
        "<thead><tr>",
        "<th class=\"num\">rank</th><th>ticker</th>",
        "<th class=\"num\">bull</th><th class=\"num\">bear</th>",
        f"<th>net</th><th class=\"spark\">{html.escape(spark_header)}</th>",
        "</tr></thead><tbody>",
    ]
    for i, r in enumerate(rows, start=1):
        net = r.get("net") or 0
        out.append(
            "<tr>"
            f"<td class=\"num\">{i}</td>"
            f"<td><strong>${html.escape(r['ticker'])}</strong></td>"
            f"<td class=\"num\">{r.get('bull') or 0}</td>"
            f"<td class=\"num\">{r.get('bear') or 0}</td>"
            f"<td>{pbar_html(net, max_abs_net)}</td>"
            f"<td class=\"spark\">{html.escape(r.get('sparkline') or '')}</td>"
            "</tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def render_provider_heading(provider: str) -> str:
    label, src = PROVIDER_ICONS.get(provider, (provider, ""))
    if not src:
        return html.escape(label)
    return (
        f'<span class="provider-head" title="{html.escape(label)}">'
        f'<img class="provider-icon" src="{html.escape(src)}" alt="" aria-hidden="true">'
        f'<span class="sr-only">{html.escape(label)}</span>'
        "</span>"
    )


def provider_cell(row: dict, provider: str) -> str:
    """Layered bull/bear cell. Bear gets a dim class so the eye reads bull first;
    when bear is zero it fades further into the background. Returns raw HTML —
    callers must not html-escape it."""
    bull = row.get(f"{provider}_bull") or 0
    bear = row.get(f"{provider}_bear") or 0
    cls = "bear-zero" if bear == 0 else "bear"
    return f'{bull}<span class="{cls}">/{bear}</span>'


def render_first_sightings(rows: list[dict], providers: list[str],
                           compact: bool = False) -> str:
    if not rows:
        return '<p class="dim">no first sightings yet.</p>'
    providers = providers or []
    lines = [
        '<div class="scroll"><table class="data-table provider-table">',
        "<thead><tr>",
        "<th>ticker</th><th>first seen</th>" if compact
        else "<th>ticker</th><th>first seen</th><th>last seen</th>",
    ]
    lines.extend(f"<th>{render_provider_heading(p)}</th>" for p in providers)
    lines.append("<th>net</th></tr></thead><tbody>" if compact
                 else "<th>net</th><th>n</th><th>days</th></tr></thead><tbody>")
    for r in rows:
        net = r.get("net_since") or 0
        sign = "+" if net > 0 else ("-" if net < 0 else " ")
        first_seen = r["first_seen"][5:] if compact else r["first_seen"]
        lines.append("<tr>")
        lines.append(f"<td>${html.escape(r['ticker'])}</td>")
        lines.append(f"<td>{html.escape(first_seen)}</td>")
        if not compact:
            lines.append(f"<td>{html.escape(r.get('last_seen') or '-')}</td>")
        for provider in providers:
            lines.append(f"<td class=\"num\">{provider_cell(r, provider)}</td>")
        lines.append(f"<td class=\"num\">{sign}{abs(net)}</td>")
        if not compact:
            lines.append(f"<td class=\"num\">{r.get('n') or 0}</td>")
            lines.append(f"<td class=\"num\">{r.get('days_seen') or 0}</td>")
        lines.append("</tr>")
    lines.append("</tbody></table></div>")
    return "".join(lines)


def render_consensus(rows: list[dict], providers: list[str],
                     compact: bool = False) -> str:
    if not rows:
        return '<p class="dim">no tickers yet where multiple providers were bullish.</p>'
    n_days = max((r.get("spark_days") or 0 for r in rows), default=0)
    spark_header = f"{n_days}d trend" if n_days else "trend"
    providers = providers or []
    lines = [
        '<div class="scroll"><table class="data-table provider-table">',
        "<thead><tr>",
        "<th>ticker</th>",
    ]
    lines.extend(f"<th>{render_provider_heading(p)}</th>" for p in providers)
    lines.append(
        "<th>total</th><th>verdict</th></tr></thead><tbody>" if compact else
        f"<th>total</th><th>verdict</th><th>{html.escape(spark_header)}</th>"
        "</tr></thead><tbody>"
    )
    for r in rows:
        total_bull = r.get("total_bull") or 0
        total_bear = r.get("total_bear") or 0
        provider_total = r.get("provider_total") or 0
        bullish_providers = r.get("bullish_providers") or 0
        bearish_providers = r.get("bearish_providers") or 0
        verdict = f"{bullish_providers}/{provider_total} BULL"
        if total_bear and bearish_providers:
            verdict = f"{verdict} split"
        spark = r.get("sparkline", "")
        lines.append("<tr>")
        lines.append(f"<td>${html.escape(r['ticker'])}</td>")
        for provider in providers:
            lines.append(f"<td class=\"num\">{provider_cell(r, provider)}</td>")
        lines.append(f"<td class=\"num\">{total_bull-total_bear:+}</td>")
        lines.append(f"<td>{html.escape(verdict)}</td>")
        if not compact:
            lines.append(f"<td class=\"spark\">{html.escape(spark)}</td>")
        lines.append("</tr>")
    lines.append("</tbody></table></div>")
    return "".join(lines)


def render_days_index(rows: list[dict]) -> str:
    if not rows:
        return '<p class="dim">no nights yet.</p>'
    out = [
        '<div class="scroll"><table class="data-table">',
        "<thead><tr>",
        "<th>night</th><th class=\"num\">responses</th><th class=\"num\">unique tickers</th><th class=\"num\">top pick</th>",
        "</tr></thead><tbody>",
    ]
    for r in rows:
        lead = '<span class="zero">n/a</span>'
        if r.get("lead_ticker"):
            net = r.get("lead_net") or 0
            lead = f'${html.escape(r["lead_ticker"])} {signed_int_span(net)}'
        day = r["day"]
        out.append(
            "<tr>"
            f'<td><a href="day/{html.escape(day)}.html">{html.escape(day)}</a></td>'
            f'<td class="num">{r.get("n_responses") or 0}</td>'
            f'<td class="num">{r.get("n_unique") or 0}</td>'
            f'<td class="num">{lead}</td>'
            "</tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


# ───────────────────────── html template ─────────────────────────



BASE_CSS = """/* BASE_CSS — Qt desktop-app skin (Fusion-style widgets, light + dark palettes) */
@font-face {
  font-family: 'JetBrains Mono';
  src: url('assets/fonts/JetBrainsMono-Regular.woff2') format('woff2');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: 'JetBrains Mono';
  src: url('assets/fonts/JetBrainsMono-Bold.woff2') format('woff2');
  font-weight: 700;
  font-style: normal;
  font-display: swap;
}
:root {
  color-scheme: light;
  --backdrop: radial-gradient(120% 130% at 50% 0%, #585c63 0%, #43464c 55%, #34373c 100%);
  --win: #efefef;          /* QPalette::Window */
  --base: #ffffff;         /* QPalette::Base */
  --alt: #f6f6f6;          /* QPalette::AlternateBase */
  --text: #1c1c1c;
  --dim: #6b6b6b;
  --frame: #b4b4b4;        /* sunken/raised frame line */
  --frame-light: #c9c9c9;
  --gridline: #efefef;     /* table cell separators */
  --hl: #308cc6;           /* Fusion highlight */
  --hl-text: #ffffff;
  --hover-row: #e6f2fa;
  --link: #0a66b8;
  --up: #1d6fa5;
  --down: #b3261e;
  --zero: #9a9a9a;
  --bear: #8a8a8a;
  --bear-zero: #c4c4c4;
  --spark: #9a9a9a;
  --axis: #9a9a9a;
  --plot-grid: #e7e7e7;
  --plot-zero: #b0b0b0;
  --qqq: #909090;
  --title-grad: linear-gradient(#f6f6f6, #dcdcdc);
  --title-border: #b0b0b0;
  --title-text: #333333;
  --btn-grad: linear-gradient(#fefefe, #e8e8e8);
  --btn-hover-grad: linear-gradient(#ffffff, #ededed);
  --btn-border: #a9a9a9;
  --hdr-grad: linear-gradient(#ffffff, #e5e5e5);
  --hdr-border: #d4d4d4;
  --tab-grad: linear-gradient(#ececec, #dcdcdc);
  --dock-grad: linear-gradient(#ececec, #dedede);
  --chunk-grad: linear-gradient(#55a3d8, #2a7fc0);
  --chunk-border: #1d6fa5;
  --chunk-neg-grad: linear-gradient(#d87a6c, #c0503f);
  --chunk-neg-border: #a53e2e;
  --seg-alloc-grad: linear-gradient(#a9a9a9, #8d8d8d);
  --seg-alloc-border: #7d7d7d;
  --axis-split: #9a9a9a;
  --sunken-dark: #c0c0c0;
  --sunken-light: #fdfdfd;
  --grip-dot: #9a9a9a;
  --win-border: #8f8f8f;
  --close-hover: #e81123;
  --font-ui: 'Segoe UI', 'Helvetica Neue', 'Cantarell', 'Ubuntu', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --backdrop: radial-gradient(120% 130% at 50% 0%, #2c2e32 0%, #222428 55%, #1a1b1e 100%);
    --win: #353535;
    --base: #232323;
    --alt: #2b2b2b;
    --text: #d8d8d8;
    --dim: #9f9f9f;
    --frame: #1f1f1f;
    --frame-light: #2a2a2a;
    --gridline: #2f2f2f;
    --hl: #2a82da;
    --hl-text: #ffffff;
    --hover-row: #2c3a46;
    --link: #6ab0e8;
    --up: #6ab0e8;
    --down: #e57368;
    --zero: #7d7d7d;
    --bear: #8d8d8d;
    --bear-zero: #4d4d4d;
    --spark: #777777;
    --axis: #8a8a8a;
    --plot-grid: #333333;
    --plot-zero: #555555;
    --qqq: #8a8a8a;
    --title-grad: linear-gradient(#3f3f3f, #313131);
    --title-border: #232323;
    --title-text: #cccccc;
    --btn-grad: linear-gradient(#484848, #3b3b3b);
    --btn-hover-grad: linear-gradient(#525252, #434343);
    --btn-border: #292929;
    --hdr-grad: linear-gradient(#454545, #383838);
    --hdr-border: #2e2e2e;
    --tab-grad: linear-gradient(#3a3a3a, #303030);
    --dock-grad: linear-gradient(#3a3a3a, #313131);
    --chunk-grad: linear-gradient(#3a8fd6, #2a6faf);
    --chunk-border: #1d5a8f;
    --chunk-neg-grad: linear-gradient(#c0604f, #a04030);
    --chunk-neg-border: #7d3022;
    --seg-alloc-grad: linear-gradient(#7d7d7d, #696969);
    --seg-alloc-border: #585858;
    --axis-split: #6f6f6f;
    --sunken-dark: #222222;
    --sunken-light: #454545;
    --grip-dot: #6f6f6f;
    --win-border: #181818;
    --close-hover: #c11020;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  min-height: 100vh;
  background: var(--backdrop);
  font-family: var(--font-ui);
  font-size: 13px;
  color: var(--text);
  font-variant-numeric: tabular-nums lining-nums;
  padding: 24px 16px 36px;
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
a:focus-visible, summary:focus-visible, select:focus-visible { outline: 2px solid var(--hl); outline-offset: 1px; }
header, nav, main, section, footer, pre, table, p, h1, h2, h3, figure { margin: 0; }
pre { white-space: pre-wrap; word-break: normal; overflow-wrap: anywhere; font: 12px/1.5 var(--font-mono); }
.dim, .intro, .source, .caption { color: var(--dim); }
.nb { white-space: nowrap; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.scroll { overflow-x: auto; max-width: 100%; }

/* ---------- window ---------- */
.window {
  width: min(1180px, 100%);
  margin: 0 auto;
  background: var(--win);
  border: 1px solid var(--win-border);
  border-radius: 7px;
  box-shadow: 0 22px 60px rgba(0,0,0,.5), 0 2px 8px rgba(0,0,0,.35);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ---------- title bar + menu bar ---------- */
.titlebar {
  display: flex;
  align-items: center;
  height: 32px;
  background: var(--title-grad);
  border-bottom: 1px solid var(--title-border);
  user-select: none;
}
.titlebar .home-link {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
  height: 100%;
  color: inherit;
  text-decoration: none;
}
.titlebar .home-link:hover { text-decoration: none; }
.titlebar .home-link:hover .title { color: var(--hl); }
.titlebar .app-icon { width: 16px; height: 16px; margin: 0 8px 0 10px; }
.titlebar .title {
  flex: 1;
  text-align: center;
  font-size: 13px;
  font-weight: 600;
  color: var(--title-text);
  margin-left: -34px;
  padding-left: 34px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.winbtns { display: flex; height: 100%; }
.winbtn {
  width: 40px; height: 100%;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: var(--dim);
}
.winbtn:hover { background: var(--frame-light); }
.winbtn.close:hover { background: var(--close-hover); color: #fff; }

/* ---------- toolbar ---------- */
.toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  background: var(--win);
  border-bottom: 1px solid var(--frame-light);
  user-select: none;
}
.tbtn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: 3px;
  font-size: 12px;
  color: var(--text);
}
a.tbtn:hover { background: var(--btn-grad); border-color: var(--btn-border); text-decoration: none; }
.tbtn.disabled { color: var(--zero); }
.tsep { width: 1px; height: 20px; margin: 0 4px; background: var(--frame); box-shadow: 1px 0 0 var(--sunken-light); }
.tspacer { flex: 1; }
select.combo-select {
  height: 26px;
  padding: 0 4px;
  border: 1px solid var(--btn-border);
  border-radius: 3px;
  background: var(--win);
  color: var(--text);
  font: 12px var(--font-ui);
  font-variant-numeric: tabular-nums;
}

/* ---------- app body: dock + main ---------- */
.appbody { display: flex; align-items: stretch; min-height: 0; }
.dock {
  width: 178px;
  flex: none;
  border-right: 1px solid var(--frame-light);
  background: var(--win);
}
.dock-inner { position: sticky; top: 8px; display: flex; flex-direction: column; }
.dock-title {
  display: flex;
  align-items: center;
  height: 22px;
  padding: 0 6px;
  background: var(--dock-grad);
  border-bottom: 1px solid var(--frame-light);
  font-size: 11px;
  font-weight: 600;
  color: var(--dim);
  user-select: none;
}
.dock-title .dock-glyphs { margin-left: auto; color: var(--zero); font-size: 10px; letter-spacing: 4px; }
.listview {
  margin: 6px;
  background: var(--base);
  border: 1px solid var(--frame);
  border-radius: 2px;
  overflow-y: auto;
  max-height: calc(100vh - 140px);
  font-size: 12px;
}
.listview .ditem {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 22px;
  padding: 0 8px;
  color: var(--text);
  text-decoration: none;
  white-space: nowrap;
}
.listview .ditem:nth-child(even) { background: var(--alt); }
.listview .ditem:hover { background: var(--hover-row); text-decoration: none; }
.listview .ditem.selected, .listview .ditem.selected:hover { background: var(--hl); color: var(--hl-text); }
.listview .led { width: 7px; height: 7px; border-radius: 1px; background: var(--hl); border: 1px solid var(--chunk-border); flex: none; }
.listview .ditem.selected .led { background: #fff; border-color: #d8ecf8; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; padding: 8px 10px 10px; }

/* ---------- tab bar + pane ---------- */
.tabbar {
  display: flex;
  align-items: flex-end;
  padding: 0; /* first tab's left border sits flush on the pane frame */
  user-select: none;
  position: relative;
  z-index: 2; /* tabs paint over the pane's top border */
}
.tab {
  padding: 4px 14px 5px;
  font-size: 12px;
  color: var(--dim);
  background: var(--tab-grad);
  border: 1px solid var(--frame);
  border-bottom: none;
  border-radius: 3px 3px 0 0;
  margin-right: -1px;
  text-decoration: none;
}
a.tab:hover { color: var(--text); text-decoration: none; }
.tab.active {
  background: var(--win);
  color: var(--text);
  font-weight: 600;
  padding-top: 6px;
  padding-bottom: 6px;
  margin-bottom: -1px; /* overlap the pane border so tab and pane merge */
}
.tab .tab-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  margin: 0 -5px 0 8px;
  border-radius: 2px;
  font-size: 9px;
  font-weight: 400;
  color: var(--dim);
  text-decoration: none;
  vertical-align: 1px;
}
.tab .tab-close:hover { background: var(--close-hover); color: #fff; text-decoration: none; }
.tabpane {
  display: block;
  border: 1px solid var(--frame);
  border-radius: 0 3px 3px 3px;
  background: var(--win);
  padding: 14px 12px 16px;
}

/* ---------- group boxes ---------- */
.groupbox {
  position: relative;
  border: 1px solid var(--frame);
  border-radius: 3px;
  padding: 14px 10px 10px;
  margin-top: 18px;
}
.groupbox:first-child, .dek-strip + .groupbox { margin-top: 8px; }
.dek-strip + .groupbox { margin-top: 14px; }
.groupbox > .gtitle {
  position: absolute;
  top: -9px;
  left: 8px;
  max-width: calc(100% - 24px);
  padding: 0 5px;
  background: var(--win);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.gnote, .insight { margin: 8px 2px 0; font-size: 12px; color: var(--dim); }
.dek-strip { display: flex; align-items: baseline; gap: 7px; padding: 2px 2px 6px; font-size: 12.5px; color: var(--dim); }
.dek-strip::before { content: 'ⓘ'; color: var(--hl); font-size: 13px; }
.label { font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--dim); }
.intro, .prose, .dek { font-size: 12.5px; line-height: 1.55; max-width: 86ch; }
.intro { margin: 0 2px 10px; }
.prose, .dek { margin-top: 8px; }
.prose:first-child, .dek:first-child { margin-top: 0; }
h3 { font-size: 12px; font-weight: 600; margin: 14px 2px 6px; }

/* ---------- tables (QTableView) ---------- */
.flow-table, .data-table, .alpha-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  background: var(--base);
  border: 1px solid var(--frame);
}
th {
  background: var(--hdr-grad);
  border-bottom: 1px solid var(--frame);
  border-right: 1px solid var(--hdr-border);
  padding: 3px 8px;
  font-weight: 600;
  text-align: left;
  white-space: nowrap;
  color: var(--text);
  text-transform: capitalize;
  user-select: none;
}
th:last-child { border-right: none; }
td {
  padding: 3px 8px;
  border-right: 1px solid var(--gridline);
  white-space: nowrap;
  vertical-align: middle;
  text-align: left;
}
td:last-child { border-right: none; }
tbody tr:nth-child(even) { background: var(--alt); }
tbody tr:hover { background: var(--hover-row); }
td.num, th.num { text-align: right; }
.flow-table .ticker, .data-table strong { font-weight: 600; }
.table-scroll {
  max-height: 340px; /* header + ~15 rows visible, rest scrolls */
  overflow: auto;
  border: 1px solid var(--frame);
  border-radius: 2px;
  background: var(--base);
}
.table-scroll > table { border: none; }
.table-scroll thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  /* border-collapse drops sticky cell borders while scrolling; the
     shadow keeps the header rule visible */
  box-shadow: inset 0 -1px 0 var(--frame);
}
.table-scroll::-webkit-scrollbar, .listview::-webkit-scrollbar { width: 13px; height: 13px; }
.table-scroll::-webkit-scrollbar-track, .listview::-webkit-scrollbar-track { background: var(--win); border-left: 1px solid var(--frame-light); }
.table-scroll::-webkit-scrollbar-thumb, .listview::-webkit-scrollbar-thumb { background: var(--btn-grad); border: 1px solid var(--btn-border); border-radius: 2px; }
.gcaption { margin: -2px 0 8px; }
.up { color: var(--up); }
.down { color: var(--down); }
.zero { color: var(--zero); }
.bear { color: var(--bear); }
.bear-zero { color: var(--bear-zero); }
.spark { font-family: var(--font-mono); font-size: 11px; color: var(--spark); letter-spacing: 1px; white-space: nowrap; }

/* ---------- progress bars (QProgressBar) ---------- */
.pbar {
  position: relative;
  width: 200px;
  height: 15px;
  border: 1px solid var(--btn-border);
  border-radius: 2px;
  background: var(--base);
  overflow: hidden;
}
.pbar .chunk { position: absolute; inset: 0 auto 0 0; background: var(--chunk-grad); border-right: 1px solid var(--chunk-border); }
.pbar .chunk.neg { background: var(--chunk-neg-grad); border-right-color: var(--chunk-neg-border); }
.pbar .ptext {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10.5px;
  font-weight: 600;
  color: var(--text);
  mix-blend-mode: multiply;
}
@media (prefers-color-scheme: dark) {
  .pbar .ptext { mix-blend-mode: normal; color: #eaeaea; text-shadow: 0 1px 2px rgba(0,0,0,.5); }
}

/* ---------- diverging persona bars ---------- */
.seg { display: inline-block; height: 11px; border-radius: 1px; vertical-align: middle; }
.seg.alloc { background: var(--seg-alloc-grad); border: 1px solid var(--seg-alloc-border); }
.seg.spec { background: var(--chunk-grad); border: 1px solid var(--chunk-border); }
td.side-a, th.side-a { text-align: right; }
td.side-s, th.side-s { border-left: 2px solid var(--axis-split); }
.side-a .count { margin-right: 5px; }
.side-s .count { margin-left: 5px; }
.count { display: inline-block; min-width: 2ch; font-size: 11px; vertical-align: middle; }

/* ---------- provider icons ---------- */
.provider-head { display: inline-flex; width: 3ch; align-items: center; justify-content: center; vertical-align: middle; }
.provider-icon { width: 14px; height: 14px; display: block; filter: grayscale(100%) brightness(40%); opacity: .85; }
@media (prefers-color-scheme: dark) {
  .provider-icon { filter: grayscale(100%) invert(80%); }
}

/* ---------- plot (chart frame) + legend ---------- */
.plot { border: 1px solid var(--frame); border-radius: 2px; background: var(--base); padding: 8px; }
.legend { display: flex; gap: 14px; margin: 2px 4px 8px; font-size: 11px; color: var(--dim); }
.legend .swatch { display: inline-block; width: 18px; height: 0; border-top: 2px solid; vertical-align: middle; margin-right: 5px; }
.legend .swatch.models { border-color: var(--chart-models, var(--up)); }
.legend .swatch.qqq { border-color: var(--qqq); border-top-width: 1.4px; }
.alpha-svg { width: 100%; height: auto; display: block; }
.alpha-svg text { font: 10.5px var(--font-ui); fill: var(--axis); }
.alpha-svg .grid { stroke: var(--plot-grid); stroke-width: 1; vector-effect: non-scaling-stroke; }
.alpha-svg .zero-line { stroke: var(--plot-zero); stroke-width: 1; stroke-dasharray: 3 2; vector-effect: non-scaling-stroke; }
.alpha-svg .models-line { stroke: var(--chart-models, var(--up)); stroke-width: 2; vector-effect: non-scaling-stroke; }
.alpha-svg .qqq-line { stroke: var(--qqq); stroke-width: 1.4; vector-effect: non-scaling-stroke; }

/* ---------- scoreboard band ---------- */
.scoreboard { display: grid; grid-template-columns: minmax(0, 1fr) 250px; gap: 14px; align-items: start; }
.score-side { display: flex; flex-direction: column; gap: 8px; }
.stat-frame { border: 1px solid var(--frame); border-radius: 2px; background: var(--base); padding: 10px 12px; }
.stat-num { font-size: 21px; font-weight: 700; }
.stat-split { margin-top: 3px; font-size: 12px; font-weight: 600; color: var(--dim); }
.stat-rest { margin-top: 6px; font-size: 11.5px; color: var(--dim); line-height: 1.45; }
.source { font-size: 10.5px; color: var(--zero); margin-top: 6px; }
.qbutton {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 26px;
  padding: 0 14px;
  border: 1px solid var(--btn-border);
  border-radius: 3px;
  background: var(--btn-grad);
  font-size: 12px;
  color: var(--text);
  text-decoration: none;
  align-self: flex-start;
}
.qbutton:hover { background: var(--btn-hover-grad); text-decoration: none; }
.qbutton:active { filter: brightness(0.96); }
.more { margin-top: 8px; font-size: 11.5px; }

/* ---------- teaser row ---------- */
.teaser-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.teaser-grid .groupbox { margin-top: 0; min-width: 0; }
.teaser-grid .scroll { overflow-x: auto; }

/* ---------- record squares ---------- */
.pipeline { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; padding: 2px; }
.sq { width: 13px; height: 13px; border-radius: 2px; background: var(--hl); border: 1px solid var(--chunk-border); display: inline-block; }
.sq.missed { background: var(--base); border-color: var(--frame); }
.sq.excluded { background: linear-gradient(135deg, var(--hl) 50%, var(--base) 50%); border-color: var(--frame); }
a.sq:hover { outline: 2px solid var(--hover-row); outline-offset: 1px; }
.pipeline .caption { margin-left: 10px; font-size: 11.5px; }

/* ---------- terms / details expander ---------- */
details { margin-top: 14px; padding: 2px; }
summary { cursor: pointer; list-style: none; font-size: 12px; font-weight: 600; color: var(--text); user-select: none; }
summary::-webkit-details-marker { display: none; }
summary::before { content: '▸ '; color: var(--dim); }
details[open] summary::before { content: '▾ '; }
details .details-body { margin: 8px 0 0 14px; max-width: 90ch; font-size: 12px; color: var(--dim); line-height: 1.5; }

/* ---------- exhibits (sample responses as readonly text areas) ---------- */
.exhibit { margin-top: 14px; border: 1px solid var(--frame); border-radius: 2px; background: var(--base); overflow: hidden; }
.exhibit figcaption {
  display: block;
  padding: 3px 8px;
  background: var(--hdr-grad);
  border-bottom: 1px solid var(--frame);
  font-size: 11px;
  color: var(--dim);
  letter-spacing: 0.03em;
}
.exhibit-question { padding: 7px 10px 0; font-size: 12px; color: var(--dim); max-width: 92ch; }
.exhibit-body { padding: 7px 10px 9px; font: 12px/1.5 var(--font-mono); color: var(--text); max-width: 100ch; }

/* ---------- methodology blocks ---------- */
.method-block { margin-top: 10px; }
.method-block pre, .prompt-list pre {
  border: 1px solid var(--frame);
  border-radius: 2px;
  background: var(--base);
  padding: 8px 10px;
}
.prompt-list { display: grid; gap: 10px; max-width: 92ch; margin-top: 8px; }
.prompt-list h3 { margin: 8px 0 0; }
.prompt-item { border: 1px solid var(--frame-light); border-radius: 2px; background: var(--base); padding: 7px 10px; }
.prompt-item p { margin: 3px 0 0; font-size: 12.5px; line-height: 1.5; }
.prompt-id { font-size: 11px; font-weight: 600; color: var(--hl); }

/* ---------- status bar ---------- */
.statusbar {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: stretch;
  gap: 6px;
  padding: 3px 4px;
  border-top: 1px solid var(--frame-light);
  background: var(--win);
  font-size: 11.5px;
  color: var(--dim);
  user-select: none;
  z-index: 5;
}
.status-cell {
  display: flex;
  align-items: center;
  padding: 1px 8px;
  border: 1px solid;
  border-color: var(--sunken-dark) var(--sunken-light) var(--sunken-light) var(--sunken-dark);
  border-radius: 1px;
  white-space: nowrap;
}
.status-cell strong { color: var(--text); font-weight: 600; }
.status-cell.stretch { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; display: block; padding-top: 3px; }
.sizegrip {
  align-self: flex-end;
  width: 14px; height: 14px;
  flex: none;
  background:
    radial-gradient(circle at 11px 11px, var(--grip-dot) 1.2px, transparent 1.6px),
    radial-gradient(circle at 11px 6px,  var(--grip-dot) 1.2px, transparent 1.6px),
    radial-gradient(circle at 6px 11px,  var(--grip-dot) 1.2px, transparent 1.6px),
    radial-gradient(circle at 11px 1px,  var(--grip-dot) 1.2px, transparent 1.6px),
    radial-gradient(circle at 6px 6px,   var(--grip-dot) 1.2px, transparent 1.6px),
    radial-gradient(circle at 1px 11px,  var(--grip-dot) 1.2px, transparent 1.6px);
}

/* ---------- responsive ---------- */
@media (max-width: 900px) {
  body { padding: 0; }
  .window { border: none; border-radius: 0; box-shadow: none; width: 100%; min-height: 100vh; }
  .dock { display: none; }
  .teaser-grid { grid-template-columns: 1fr; }
  .scoreboard { grid-template-columns: 1fr; }
  .flow-table .spark-col { display: none; }
  .pbar { width: 120px; }
  .titlebar .title { font-size: 12px; }
  .tabbar { overflow-x: auto; }
  .toolbar { flex-wrap: wrap; }
  .status-cell { padding: 1px 5px; }
}
"""

PAGE_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{description}">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="pythia">
<meta name="theme-color" content="#43464c">
<link rel="icon" type="image/svg+xml" href="{root_prefix}assets/favicon.svg">
<style>
{base_css}
</style>
</head>
<body>
<div class="window">
{titlebar}
{toolbar}
<div class="appbody">
{dock}
<div class="main">
{tabbar}
<main class="tabpane">
{content}
</main>
</div>
</div>
{statusbar}
</div>
</body>
</html>
"""

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="10" fill="#efefef"/>
<path d="M14 50V14h21c9 0 15 5 15 14s-6 14-15 14H26v8H14Zm12-19h8c3 0 5-1 5-3s-2-3-5-3h-8v6Z" fill="#308cc6"/>
</svg>
"""

DESCRIPTIONS = {
    "index": "nightly AI recommendation flow, scoreboard, first sightings, and consensus.",
    "day": "full nightly pythia panel artifact with ticker flow, model samples, and prompts.",
    "trends": "rolling pythia recommendation flow, first sightings, and provider consensus.",
    "alpha": "pythia paper scoreboard comparing the top-20 basket with QQQ.",
    "methodology": "pythia methodology, prompts, personas, and model surfaces.",
}


def page_shell(title: str, page: str, window_title: str, toolbar: str, dock: str,
               content: str, statusbar: str, root_prefix: str = "",
               description: str | None = None, session: str | None = None) -> str:
    desc = description or DESCRIPTIONS.get(page, DESCRIPTIONS["index"])
    return PAGE_TMPL.format(
        title=html.escape(title),
        description=html.escape(desc),
        og_title=html.escape(title),
        root_prefix=html.escape(root_prefix),
        base_css=BASE_CSS.replace("assets/", f"{root_prefix}assets/"),
        titlebar=render_titlebar(window_title, root_prefix),
        toolbar=toolbar,
        dock=dock,
        tabbar=render_tabbar(page, root_prefix, session),
        content=content,
        statusbar=statusbar,
    )


def parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_et(iso: str | None) -> str:
    dt = parse_dt(iso)
    if not dt:
        return "time pending"
    return dt.astimezone(ET).strftime("%Y-%m-%d %H:%M ET")


DEK = "Every night we ask Claude, GPT-5.5 and Gemini what stocks to buy. We log every answer."


def render_titlebar(window_title: str, root_prefix: str = "") -> str:
    return (
        '<div class="titlebar">'
        f'<a class="home-link" href="{html.escape(root_prefix)}index.html" title="Back to overview">'
        f'<img class="app-icon" src="{html.escape(root_prefix)}assets/favicon.svg" alt="">'
        f'<div class="title">{html.escape(window_title)}</div>'
        '</a>'
        '<div class="winbtns" aria-hidden="true">'
        '<span class="winbtn">─</span><span class="winbtn">▢</span>'
        '<span class="winbtn close">✕</span></div>'
        '</div>'
    )


def render_tabbar(page: str, root_prefix: str = "", session: str | None = None) -> str:
    """Page tabs. A day page opens as a closable document tab next to
    Overview; its ✕ closes the session and returns to the index."""
    tabs = [
        ("overview", "Overview", "index.html"),
        ("trends", "Trends", "trends.html"),
        ("alpha", "Scoreboard", "alpha.html"),
        ("methodology", "Methodology", "methodology.html"),
    ]
    active = "overview" if page == "index" else page
    out = ['<nav class="tabbar">']
    for key, label, href in tabs:
        if key == active and not session:
            out.append(f'<span class="tab active">{label}</span>')
        else:
            out.append(f'<a class="tab" href="{html.escape(root_prefix + href)}">{label}</a>')
        if key == "overview" and session:
            out.append(
                f'<span class="tab active">{html.escape(session)}'
                f'<a class="tab-close" href="{html.escape(root_prefix)}index.html" '
                'title="Close session" aria-label="Close session, back to overview">✕</a></span>'
            )
    out.append("</nav>")
    return "".join(out)


def render_toolbar(current: str, days: list[str], root_prefix: str = "") -> str:
    """Session navigation: prev/next night buttons around a date combo, plus
    raw-data and about links. `days` is newest-first."""
    is_index = root_prefix == ""
    try:
        idx = days.index(current)
    except ValueError:
        idx = 0
    older = days[idx + 1] if idx + 1 < len(days) else None
    newer = days[idx - 1] if idx > 0 else None

    def nav_btn(day: str | None, glyph: str, label: str) -> str:
        if not day:
            return f'<span class="tbtn disabled" aria-hidden="true">{glyph}</span>'
        return (
            f'<a class="tbtn" href="{html.escape(_day_href(day, is_index))}" '
            f'title="{label}: {html.escape(day)}">{glyph}</a>'
        )

    options = "".join(
        f'<option value="{html.escape(_day_href(dd, is_index))}"'
        f'{" selected" if dd == current else ""}>{html.escape(dd)}</option>'
        for dd in days
    )
    return (
        '<div class="toolbar">'
        + nav_btn(older, "◀", "previous night")
        + '<select class="combo-select" aria-label="select night" '
        f'onchange="if(this.value)location.href=this.value">{options}</select>'
        + nav_btn(newer, "▶", "next night")
        + '<div class="tsep"></div>'
        + f'<a class="tbtn" href="https://{html.escape(REPO_URL)}">&lt;/&gt; Open source code</a>'
        + '<div class="tspacer"></div>'
        + f'<a class="tbtn" href="{html.escape(root_prefix)}methodology.html" '
        f'title="{html.escape(DEK)}">ⓘ About this experiment</a>'
        + '</div>'
    )


def render_dock(current: str | None, days: list[str], root_prefix: str = "") -> str:
    """Sessions dock: one list row per clean night, newest first."""
    is_index = root_prefix == ""
    items = []
    for dd in days:
        sel = " selected" if dd == current else ""
        items.append(
            f'<a class="ditem{sel}" href="{html.escape(_day_href(dd, is_index))}">'
            f'<span class="led"></span>{html.escape(dd)}</a>'
        )
    return (
        '<aside class="dock"><div class="dock-inner">'
        '<div class="dock-title">Sessions'
        '<span class="dock-glyphs" aria-hidden="true">▣ ✕</span></div>'
        '<div class="listview">' + "".join(items) + '</div>'
        '</div></aside>'
    )


def render_statusbar(d: dict, panel_no: int, root_prefix: str = "") -> str:
    latest = d.get("latest_run")
    counts = d.get("counts")
    ok = counts["n_responses_ok"] if counts else 0
    total = ok + (counts["n_responses_fail"] if counts else 0)
    finished = latest["finished_at"] if latest else None
    started = latest["started_at"] if latest else None
    stamp_time = fmt_et(finished or started)
    return (
        '<div class="statusbar">'
        f'<div class="status-cell"><strong>Nightly panel No. {panel_no}</strong></div>'
        f'<div class="status-cell">{ok}/{total} responses</div>'
        f'<div class="status-cell">Last panel: {html.escape(stamp_time)}</div>'
        '<div class="status-cell stretch">Not investment advice; a public measurement experiment — '
        f'<a href="{html.escape(root_prefix)}methodology.html">methodology</a> · '
        f'<a href="https://{html.escape(REPO_URL)}">open source code</a></div>'
        '<div class="sizegrip" aria-hidden="true"></div>'
        '</div>'
    )

# ───────────────────────── main ─────────────────────────



def _day_href(day: str, is_index: bool) -> str:
    return f"day/{day}.html" if is_index else f"{day}.html"


def pbar_html(net: int, max_abs: int) -> str:
    """QProgressBar-style flow bar: blue chunk for positive net, red for
    negative, with the signed value centered over the bar."""
    pct = 0 if max_abs <= 0 else min(100, round(100 * abs(net) / max_abs))
    if net and pct < 4:
        pct = 4
    cls = " neg" if net < 0 else ""
    return (
        f'<div class="pbar"><div class="chunk{cls}" style="width:{pct}%"></div>'
        f'<div class="ptext">{net:+d}</div></div>'
    )


def signed_int(n: int) -> str:
    return f"{n:+d}"


def flow_caption(d: dict, day: str) -> str:
    """Dim caption under the flow group title: which panel, the net
    definition, and how much of the night's data is shown."""
    counts = d.get("counts")
    n_ok = counts["n_responses_ok"] if counts else 0
    n_rows = len(d.get("top_mentions") or [])
    return (
        f'<div class="label gcaption">panel of {html.escape(day)} · '
        f'net = bullish − bearish · {n_ok} responses · '
        f'top {n_rows} tickers</div>'
    )


def render_flow_table(d: dict, day: str) -> str:
    rows = d["top_mentions"]
    if not rows:
        return '<p class="dim">no panel data for this night yet.</p>'
    max_abs_net = max((abs(r["net"] or 0) for r in rows), default=1) or 1
    out = [
        '<div class="table-scroll"><table class="flow-table">',
        '<thead><tr><th>ticker</th><th>net</th><th class="spark-col">14d</th></tr></thead><tbody>',
    ]
    for r in rows:
        net = r["net"] or 0
        out.append(
            '<tr>'
            f'<td class="ticker">${html.escape(r["ticker"])}</td>'
            f'<td>{pbar_html(net, max_abs_net)}</td>'
            f'<td class="spark spark-col">{html.escape(r.get("sparkline") or "")}</td>'
            '</tr>'
        )
    out.append('</tbody></table></div>')
    return "".join(out)


def compute_insight(con, latest_day: str) -> str:
    rows = [dict(r) for r in con.execute(
        """
        WITH ticker_days AS (
          SELECT m.ticker, DATE(ru.started_at, '-5 hours') AS day,
                 SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                          WHEN m.sentiment_hint='bearish' THEN -1
                          ELSE 0 END) AS net
          FROM mentions m
          JOIN responses r ON m.response_id = r.id
          JOIN runs ru ON r.run_id = ru.id
          WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0
          GROUP BY m.ticker, day
        ), firsts AS (
          SELECT ticker, MIN(day) AS first_day FROM ticker_days GROUP BY ticker
        )
        SELECT td.ticker, td.net
        FROM ticker_days td JOIN firsts f USING (ticker)
        WHERE td.day = ? AND f.first_day = ? AND td.net > 0
        ORDER BY td.net DESC, td.ticker
        LIMIT 2
        """,
        (latest_day, latest_day),
    ).fetchall()]
    clauses = []
    if rows:
        names = [f"${r['ticker']}" for r in rows]
        joined = names[0] if len(names) == 1 else f"{names[0]} and {names[1]}"
        clauses.append(f"{joined} entered the flow for the first time")

    leaders = [dict(r) for r in con.execute(
        """
        SELECT day, ticker, net FROM (
            SELECT DATE(ru.started_at, '-5 hours') AS day, m.ticker,
                   SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                            WHEN m.sentiment_hint='bearish' THEN -1
                            ELSE 0 END) AS net,
                   ROW_NUMBER() OVER (PARTITION BY DATE(ru.started_at, '-5 hours')
                     ORDER BY SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                                        WHEN m.sentiment_hint='bearish' THEN -1
                                        ELSE 0 END) DESC, m.ticker) AS rk
            FROM mentions m
            JOIN responses r ON m.response_id = r.id
            JOIN runs ru ON r.run_id = ru.id
            WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0
            GROUP BY day, m.ticker
        ) WHERE rk = 1
        ORDER BY day DESC
        """
    ).fetchall()]
    lead = next((r for r in leaders if r["day"] == latest_day), leaders[0] if leaders else None)
    if lead:
        streak = 0
        for r in leaders:
            if r["ticker"] == lead["ticker"]:
                streak += 1
            else:
                break
        if streak >= 2:
            clauses.append(f"${lead['ticker']} leads for the {ordinal(streak)} straight night")
    if not clauses and lead:
        clauses.append(f"${lead['ticker']} leads the night's flow at {signed_int(lead['net'] or 0)}")
    if not clauses:
        clauses.append("the panel logged no positive flow this night")
    return "; ".join(clauses) + "."


def render_scoreboard_stat(alpha: dict) -> str:
    if not alpha.get("available"):
        return '<p class="stat-rest">scoreboard waiting for price data.</p>'
    s = alpha["summary"]
    excess = s["cum_top_vs_qqq"]
    cum_top = s["cum_top"]
    cum_qqq = cum_top - excess
    cls = "up" if excess >= 0 else "down"
    caveat = "; not yet statistically significant" if s["n_days"] < 60 else ""
    return (
        f'<div class="stat-num {cls}">{html.escape(fmt_signed_pct(excess))} vs QQQ</div>'
        f'<div class="stat-split">top-{alpha["top_n"]} {signed_pct_span(cum_top)}'
        f' · QQQ {signed_pct_span(cum_qqq)}</div>'
        f'<p class="stat-rest">cumulative excess of the nightly top-{alpha["top_n"]} '
        f"basket over QQQ across {s['n_days']} sessions, next open to close"
        f"{caveat}.</p>"
    )


def render_pipeline(con, days_span: int = 25) -> str:
    # The strip ends at the most recent night whose panel is expected to
    # exist: today once the 8 PM ET run has fired, otherwise yesterday.
    # Without this, every page built before 8 PM would show today as a
    # false "missed" square.
    now_et = datetime.now(ET)
    end = now_et.date() if now_et.hour >= 20 else now_et.date() - timedelta(days=1)
    dates = [(end - timedelta(days=i)).isoformat() for i in reversed(range(days_span))]
    states = {d: {"clean": False, "excluded": False} for d in dates}
    for r in con.execute(
        """
        SELECT DATE(started_at, '-5 hours') AS day,
               MAX(CASE WHEN is_clean=1 THEN 1 ELSE 0 END) AS has_clean,
               MAX(CASE WHEN is_clean=0 THEN 1 ELSE 0 END) AS has_excluded
        FROM runs
        WHERE DATE(started_at, '-5 hours') BETWEEN ? AND ?
        GROUP BY day
        """,
        (dates[0], dates[-1]),
    ).fetchall():
        if r["day"] in states:
            states[r["day"]] = {"clean": bool(r["has_clean"]), "excluded": bool(r["has_excluded"])}
    ran = sum(1 for d in dates if states[d]["clean"])
    pieces = ['<div class="pipeline">']
    for d in dates:
        st = states[d]
        if st["clean"]:
            pieces.append(f'<a class="sq" href="day/{html.escape(d)}.html" title="{html.escape(d)}"></a>')
        elif st["excluded"]:
            pieces.append(f'<span class="sq excluded" title="{html.escape(d)} (excluded)"></span>')
        else:
            pieces.append(f'<span class="sq missed" title="{html.escape(d)} (missed)"></span>')
    pieces.append(f'<span class="caption">{ran} of {days_span} nights</span></div>')
    return "".join(pieces)


def render_alpha_source(alpha: dict) -> str:
    if not alpha.get("available"):
        return "Source: nightly model runs · prices via yfinance · as of pending"
    return f"Source: nightly model runs · prices via yfinance · as of {html.escape(alpha['summary']['latest_trade_date'])}"


def render_persona_teaser(d: dict, day: str) -> str:
    """Index teaser: the night's strongest persona skews, linking to the
    full table on the day page."""
    rows = []
    for r in d["persona_delta"]:
        spec = r["spec_n"] or 0
        alloc = r["alloc_n"] or 0
        if spec + alloc >= 4:
            rows.append({"ticker": r["ticker"], "spec_n": spec, "alloc_n": alloc})
    # five most lopsided names, displayed as a gradient from
    # speculator-heavy down to allocator-heavy
    rows.sort(key=lambda r: (-abs(r["spec_n"] / (r["spec_n"] + r["alloc_n"]) - 0.5),
                             -(r["spec_n"] + r["alloc_n"])))
    rows = rows[:5]
    rows.sort(key=lambda r: -(r["spec_n"] - r["alloc_n"]))
    if not rows:
        return '<p class="dim">no persona split recorded for this night yet.</p>'
    return render_persona_split(rows, half=8, limit=5)


def render_index_page(d: dict, trends: dict, alpha: dict, day: str, days: list[str],
                      n_total_responses: int, con) -> tuple[str, str, str]:
    insight = compute_insight(con, day)
    score_stat = render_scoreboard_stat(alpha)
    content = f"""
<div class="dek-strip">{html.escape(DEK)}</div>

<div class="groupbox" id="flow">
  <div class="gtitle">Recommendation flow</div>
  {flow_caption(d, day)}
  {render_flow_table(d, day)}
  <p class="insight">{html.escape(insight)}</p>
  <div class="more"><a href="day/{html.escape(day)}.html#full-breakdown">Full breakdown…</a></div>
</div>

<div class="groupbox" id="scoreboard">
  <div class="gtitle">Scoreboard — nightly top-{alpha.get("top_n", 20)} basket vs QQQ</div>
  <div class="scoreboard">
    {render_plot(alpha, compact=True)}
    <div class="score-side">
      <div class="stat-frame">
        {score_stat}
        <div class="source">{render_alpha_source(alpha)}</div>
      </div>
      <a class="qbutton" href="alpha.html">Open full scoreboard…</a>
    </div>
  </div>
</div>

<div class="teaser-grid">
  <div class="groupbox" id="first-sightings">
    <div class="gtitle">First sightings</div>
    {render_first_sightings(trends["first_sightings"][:5], trends["providers"], compact=True)}
    <div class="more"><a href="trends.html#first-sightings">Full table…</a></div>
  </div>
  <div class="groupbox" id="consensus">
    <div class="gtitle">Consensus</div>
    {render_consensus(trends["consensus"][:5], trends["providers"], compact=True)}
    <div class="more"><a href="trends.html#consensus">Full table…</a></div>
  </div>
  <div class="groupbox" id="personas">
    <div class="gtitle">Who's asking — bullish mentions by persona</div>
    {render_persona_teaser(d, day)}
    <div class="more"><a href="day/{html.escape(day)}.html#persona-delta">Full table…</a></div>
  </div>
</div>

<div class="groupbox" id="record">
  <div class="gtitle">Record — one square per night (filled = panel ran, open = missed)</div>
  {render_pipeline(con)}
</div>

<details>
  <summary>Terms</summary>
  <div class="details-body">
    <p>Net means bullish mentions minus bearish mentions. Flow is the ranked push models gave tickers on the night shown. First sighting means the first night a ticker appeared in the logged panel. Consensus means more than one provider pushed the same ticker bullish. The who's-asking bars split a ticker's bullish mentions between the allocator (left of the axis) and the speculator (right).</p>
  </div>
</details>
"""
    page = page_shell(
        title=f"pythia: {day}",
        page="index",
        window_title=f"Pythia — Nightly Panel No. {len(days)} — {day}",
        toolbar=render_toolbar(day, days),
        dock=render_dock(day, days),
        content=content,
        statusbar=render_statusbar(d, len(days)),
    )
    return page, insight, score_stat


def render_main_page(d: dict, day: str, days: list[str], is_index: bool) -> str:
    root_prefix = "../" if not is_index else ""
    content = f"""
<div class="groupbox" id="flow">
  <div class="gtitle">Recommendation flow</div>
  {flow_caption(d, day)}
  {render_flow_table(d, day)}
</div>

<div class="groupbox" id="full-breakdown">
  <div class="gtitle">Full breakdown</div>
  <p class="intro prose">{html.escape(no_emdash(INTRO_TOP_MENTIONS))}</p>
  {render_top_mentions(d)}
</div>

<div class="groupbox" id="persona-delta">
  <div class="gtitle">Does it matter who's asking?</div>
  <p class="intro prose">{html.escape(no_emdash(INTRO_PERSONA_DELTA))}</p>
  {render_persona_delta(d)}
</div>

<div class="groupbox" id="samples">
  <div class="gtitle">See for yourself</div>
  <p class="intro prose">{html.escape(no_emdash(INTRO_SAMPLES))}</p>
  {render_samples(d)}
</div>
"""
    return page_shell(
        title=f"pythia: {day}",
        page="day",
        window_title=f"Pythia — Session {day}",
        toolbar=render_toolbar(day, days, root_prefix),
        dock=render_dock(day, days, root_prefix),
        content=content,
        statusbar=render_statusbar(d, len(days), root_prefix),
        root_prefix=root_prefix,
        description=f"what frontier AI models told people to buy on {day}",
        session=day,
    )


def render_trends_page(d: dict, trends: dict, days: list[str], n_total_responses: int) -> str:
    latest = days[0] if days else ""
    content = f"""
<div class="groupbox" id="rolling7">
  <div class="gtitle">Last 7 days — rolling window</div>
  {render_rolling_top(trends["top_7d"], "7 days")}
</div>
<div class="groupbox" id="rolling30">
  <div class="gtitle">Last 30 days — rolling window</div>
  {render_rolling_top(trends["top_30d"], "30 days")}
</div>
<div class="groupbox" id="alltime">
  <div class="gtitle">All time — cumulative window</div>
  {render_rolling_top(trends["top_all"], "all-time")}
</div>
<div class="groupbox" id="first-sightings">
  <div class="gtitle">First sightings — newest tickers by first night seen</div>
  {render_first_sightings(trends["first_sightings"], trends["providers"])}
</div>
<div class="groupbox" id="consensus">
  <div class="gtitle">Consensus — tickers with bullish flow from multiple providers</div>
  {render_consensus(trends["consensus"], trends["providers"])}
</div>
<div class="groupbox" id="days">
  <div class="gtitle">All nights — nightly panel index</div>
  {render_days_index(trends["days_index"])}
</div>
"""
    return page_shell(
        title="pythia: trends",
        page="trends",
        window_title="Pythia — Trends",
        toolbar=render_toolbar(latest, days),
        dock=render_dock(None, days),
        content=content,
        statusbar=render_statusbar(d, len(days)),
    )


def render_alpha_page(alpha: dict, d: dict, days: list[str]) -> str:
    latest = days[0] if days else ""
    content = f"""
<div class="groupbox" id="curve">
  <div class="gtitle">Cumulative basket and QQQ</div>
  {render_plot(alpha)}
  <div class="source">{render_alpha_source(alpha)}</div>
</div>
<div class="groupbox" id="headline">
  <div class="gtitle">Scoreboard</div>
  {render_scoreboard_stat(alpha)}
</div>
<div class="groupbox" id="definition">
  <div class="gtitle">Benchmark definition — what is being measured</div>
  <p class="dek">The signal date is the panel timestamp converted to the ET calendar date. For each signal date, the basket is the top 20 tickers by net score, equal weighted and unhedged. The entry is the next market session open, and the exit is that same session close. QQQ is measured over the same open to close session.</p>
  <p class="dek">If weekend or holiday signals point to the same next market session, only the last signal for that session is kept. That prevents duplicate panels from counting the same trade window more than once.</p>
  <p class="dek">Caveats: this is a paper benchmark with no execution costs or slippage. There is no look-ahead: the signal is timestamped before the next open, while prices are fetched after the session. The sample is still small. The basket is fixed at signal time, so later winners or deleted names are not added after the fact.</p>
</div>
<div class="groupbox" id="running-averages">
  <div class="gtitle">Running averages — session means and cumulative returns</div>
  <div class="scroll">{render_alpha_summary(alpha)}</div>
</div>
<div class="groupbox" id="daily-rows">
  <div class="gtitle">Daily rows — one row per benchmark session</div>
  <div class="scroll">{render_alpha_table(alpha)}</div>
</div>
"""
    return page_shell(
        title="pythia: scoreboard",
        page="alpha",
        window_title="Pythia — Scoreboard",
        toolbar=render_toolbar(latest, days),
        dock=render_dock(None, days),
        content=content,
        statusbar=render_statusbar(d, len(days)),
    )


def render_methodology_page(d: dict, days: list[str], preamble: str, assembled_on: str) -> str:
    why = (
        "Pythia measures the recommendation flow retail investors receive from "
        "frontier AI systems. People already ask these models what to buy. This "
        "site records the tickers named, the stance attached to each mention, "
        "and how the answer changes by persona."
    )
    night = (
        "Each night runs 10 questions through 2 personas and 3 configured model "
        "surfaces, for 60 responses when every call succeeds. Each model is "
        "invoked through its production agent harness: Claude Code for claude, "
        "the Codex CLI for gpt, and the google-genai SDK with Google Search "
        "grounding for gemini, with web and search tools available where the "
        "surface supports them. Consumer chat surfaces (chatgpt.com, claude.ai, "
        "gemini.google.com) are not yet measured."
    )
    assembly = (
        "A prompt is assembled as persona context, global preamble, then the "
        "question, asked verbatim. The preamble instructs the model to ground "
        "its answer in current market state and to prefix every ticker with $ "
        "so extraction is deterministic; compliance with the $ rule has been "
        "roughly 100% so far. The example below is the literal string sent to "
        "the model."
    )
    personas_note = (
        "The two personas bracket the spectrum of who plausibly asks an AI for "
        "investment advice. Together they measure how much a model changes its "
        "tune based on who it thinks is listening."
    )
    seeded_note = (
        "Some questions deliberately name tickers, mirroring real retail "
        "queries. The recommendation volume those names receive is part of the "
        "signal being measured, not a bias to scrub."
    )
    classification = (
        "Ticker extraction keys off $TICKER tokens. Each mention is then judged "
        "as bullish, bearish, neutral, or context by a smaller model. Uncertain "
        "labels are held back for review and excluded from public flow counts. "
        "Refusals and errored responses are counted in run totals and excluded "
        "from recommendation flow."
    )
    raw = (
        f"Raw rows live in the SQLite database, with gzipped traces for replay. "
        f"The source repository is https://{REPO_URL}."
    )
    content = f"""
<div class="groupbox" id="what">
  <div class="gtitle">What Pythia measures and why</div>
  <p class="prose">{html.escape(why)}</p>
</div>

<div class="groupbox" id="night-run">
  <div class="gtitle">How a night runs</div>
  <p class="prose intro">{html.escape(night)}</p>
  {render_model_configs(d)}
</div>

<div class="groupbox" id="assembly">
  <div class="gtitle">How a prompt is assembled</div>
  <p class="prose">{html.escape(assembly)}</p>
  <h3>Example: portfolio_01 x speculator</h3>
  <div class="scroll method-block"><pre>{html.escape(no_emdash(assembled_on))}</pre></div>
  <h3>Preamble</h3>
  <div class="scroll method-block"><pre>{html.escape(no_emdash("  " + preamble.replace(chr(10), chr(10) + "  ") if preamble else "missing"))}</pre></div>
</div>

<div class="groupbox" id="personas">
  <div class="gtitle">The 2 personas</div>
  <p class="prose">{html.escape(personas_note)}</p>
  <div class="scroll method-block"><pre>{html.escape(render_personas(d))}</pre></div>
</div>

<div class="groupbox" id="questions">
  <div class="gtitle">The 10 questions</div>
  <p class="prose">{html.escape(seeded_note)}</p>
  {render_prompts_html(d)}
</div>

<div class="groupbox" id="classification">
  <div class="gtitle">How mentions are classified</div>
  <p class="prose">{html.escape(classification)}</p>
</div>

<div class="groupbox" id="caveats">
  <div class="gtitle">Caveats</div>
  <p class="prose">The scoreboard is a paper benchmark. It ignores execution costs, spread, taxes, capacity, and market impact.</p>
  <p class="prose">The sample is small. It is useful as a public measurement feed, not proof of durable alpha.</p>
  <p class="prose">This dashboard is public, so models with search tools can in principle read it. We note that feedback loop rather than pretend it cannot exist.</p>
  <p class="prose">Recommendation flow measures what models say, not what anyone should buy. It is not investment advice.</p>
</div>

<div class="groupbox" id="raw-data">
  <div class="gtitle">Raw data</div>
  <p class="prose">{html.escape(raw)}</p>
</div>
"""
    return page_shell(
        title="pythia: methodology",
        page="methodology",
        window_title="Pythia — Methodology",
        toolbar=render_toolbar(days[0] if days else "", days),
        dock=render_dock(None, days),
        content=content,
        statusbar=render_statusbar(d, len(days)),
    )

def main() -> int:
    if not DB_PATH.exists():
        print(f"db missing: {DB_PATH}")
        return 1
    out_dir = OUT_PATH.parent
    day_dir = out_dir / "day"
    out_dir.mkdir(parents=True, exist_ok=True)
    day_dir.mkdir(parents=True, exist_ok=True)
    if ASSETS_DIR.exists():
        shutil.copytree(ASSETS_DIR, out_dir / "assets", dirs_exist_ok=True)
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    (out_dir / "assets" / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        days = list_clean_days(con)
        if not days:
            placeholder = page_shell(
                title="pythia",
                page="index",
                window_title="Pythia",
                toolbar="",
                dock="",
                content='<div class="groupbox"><div class="gtitle">Status</div><p class="prose">no panels yet. pythia is collecting.</p></div>',
                statusbar='<div class="statusbar"><div class="status-cell stretch">no panels yet</div><div class="sizegrip" aria-hidden="true"></div></div>',
            )
            OUT_PATH.write_text(placeholder, encoding="utf-8")
            print(f"wrote {OUT_PATH} (no panels yet)")
            return 0

        for day in days:
            d_day = fetch(con, day=day)
            page = render_main_page(d_day, day, days, is_index=False)
            day_path = day_dir / f"{day}.html"
            day_path.write_text(page, encoding="utf-8")
            print(f"wrote {day_path}  ({len(page)} bytes)")

        d = fetch(con, day=None)
        trends = fetch_trends(con)
        alpha = fetch_alpha(con)
        n_total_responses = sum(r.get("n_responses") or 0 for r in trends["days_index"])

        latest = days[0]
        d_latest = fetch(con, day=latest)
        index_page, insight, score_stat = render_index_page(
            d_latest, trends, alpha, latest, days, n_total_responses, con
        )
        OUT_PATH.write_text(index_page, encoding="utf-8")
        print(f"wrote {OUT_PATH}  ({len(index_page)} bytes)  [index = {latest}, focused]")
        print(f"insight: {insight}")
        print(f"scoreboard: {score_stat}")

        trends_page = render_trends_page(d, trends, days, n_total_responses)
        OUT_TRENDS_PATH.write_text(trends_page, encoding="utf-8")
        print(f"wrote {OUT_TRENDS_PATH}  ({len(trends_page)} bytes)")

        alpha_page = render_alpha_page(alpha, d, days)
        OUT_ALPHA_PATH.write_text(alpha_page, encoding="utf-8")
        print(f"wrote {OUT_ALPHA_PATH}  ({len(alpha_page)} bytes)")

        preamble = load_preamble()
        example_prompt = next((p for p in d["prompts"] if p["id"] == "portfolio_01"),
                              d["prompts"][0] if d["prompts"] else None)
        example_persona = next((p for p in d["personas"] if p["id"] == "speculator"),
                               d["personas"][0] if d["personas"] else None)
        if example_prompt and example_persona and preamble:
            assembled_on = assemble_example(
                example_persona["description"], example_prompt["text"], preamble, "on"
            )
        else:
            assembled_on = "unavailable: db missing prompts or personas"
        methodology_page = render_methodology_page(d, days, preamble, assembled_on)
        OUT_METHODOLOGY_PATH.write_text(methodology_page, encoding="utf-8")
        print(f"wrote {OUT_METHODOLOGY_PATH}  ({len(methodology_page)} bytes)")
        old_prompts_path = out_dir / "prompts.html"
        if old_prompts_path.exists():
            old_prompts_path.unlink()
            print(f"removed {old_prompts_path}")
    finally:
        con.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
