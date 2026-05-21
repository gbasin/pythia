#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0"]
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
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("PYTHIA_DB_PATH", ROOT / "db" / "panel.sqlite"))
PROMPTS_YAML_PATH = ROOT / "prompts.yaml"
ASSETS_DIR = ROOT / "assets"
OUT_DIR = Path(os.environ.get("PYTHIA_DIST_DIR", ROOT / "dist"))
OUT_PATH = OUT_DIR / "index.html"
OUT_PROMPTS_PATH = OUT_DIR / "prompts.html"
OUT_TRENDS_PATH = OUT_DIR / "trends.html"

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
    "agy": ("Gemini", "assets/icons/gemini.svg"),
}


def load_preamble() -> str:
    try:
        with PROMPTS_YAML_PATH.open() as f:
            data = yaml.safe_load(f) or {}
        return (data.get("preamble") or "").strip()
    except Exception:
        return ""


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


INTRO_FINDINGS = """\
this day: {n_runs} run(s) · {n_responses} successful responses ·
{n_unique} unique tickers. use the day nav above to page back
through earlier days."""


INTRO_TOP_MENTIONS = """\
every $TICKER the model mentions is classified by a separate
smaller LLM (claude-haiku-4-5) as one of four stances:

  bullish  — recommended to buy / own / overweight
  bearish  — recommended to avoid / sell / underweight
  neutral  — mentioned without a clear recommendation
  context  — mentioned only as a benchmark or comparison

the headline column is  net = bullish - bearish. it's sorted by
net descending — most-pushed names at the top, most-pushed-against
at the bottom. the signed bar runs from bearish (left of the │
divider) to bullish (right). n is the total raw mention count;
avg_pos is the average position in the response (1 = lead pick).

tickers seeded by the prompt itself (e.g. NVDA in "is NVDA a buy?")
will get more mentions by design — those prompts mirror real
retail questions, and the volume of recommendation retail receives
on those names is the signal we're capturing."""


INTRO_PERSONA_DELTA = """\
the same 10 questions get asked twice per model: once as an
aggressive 28-year-old speculator hunting the next 10×, once as
the CIO of a $500M family office with a real return mandate.

delta = (speculator count) − (allocator count). positive = the
model pitches this name more aggressively to retail. negative
= it sleeves this name for institutions."""


INTRO_SAMPLES = """\
below are the most recent successful responses — exactly as the
models wrote them, capped at the first ~620 chars. the complete
text and the full tool-call trace (every web search, every
reasoning step) is preserved in the local database for replay."""


INTRO_PROMPTS = """\
each question is asked verbatim. before every question we attach
one of the two personas ("about me: ...") and a global preamble
that instructs the model to ground its answer in current market
state and to prefix every ticker with $ so extraction is
deterministic. compliance with the $ rule has been ~100% so far."""


INTRO_PERSONAS = """\
these descriptions are injected as "about me" context before
each question. the speculator and allocator bracket the spectrum
of who is plausibly asking an AI for investment advice — together
they let us measure how much the same model changes its tune
based on who it thinks is listening."""


