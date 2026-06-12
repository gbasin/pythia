# DESIGN.md: pythia

Direction: **Qt desktop app**. The whole site renders as a single desktop
application window — Qt Widgets, Fusion style — sitting on a dark desktop
backdrop. Lineage: Qt Fusion (light + dark palettes), classic
QTableView/QGroupBox density, Bloomberg-terminal-adjacent data chrome.
Light is canonical; dark ships as a Fusion-dark `prefers-color-scheme`
palette. Built as its own palette; do not invert.

(The previous paper-datasheet direction was retired 2026-06-12; this
replaced it wholesale.)

## The window metaphor

Every page is the same app window:

- **Title bar**: app icon + window title (together a home link back to
  the index — the Qt heir to the wordmark link) + decorative
  min/max/close. Title carries the page identity ("Pythia — Nightly
  Panel No. N — date", "Pythia — Trends", "Pythia — Session <date>").
  No menu bar: a File/Edit row would be all dead entries, and dead
  controls are banned.
- **Toolbar**: real controls only — ◀ / date combo (a styled `<select>`
  with a one-line `onchange` redirect, the site's only JS) / ▶ for session
  navigation, Raw data link, About link. No dead buttons.
- **Sessions dock** (left): QListView of clean nights, newest first,
  selected row in highlight blue. Hidden below 900px.
- **Tab bar**: Overview / Trends / Scoreboard / Methodology = the four
  pages. A day page opens as a closable document tab next to Overview
  ("2026-06-11 ✕"); the ✕ closes the session back to the index, and
  Overview stays clickable. Never render the current page's escape
  hatch as a dead active tab.
- **Status bar**: sunken cells — panel number, responses ok/total, last
  panel time, the not-investment-advice line with methodology/raw-data
  links — plus a size grip. `position: sticky; bottom: 0`.

Content lives in QGroupBoxes: 1px frame, floating bold 12px title over
the border. Section headers, labels, and "h2" prose headers all fold into
group-box titles ("Flow — night of 2026-06-12 (net = bullish − bearish
across 60 responses)").

## Palette

Hex, Fusion-derived, all swappable via CSS custom properties.

Light (canonical): window `#efefef`, base `#ffffff`, alternate `#f6f6f6`,
text `#1c1c1c`, dim `#6b6b6b`, frame `#b4b4b4`, highlight `#308cc6`,
up `#1d6fa5`, down `#b3261e`, link `#0a66b8`.

Dark (Fusion dark): window `#353535`, base `#232323`, alternate `#2b2b2b`,
text `#d8d8d8`, highlight `#2a82da`, up `#6ab0e8`, down `#e57368`.

Backdrop: dark radial gradient desktop behind the window in both schemes.
Deltas always carry +/- signs so hue stays redundant.

## Typography

- UI text: system stack (`Segoe UI, Helvetica Neue, Cantarell, Ubuntu`),
  13px base, 12px in tables/controls, 11px status/captions. Desktop-app
  small.
- Data still respects `font-variant-numeric: tabular-nums lining-nums`.
- JetBrains Mono survives only where it earns it: sparklines, sample
  response bodies, methodology `<pre>` blocks.
- Table headers `text-transform: capitalize`, 600 weight, gradient fill.

## Widgets

- **Tables** are QTableViews: gradient header cells with 1px separators,
  alternating row colors, hover row highlight, 1px sunken frame, dense
  3px/8px cell padding.
- **Flow bars** are QProgressBars: 1px border, blue gradient chunk
  (red for negative net), signed value centered over the bar.
- **Persona split** is a diverging widget bar around a 2px center axis:
  gray allocator segments grow left, blue speculator segments grow right.
- **Charts** sit in a sunken white plot frame with a legend row (swatch +
  label, top-left). Gridlines light gray, dashed zero line, models line
  2px in up/down color, QQQ 1.4px gray. Inline SVG, build-time, no JS.
- **Record strip** is LED squares: filled blue = ran, open = missed,
  half-filled = excluded. Squares link to day pages.
- **Sample responses** are read-only text areas: framed white boxes with
  a gradient header strip (response id · age · prompt × persona ×
  provider), mono body.
- **Sparklines** stay unicode block glyphs (U+2581-2588, `·` for absent),
  11px mono, gray.

## Motion

Essentially none. Hover states on buttons/tabs/rows/menu items, native
`details` disclosure (▸/▾). No transitions, no entrance animations.

## Bans

Dead controls that look clickable but go nowhere (decorative chrome must
be `aria-hidden` and obviously inert: window buttons, dock glyphs; this
ban is why there is no menu bar). Rounded-blob cards, glassmorphism, gradient text, pies, gauges,
dual y-axes, em dashes in copy. No flat-web aesthetics inside the window:
if an element exists, it should look like a Qt widget.

## Accessibility floor

Text contrast >= 4.5:1 against its ground in both palettes. Hue never the
only encoding (signs on every delta). SVG charts carry role="img" +
aria-label with the headline value. Decorative chrome aria-hidden; the
tab bar and dock are real links. OG/meta/favicon present on every page.

## Mobile (< 900px)

Window goes full-bleed (no backdrop, border, or shadow), dock hides
(toolbar combo still navigates sessions), teaser grid and scoreboard
stack to one column, sparkline column drops from the flow table, progress
bars shrink to 120px. Wide tables scroll inside `.scroll` wrappers.
