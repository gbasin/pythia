# PRODUCT.md: pythia

register: product

## What this is

A nightly measurement instrument, published as a static site. Every night at
8 PM ET pythia asks Claude, GPT-5.5, and Gemini the same 10 retail investing
questions under 2 personas (60 responses), classifies every $TICKER mention as
bullish/bearish/neutral/context, and publishes:

1. **Recommendation flow**: the net bullish-minus-bearish push per ticker,
   nightly. The unique data; meaningful every single night.
2. **Scoreboard**: a paper backtest of the top-20 basket vs QQQ (next session
   open to close). The accountability layer, framed as measurement, not pitch;
   the framing must survive negative alpha and small-sample dismissals.

Thesis: AI chatbots are quietly becoming a retail market force, and nobody is
measuring the recommendations themselves in public.

## Users

- **The HN/fintwit skeptic** (primary, launch): arrives from a link, decides in
  seconds whether this is rigorous measurement or AI-trading hype. Will attack
  look-ahead/leakage, execution assumptions, survivorship, sample size, and the
  models-reading-the-dashboard feedback loop. Win them by pre-empting every
  attack in visible methodology.
- **The returning checker**: opens it premarket on a phone. Wants what changed
  tonight: new names, consensus shifts, the one-sentence insight.
- **The journalist/researcher**: needs methodology, exact prompts, raw data,
  citations.
- **Not a user of public surfaces**: the operator. Run commands, panel_version,
  ops tables, and operator empty states never appear on visitor pages.

## Voice and tone

Deadpan engineering document. The site is a dated nightly artifact (panel
number, as-of stamps, source lines), not a product pitch. Honesty is the brand:
caveats stated before the skeptic finds them, uncertainty shown inline, the
scoreboard published win or lose. Lowercase, terse, zero hype. No em dashes.

## Strategic principles

- Verdict-first, but the verdict is the flow: "here is what they're telling
  people to buy tonight." The scoreboard is the standing second band.
- Every number gets its comparator (QQQ is a peer row/line, never absent).
- Freshness at item level: every panel carries its own "as of" stamp.
- Raw data one click away: GitHub, SQLite, prompts, traces.
- One written sentence of nightly insight on the hero; annotation over chrome.
- No jargon without definition in place ("clean days" is banned; show the
  pipeline strip and audit count instead).

## Anti-references

- Alpha Arena: polish without disclosure; hype framing that collapsed under
  scrutiny.
- usdebtclock: ticking numbers without comparators; anxiety as design.
- Green-on-black hacker terminal templates: scanlines, typewriter effects,
  Matrix rain, boot sequences.
- SaaS dashboard kit: hero-metric cards, gauges, drop shadows, card grids.

## Surfaces

- `index.html`: dek, tonight's flow (hero), scoreboard band, first sightings +
  consensus teasers, pipeline strip, footer (methodology, data, disclaimer).
- `day/DATE.html`: the nightly artifact in full: flow, per-ticker breakdown,
  persona delta, response samples.
- `trends.html`: 7d / 30d / all-time windows, first sightings, consensus.
- `alpha.html`: scoreboard in full: equity curve, definition, daily rows.
- `methodology.html`: prompts, personas, pipeline, classification, refusal
  handling, leakage/execution/survivorship caveats, feedback-loop note.