INTRO_MODELS = """\
each model is invoked through its coding-agent CLI harness —
claude code for claude, codex CLI for gpt, antigravity CLI for
gemini — with web/search tools available by default. consumer chat
surfaces (chatgpt.com, claude.ai, gemini.google.com) are deferred
to a later version."""


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
                   WHEN 'agy' THEN 3
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
               SUM(CASE WHEN mc.provider='agy'    AND m.sentiment_hint='bullish' THEN 1 ELSE 0 END) AS agy_bull,
               SUM(CASE WHEN mc.provider='agy'    AND m.sentiment_hint='bearish' THEN 1 ELSE 0 END) AS agy_bear,
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
               SUM(CASE WHEN mc.provider='agy'    AND m.sentiment_hint='bullish' THEN 1 ELSE 0 END) AS agy_bull,
               SUM(CASE WHEN mc.provider='agy'    AND m.sentiment_hint='bearish' THEN 1 ELSE 0 END) AS agy_bear,
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
            "SELECT id, started_at, finished_at, status, panel_version "
            "FROM runs WHERE is_clean=1 AND DATE(started_at)=? "
            "ORDER BY id DESC LIMIT 1",
            (day,),
        ).fetchone()
    else:
        latest_run = con.execute(
            "SELECT id, started_at, finished_at, status, panel_version "
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
        return "—"
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


def signed_bar(net: int, max_abs: int, half_width: int = 10) -> str:
    """Two-sided bar around a │ divider. Bearish fills left, bullish fills right."""
    if max_abs <= 0:
        return " " * half_width + "│" + " " * half_width
    pos = round(half_width * net / max_abs) if net > 0 else 0
    neg = round(half_width * (-net) / max_abs) if net < 0 else 0
    left = " " * (half_width - neg) + "█" * neg
    right = "█" * pos + " " * (half_width - pos)
    return left + "│" + right


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


def indent2(text: str) -> str:
    return textwrap.indent(text, "  ")


# ───────────────────────── section renderers ─────────────────────────


def render_hero_chart(d: dict) -> str:
    """Big, minimalist version of the top-mentions chart for the page hero.
    Just ticker + net + a wide signed bar. Top 15 only. The full table with
    bull/bear/neut/ctx columns lives below as 'details'."""
    rows = d["top_mentions"][:15]
    if not rows:
        return "\n     (no clean data for this day yet — run the panel)\n"
    max_abs_net = max((abs(r["net"] or 0) for r in rows), default=0) or 1
    HALF = 28
    lines = [""]
    for r in rows:
        net = r["net"] or 0
        sign = "+" if net > 0 else ("-" if net < 0 else " ")
        bar_str = signed_bar(net, max_abs_net, half_width=HALF)
        lines.append(f"  ${r['ticker']:<5}  {sign}{abs(net):<3}   {bar_str}")
    lines.append("")
    return "\n".join(lines)


def render_top_mentions(d: dict) -> str:
    rows = d["top_mentions"]
    if not rows:
        return "  (no mentions yet — run the panel to populate)"
    max_abs_net = max((abs(r["net"] or 0) for r in rows), default=0) or 1
    n_days = max((r.get("spark_days", 0) for r in rows), default=0)
    spark_header = f"{n_days}d trend" if n_days else "trend"
    lines = [
        f"  rank  ticker   bull  bear  neut  ctx  net    n   avg_pos       bar (today)            {spark_header}",
        f"  ----  ------   ----  ----  ----  ---  ----   --  -------       ──────────│──────────  {'─' * max(n_days, 4)}",
    ]
    for i, r in enumerate(rows, start=1):
        net = r["net"] or 0
        sign = "+" if net > 0 else ("-" if net < 0 else " ")
        spark = r.get("sparkline", "")
        lines.append(
            f"  {i:>4}  ${r['ticker']:<5}   {r['bull']:>3}   {r['bear']:>3}   "
            f"{r['neut']:>3}  {r['ctx']:>3}  {sign}{abs(net):<3}  {r['n']:>3}   "
            f"{r['avg_pos']:>4.1f}    {signed_bar(net, max_abs_net)}  {spark}"
        )
    return "\n".join(lines)


def render_persona_delta(d: dict) -> str:
    rows = d["persona_delta"]
    if not rows:
        return "  (no data yet)"
    lines = ["  ticker   speculator  allocator  delta"]
    lines.append("  ------   ----------  ---------  ─────")
    for r in rows[:20]:
        spec = r["spec_n"] or 0
        alloc = r["alloc_n"] or 0
        delta = spec - alloc
        sign = "+" if delta > 0 else ("-" if delta < 0 else " ")
        lines.append(f"  ${r['ticker']:<5}    {spec:>7}    {alloc:>7}     {sign}{abs(delta)}")
    return "\n".join(lines)


def render_samples(d: dict) -> str:
    rows = d["samples"]
    if not rows:
        return "  (no completed responses yet)"
    SEP = "  " + "─" * 76
    parts = [SEP]
    for s, tickers in rows:
        age = humanize_age(s["started_at"])
        prompt_one = " ".join((s["prompt_text"] or "").split())
        if len(prompt_one) > 110:
            prompt_one = prompt_one[:107] + "..."
        ticker_str = "  ".join(f"${t}" for t in tickers) if tickers else "—"
        text = s["raw_text"] or ""
        snippet = text[:620].rstrip()
        if len(text) > 620:
            snippet += " …"
        body = textwrap.indent(snippet, "    ", lambda _l: True)
        parts.append(
            f"  resp #{s['resp_id']}  ·  {age}  ·  "
            f"{s['prompt_id']} × {s['persona_id']} × "
            f"{s['provider']}/{s['tools_state']}  ·  "
            f"{s['tokens_out'] or 0} out_tokens"
        )
        parts.append(f"  Q:  {prompt_one}")
        parts.append(f"  AI named:  {ticker_str}")
        parts.append("")
        parts.append(body)
        parts.append(SEP)
    return "\n".join(parts)


def render_prompts(d: dict) -> str:
    rows = d["prompts"]
    if not rows:
        return "  (no prompts registered)"
    out = []
    current_cat = None
    cat_labels = {
        "portfolio": "portfolio construction · 4 questions",
        "single_name": "single-name views · 3 questions",
        "sector_macro": "sector / macro · 3 questions",
    }
    for r in rows:
        if r["category"] != current_cat:
            current_cat = r["category"]
            out.append("")
            out.append(f"  ── {cat_labels.get(current_cat, current_cat)}")
        text = " ".join((r["text"] or "").split())
        wrapped = textwrap.fill(
            text, width=72, initial_indent="    ", subsequent_indent="    "
        )
        out.append(f"  [{r['id']}]")
        out.append(wrapped)
    return "\n".join(out).lstrip()


def render_personas(d: dict) -> str:
    rows = d["personas"]
    if not rows:
        return "  (no personas registered)"
    out = []
    for r in rows:
        out.append(f"  ▸ {r['label'].lower()}  [{r['id']}]")
        body = " ".join((r["description"] or "").split())
        wrapped = textwrap.fill(
            body, width=74, initial_indent="    ", subsequent_indent="    "
        )
        out.append(wrapped)
        out.append("")
    return "\n".join(out).rstrip()


def render_model_configs(d: dict) -> str:
    rows = d["model_configs"]
    if not rows:
        return "  (no model_configs registered)"
    lines = ["  id                          provider  model"]
    lines.append("  --------------------------  --------  ------------------")
    for r in rows:
        lines.append(f"  {r['id']:<26}  {r['provider']:<8}  {r['model_name']}")
    return "\n".join(lines)


def render_runs(d: dict) -> str:
    rows = d["runs"]
    if not rows:
        return "  (no runs yet)"
    lines = ["  run_id  started_at (utc)         status       tuples  ok  fail  refused"]
    lines.append("  ------  -----------------------  ----------   ------  --  ----  -------")
    for r in rows:
        started_short = (r["started_at"] or "")[:19].replace("T", " ")
        lines.append(
            f"  {r['id']:>5}   {started_short:<23}  {r['status']:<10}     "
            f"{r['n_total']:>2}    {r['n_ok']:>2}   {r['n_fail']:>2}    {r['n_refused']:>3}"
        )
    return "\n".join(lines)


def render_rolling_top(rows: list[dict], window_label: str) -> str:
    if not rows:
        return f"  (no data in window: {window_label})"
    max_abs_net = max((abs(r.get("net") or 0) for r in rows), default=0) or 1
    n_days = max((r.get("spark_days") or 0 for r in rows), default=0)
    spark_header = f"{n_days}d trend" if n_days else "trend"
    lines = [
        f"  rank  ticker   bull  bear  net    n    days       bar (net)              {spark_header}",
        f"  ----  ------   ----  ----  ----   --   ----       ──────────│──────────  {'─' * max(n_days, 4)}",
    ]
    for i, r in enumerate(rows, start=1):
        net = r.get("net") or 0
        sign = "+" if net > 0 else ("-" if net < 0 else " ")
        spark = r.get("sparkline", "")
        lines.append(
            f"  {i:>4}  ${r['ticker']:<5}   {r.get('bull') or 0:>3}   {r.get('bear') or 0:>3}   "
            f"{sign}{abs(net):<3}  {r.get('n') or 0:>3}    {r.get('days_seen') or 0:>3}    "
            f"{signed_bar(net, max_abs_net)}  {spark}"
        )
    return "\n".join(lines)


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
    bull = row.get(f"{provider}_bull") or 0
    bear = row.get(f"{provider}_bear") or 0
    return f"{bull}/{bear}"


def render_first_sightings(rows: list[dict], providers: list[str]) -> str:
    if not rows:
        return '<pre class="tbl">  (no first sightings yet)</pre>'
    providers = providers or []
    lines = [
        '<div class="scroll"><table class="data-table provider-table">',
        "<thead><tr>",
        "<th>ticker</th><th>first_seen</th><th>last_seen</th>",
    ]
    lines.extend(f"<th>{render_provider_heading(p)}</th>" for p in providers)
    lines.append("<th>net</th><th>n</th><th>days</th></tr></thead><tbody>")
    for r in rows:
        net = r.get("net_since") or 0
        sign = "+" if net > 0 else ("-" if net < 0 else " ")
        lines.append("<tr>")
        lines.append(f"<td>${html.escape(r['ticker'])}</td>")
        lines.append(f"<td>{html.escape(r['first_seen'])}</td>")
        lines.append(f"<td>{html.escape(r.get('last_seen') or '-')}</td>")
        for provider in providers:
            lines.append(f"<td class=\"num\">{html.escape(provider_cell(r, provider))}</td>")
        lines.append(f"<td class=\"num\">{sign}{abs(net)}</td>")
        lines.append(f"<td class=\"num\">{r.get('n') or 0}</td>")
        lines.append(f"<td class=\"num\">{r.get('days_seen') or 0}</td>")
        lines.append("</tr>")
    lines.append("</tbody></table></div>")
    return "".join(lines)


def render_consensus(rows: list[dict], providers: list[str]) -> str:
    if not rows:
        return '<pre class="tbl">  (no tickers yet where multiple providers were bullish)</pre>'
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
            lines.append(f"<td class=\"num\">{html.escape(provider_cell(r, provider))}</td>")
        lines.append(f"<td class=\"num\">{total_bull-total_bear:+}</td>")
        lines.append(f"<td>{html.escape(verdict)}</td>")
        lines.append(f"<td>{html.escape(spark)}</td>")
        lines.append("</tr>")
    lines.append("</tbody></table></div>")
    return "".join(lines)


def render_days_index(rows: list[dict]) -> str:
    if not rows:
        return "  (no clean days yet)"
    lines = ["  day          n_resp  unique_tickers   top pick                link"]
    lines.append("  ----------   ------  --------------   ----------------------  -----------------")
    for r in rows:
        lead = ""
        if r.get("lead_ticker"):
            net = r.get("lead_net") or 0
            sign = "+" if net > 0 else ("-" if net < 0 else " ")
            lead = f"${r['lead_ticker']:<5} ({sign}{abs(net)})"
        link = f"day/{r['day']}.html"
        lines.append(
            f"  {r['day']}   {r.get('n_responses') or 0:>4}    {r.get('n_unique') or 0:>4}            "
            f"{lead:<22}  → {link}"
        )
    return "\n".join(lines)


def render_overview(d: dict) -> str:
    c = d["counts"]
    lr = d["latest_run"]
    latest = (
        f"#{lr['id']}  status={lr['status']}  {humanize_age(lr['finished_at'] or lr['started_at'])}"
        if lr else "—"
    )
    return (
        f"  runs              {c['n_runs']:>6}\n"
        f"  responses_ok      {c['n_responses_ok']:>6}    "
        f"(failures: {c['n_responses_fail']}, refused: {c['n_refused']})\n"
        f"  mentions          {c['n_mentions']:>6}\n"
        f"  unique_tickers    {c['n_unique_tickers']:>6}\n"
        f"  latest_run        {latest}"
    )


# ───────────────────────── html template ─────────────────────────


HTML_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>pythia — {current_day}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{
    --bg: #0a0a0a;
    --fg: #e6e4dd;
    --dim: #7a766b;
    --accent: #6ad08a;
    --accent-dim: #4a9263;
    --warn: #e6a93c;
    --err: #e36a6a;
    --hair: #1a1a1a;
  }}
  html, body {{ background: var(--bg); color: var(--fg); margin: 0; padding: 0; }}
  body {{
    font-family: 'JetBrains Mono', 'IBM Plex Mono', 'Fira Code', ui-monospace,
                 SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13.5px;
    line-height: 1.62;
    padding: 40px 24px 80px;
    max-width: 920px;
    margin: 0 auto;
  }}
  header {{ margin-bottom: 6px; }}
  h1 {{
    font-size: 13.5px;
    margin: 0;
    letter-spacing: 2px;
    font-weight: 700;
    color: var(--fg);
  }}
  .tag {{ color: var(--dim); }}
  .meta-top {{ color: var(--dim); font-size: 12px; margin-top: 6px; }}
  pre {{ margin: 0; white-space: pre-wrap; word-break: keep-all; }}
  pre.tbl {{ white-space: pre; }}
  section {{ margin-top: 36px; }}
  h2 {{
    font-size: 13.5px;
    color: var(--accent);
    letter-spacing: 1px;
    font-weight: 700;
    margin: 0 0 12px 0;
  }}
  h3 {{
    font-size: 13.5px;
    color: var(--accent-dim);
    font-weight: 700;
    margin: 26px 0 8px 0;
  }}
  .intro {{ color: var(--dim); margin: 0 0 14px 0; }}
  .scroll {{ overflow-x: auto; }}
  nav {{
    margin-top: 14px;
    color: var(--dim);
    border-top: 1px dashed var(--hair);
    border-bottom: 1px dashed var(--hair);
    padding: 8px 0;
  }}
  nav a {{ color: var(--dim); margin-right: 14px; text-decoration: none; }}
  nav a:hover {{ color: var(--accent); }}
  nav.day-nav {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 14px;
    margin-top: 14px;
    padding: 10px 0;
    border-top: 1px dashed var(--hair);
    border-bottom: 1px dashed var(--hair);
  }}
  nav.day-nav a {{ margin-right: 0; }}
  nav.day-nav .day-strip {{
    flex: 1;
    text-align: center;
    letter-spacing: 0.5px;
    white-space: nowrap;
    overflow-x: auto;
  }}
  nav.day-nav .day-strip a {{ margin: 0 8px; }}
  nav.day-nav .day-strip .day-current {{
    color: var(--accent);
    font-weight: 700;
    letter-spacing: 1px;
    margin: 0 8px;
  }}
  nav.day-nav .dim {{ color: var(--hair); }}
  .hero-chart {{
    margin: 28px 0 18px;
    padding: 22px 0;
    border-top: 2px solid var(--accent);
    border-bottom: 2px solid var(--accent);
  }}
  .hero-chart .label {{
    color: var(--accent);
    font-weight: 700;
    letter-spacing: 2px;
    margin-bottom: 6px;
    text-align: center;
  }}
  .hero-chart pre {{
    font-size: 14px;
    line-height: 1.55;
    white-space: pre;
    overflow-x: auto;
  }}
  .caption {{
    color: var(--dim);
    margin: 18px 0 30px;
    line-height: 1.6;
  }}
  .meta {{
    color: var(--dim);
    margin-top: 56px;
    padding-top: 20px;
    border-top: 1px dashed var(--hair);
    font-size: 12px;
  }}
  ::selection {{ background: var(--accent); color: var(--bg); }}
