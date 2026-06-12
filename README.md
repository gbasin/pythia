# pythia

what frontier AI models tell people to buy, captured nightly.

**live dashboard: https://gbasin.github.io/pythia/**

every night at 8 PM ET, pythia asks the current top model from three
providers the same 10 retail investing questions under two personas
(an aggressive young speculator and a professional allocator), with web
search available — 60 responses:

- **claude** via the Claude Code CLI (`claude -p`, floating `opus` alias)
- **openai gpt** via the Codex CLI (`codex exec`, CLI default model)
- **gemini** via the Gemini API with Google Search grounding
  (`gemini-flash-latest`)

every `$TICKER` a model emits is classified by a smaller LLM as bullish,
bearish, neutral, or context. raw text and full JSON traces are gzipped
into SQLite, a static dashboard rebuilds, and the result publishes to
GitHub Pages.

## why

people increasingly ask ChatGPT and Claude what to buy, and those
recommendations feed retail flows. nobody measures the recommendations
themselves in public. pythia tracks this **recommendation flow**: the
net bullish-minus-bearish push per ticker, by persona and provider, over
time, plus a paper benchmark of what following it would have returned.

prompts deliberately mirror real retail queries, including ones that
name tickers ("is NVDA a buy?"). the volume of recommendation those
names receive is part of the signal, not a bias to scrub.

## quick start

