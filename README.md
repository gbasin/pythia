# pythia

what frontier AI models tell people to buy, captured daily.

every night at 8 PM ET, pythia asks **claude opus 4.7** and **gpt-5.5** to
recommend stocks — across 10 prompts, two personas (an aggressive young
speculator and a professional allocator), with web search enabled. every
`$TICKER` the model emits is classified by a smaller LLM as **bullish**,
**bearish**, **neutral**, or **context**. raw text + full JSON traces are
gzipped and stored in SQLite. a static terminal-aesthetic dashboard rebuilds
on every run.

## what this measures

hundreds of millions of people now use ChatGPT and Claude as a first stop
for investment ideas. the recommendations they receive — which names get
praised, which get dismissed, which are repeatedly singled out as winners —
quietly become a market force as retail follows. pythia measures this
**recommendation flow** in public: the net bullish-minus-bearish push per
ticker, broken down by persona and provider, over time.

prompts deliberately mirror real retail queries, including ones that name
specific tickers ("is NVDA a buy?"). the volume of recommendation those
names receive is the signal we're capturing, not a bias to scrub.

## quick start

prereqs (macOS):
- [Claude Code CLI](https://docs.claude.com/claude-code) authenticated with a Pro/Max subscription
- [Codex CLI](https://github.com/openai/codex) authenticated with a ChatGPT Pro subscription
- [uv](https://docs.astral.sh/uv/) for Python script execution

```bash
git clone git@github.com:gbasin/pythia.git
cd pythia
sqlite3 db/panel.sqlite < schema.sql      # initialize DB (first time only)

uv run scripts/run_panel.py --dry-run     # preview the 40-tuple matrix
./scripts/daily_run.sh                    # run_panel → classify → render
open dist/index.html                      # view dashboard
```

individual stages:

```bash
uv run scripts/run_panel.py               # full panel (~30 min)
uv run scripts/run_panel.py --prompt-id name_01 --persona-id speculator \
    --model-config-id claude_opus        # one tuple, for smoke-testing
uv run scripts/classify_mentions.py       # label sentiment on new mentions
uv run scripts/classify_mentions.py --reclassify   # nuke + redo all labels
uv run scripts/render_page.py             # rebuild index.html + prompts.html
```

## panel composition

per nightly run: **10 prompts × 2 personas × 2 models = 40 CLI calls**.

every prompt is composed as:
1. `About me:` persona block
2. global preamble (current-state grounding + `$TICKER` format directive)
3. the question (verbatim)

then piped to `claude -p` or `codex exec` over stdin. the full JSONL trace
(every web search, every reasoning step) is gzipped and stored alongside
the final response text.

## project layout

```
prompts.yaml                       # 10 prompts + global preamble
personas.yaml                      # 2 personas (speculator, allocator)
model_configs.yaml                 # claude_opus, codex_gpt55 CLI specs
schema.sql                         # sqlite schema

scripts/run_panel.py               # orchestrator
scripts/classify_mentions.py       # LLM-as-judge sentiment labeler (haiku)
scripts/render_page.py             # static html dashboard generator
scripts/daily_run.sh               # wrapper: run_panel → classify → render

launchd/com.pythia.daily.plist     # 8 PM ET nightly schedule

db/panel.sqlite                    # all data (gitignored)
dist/index.html                    # main dashboard (gitignored)
dist/prompts.html                  # prompts review subpage (gitignored)
logs/panel-YYYYMMDD.log            # per-run logs (gitignored)
```

## schedule

a launchd agent fires `scripts/daily_run.sh` nightly at **8 PM ET**
(machine local time; assumes ET).

```bash
launchctl bootstrap gui/$UID launchd/com.pythia.daily.plist   # load
launchctl bootout    gui/$UID/com.pythia.daily                # unload
launchctl print      gui/$UID/com.pythia.daily                # inspect
```

## dashboard

after a run, view at:
- `file:///.../pythia/dist/index.html`
- `python3 -m http.server 8731 -d dist` → `http://localhost:8731`
- accessible over Tailscale at the same URL via IP / MagicDNS

two pages:
- `/` — net recommendation flow, persona contrast, sample responses, methodology, runs
- `/prompts.html` — full prompts + personas + an example of what the model literally sees

## design decisions

- **coding-agent CLI surfaces, not consumer chat or API.** claude code and
  codex exec are scriptable, free under our subscriptions, and capture the
  "AI agent" surface. consumer chat (chatgpt.com, claude.ai) is deferred
  to a later version — it'd need browser automation.
- **named-ticker prompts kept on purpose.** "is NVDA a buy?" is what real
  retail asks; the volume of recommendation those names receive is the
  flow signal, not a bias to scrub. unopinionated rephrasing would measure
  what AI spontaneously recommends in a vacuum — less useful.
- **no tools_off variant (v1.1+).** earlier we ran a variant with web
  search disabled to measure training-data baselines. codex has no
  documented way to actually disable web search, so the comparison was
  asymmetric. dropped in favor of doubling the realistic tools-on signal.
- **LLM-as-judge for sentiment**, not regex. real responses have nuance
  ("$NVDA is exceptional but I'd wait for a pullback") that keyword
  matching mangles. claude haiku 4.5 reads each response and labels each
  ticker as bullish / bearish / neutral / context.
- **`$TICKER` format directive in the preamble.** makes extraction
  deterministic — a single regex `\$[A-Z]{1,5}\b` catches every mention.
  compliance has been ~100% so far.

## data

everything lives in `db/panel.sqlite`. schema highlights:

- `runs` — one per panel invocation
- `prompts`, `personas` — versioned by content hash (edits don't break old data)
- `model_configs` — one per CLI variant
- `responses` — `raw_text` + `raw_trace_gz BLOB` (gzipped full JSONL) +
  tokens, latency, session_id
- `mentions` — one row per unique ticker per response, with classifier
  `sentiment_hint` ∈ {bullish, bearish, neutral, context} and 1-indexed
  `position`

## known limitations (later versions)

- consumer chat surfaces (chatgpt.com, claude.ai web) not yet captured
- single-vendor classifier (claude haiku) — could add gpt-mini for cross-vendor sanity
- US-only personas, US-only ticker universe
- no price-impact backtests yet (the dataset is too young; need weeks of data first)

---

private personal-research repo. not investment advice. not a recommendation.
just an experiment.