</style>
</head>
<body>

<header>
  <h1>PYTHIA</h1>
  <div class="tag">// {tagline}</div>
  <div class="meta-top">rendered {rendered} · panel_version {panel_version}</div>
</header>

{day_nav}

<section class="hero-chart">
  <div class="label">NET AI RECOMMENDATION FLOW · {current_day}</div>
  <div class="scroll"><pre>{hero_chart}</pre></div>
</section>

<div class="caption">{caption}</div>

<nav>
  <a href="#findings">details</a>
  <a href="#samples">see for yourself</a>
  <a href="#why">why</a>
  <a href="#how">how it works</a>
  <a href="#ops">operational</a>
  <a href="trends.html">▸ trends</a>
  <a href="prompts.html">▸ prompts</a>
</nav>

<section id="findings">
  <h2>▸ details</h2>
  <pre class="intro">{intro_findings}</pre>

  <h3>full breakdown — bull / bear / neut / ctx per ticker</h3>
  <pre class="intro">{intro_top_mentions}</pre>
  <div class="scroll"><pre class="tbl">{top_mentions}</pre></div>

  <h3>does it matter who's asking?</h3>
  <pre class="intro">{intro_persona_delta}</pre>
  <div class="scroll"><pre class="tbl">{persona_delta}</pre></div>
