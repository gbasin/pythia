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
import sqlite3
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "panel.sqlite"
PROMPTS_YAML_PATH = ROOT / "prompts.yaml"
OUT_PATH = ROOT / "dist" / "index.html"
OUT_PROMPTS_PATH = ROOT / "dist" / "prompts.html"

# Mirrors TOOLS_OFF_SUFFIX in scripts/run_panel.py — duplicated so the
# review page can show the exact text models see for tools_off runs.
TOOLS_OFF_SUFFIX = (
    "IMPORTANT: For this query, you may NOT use any web search, browser, "
    "or external lookup tools. Answer entirely from your training data. "
    "If your information is stale, say so and proceed anyway with the "
    "best answer you can give from what you know."
)


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

HERO = """\
every day at 4:30 PM ET, pythia asks claude opus 4.7 and gpt-5.5
what stocks to buy. 10 questions × 2 personas × 2 models = 40
calls per run. every $TICKER the model mentions is labeled
(bullish / bearish / neutral / context) by a smaller LLM. the
chart below is the net flow: bullish - bearish across the panel."""


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
pythia started recently — patterns will sharpen as more daily runs
accumulate. {n_runs} runs · {n_responses} successful responses
· {n_unique} unique tickers extracted so far."""


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
two models, one config each. each is invoked through its coding-
agent CLI harness — claude code for claude, codex CLI for gpt —
with web search enabled by default. consumer chat surfaces
(chatgpt.com, claude.ai) are deferred to a later version."""


FOOTER = """\
  not investment advice. not a recommendation. just an experiment.
  raw data lives in db/panel.sqlite. this page rebuilds on every
  panel run, from that database — no other source of truth."""


# ───────────────────────── data fetch ─────────────────────────


def fetch(con) -> dict:
    con.row_factory = sqlite3.Row
    counts = con.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM runs)                                   AS n_runs,
            (SELECT COUNT(*) FROM responses)                              AS n_responses_total,
            (SELECT COUNT(*) FROM responses WHERE error IS NULL)          AS n_responses_ok,
            (SELECT COUNT(*) FROM responses WHERE error IS NOT NULL)      AS n_responses_fail,
            (SELECT COUNT(*) FROM responses WHERE refused=1)              AS n_refused,
            (SELECT COUNT(*) FROM mentions)                               AS n_mentions,
            (SELECT COUNT(DISTINCT ticker) FROM mentions)                 AS n_unique_tickers
        """
    ).fetchone()

    latest_run = con.execute(
        "SELECT id, started_at, finished_at, status, panel_version FROM runs ORDER BY id DESC LIMIT 1"
    ).fetchone()

    runs = con.execute(
        """
        SELECT r.id, r.started_at, r.status,
               (SELECT COUNT(*) FROM responses WHERE run_id=r.id) AS n_total,
               (SELECT COUNT(*) FROM responses WHERE run_id=r.id AND error IS NULL) AS n_ok,
               (SELECT COUNT(*) FROM responses WHERE run_id=r.id AND error IS NOT NULL) AS n_fail,
               (SELECT COUNT(*) FROM responses WHERE run_id=r.id AND refused=1) AS n_refused
        FROM runs r ORDER BY id DESC LIMIT 10
        """
    ).fetchall()

    top_mentions = con.execute(
        """
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
        WHERE r.error IS NULL
        GROUP BY m.ticker
        ORDER BY net DESC, n DESC, avg_pos ASC
        LIMIT 24
        """
    ).fetchall()

    persona_delta = con.execute(
        """
        SELECT m.ticker,
               SUM(CASE WHEN r.persona_id='speculator' THEN 1 ELSE 0 END) AS spec_n,
               SUM(CASE WHEN r.persona_id='allocator'  THEN 1 ELSE 0 END) AS alloc_n
        FROM mentions m JOIN responses r ON m.response_id=r.id
        WHERE r.error IS NULL
        GROUP BY m.ticker
        HAVING (spec_n + alloc_n) >= 1
        ORDER BY (spec_n - alloc_n) DESC, m.ticker
        """
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
        """
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
        WHERE r.error IS NULL AND r.raw_text IS NOT NULL AND LENGTH(r.raw_text) > 100
        ORDER BY r.id DESC
        LIMIT 6
        """
    ).fetchall()

    samples_enriched = []
    for s in samples:
        tickers = con.execute(
            "SELECT ticker FROM mentions WHERE response_id=? ORDER BY position LIMIT 10",
            (s["resp_id"],),
        ).fetchall()
        samples_enriched.append((s, [t["ticker"] for t in tickers]))

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


def indent2(text: str) -> str:
    return textwrap.indent(text, "  ")


# ───────────────────────── section renderers ─────────────────────────


def render_top_mentions(d: dict) -> str:
    rows = d["top_mentions"]
    if not rows:
        return "  (no mentions yet — run the panel to populate)"
    max_abs_net = max((abs(r["net"] or 0) for r in rows), default=0) or 1
    lines = [
        "  rank  ticker   bull  bear  neut  ctx  net    n   avg_pos       bearish ──│── bullish",
        "  ----  ------   ----  ----  ----  ---  ----   --  -------       ──────────│──────────",
    ]
    for i, r in enumerate(rows, start=1):
        net = r["net"] or 0
        sign = "+" if net > 0 else ("-" if net < 0 else " ")
        lines.append(
            f"  {i:>4}  ${r['ticker']:<5}   {r['bull']:>3}   {r['bear']:>3}   "
            f"{r['neut']:>3}  {r['ctx']:>3}  {sign}{abs(net):<3}  {r['n']:>3}   "
            f"{r['avg_pos']:>4.1f}        {signed_bar(net, max_abs_net)}"
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
<title>pythia — what AIs tell people to buy</title>
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

<nav>
  <a href="#findings">what we found</a>
  <a href="#samples">see for yourself</a>
  <a href="#why">why</a>
  <a href="#how">how it works</a>
  <a href="#ops">operational</a>
  <a href="prompts.html">▸ review prompts</a>
</nav>

<section id="hero">
  <pre>{hero}</pre>
</section>

<section id="findings">
  <h2>▸ what we found</h2>
  <pre class="intro">{intro_findings}</pre>

  <h3>net recommendation flow per ticker</h3>
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

  <h3>the 2 models · 4 configurations</h3>
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


def main() -> int:
    if not DB_PATH.exists():
        print(f"db missing: {DB_PATH}")
        return 1
    OUT_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        d = fetch(con)
    finally:
        con.close()

    counts = d["counts"]
    intro_findings = INTRO_FINDINGS.format(
        n_runs=counts["n_runs"],
        n_responses=counts["n_responses_ok"],
        n_unique=counts["n_unique_tickers"],
    )
    panel_version = d["latest_run"]["panel_version"] if d["latest_run"] else "—"

    page = HTML_TMPL.format(
        tagline=html.escape(TAGLINE),
        rendered=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        panel_version=html.escape(panel_version),
        hero=html.escape(HERO),
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
        db_rel=html.escape(str(DB_PATH.relative_to(ROOT))),
        root=html.escape(str(ROOT)),
    )
    OUT_PATH.write_text(page, encoding="utf-8")
    print(f"wrote {OUT_PATH}  ({len(page)} bytes)")

    # ── prompts subpage ──
    preamble = load_preamble()
    # Pick an illustrative tuple — portfolio_01 × speculator.
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
