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
speculator and a family-office allocator. delta shows which names the
models route toward one audience more than the other."""


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
                   COUNT(DISTINCT DATE(ru.started_at)) AS days_seen
            FROM mentions m
            JOIN responses r ON m.response_id = r.id
            JOIN runs ru ON r.run_id = ru.id
            WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0
              AND DATE(ru.started_at) >= DATE('now', ?)
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
        SELECT m.ticker, MIN(DATE(ru.started_at)) AS first_seen,
               MAX(DATE(ru.started_at)) AS last_seen,
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
               COUNT(DISTINCT DATE(ru.started_at)) AS days_seen
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
        SELECT DATE(ru.started_at) AS day,
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
            SELECT DATE(ru.started_at) AS day, m.ticker,
                   SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                            WHEN m.sentiment_hint='bearish' THEN -1
                            ELSE 0 END) AS net,
                   ROW_NUMBER() OVER (PARTITION BY DATE(ru.started_at)
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
            SELECT DISTINCT DATE(started_at) AS day
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
        day_pred = "AND DATE(ru.started_at) = ?"
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
            "FROM runs WHERE is_clean=1 AND DATE(started_at)=? "
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
        WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0 {day_pred}
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
        ORDER BY r.id DESC
        LIMIT 6
        """,
        day_params,
    ).fetchall()

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


def bar(value: int, max_value: int, width: int = 24) -> str:
    if max_value <= 0:
        return ""
    n = round(width * value / max_value)
    return "█" * n + "░" * (width - n)


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
            SELECT DISTINCT DATE(started_at) AS day FROM runs
            WHERE is_clean = 1 AND DATE(started_at) >= DATE('now', ?)
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
        SELECT m.ticker, DATE(ru.started_at) AS day,
               SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                        WHEN m.sentiment_hint='bearish' THEN -1
                        ELSE 0 END) AS net
        FROM mentions m
        JOIN responses r ON m.response_id = r.id
        JOIN runs ru ON r.run_id = ru.id
        WHERE r.error IS NULL AND ru.is_clean = 1 AND m.needs_review = 0
          AND m.ticker IN ({placeholders})
          AND DATE(ru.started_at) >= DATE('now', ?)
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
    left, right, top, bottom = 12, 72, 20, 28
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
    color_var = "var(--up)" if latest_model >= 0 else "var(--down)"
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
    baseline_y = y_at(lo)
    label_x = min(width - 4, x_at(len(model_values) - 1) + 8)
    # direct labels sit at each line's end; push them apart when the lines
    # converge so the two words never overprint
    model_label_y = y_at(latest_model) + 4
    qqq_label_y = y_at(qqq_values[-1]) + 4
    if abs(model_label_y - qqq_label_y) < 14:
        if model_label_y <= qqq_label_y:
            qqq_label_y = model_label_y + 14
        else:
            qqq_label_y = model_label_y - 14
    aria = (
        f"cumulative top-{n} basket {fmt_signed_pct(latest_model)} and "
        f"cumulative excess versus QQQ {fmt_signed_pct(latest_excess)}"
    )
    return f"""<svg class="alpha-svg" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(aria)}" style="--chart-models: {color_var}">
  {"".join(grid)}
  <line x1="{left}" y1="{baseline_y:.1f}" x2="{width - right}" y2="{baseline_y:.1f}" class="baseline"/>
  <polyline points="{qqq_points}" fill="none" class="qqq-line"/>
  <polyline points="{model_points}" fill="none" class="models-line"/>
  <text x="{label_x:.1f}" y="{model_label_y:.1f}" class="direct-label models-label">models</text>
  <text x="{label_x:.1f}" y="{qqq_label_y:.1f}" class="direct-label">QQQ</text>
</svg>"""


def indent2(text: str) -> str:
    return textwrap.indent(text, "  ")


def no_emdash(text: str) -> str:
    return (text or "").replace("\u2014", "-")