</section>

<section id="samples">
  <h2>▸ see for yourself</h2>
  <pre class="intro">{intro_samples}</pre>
  <div class="scroll"><pre>{samples}</pre></div>
</section>

<section id="why">
  <h2>▸ why this exists</h2>
  <pre>{why}</pre>
</section>

<section id="how">
  <h2>▸ how this works</h2>

  <h3>the 10 questions</h3>
  <pre class="intro">{intro_prompts}</pre>
  <div class="scroll"><pre>{prompts}</pre></div>

  <h3>the 2 personas</h3>
  <pre class="intro">{intro_personas}</pre>
  <div class="scroll"><pre>{personas}</pre></div>

  <h3>configured model surfaces</h3>
  <pre class="intro">{intro_models}</pre>
  <div class="scroll"><pre class="tbl">{model_configs}</pre></div>
</section>

<section id="ops">
  <h2>▸ operational</h2>

  <h3>overview</h3>
  <pre class="tbl">{overview}</pre>

  <h3>recent runs</h3>
  <div class="scroll"><pre class="tbl">{runs}</pre></div>
</section>

<div class="meta"><pre>{footer}</pre>
  <pre>  rebuilt from {db_rel} · sources at {root}</pre>
</div>

</body>
</html>
"""


HTML_INDEX_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>pythia — {current_day}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{
    --bg: #0a0a0a; --fg: #e6e4dd; --dim: #7a766b;
    --accent: #6ad08a; --accent-dim: #4a9263; --hair: #1a1a1a;
  }}
  html, body {{ background: var(--bg); color: var(--fg); margin: 0; padding: 0; }}
  body {{
    font-family: 'JetBrains Mono', 'IBM Plex Mono', 'Fira Code', ui-monospace,
                 SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13.5px; line-height: 1.62;
    padding: 40px 24px 80px; max-width: 1000px; margin: 0 auto;
  }}
  header {{ margin-bottom: 6px; }}
  h1 {{ font-size: 13.5px; margin: 0; letter-spacing: 2px; font-weight: 700; }}
  .tag {{ color: var(--dim); }}
  .meta-top {{ color: var(--dim); font-size: 12px; margin-top: 6px; }}
  pre {{ margin: 0; white-space: pre-wrap; word-break: keep-all; }}
  pre.tbl {{ white-space: pre; }}
  section {{ margin-top: 40px; }}
  h2 {{
    font-size: 13.5px; color: var(--accent); letter-spacing: 1px;
    font-weight: 700; margin: 0 0 12px 0;
  }}
  .intro {{ color: var(--dim); margin: 0 0 14px 0; }}
  .more {{ color: var(--dim); margin-top: 10px; font-size: 12.5px; }}
  .more a {{ color: var(--accent-dim); text-decoration: none; }}
  .more a:hover {{ color: var(--accent); }}
  nav.day-nav {{
    display: flex; justify-content: space-between; align-items: center; gap: 14px;
    margin-top: 14px; padding: 10px 0;
    border-top: 1px dashed var(--hair); border-bottom: 1px dashed var(--hair);
  }}
  nav.day-nav a {{ color: var(--dim); margin-right: 0; text-decoration: none; }}
  nav.day-nav a:hover {{ color: var(--accent); }}
  nav.day-nav .day-strip {{
    flex: 1; text-align: center; letter-spacing: 0.5px;
    white-space: nowrap; overflow-x: auto;
  }}
  nav.day-nav .day-strip a {{ margin: 0 8px; }}
  nav.day-nav .day-strip .day-current {{
    color: var(--accent); font-weight: 700; letter-spacing: 1px; margin: 0 8px;
  }}
  nav.day-nav .dim {{ color: var(--hair); }}
  nav.sections {{
    color: var(--dim); margin-top: 28px; padding: 8px 0;
    border-top: 1px dashed var(--hair); border-bottom: 1px dashed var(--hair);
  }}
  nav.sections a {{ color: var(--dim); margin-right: 14px; text-decoration: none; }}
  nav.sections a:hover {{ color: var(--accent); }}
  .hero-chart {{
    margin: 28px 0 18px;
    padding: 22px 0;
    border-top: 2px solid var(--accent);
    border-bottom: 2px solid var(--accent);
  }}
  .hero-chart .label {{
    color: var(--accent); font-weight: 700; letter-spacing: 2px;
    margin-bottom: 6px; text-align: center;
  }}
  .hero-chart pre {{
    font-size: 14px; line-height: 1.55; white-space: pre; overflow-x: auto;
  }}
  details.explainer {{
    margin: 12px 0 28px;
    padding: 10px 14px;
    border: 1px dashed var(--hair);
  }}
  details.explainer > summary {{
    color: var(--dim); cursor: pointer; outline: none;
    list-style: none;
  }}
  details.explainer > summary::-webkit-details-marker {{ display: none; }}
  details.explainer > summary::before {{
    content: "▸ "; color: var(--accent-dim);
  }}
  details.explainer[open] > summary::before {{
    content: "▾ "; color: var(--accent);
  }}
  details.explainer > pre {{
    margin-top: 12px; line-height: 1.6;
  }}
  .scroll {{ overflow-x: auto; }}
  .data-table {{
    border-collapse: collapse; font: inherit; color: var(--fg);
  }}
  .data-table th, .data-table td {{
    padding: 0 18px 0 0; text-align: left; white-space: nowrap;
  }}
  .data-table th {{
    color: var(--dim); font-weight: 700;
    border-bottom: 1px dashed var(--dim);
  }}
  .data-table .num {{ text-align: right; }}
  .provider-head {{
    display: inline-flex; width: 42px; align-items: center; justify-content: center;
    vertical-align: middle;
  }}
  .provider-icon {{
    width: 16px; height: 16px; display: block; opacity: 0.9;
    filter: invert(92%) sepia(9%) saturate(225%) hue-rotate(3deg) brightness(102%) contrast(90%);
  }}
  .sr-only {{
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
  }}
  .meta {{
    color: var(--dim); margin-top: 56px; padding-top: 20px;
    border-top: 1px dashed var(--hair); font-size: 12px;
  }}
  .meta a {{ color: var(--accent-dim); text-decoration: none; }}
  .meta a:hover {{ color: var(--accent); }}
  ::selection {{ background: var(--accent); color: var(--bg); }}
</style>
</head>
<body>

<header>
  <h1>PYTHIA</h1>
  <div class="tag">// what frontier AI models tell people to buy</div>
</header>

{day_nav}

<section class="hero-chart">
  <div class="label">NET AI RECOMMENDATION FLOW · {current_day}</div>
  <div class="scroll"><pre>{hero_chart}</pre></div>
</section>

<details class="explainer">
  <summary>what am I looking at?</summary>
  <pre>{explainer}</pre>
</details>

<section id="new">
  <h2>▸ first sightings</h2>
  {first_sightings}
  <div class="more">→ <a href="trends.html#first-sightings">full list</a></div>
</section>

<section id="consensus">
  <h2>▸ provider consensus</h2>
  {consensus}
  <div class="more">→ <a href="trends.html#consensus">full table</a></div>
</section>

<section id="rolling7">
  <h2>▸ top picks · last 7 days</h2>
  <div class="scroll"><pre class="tbl">{rolling_7d}</pre></div>
  <div class="more">→ <a href="trends.html">30d + all-time on trends</a></div>
</section>

<div class="meta">
  <pre>  detail per day  → <a href="day/{current_day}.html">today's deep view</a>  ·  <a href="trends.html">trends</a>  ·  <a href="prompts.html">methodology</a></pre>
  <pre>  {n_clean_days} clean days · {n_total_responses} responses · rendered {rendered}</pre>
  <pre>{footer}</pre>
</div>

</body>
</html>
"""


