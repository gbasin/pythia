# DESIGN.md: pythia

Direction: **paper datasheet**. A dated engineering document on warm paper,
all monospace, set on a true character grid. Lineage: Berkeley Graphics /
US Graphics datasheets, Oxide's mono discipline, Economist chart rules.
Light is canonical; dark ships as a secondary `prefers-color-scheme` palette.

## Color

OKLCH only. Never #000 or #fff. Budget: ground + ink + two grays + one accent
+ two semantic deltas. Nothing else.

Light (canonical, "paper"):

- `--paper`:  oklch(0.96 0.008 90)   warm off-white ground
- `--ink`:    oklch(0.24 0.012 90)   warm near-black text
- `--dim`:    oklch(0.47 0.012 90)   secondary text (passes 4.5:1 on paper)
- `--faint`:  oklch(0.87 0.008 90)   hairlines, gridlines; never used as text
- `--accent`: oklch(0.60 0.12 70)    ochre stamp ink; ritual marks only
                                     (top rules, the panel number, links)
- `--up`:     oklch(0.48 0.10 245)   blue, bullish/positive
- `--down`:   oklch(0.48 0.13 20)    claret, bearish/negative

Dark (secondary): ground oklch(0.19 0.008 90), text oklch(0.89 0.01 90),
desaturate accent and deltas one step; hairlines oklch(0.30 0.008 90).
Build it as its own palette; do not invert.

Rules: red/green is banned as the only encoding; deltas always carry +/- signs
so hue is redundant. Color the 3-5 tickers the story is about; gray the rest.

## Typography

- One family: JetBrains Mono (box-drawing stays connected at 120%+ line
  height), fallback ui-monospace stack. Berkeley Mono is the upgrade path if
  purchased; nothing else changes.
- `font-variant-numeric: tabular-nums lining-nums` globally. Non-negotiable.
- Three sizes only: 12px labels (uppercase, +0.08em tracking), 14px body/data,
  21px section display. Hierarchy beyond that is weight (400/700) and dimming
  (`--dim`), never more sizes.
- Prose measure capped at 72ch.

## Grid and layout

- Character grid: cell = 1ch x var(--lh) where --lh: 1.5rem (21px). Every
  box height and vertical margin is a whole multiple of --lh.
- Page width in characters, stepping down whole columns:
  `max-width: calc(min(100ch, round(down, 100%, 1ch)))`. This is also the
  mobile strategy: columns drop, nothing clips, no horizontal scroll at 390px.
- Section gaps generous (3-4 line units); rhythm varies, padding is not
  uniform. No cards, no nested containers. Structure comes from rules:
  a 2px accent top rule opens a section, 1px `--faint` hairlines divide rows.
- Document frame: masthead carries the dek and the panel number / timestamp
  block; every chart and table closes with a source line in `--dim`
  ("Source: nightly model runs - prices via yfinance - as of <date>").

## Charts

- Time series are inline SVG (build-time generated, no JS), styled to the
  grid: horizontal gridlines only (3-5, `--faint`), no y-axis line, y labels
  right-aligned above gridlines, solid baseline only, direct labels at line
  ends (never legends), marked zero line, `vector-effect: non-scaling-stroke`,
  axis text in 12px mono tabular-nums.
- QQQ is always the gray reference line; the basket takes a semantic color.
- Unicode bars and sparklines live only inside tables (block elements
  : U+2581-2588, dot for absent days), sized in ch so they sit on the grid.
  They never appear as a standalone hero chart.
- The pipeline strip is the one status visual: one square per night
  (filled ran / open missed / dotted excluded).

## Motion

Essentially none. Native `details` disclosure, CSS :hover color shifts
(ease-out, <150ms). No typewriter effects, no cursors, no scanlines, no
entrance animations.

## Components

- **Masthead**: PYTHIA wordmark, two-line dek, right-aligned stamp block
  (NIGHTLY PANEL No. N, date/time ET, responses ok/total).
- **Flow table** (hero): ticker, signed net, bar in ch units, 14d sparkline;
  one written insight sentence beneath it.
- **Scoreboard band**: compact SVG curve vs QQQ + one number with units and
  session count, caveat inline ("not yet significant" while n is small).
- **Data tables**: 1px `--faint` row rules, header row 700 over hairline,
  numbers right-aligned, text left-aligned, bars-in-cells welcome.
- **Day nav**: character strip, current night in accent, never scrolls the
  current day out of view.

## Bans

Side-stripe borders, gradient text, glassmorphism, hero-metric cards, gauges,
pies, dual y-axes, legends where direct labels fit, vertical gridlines,
em dashes in copy, green-on-black, CRT cosplay of any kind.

## Accessibility floor

All text contrast >= 4.5:1 against its ground (this killed the old #7a766b
dim and #1a1a1a-as-text). Hue never the only encoding. SVG charts carry
role="img" + aria-label stating the headline value. OG/meta/favicon present
on every page so link previews carry the dek.