prereqs (macOS):
- [Claude Code CLI](https://docs.claude.com/claude-code) authenticated with a Pro/Max subscription
- [Codex CLI](https://github.com/openai/codex) authenticated with a ChatGPT Pro subscription
- a [Gemini API key](https://aistudio.google.com/apikey) (pay-per-token; the flash leg costs cents/day)
- [uv](https://docs.astral.sh/uv/) for Python script execution

```bash
git clone https://github.com/gbasin/pythia.git
cd pythia
mkdir -p db && sqlite3 db/panel.sqlite < schema.sql   # initialize DB (first time only)

cat > .env <<'ENV'                        # secrets; gitignored
GEMINI_API_KEY=...                        # required for the gemini leg
PYTHIA_NTFY_TOPIC=...                     # optional: ntfy.sh push alerts
PYTHIA_HEALTH_REPO=you/your-fork          # optional: gh issues for health alerts
ENV
chmod 600 .env

uv run scripts/run_panel.py --dry-run     # preview the full run matrix
./scripts/daily_run.sh                    # full pipeline (~30 min; silent — watch logs/panel-YYYYMMDD.log)
open dist/index.html                      # view dashboard
```

both health-alert transports are optional: leave `PYTHIA_NTFY_TOPIC` or
`PYTHIA_HEALTH_REPO` unset to skip that one. for github issues, create
the label first: `gh label create pythia-health`.

individual stages:

```bash
uv run scripts/run_panel.py               # full panel (~30 min)
uv run scripts/run_panel.py --prompt-id name_01 --persona-id speculator \
    --model-config-id claude_opus        # one tuple, for smoke-testing
uv run scripts/classify_mentions.py       # label sentiment on new mentions
uv run scripts/render_page.py             # rebuild all dashboard pages
uv run scripts/benchmark_alpha.py --rebuild-signals  # paper benchmark
```

## how a response is produced

every prompt runs for both personas on all three models, every night.
each call is composed as:

1. `About me:` persona block
2. global preamble (current-state grounding + `$TICKER` format directive)
3. the question, verbatim

then piped to `claude -p`, `codex exec`, or the gemini wrapper. the full
trace is gzipped and stored alongside the final response text.

each leg runs the provider's "latest" alias rather than a pinned version,
so the panel follows model releases automatically. the model id that
actually served each response is recorded in
`responses.model_name_reported`, so model eras can be separated in
analysis.

## project layout

```
prompts.yaml                       # panel prompts + global preamble
personas.yaml                      # personas: speculator, allocator
model_configs.yaml                 # per-provider invocation specs
health_checks.yaml                 # post-run health thresholds + alert routing
schema.sql                         # sqlite schema
data/                              # NASDAQ/NYSE symbol directories (ticker universe)

scripts/run_panel.py               # orchestrator
scripts/gemini_panel_call.py       # gemini API wrapper (emits a JSONL trace)
scripts/classify_mentions.py       # LLM-as-judge sentiment labeler
scripts/benchmark_alpha.py         # price cache + paper benchmark
scripts/render_page.py             # static dashboard generator
scripts/health_check.py            # post-run checks → ntfy push + github issues
scripts/publish_pages.sh           # push dist/ to the gh-pages branch
scripts/daily_run.sh               # run → classify → benchmark → render → publish → health check

launchd/com.pythia.daily.plist     # 8 PM nightly schedule
db/panel.sqlite                    # all data (gitignored)
dist/                              # rendered dashboard (gitignored)
```

## schedule

a launchd agent fires `scripts/daily_run.sh` nightly at 8 PM local time.
the tracked plist carries a `/PATH/TO/pythia` placeholder (launchd needs
an absolute path); install substitutes it. the same commands reinstall
after editing the plist:

```bash
mkdir -p ~/Library/LaunchAgents
launchctl bootout gui/$UID/com.pythia.daily 2>/dev/null || true
sed "s|/PATH/TO/pythia|$PWD|" launchd/com.pythia.daily.plist \
  > ~/Library/LaunchAgents/com.pythia.daily.plist
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.pythia.daily.plist
```

remove with `launchctl bootout gui/$UID/com.pythia.daily` and delete the
plist from `~/Library/LaunchAgents`.

## dashboard

`dist/` is a self-contained static directory; the nightly run pushes it
to the `gh-pages` branch. pages:

- `/` — tonight's flow + scoreboard + trend teasers
- `/day/DATE.html` — one night in full: per-ticker breakdown, persona delta, response samples
- `/trends.html` — rolling ranks, first sightings, provider consensus
- `/alpha.html` — paper benchmark: top-20 flow basket vs QQQ, next-session open→close
- `/methodology.html` — exact prompts, personas, pipeline, caveats

## data

everything lives in `db/panel.sqlite`:

- `runs` — one per panel invocation
- `prompts`, `personas` — versioned by content hash (edits don't break old data)
- `model_configs` — one row per invocation-spec change
- `responses` — `raw_text` + gzipped full trace + tokens, latency, and
  `model_name_reported` (what the floating alias actually resolved to)
- `mentions` — one row per unique ticker per response, with classifier
  sentiment ∈ {bullish, bearish, neutral, context}
- `daily_signals`, `prices`, `forward_returns` — built by
  `scripts/benchmark_alpha.py`

set `PYTHIA_DB_PATH` to point every script at a different database
(useful for testing against a copy).

## design decisions

- **coding-agent surfaces, not consumer chat.** claude code and codex
  exec are scriptable under authenticated subscriptions and capture the
  "AI agent" surface. the gemini leg uses the API with Google Search
  grounding (the closest equivalent). consumer chat (chatgpt.com,
  claude.ai) would need browser automation; deferred.
- **named-ticker prompts kept on purpose.** "is NVDA a buy?" is what
  real retail asks. rephrasing to be unopinionated would measure what AI
  spontaneously recommends in a vacuum — less useful.
- **no tools-off variant.** codex has no documented way to disable web
  search, so a with/without comparison was asymmetric. dropped in favor
  of doubling the realistic tools-on signal.
- **latest models, recorded per response.** floating aliases mean the
  panel picks up new model releases on the next nightly run, and the
  recorded `model_name_reported` keeps eras separable.
- **LLM-as-judge for sentiment, not regex.** real responses have nuance
  ("$NVDA is exceptional but I'd wait for a pullback") that keyword
  matching mangles.
- **`$TICKER` format directive in the preamble.** makes extraction
  deterministic with a single regex. compliance has been ~100%.

## known limitations

- consumer chat surfaces (chatgpt.com, claude.ai web) not yet captured
- single-vendor classifier (claude haiku); could add a second judge for
  cross-vendor sanity
- US-only personas, US-only ticker universe
- nothing deeper than the 1-day benchmark yet — no multi-day horizons,
  no factor controls (the dataset is too young)

---

MIT licensed. not investment advice. not a recommendation. just an
experiment.