HTML_TRENDS_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>pythia — trends</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{
    --bg: #0a0a0a; --fg: #e6e4dd; --dim: #7a766b;
    --accent: #6ad08a; --accent-dim: #4a9263; --hair: #1a1a1a;
  }}
  html, body {{ background: var(--bg); color: var(--fg); margin: 0; padding: 0; }}
  body {{
    font-family: 'JetBrains Mono', 'IBM Plex Mono', 'Fira Code', ui-monospace,
                 SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13.5px; line-height: 1.62;
    padding: 40px 24px 80px; max-width: 1000px; margin: 0 auto;
  }}
  header {{ margin-bottom: 6px; }}
  h1 {{ font-size: 13.5px; margin: 0; letter-spacing: 2px; font-weight: 700; }}
  .tag {{ color: var(--dim); }}
  .meta-top {{ color: var(--dim); font-size: 12px; margin-top: 6px; }}
  pre {{ margin: 0; white-space: pre-wrap; word-break: keep-all; }}
  pre.tbl {{ white-space: pre; }}
  section {{ margin-top: 36px; }}
  h2 {{
    font-size: 13.5px; color: var(--accent); letter-spacing: 1px;
    font-weight: 700; margin: 0 0 12px 0;
  }}
  h3 {{
    font-size: 13.5px; color: var(--accent-dim); font-weight: 700;
    margin: 26px 0 8px 0;
  }}
  .intro {{ color: var(--dim); margin: 0 0 14px 0; }}
  nav {{
    margin-top: 14px; color: var(--dim);
    border-top: 1px dashed var(--hair); border-bottom: 1px dashed var(--hair);
    padding: 8px 0;
  }}
  nav a {{ color: var(--dim); margin-right: 14px; text-decoration: none; }}
  nav a:hover {{ color: var(--accent); }}
  .scroll {{ overflow-x: auto; }}
  .data-table {{
    border-collapse: collapse; font: inherit; color: var(--fg);
  }}
  .data-table th, .data-table td {{
    padding: 0 18px 0 0; text-align: left; white-space: nowrap;
  }}
  .data-table th {{
    color: var(--dim); font-weight: 700;
    border-bottom: 1px dashed var(--dim);
  }}
  .data-table .num {{ text-align: right; }}
  .provider-head {{
    display: inline-flex; width: 42px; align-items: center; justify-content: center;
    vertical-align: middle;
  }}
  .provider-icon {{
    width: 16px; height: 16px; display: block; opacity: 0.9;
    filter: invert(92%) sepia(9%) saturate(225%) hue-rotate(3deg) brightness(102%) contrast(90%);
  }}
  .sr-only {{
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
  }}
  .meta {{
    color: var(--dim); margin-top: 56px; padding-top: 20px;
    border-top: 1px dashed var(--hair); font-size: 12px;
  }}
  ::selection {{ background: var(--accent); color: var(--bg); }}