def signed_span(n: int) -> str:
    cls = "up" if n > 0 else "down" if n < 0 else "zero"
    return f'<span class="{cls}">{n:+d}</span>'


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
        "<th class=\"num\">net</th><th class=\"num\">n</th>"
        "<th class=\"num\">lead position</th><th>bar</th><th>14d sparkline</th>"
        "</tr></thead><tbody>",
    ]
    for i, r in enumerate(rows, start=1):
        net = r["net"] or 0
        cls = "up" if net > 0 else "down" if net < 0 else "zero"
        out.append(
            "<tr>"
            f'<td class="num">{i}</td>'
            f'<td><strong>${html.escape(r["ticker"])}</strong></td>'
            f'<td class="num">{r["bull"] or 0}</td>'
            f'<td class="num">{r["bear"] or 0}</td>'
            f'<td class="num">{r["neut"] or 0}</td>'
            f'<td class="num">{r["ctx"] or 0}</td>'
            f'<td class="num">{signed_span(net)}</td>'
            f'<td class="num">{r["n"] or 0}</td>'
            f'<td class="num">{(r["avg_pos"] or 0):.1f}</td>'
            f'<td class="bar {cls}">{single_bar(net, max_abs_net)}</td>'
            f'<td class="spark">{html.escape(r.get("sparkline") or "")}</td>'
            "</tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def render_persona_delta(d: dict) -> str:
    rows = d["persona_delta"]
    if not rows:
        return '<p class="dim">no persona split was recorded for this night.</p>'
    out = [
        '<div class="scroll"><table class="data-table">',
        "<thead><tr><th>ticker</th><th class=\"num\">speculator</th>"
        "<th class=\"num\">allocator</th><th class=\"num\">delta</th>"
        "</tr></thead><tbody>",
    ]
    for r in rows[:20]:
        spec = r["spec_n"] or 0
        alloc = r["alloc_n"] or 0
        delta = spec - alloc
        out.append(
            "<tr>"
            f'<td>${html.escape(r["ticker"])}</td>'
            f'<td class="num">{spec}</td>'
            f'<td class="num">{alloc}</td>'
            f'<td class="num">{signed_span(delta)}</td>'
            "</tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


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
        "<th class=\"num\">bull</th><th class=\"num\">bear</th><th class=\"num\">net</th>",
        f"<th>bar</th><th class=\"spark\">{html.escape(spark_header)}</th>",
        "</tr></thead><tbody>",
    ]
    for i, r in enumerate(rows, start=1):
        net = r.get("net") or 0
        cls = signed_class(net)
        out.append(
            "<tr>"
            f"<td class=\"num\">{i}</td>"
            f"<td><strong>${html.escape(r['ticker'])}</strong></td>"
            f"<td class=\"num\">{r.get('bull') or 0}</td>"
            f"<td class=\"num\">{r.get('bear') or 0}</td>"
            f"<td class=\"num\">{signed_int_span(net)}</td>"
            f"<td class=\"bar {cls}\">{html.escape(single_bar(net, max_abs_net))}</td>"
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



BASE_CSS = """/* BASE_CSS */
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
  --paper: oklch(0.96 0.008 90);
  --ink: oklch(0.24 0.012 90);
  --dim: oklch(0.47 0.012 90);
  --faint: oklch(0.87 0.008 90);
  --accent: oklch(0.60 0.12 70);
  --up: oklch(0.48 0.10 245);
  --down: oklch(0.48 0.13 20);
  --spark: oklch(0.70 0.010 90);
  --lh: 1.5rem;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --paper: oklch(0.19 0.008 90);
    --ink: oklch(0.89 0.010 90);
    --dim: oklch(0.68 0.010 90);
    --faint: oklch(0.30 0.008 90);
    --accent: oklch(0.66 0.09 70);
    --up: oklch(0.68 0.08 245);
    --down: oklch(0.68 0.10 20);
    --spark: oklch(0.45 0.010 90);
  }
}
* { box-sizing: border-box; }
html { background: var(--paper); color: var(--ink); font-variant-numeric: tabular-nums lining-nums; }
body {
  margin: 0 auto;
  padding: calc(var(--lh) * 2) 2ch calc(var(--lh) * 3);
  max-width: 100ch;
  max-width: calc(min(100ch, round(down, 100%, 1ch)));
  background: var(--paper);
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 14px;
  line-height: var(--lh);
}
::selection { background: var(--accent); color: var(--paper); }
a { color: var(--accent); text-decoration: none; text-underline-offset: 0.25em; }
a:hover { text-decoration: underline; }
a:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 0.25rem; }
header, nav, main, section, footer, pre, table, p, h1, h2, h3 { margin: 0; }
pre { white-space: pre-wrap; word-break: normal; overflow-wrap: anywhere; font: inherit; }
pre.tbl { white-space: pre; overflow-wrap: normal; }
section { margin-top: calc(var(--lh) * 3); padding-top: calc(var(--lh) * 0.5); border-top: 2px solid var(--accent); }
h1, .wordmark { font-size: 21px; line-height: var(--lh); font-weight: 700; letter-spacing: 0; }
h2 { font-size: 21px; line-height: var(--lh); font-weight: 700; letter-spacing: 0; }
h3 { margin-top: calc(var(--lh) * 1.5); font-size: 14px; line-height: var(--lh); font-weight: 700; }
.label, th, .stamp, .source, .meta-line, .nav, summary, .chart-title {
  font-size: 12px;
  line-height: var(--lh);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.dim, .intro, .source, .meta-line, .caption, .chart-dim { color: var(--dim); }
.masthead { display: grid; grid-template-columns: minmax(0, 1fr) max-content; gap: 4ch; padding-bottom: var(--lh); border-bottom: 1px solid var(--faint); }
.dek { margin-top: var(--lh); max-width: 72ch; color: var(--dim); }
.stamp { text-align: right; color: var(--dim); }
.stamp strong { color: var(--accent); font-weight: 700; }
.nav { display: flex; flex-wrap: wrap; gap: 0 2ch; align-items: center; margin-top: var(--lh); padding: calc(var(--lh) * 0.5) 0; border-top: 1px solid var(--faint); border-bottom: 1px solid var(--faint); }
.nav a { color: var(--accent); }
.day-nav { display: grid; grid-template-columns: 3ch minmax(0, 1fr) 3ch; gap: 1ch; align-items: center; }
.day-nav a, .day-nav span { display: inline-block; }
.day-nav .day-strip { display: flex; justify-content: center; gap: 1ch; min-width: 0; overflow: hidden; white-space: nowrap; }
.day-nav .day-current { color: var(--accent); font-weight: 700; }
.day-nav .dim { color: var(--dim); }
.flow-table, .data-table, .alpha-table { width: 100%; border-collapse: collapse; font: inherit; }
th { color: var(--ink); font-weight: 700; border-bottom: 1px solid var(--faint); }
th, td { padding: calc(var(--lh) * 0.5) 1ch calc(var(--lh) * 0.5) 0; vertical-align: top; border-bottom: 1px solid var(--faint); text-align: left; white-space: nowrap; }
td.num, th.num { text-align: right; }
.flow-table .ticker { font-weight: 700; }
.flow-table .bar { width: 30ch; font-weight: 700; white-space: nowrap; }
.spark { color: var(--spark); white-space: nowrap; }
.up { color: var(--up); }
.down { color: var(--down); }
.zero { color: var(--dim); }
.insight { margin-top: var(--lh); max-width: 72ch; }
.scoreboard { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 0.6fr); gap: 4ch; align-items: end; }
.stat-num { font-size: 21px; line-height: var(--lh); font-weight: 700; }
.stat-rest { margin-top: calc(var(--lh) * 0.5); max-width: 44ch; color: var(--dim); }
.source { margin-top: var(--lh); color: var(--dim); }
.teaser-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 4ch; }
.scroll { overflow-x: auto; max-width: 100%; }
.more { margin-top: var(--lh); color: var(--dim); }
.provider-head { display: inline-flex; width: 4ch; align-items: center; justify-content: center; vertical-align: middle; }
.provider-icon { width: 16px; height: 16px; display: block; opacity: 0.95; filter: sepia(12%) saturate(220%) hue-rotate(5deg) brightness(42%); }
.provider-head, .provider-icon { color: var(--ink); fill: currentColor; }
.provider-icon path { fill: currentColor; }
.bear { color: var(--dim); }
.bear-zero { color: var(--faint); }
.pipeline { display: flex; flex-wrap: wrap; gap: 1ch; align-items: center; }
.pipeline-square { display: inline-flex; width: 1.5ch; height: var(--lh); align-items: center; justify-content: center; color: var(--dim); text-decoration: none; }
.pipeline-square.clean { color: var(--ink); }
.pipeline-square.excluded { color: var(--dim); }
.pipeline-square.missed { color: var(--faint); }
details { margin-top: calc(var(--lh) * 2); padding-top: calc(var(--lh) * 0.5); border-top: 1px solid var(--faint); }
summary { color: var(--accent); cursor: pointer; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary::before { content: '+ '; }
details[open] summary::before { content: '- '; }
details .details-body { margin-top: var(--lh); max-width: 72ch; color: var(--dim); }
.alpha-svg { width: 100%; height: auto; display: block; }
.alpha-svg text { font: 12px var(--font-mono); letter-spacing: 0.08em; text-transform: uppercase; fill: var(--dim); }
.alpha-svg .grid { stroke: var(--faint); stroke-width: 1; vector-effect: non-scaling-stroke; }
.alpha-svg .baseline { stroke: var(--ink); stroke-width: 1; vector-effect: non-scaling-stroke; }
.alpha-svg .zero-line { stroke: var(--dim); stroke-width: 1.2; vector-effect: non-scaling-stroke; }
.alpha-svg .models-line { stroke: var(--chart-models, var(--up)); stroke-width: 2; vector-effect: non-scaling-stroke; }
.alpha-svg .qqq-line { stroke: var(--dim); stroke-width: 1.4; vector-effect: non-scaling-stroke; }
.alpha-svg .direct-label { font-weight: 700; fill: var(--ink); }
.alpha-svg .models-label { fill: var(--chart-models, var(--up)); }
footer { margin-top: calc(var(--lh) * 4); padding-top: var(--lh); border-top: 1px solid var(--faint); color: var(--dim); }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (prefers-color-scheme: dark) {
  .provider-icon { color: var(--ink); filter: invert(94%) sepia(8%) saturate(120%) hue-rotate(5deg) brightness(94%); }
}
@media (max-width: 60ch) {
  body { padding-left: 1ch; padding-right: 1ch; }
  .masthead { grid-template-columns: 1fr; gap: var(--lh); }
  .stamp { text-align: left; }
  .scoreboard, .teaser-grid { grid-template-columns: minmax(0, 1fr); }
  .flow-table .spark-col, .flow-table .spark { display: none; }
  .flow-table .bar { width: 18ch; }
  th, td { padding-right: 0.5ch; }
}
/* phase2c */
.prose { max-width: 72ch; }
.method-block { margin-top: var(--lh); }
.prompt-list { display: grid; gap: var(--lh); max-width: 72ch; }
.prompt-item { padding-bottom: var(--lh); border-bottom: 1px solid var(--faint); }
.prompt-id { color: var(--accent); font-weight: 700; }
.exhibit { margin: var(--lh) 0 0; padding-top: calc(var(--lh) * 0.5); border-top: 1px solid var(--faint); }
.exhibit-question { max-width: 72ch; color: var(--dim); }
.exhibit-body { max-width: 72ch; color: var(--ink); }
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
<meta name="theme-color" content="oklch(0.96 0.008 90)">
<link rel="icon" type="image/svg+xml" href="{root_prefix}assets/favicon.svg">
<style>
{base_css}
</style>
</head>
<body>
{masthead}
{nav}
{day_nav}
<main>
{content}
</main>
{footer}
</body>
</html>
"""

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" fill="oklch(0.96 0.008 90)"/>
<path d="M14 50V14h21c9 0 15 5 15 14s-6 14-15 14H26v8H14Zm12-19h8c3 0 5-1 5-3s-2-3-5-3h-8v6Z" fill="oklch(0.60 0.12 70)"/>
</svg>
"""

DESCRIPTIONS = {
    "index": "nightly AI recommendation flow, scoreboard, first sightings, and consensus.",
    "day": "full nightly pythia panel artifact with ticker flow, model samples, and prompts.",
    "trends": "rolling pythia recommendation flow, first sightings, and provider consensus.",
    "alpha": "pythia paper scoreboard comparing the top-20 basket with QQQ.",
    "methodology": "pythia methodology, prompts, personas, and model surfaces.",
}


def page_shell(title: str, page: str, masthead: str, nav: str, day_nav: str,
               content: str, footer: str, root_prefix: str = "",
               description: str | None = None) -> str:
    desc = description or DESCRIPTIONS.get(page, DESCRIPTIONS["index"])
    return PAGE_TMPL.format(
        title=html.escape(title),
        description=html.escape(desc),
        og_title=html.escape(title),
        root_prefix=html.escape(root_prefix),
        base_css=BASE_CSS.replace("assets/", f"{root_prefix}assets/"),
        masthead=masthead,
        nav=nav,
        day_nav=day_nav,
        content=content,
        footer=footer,
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


def stamp_block(d: dict, panel_no: int) -> str:
    latest = d.get("latest_run")
    counts = d.get("counts")
    ok = counts["n_responses_ok"] if counts else 0
    total = ok + (counts["n_responses_fail"] if counts else 0)
    finished = latest["finished_at"] if latest else None
    started = latest["started_at"] if latest else None
    stamp_time = fmt_et(finished or started)
    return (
        '<div class="stamp">'
        f'<div><strong>NIGHTLY PANEL No. {panel_no}</strong></div>'
        f'<div>{html.escape(stamp_time)}</div>'
        f'<div>{ok}/{total} responses</div>'
        '</div>'
    )


def render_masthead(d: dict, panel_no: int, page_name: str | None = None, compact: bool = False) -> str:
    title = "PYTHIA" if not page_name else f"PYTHIA / {page_name}"
    dek = (
        "Every night we ask Claude, GPT-5.5 and Gemini what stocks to buy.<br>"
        "We log every answer."
    )
    dek_html = "" if compact else f'<div class="dek">{dek}</div>'
    return (
        '<header class="masthead">'
        f'<div><div class="wordmark">{html.escape(title)}</div>{dek_html}</div>'
        f'{stamp_block(d, panel_no)}'
        '</header>'
    )


def render_main_nav(root_prefix: str = "") -> str:
    links = [
        ("index", "index.html"),
        ("trends", "trends.html"),
        ("scoreboard", "alpha.html"),
        ("methodology", "methodology.html"),
    ]
    return '<nav class="nav">' + "".join(
        f'<a href="{html.escape(root_prefix + href)}">{label}</a>'
        for label, href in links
    ) + "</nav>"


def render_footer(root_prefix: str = "") -> str:
    return (
        '<footer>'
        f'<a href="{html.escape(root_prefix)}methodology.html">methodology</a> · '
        f'<a href="https://{html.escape(REPO_URL)}">raw data</a> · '
        'not investment advice; a public measurement experiment'
        '</footer>'
    )

# ───────────────────────── main ─────────────────────────



def _day_href(day: str, is_index: bool) -> str:
    return f"day/{day}.html" if is_index else f"{day}.html"


def render_day_nav(current: str, days: list[str], is_index: bool) -> str:
    """Render at most nine days, centered on the current day."""
    strip_len = 9
    try:
        idx = days.index(current)
    except ValueError:
        idx = 0
    start = max(0, idx - strip_len // 2)
    end = min(len(days), start + strip_len)
    start = max(0, end - strip_len)
    visible_asc = list(reversed(days[start:end]))

    def short(d: str) -> str:
        return d[5:] if len(d) >= 10 else d

    def chip(d: str) -> str:
        if d == current:
            return f'<span class="day-current">[{html.escape(short(d))}]</span>'
        return f'<a href="{html.escape(_day_href(d, is_index))}" title="{html.escape(d)}">{html.escape(short(d))}</a>'

    older = days[idx + 1] if idx + 1 < len(days) else None
    newer = days[idx - 1] if idx > 0 else None
    older_html = (
        f'<a href="{html.escape(_day_href(older, is_index))}" title="{html.escape(older)}">◀</a>'
        if older else '<span class="dim">◀</span>'
    )
    newer_html = (
        f'<a href="{html.escape(_day_href(newer, is_index))}" title="{html.escape(newer)}">▶</a>'
        if newer else '<span class="dim">▶</span>'
    )
    return (
        '<nav class="nav day-nav">'
        f'{older_html}<span class="day-strip">'
        + "".join(chip(d) for d in visible_asc)
        + f'</span>{newer_html}</nav>'
    )


def single_bar(net: int, max_abs: int, width: int = 24) -> str:
    if max_abs <= 0:
        return "░" * width
    n = max(1 if net else 0, round(width * abs(net) / max_abs))
    return "█" * n + "░" * (width - n)


def signed_int(n: int) -> str:
    return f"{n:+d}"


def render_flow_table(d: dict, day: str) -> str:
    rows = d["top_mentions"][:15]
    if not rows:
        return '<p class="dim">no panel data for this night yet.</p>'
    max_abs_net = max((abs(r["net"] or 0) for r in rows), default=1) or 1
    out = [
        '<table class="flow-table">',
        '<thead><tr><th>ticker</th><th class="num">net</th><th>bar</th><th class="spark-col">14d</th></tr></thead><tbody>',
    ]
    for r in rows:
        net = r["net"] or 0
        cls = "up" if net > 0 else "down" if net < 0 else "zero"
        out.append(
            '<tr>'
            f'<td class="ticker">${html.escape(r["ticker"])}</td>'
            f'<td class="num {cls}">{signed_int(net)}</td>'
            f'<td class="bar {cls}">{single_bar(net, max_abs_net)}</td>'
            f'<td class="spark spark-col">{html.escape(r.get("sparkline") or "")}</td>'
            '</tr>'
        )
    out.append('</tbody></table>')
    return "".join(out)


def compute_insight(con, latest_day: str) -> str:
    rows = [dict(r) for r in con.execute(
        """
        WITH ticker_days AS (
          SELECT m.ticker, DATE(ru.started_at) AS day,
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
        clauses.append(f"{joined} entered the flow for the first time tonight")

    leaders = [dict(r) for r in con.execute(
        """
        SELECT day, ticker, net FROM (
            SELECT DATE(ru.started_at) AS day, m.ticker,
                   SUM(CASE WHEN m.sentiment_hint='bullish' THEN 1
                            WHEN m.sentiment_hint='bearish' THEN -1
                            ELSE 0 END) AS net,
                   ROW_NUMBER() OVER (PARTITION BY DATE(ru.started_at)
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
        clauses.append(f"${lead['ticker']} leads tonight's flow at {signed_int(lead['net'] or 0)}")
    if not clauses:
        clauses.append("the panel logged no positive flow tonight")
    return "; ".join(clauses) + "."


def render_scoreboard_stat(alpha: dict) -> str:
    if not alpha.get("available"):
        return '<p class="stat-rest">scoreboard waiting for price data.</p>'
    s = alpha["summary"]
    excess = s["cum_top_vs_qqq"]
    cls = "up" if excess >= 0 else "down"
    caveat = "; not yet statistically significant" if s["n_days"] < 60 else ""
    return (
        f'<div class="stat-num {cls}">{html.escape(fmt_signed_pct(excess))} vs QQQ</div>'
        f'<p class="stat-rest">cumulative excess of the nightly top-{alpha["top_n"]} '
        f"basket over QQQ across {s['n_days']} sessions, next open to close"
        f"{caveat}.</p>"
    )


def render_pipeline(con, days_span: int = 25) -> str:
    today = date.today()
    dates = [(today - timedelta(days=i)).isoformat() for i in reversed(range(days_span))]
    states = {d: {"clean": False, "excluded": False} for d in dates}
    for r in con.execute(
        """
        SELECT DATE(started_at) AS day,
               MAX(CASE WHEN is_clean=1 THEN 1 ELSE 0 END) AS has_clean,
               MAX(CASE WHEN is_clean=0 THEN 1 ELSE 0 END) AS has_excluded
        FROM runs
        WHERE DATE(started_at) BETWEEN ? AND ?
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
            pieces.append(f'<a class="pipeline-square clean" href="day/{html.escape(d)}.html" title="{html.escape(d)}">■</a>')
        elif st["excluded"]:
            pieces.append(f'<span class="pipeline-square excluded" title="{html.escape(d)}">◧</span>')
        else:
            pieces.append(f'<span class="pipeline-square missed" title="{html.escape(d)}">□</span>')
    pieces.append(f'<span class="caption">{ran} of {days_span} nights</span></div>')
    return "".join(pieces)


def render_alpha_source(alpha: dict) -> str:
    if not alpha.get("available"):
        return "Source: nightly model runs · prices via yfinance · as of pending"
    return f"Source: nightly model runs · prices via yfinance · as of {html.escape(alpha['summary']['latest_trade_date'])}"


def render_index_page(d: dict, trends: dict, alpha: dict, day: str, days: list[str],
                      n_total_responses: int, con) -> tuple[str, str, str]:
    insight = compute_insight(con, day)
    score_stat = render_scoreboard_stat(alpha)
    content = f"""
<section id="flow">
  <div class="label">TONIGHT'S FLOW · {html.escape(day)} · net = bullish − bearish mentions across 60 responses</div>
  {render_flow_table(d, day)}
  <p class="insight">{html.escape(insight)}</p>
</section>

<section id="scoreboard">
  <div class="label">SCOREBOARD</div>
  <div class="scoreboard">
    {render_alpha_svg(alpha, compact=True)}
    <div>
      {score_stat}
      <div class="source">{render_alpha_source(alpha)}</div>
      <div class="more"><a href="alpha.html">full scoreboard</a></div>
    </div>
  </div>
</section>

<div class="teaser-grid">
  <section id="first-sightings">
    <h2>FIRST SIGHTINGS</h2>
    {render_first_sightings(trends["first_sightings"][:5], trends["providers"], compact=True)}
    <div class="more"><a href="trends.html#first-sightings">full table</a></div>
  </section>
  <section id="consensus">
    <h2>CONSENSUS</h2>
    {render_consensus(trends["consensus"][:5], trends["providers"], compact=True)}
    <div class="more"><a href="trends.html#consensus">full table</a></div>
  </section>
</div>

<section id="pipeline">
  <h2>PIPELINE</h2>
  {render_pipeline(con)}
</section>

<details>
  <summary>terms</summary>
  <div class="details-body">
    <p>net means bullish mentions minus bearish mentions. flow is the ranked push models gave tickers tonight. first sighting means the first night a ticker appeared in the logged panel. consensus means more than one provider pushed the same ticker bullish.</p>
  </div>
</details>
"""
    page = page_shell(
        title=f"pythia: {day}",
        page="index",
        masthead=render_masthead(d, len(days)),
        nav=render_main_nav(),
        day_nav=render_day_nav(day, days, is_index=True),
        content=content,
        footer=render_footer(),
    )
    return page, insight, score_stat


def render_main_page(d: dict, day: str, days: list[str], is_index: bool) -> str:
    root_prefix = "../" if not is_index else ""
    content = f"""
<section id="flow">
  <div class="label">TONIGHT'S FLOW · {html.escape(day)} · net = bullish − bearish mentions across 60 responses</div>
  {render_flow_table(d, day)}
</section>

<section id="full-breakdown">
  <h2>FULL BREAKDOWN</h2>
  <p class="intro prose">{html.escape(no_emdash(INTRO_TOP_MENTIONS))}</p>
  {render_top_mentions(d)}
</section>

<section id="persona-delta">
  <h2>DOES IT MATTER WHO'S ASKING?</h2>
  <p class="intro prose">{html.escape(no_emdash(INTRO_PERSONA_DELTA))}</p>
  {render_persona_delta(d)}
</section>

<section id="samples">
  <h2>SEE FOR YOURSELF</h2>
  <p class="intro prose">{html.escape(no_emdash(INTRO_SAMPLES))}</p>
  {render_samples(d)}
</section>
"""
    return page_shell(
        title=f"pythia: {day}",
        page="day",
        masthead=render_masthead(d, len(days), page_name=day, compact=True),
        nav=render_main_nav(root_prefix),
        day_nav=render_day_nav(day, days, is_index),
        content=content,
        footer=render_footer(root_prefix),
        root_prefix=root_prefix,
        description=f"what frontier AI models told people to buy on {day}",
    )


def render_trends_page(d: dict, trends: dict, days: list[str], n_total_responses: int) -> str:
    content = f"""
<section id="rolling7">
  <h2>LAST 7 DAYS</h2>
  <div class="label">ROLLING WINDOW</div>
  {render_rolling_top(trends["top_7d"], "7 days")}
</section>
<section id="rolling30">
  <h2>LAST 30 DAYS</h2>
  <div class="label">ROLLING WINDOW</div>
  {render_rolling_top(trends["top_30d"], "30 days")}
</section>
<section id="alltime">
  <h2>ALL TIME</h2>
  <div class="label">CUMULATIVE WINDOW</div>
  {render_rolling_top(trends["top_all"], "all-time")}
</section>
<section id="first-sightings">
  <h2>FIRST SIGHTINGS</h2>
  <div class="label">NEWEST TICKERS BY FIRST NIGHT SEEN</div>
  {render_first_sightings(trends["first_sightings"], trends["providers"])}
</section>
<section id="consensus">
  <h2>CONSENSUS</h2>
  <div class="label">TICKERS WITH BULLISH FLOW FROM MULTIPLE PROVIDERS</div>
  {render_consensus(trends["consensus"], trends["providers"])}
</section>
<section id="days">
  <h2>ALL NIGHTS</h2>
  <div class="label">NIGHTLY PANEL INDEX</div>
  {render_days_index(trends["days_index"])}
</section>
"""
    return page_shell(
        title="pythia: trends",
        page="trends",
        masthead=render_masthead(d, len(days), page_name="trends", compact=True),
        nav=render_main_nav(),
        day_nav="",
        content=content,
        footer=render_footer(),
    )


def render_alpha_page(alpha: dict, d: dict, days: list[str]) -> str:
    chart = (
        render_alpha_svg(alpha)
        if alpha.get("available")
        else '<p class="dim">no scoreboard data yet; the first benchmark session lands after the next market open.</p>'
    )
    content = f"""
<section id="curve">
  <div class="label">CUMULATIVE BASKET AND QQQ</div>
  {chart}
  <div class="source">{render_alpha_source(alpha)}</div>
</section>
<section id="headline">
  <h2>SCOREBOARD</h2>
  {render_scoreboard_stat(alpha)}
</section>
<section id="definition">
  <h2>BENCHMARK DEFINITION</h2>
  <div class="label">WHAT IS BEING MEASURED</div>
  <p class="dek">The signal date is the panel timestamp converted to the ET calendar date. For each signal date, the basket is the top 20 tickers by net score, equal weighted and unhedged. The entry is the next market session open, and the exit is that same session close. QQQ is measured over the same open to close session.</p>
  <p class="dek">If weekend or holiday signals point to the same next market session, only the last signal for that session is kept. That prevents duplicate panels from counting the same trade window more than once.</p>
  <p class="dek">Caveats: this is a paper benchmark with no execution costs or slippage. There is no look-ahead: the signal is timestamped before the next open, while prices are fetched after the session. The sample is still small. The basket is fixed at signal time, so later winners or deleted names are not added after the fact.</p>
</section>
<section id="running-averages">
  <h2>RUNNING AVERAGES</h2>
  <div class="label">SESSION MEANS AND CUMULATIVE RETURNS</div>
  <div class="scroll">{render_alpha_summary(alpha)}</div>
</section>
<section id="daily-rows">
  <h2>DAILY ROWS</h2>
  <div class="label">ONE ROW PER BENCHMARK SESSION</div>
  <div class="scroll">{render_alpha_table(alpha)}</div>
</section>
"""
    return page_shell(
        title="pythia: scoreboard",
        page="alpha",
        masthead=render_masthead(d, len(days), page_name="scoreboard", compact=True),
        nav=render_main_nav(),
        day_nav="",
        content=content,
        footer=render_footer(),
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
<section id="what">
  <h2>WHAT PYTHIA MEASURES AND WHY</h2>
  <p class="prose">{html.escape(why)}</p>
</section>

<section id="night-run">
  <h2>HOW A NIGHT RUNS</h2>
  <p class="prose">{html.escape(night)}</p>
  {render_model_configs(d)}
</section>

<section id="assembly">
  <h2>HOW A PROMPT IS ASSEMBLED</h2>
  <p class="prose">{html.escape(assembly)}</p>
  <h3>example: portfolio_01 x speculator</h3>
  <div class="scroll method-block"><pre>{html.escape(no_emdash(assembled_on))}</pre></div>
  <h3>preamble</h3>
  <div class="scroll method-block"><pre>{html.escape(no_emdash("  " + preamble.replace(chr(10), chr(10) + "  ") if preamble else "missing"))}</pre></div>
  <h3>personas</h3>
  <p class="prose">{html.escape(personas_note)}</p>
  <div class="scroll method-block"><pre>{html.escape(render_personas(d))}</pre></div>
</section>

<section id="questions">
  <h2>THE 10 QUESTIONS</h2>
  <p class="prose">{html.escape(seeded_note)}</p>
  {render_prompts_html(d)}
</section>

<section id="classification">
  <h2>HOW MENTIONS ARE CLASSIFIED</h2>
  <p class="prose">{html.escape(classification)}</p>
</section>

<section id="caveats">
  <h2>CAVEATS</h2>
  <p class="prose">The scoreboard is a paper benchmark. It ignores execution costs, spread, taxes, capacity, and market impact.</p>
  <p class="prose method-block">The sample is small. It is useful as a public measurement feed, not proof of durable alpha.</p>
  <p class="prose method-block">This dashboard is public, so models with search tools can in principle read it. We note that feedback loop rather than pretend it cannot exist.</p>
  <p class="prose method-block">Recommendation flow measures what models say, not what anyone should buy. It is not investment advice.</p>
</section>

<section id="raw-data">
  <h2>RAW DATA</h2>
  <p class="prose">{html.escape(raw)}</p>
</section>
"""
    return page_shell(
        title="pythia: methodology",
        page="methodology",
        masthead=render_masthead(d, len(days), page_name="methodology", compact=True),
        nav=render_main_nav(),
        day_nav="",
        content=content,
        footer=render_footer(),
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
                masthead='<header class="masthead"><div class="wordmark">PYTHIA</div></header>',
                nav="",
                day_nav="",
                content='<section><p>no panels yet. pythia is collecting.</p></section>',
                footer=render_footer(),
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
