# pythia

what frontier AI models tell people to buy, captured daily.

every night at 8 PM ET, pythia asks **claude opus 4.7** (claude code CLI),
**gpt-5.5** (codex CLI), and **gemini 3.5 flash** (Gemini API with Google
Search grounding) to recommend stocks — across 10 prompts and two personas
(an aggressive young speculator and a professional allocator), with
tools/search available. every `$TICKER` the model emits is classified by a
smaller LLM as **bullish**, **bearish**, **neutral**, or **context**. raw
text + full JSON traces are gzipped and stored in SQLite. a static
terminal-aesthetic dashboard rebuilds on every run.

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
- a [Gemini API key](https://aistudio.google.com/apikey) (pay-per-token; the flash leg costs cents/day)
- [uv](https://docs.astral.sh/uv/) for Python script execution

```bash
git clone git@github.com:gbasin/pythia.git
cd pythia
sqlite3 db/panel.sqlite < schema.sql      # initialize DB (first time only)

cat > .env <<'ENV'                        # secrets; gitignored, chmod 600 it
GEMINI_API_KEY=...                        # required for the gemini leg
PYTHIA_NTFY_TOPIC=...                     # optional: ntfy.sh push alerts
PYTHIA_HEALTH_REPO=you/your-fork          # optional: gh issues for health alerts
ENV

uv run scripts/run_panel.py --dry-run     # preview the 60-tuple matrix
./scripts/daily_run.sh                    # run_panel → classify → render
open dist/index.html                      # view dashboard
```

the health check's optional transports both come from `.env`: ntfy pushes
go to `PYTHIA_NTFY_TOPIC`, and GitHub issues are filed against
`PYTHIA_HEALTH_REPO` (create the `pythia-health` label there first:
`gh label create pythia-health`). leave either unset to skip that transport.

individual stages:

```bash
uv run scripts/run_panel.py               # full panel (~30 min)
uv run scripts/run_panel.py --prompt-id name_01 --persona-id speculator \
    --model-config-id claude_opus        # one tuple, for smoke-testing
uv run scripts/classify_mentions.py       # label sentiment on new mentions
uv run scripts/classify_mentions.py --reclassify   # nuke + redo all labels
uv run scripts/render_page.py             # rebuild index.html + trends.html + alpha.html + prompts.html
uv run scripts/benchmark_alpha.py --rebuild-signals # 1d open→close alpha check
```

## panel composition

per nightly run: **10 prompts × 2 personas × 3 models = 60 CLI calls**.

every prompt is composed as:
1. `About me:` persona block
2. global preamble (current-state grounding + `$TICKER` format directive)
3. the question (verbatim)

then sent to `claude -p`, `codex exec`, or the Gemini API (via
`scripts/gemini_panel_call.py`, which emits a JSONL trace). the full trace
is gzipped and stored alongside the final response text.

## project layout

```
prompts.yaml                       # 10 prompts + global preamble
personas.yaml                      # 2 personas (speculator, allocator)
model_configs.yaml                 # claude_opus, codex_gpt55, gemini_flash invocation specs
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
(machine local time; assumes ET). launchd needs an absolute program path,
so the tracked plist carries a `/PATH/TO/pythia` placeholder that gets
substituted at install time. Install into the user's LaunchAgents
directory; bootstrapping the copy in `launchd/` directly is only for the
current launchd session and can disappear after reboot/login changes.

first install (run from the repo root):

```bash
mkdir -p ~/Library/LaunchAgents
sed "s|/PATH/TO/pythia|$PWD|" launchd/com.pythia.daily.plist \
  > ~/Library/LaunchAgents/com.pythia.daily.plist
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.pythia.daily.plist
launchctl print gui/$UID/com.pythia.daily
```

after editing `launchd/com.pythia.daily.plist`, reinstall and reload:

```bash
launchctl bootout gui/$UID/com.pythia.daily 2>/dev/null || true
sed "s|/PATH/TO/pythia|$PWD|" launchd/com.pythia.daily.plist \
  > ~/Library/LaunchAgents/com.pythia.daily.plist
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.pythia.daily.plist
launchctl print gui/$UID/com.pythia.daily
```

remove the schedule:

```bash
launchctl bootout gui/$UID/com.pythia.daily
rm ~/Library/LaunchAgents/com.pythia.daily.plist
```

## dashboard

after a run, view at:
- `file:///.../pythia/dist/index.html`
- `python3 -m http.server 8731 -d dist` → `http://localhost:8731`
- accessible over Tailscale at the same URL via IP / MagicDNS

three pages:
- `/` — current snapshot + trend highlights
- `/trends.html` — rolling ranks, first sightings, provider consensus, day index
- `/alpha.html` — paper benchmark: top-20 recommendation flow vs all mentioned
- `/prompts.html` — full prompts + personas + an example of what the model literally sees

## design decisions

- **coding-agent surfaces, not consumer chat.** claude code and codex exec
  are scriptable under authenticated subscriptions and capture the "AI
  agent" surface. the gemini leg originally ran through the Antigravity
  CLI, but its subscription weekly caps made nightly runs unreliable, so it
  was switched to the Gemini API with Google Search grounding (the closest
  equivalent surface). consumer chat (chatgpt.com, claude.ai,
  gemini.google.com) is deferred to a later version — it'd need browser
  automation.
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
- `daily_signals`, `prices`, `forward_returns` — lazily created by
  `scripts/benchmark_alpha.py` for the simple top-20 vs all-mentioned
  next-session open→close benchmark

set `PYTHIA_DB_PATH` to point every script at a database somewhere else
(useful for testing against a copy).

## known limitations (later versions)

- consumer chat surfaces (chatgpt.com, claude.ai web) not yet captured
- single-vendor classifier (claude haiku) — could add gpt-mini for cross-vendor sanity
- US-only personas, US-only ticker universe
- no price-impact backtests yet (the dataset is too young; need weeks of data first)

---

MIT licensed. not investment advice. not a recommendation. just an
experiment.