</style>
</head>
<body>

<header>
  <h1>PYTHIA / trends</h1>
  <div class="tag">// rolling and cumulative views across all clean days</div>
  <div class="meta-top">rendered {rendered} · {n_days} clean days · {n_responses} responses</div>
</header>

<nav>
  <a href="index.html">← back to dashboard</a>
  <a href="#rolling7">last 7 days</a>
  <a href="#rolling30">last 30 days</a>
  <a href="#alltime">all-time</a>
  <a href="#first-sightings">first sightings</a>
  <a href="#consensus">consensus</a>
  <a href="#days">all days</a>
  <a href="prompts.html">▸ prompts</a>
</nav>

<section id="rolling7">
  <h2>▸ top tickers · last 7 days</h2>
  <pre class="intro">{intro_rolling}</pre>
  <div class="scroll"><pre class="tbl">{rolling_7d}</pre></div>
</section>

<section id="rolling30">
  <h2>▸ top tickers · last 30 days</h2>
  <div class="scroll"><pre class="tbl">{rolling_30d}</pre></div>
</section>

<section id="alltime">
  <h2>▸ top tickers · all-time</h2>
  <div class="scroll"><pre class="tbl">{rolling_all}</pre></div>
</section>

<section id="first-sightings">
  <h2>▸ first sightings</h2>
  <pre class="intro">{intro_first_sightings}</pre>
  {first_sightings}
</section>

<section id="consensus">
  <h2>▸ provider consensus</h2>
  <pre class="intro">{intro_consensus}</pre>
  {consensus}
</section>

<section id="days">
  <h2>▸ all clean days</h2>
  <pre class="intro">{intro_days}</pre>
  <div class="scroll"><pre class="tbl">{days_index}</pre></div>
</section>

<div class="meta"><pre>{footer}</pre></div>

</body>
</html>
"""


HTML_PROMPTS_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>pythia — prompts (review)</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{
    --bg: #0a0a0a;
    --fg: #e6e4dd;
    --dim: #7a766b;
    --accent: #6ad08a;
    --accent-dim: #4a9263;
    --hair: #1a1a1a;
  }}
  html, body {{ background: var(--bg); color: var(--fg); margin: 0; padding: 0; }}
  body {{
    font-family: 'JetBrains Mono', 'IBM Plex Mono', 'Fira Code', ui-monospace,
                 SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13.5px;
    line-height: 1.62;
    padding: 40px 24px 80px;
    max-width: 920px;
    margin: 0 auto;
  }}
  header {{ margin-bottom: 6px; }}
  h1 {{ font-size: 13.5px; margin: 0; letter-spacing: 2px; font-weight: 700; }}
  .tag {{ color: var(--dim); }}
  .meta-top {{ color: var(--dim); font-size: 12px; margin-top: 6px; }}
  pre {{ margin: 0; white-space: pre-wrap; word-break: keep-all; }}
  pre.tbl {{ white-space: pre; }}
  section {{ margin-top: 36px; }}
  h2 {{
    font-size: 13.5px; color: var(--accent); letter-spacing: 1px;
    font-weight: 700; margin: 0 0 12px 0;
  }}
  h3 {{
    font-size: 13.5px; color: var(--accent-dim); font-weight: 700;
    margin: 26px 0 8px 0;
  }}
  .intro {{ color: var(--dim); margin: 0 0 14px 0; }}
  nav {{
    margin-top: 14px; color: var(--dim);
    border-top: 1px dashed var(--hair);
    border-bottom: 1px dashed var(--hair);
    padding: 8px 0;
  }}
  nav a {{ color: var(--dim); margin-right: 14px; text-decoration: none; }}
  nav a:hover {{ color: var(--accent); }}
  .meta {{
    color: var(--dim); margin-top: 56px; padding-top: 20px;
    border-top: 1px dashed var(--hair); font-size: 12px;
  }}
  ::selection {{ background: var(--accent); color: var(--bg); }}
</style>
</head>
<body>

<header>
  <h1>PYTHIA / prompts</h1>
  <div class="tag">// the exact text claude opus + gpt-5.5 see, every run</div>
  <div class="meta-top">rendered {rendered}</div>
</header>

<nav>
  <a href="index.html">← back to dashboard</a>
</nav>

<section>
  <h2>▸ how a prompt is assembled</h2>
  <pre class="intro">{assembly_intro}</pre>
  <h3>example: portfolio_01 × speculator</h3>
  <div class="scroll"><pre>{assembled_on}</pre></div>
</section>

<section>
  <h2>▸ preamble  (applied to every prompt, after the persona)</h2>
  <pre class="intro">{preamble_intro}</pre>
  <div class="scroll"><pre>{preamble_block}</pre></div>
</section>

<section>
  <h2>▸ personas  (injected as &quot;about me&quot; context)</h2>
  <pre class="intro">{personas_intro}</pre>
  <div class="scroll"><pre>{personas_full}</pre></div>
</section>

<section>
  <h2>▸ the 10 questions  (full text, no truncation)</h2>
  <pre class="intro">{prompts_intro}</pre>
  <div class="scroll"><pre>{prompts_full}</pre></div>
</section>

<div class="meta"><pre>{footer}</pre></div>

</body>
</html>
"""


# ───────────────────────── main ─────────────────────────


def _day_href(day: str, is_index: bool) -> str:
    return f"day/{day}.html" if is_index else f"{day}.html"


def render_day_nav(current: str, days: list[str], is_index: bool) -> str:
    """Render the prev/strip/next nav. `days` is the full clean-day list in
    DESC order (latest first). Shows up to STRIP_LEN days centered around
    `current` as a clickable date strip, plus ◀ ▶ arrows on either end."""
    STRIP_LEN = 10
    try:
        idx = days.index(current)
    except ValueError:
        idx = 0

    # Surrounding window of visible days. days is DESC, so older = higher idx.
    end = min(len(days), idx + STRIP_LEN // 2 + 1)
    start = max(0, end - STRIP_LEN)
    if end - start < STRIP_LEN:
        end = min(len(days), start + STRIP_LEN)
    visible = days[start:end]                  # still DESC
    visible_asc = list(reversed(visible))      # ASC for display (older → newer)

    def short(d: str) -> str:
        # YYYY-MM-DD → MM-DD
        return d[5:] if len(d) >= 10 else d

    def chip(d: str) -> str:
        if d == current:
            return f'<span class="day-current">[{html.escape(short(d))}]</span>'
        return f'<a href="{html.escape(_day_href(d, is_index))}" title="{html.escape(d)}">{html.escape(short(d))}</a>'

    strip = " ".join(chip(d) for d in visible_asc)

    older = days[idx + 1] if idx + 1 < len(days) else None   # one step back in time
    newer = days[idx - 1] if idx > 0 else None                # one step forward
    older_html = (
        f'<a href="{html.escape(_day_href(older, is_index))}" title="{html.escape(older)}">◀</a>'
        if older else '<span class="dim">◀</span>'
    )
    newer_html = (
        f'<a href="{html.escape(_day_href(newer, is_index))}" title="{html.escape(newer)}">▶</a>'
        if newer else '<span class="dim">▶</span>'
    )

    return (
        '<nav class="day-nav">'
        f"{older_html}"
        f'<span class="day-strip">{strip}</span>'
        f"{newer_html}"
        "</nav>"
    )


def render_index_page(d: dict, trends: dict, day: str, days: list[str],
                      n_total_responses: int) -> str:
    """The /index.html landing page. Stripped down: today's hero chart, three
    compact trend tables, one collapsible explainer. Detailed per-day data
    lives on /day/<date>.html; full trends on /trends.html."""
    return HTML_INDEX_TMPL.format(
        current_day=html.escape(day),
        rendered=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        n_clean_days=len(days),
        n_total_responses=n_total_responses,
        day_nav=render_day_nav(day, days, is_index=True),
        hero_chart=html.escape(render_hero_chart(d)),
        explainer=html.escape(EXPLAINER),
        first_sightings=render_first_sightings(
            trends["first_sightings"][:8], trends["providers"]
        ),
        consensus=render_consensus(trends["consensus"][:8], trends["providers"]),
        rolling_7d=html.escape(render_rolling_top(trends["top_7d"][:8], "7 days")),
        footer=html.escape(FOOTER),
    )


def render_main_page(d: dict, day: str, days: list[str], is_index: bool) -> str:
    counts = d["counts"]
    intro_findings = INTRO_FINDINGS.format(
        n_runs=counts["n_runs"],
        n_responses=counts["n_responses_ok"],
        n_unique=counts["n_unique_tickers"],
    )
    panel_version = d["latest_run"]["panel_version"] if d["latest_run"] else "—"
    return HTML_TMPL.format(
        tagline=html.escape(TAGLINE),
        current_day=html.escape(day),
        day_nav=render_day_nav(day, days, is_index),
        rendered=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        panel_version=html.escape(panel_version),
        hero_chart=html.escape(render_hero_chart(d)),
        caption=html.escape(CAPTION),
        why=html.escape(WHY),
        intro_findings=html.escape(intro_findings),
        intro_top_mentions=html.escape(INTRO_TOP_MENTIONS),
        intro_persona_delta=html.escape(INTRO_PERSONA_DELTA),
        intro_samples=html.escape(INTRO_SAMPLES),
        intro_prompts=html.escape(INTRO_PROMPTS),
        intro_personas=html.escape(INTRO_PERSONAS),
        intro_models=html.escape(INTRO_MODELS),
        top_mentions=html.escape(render_top_mentions(d)),
        persona_delta=html.escape(render_persona_delta(d)),
        samples=html.escape(render_samples(d)),
        prompts=html.escape(render_prompts(d)),
        personas=html.escape(render_personas(d)),
        model_configs=html.escape(render_model_configs(d)),
        overview=html.escape(render_overview(d)),
        runs=html.escape(render_runs(d)),
        footer=html.escape(FOOTER),
        db_rel=html.escape(str(DB_PATH.relative_to(ROOT) if DB_PATH.is_relative_to(ROOT) else DB_PATH)),
        root=html.escape(str(ROOT)),
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

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        days = list_clean_days(con)
        if not days:
            placeholder = (
                "<!doctype html><html><head><meta charset=\"utf-8\">"
                "<title>pythia</title></head><body style=\"background:#0a0a0a;"
                "color:#e6e4dd;font-family:monospace;padding:40px;\">"
                "<pre>no clean runs yet — pythia is collecting.</pre>"
                "</body></html>"
            )
            OUT_PATH.write_text(placeholder, encoding="utf-8")
            print(f"wrote {OUT_PATH} (no clean days yet)")
            return 0

        # Render every clean day as its own snapshot under dist/day/.
        for day in days:
            d = fetch(con, day=day)
            page = render_main_page(d, day, days, is_index=False)
            day_path = day_dir / f"{day}.html"
            day_path.write_text(page, encoding="utf-8")
            print(f"wrote {day_path}  ({len(page)} bytes)")

        # Global panel data (for prompts subpage) + cumulative trends.
        d = fetch(con, day=None)
        trends = fetch_trends(con)
        n_total_responses = sum(r.get("n_responses") or 0 for r in trends["days_index"])

        # Index = focused landing: today's hero + trend highlights.
        latest = days[0]
        d_latest = fetch(con, day=latest)
        index_page = render_index_page(d_latest, trends, latest, days, n_total_responses)
        OUT_PATH.write_text(index_page, encoding="utf-8")
        print(f"wrote {OUT_PATH}  ({len(index_page)} bytes)  [index = {latest}, focused]")
    finally:
        con.close()

    # ── trends subpage ──
    trends_page = HTML_TRENDS_TMPL.format(
        rendered=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        n_days=len(days),
        n_responses=n_total_responses,
        intro_rolling=html.escape(
            "rolling windows: top tickers ranked by net (bullish - bearish) "
            "over the window. `days` is the count of distinct days the ticker "
            "appeared (persistence). the trend sparkline covers the last 30 "
            "clean days. when there's less than the window's worth of data, "
            "values are just whatever is available."
        ),
        intro_first_sightings=html.escape(
            "tickers ordered by first appearance in clean runs, newest first. "
            "useful for spotting names that have newly entered the "
            "recommendation flow. per-provider cells are bull/bear counts; "
            "net aggregates all sentiment from first sighting through now."
        ),
        intro_consensus=html.escape(
            "tickers where multiple providers contributed bullish mentions "
            "(across all clean days). provider-count agreement is a stronger "
            "signal that the recommendation flow is consensus, not a quirk "
            "of one model surface. per-provider cells are bull/bear counts."
        ),
        intro_days=html.escape(
            "every clean run grouped by calendar day. click → to open that "
            "day's snapshot. lead-pick column = the highest-net ticker for "
            "the day."
        ),
        rolling_7d=html.escape(render_rolling_top(trends["top_7d"], "7 days")),
        rolling_30d=html.escape(render_rolling_top(trends["top_30d"], "30 days")),
        rolling_all=html.escape(render_rolling_top(trends["top_all"], "all-time")),
        first_sightings=render_first_sightings(trends["first_sightings"], trends["providers"]),
        consensus=render_consensus(trends["consensus"], trends["providers"]),
        days_index=html.escape(render_days_index(trends["days_index"])),
        footer=html.escape(FOOTER),
    )
    OUT_TRENDS_PATH.write_text(trends_page, encoding="utf-8")
    print(f"wrote {OUT_TRENDS_PATH}  ({len(trends_page)} bytes)")

    # ── prompts subpage ──
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
        assembled_on = "(unavailable — db missing prompts or personas)"

    prompts_page = HTML_PROMPTS_TMPL.format(
        rendered=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        assembly_intro=html.escape(
            "every CLI invocation receives one assembled string via stdin: "
            "the persona context, then the global preamble, then the actual "
            "question. below is the literal text the model sees for one "
            "example tuple."
        ),
        assembled_on=html.escape(assembled_on),
        preamble_intro=html.escape(
            "instructs every model to ground its answer in current market "
            "state and to prefix every ticker with $ so extraction is "
            "deterministic. identical across every model + persona."
        ),
        preamble_block=html.escape("  " + preamble.replace("\n", "\n  ") if preamble else "(missing)"),
        personas_intro=html.escape(
            "these two descriptions are injected as 'about me:' context "
            "before every question. they bracket the spectrum of who is "
            "plausibly asking an AI for investment advice."
        ),
        personas_full=html.escape(render_personas(d)),
        prompts_intro=html.escape(
            "10 questions, asked verbatim each run. some deliberately name "
            "tickers (NVDA, TSLA) — those mirror real retail queries, and "
            "the volume the model returns on those names is the recommendation "
            "flow we want to measure."
        ),
        prompts_full=html.escape(render_prompts(d)),
        footer=html.escape(FOOTER),
    )
    OUT_PROMPTS_PATH.write_text(prompts_page, encoding="utf-8")
    print(f"wrote {OUT_PROMPTS_PATH}  ({len(prompts_page)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
