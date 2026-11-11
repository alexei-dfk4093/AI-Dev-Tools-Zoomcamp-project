## 12. Visual Design Direction: Market Terminal

### Design Philosophy

The EcoMind frontend uses a dark "market terminal" editorial identity:
a near-black financial intelligence surface with a single red accent,
oversized mono numerals, and hairline-separated story rows.

It communicates: live financial intelligence, analytical precision, and a
data-first reading experience. Avoid crash console aesthetics, heavy
glow effects, and decorative gradients beyond the subtle row accents.

### 12.1 Color System

- Page background: Deep Charcoal (#0e0f13).
- Card surface: (#16181d), elevated surface (#1d2027).
- Text: near-white (#f2f3f5); secondary text (#9ba1ab).
- Lines/hairlines: (#2a2e36).
- Accent: Terminal Red (#ef5350) for numerals, labels, primary actions.
- Financial semantics: green #3fb950 (positive), red accent (negative),
  amber #d29922 (uncertainty). Never use color as the only indicator.

### 12.2 Typography

- Archivo for headings (weight 700-800, tight letter-spacing).
- Inter for body text.
- IBM Plex Mono for publication timestamps, metadata, timestamps, labels, buttons.

### 12.3 Layout

- Single hairline-separated feed column (1px gap grid, not card stacks).
- Exact UTC publication stamp in the left column of every row, split into a
  muted date line (NOV 10) and an accent-red clock line (13:00:00Z). The
  machine-readable ISO value stays on the `time` element.
- Source and relative age (5H AGO) in mono caps above the headline.
- Sticky top bar with translucent background and backdrop blur.
- Asset panels use a 3px red left rule; user chat bubbles are soft-red.
- A footer strip identifies the product and the not-investment-advice caveat.

### 12.4 Interaction

- Hover: background lift to the elevated surface + red left rule fade-in
  on the story row; headline tint to red on hover/focus.
- Transitions are 140-180ms ease; respect prefers-reduced-motion.
- Avoid decorative animation inside analytical content.

### 12.5 Feed Freshness

- The toolbar shows the story count, the age of the newest headline, and a
  Refresh control. The age is derived from the newest article's publication
  time, so provider lag is visible rather than silent.
- Refresh calls `GET /api/v1/news?refresh=true` to pull from the provider;
  the feed re-polls every two minutes (without forcing) so new stories
  appear without a reload.
- New items are merged into the existing list and de-duplicated by id, so a
  refresh never drops stories the reader already loaded.
- While loading, the feed renders viewport-filling skeleton rows so the
  arriving content does not shift visible elements (keep CLS at 0).

### 12.6 Discussion Window

- The article analysis block shows the reported effect as a badge
  (positive, neutral, negative) with its summary and the reported reasons.
- Below it, the related companies and markets the article connects to the
  story, each labelled as named in the article or potential exposure.
- The question list is generated from the article itself, never from a fixed
  template. Clicking a question fills the composer so the reader can edit it
  before sending.
- Scrollable regions must stay keyboard reachable (`tabindex` plus a label),
  and the analysis block reserves its height so the page does not shift when
  the analysis arrives.

### 12.7 Restrictions

- Keep dark-on-dark contrast AA-verifiable (verify text colors by math).
- Reuse the design tokens declared on .app-shell.
- Do not reintroduce the cream constructivist palette or offset shadows.
- Do not redesign unrelated sections when implementing individual features.

### 12.8 Discussion Iteration Loop

Use bounded Ralph-style iterations when improving the discussion experience:

1. State the user-visible problem and the smallest verifiable acceptance criteria.
2. Make one coherent improvement to the discussion flow, not an unrelated redesign.
3. Run the focused frontend tests, lint, and build; inspect desktop and narrow
   viewport behavior when layout or interaction changes.
4. Review the rendered result and test output, then make another pass only to
   address a concrete gap or regression.
5. Stop when the acceptance criteria pass; report any remaining limitation
   rather than continuing an open-ended rewrite.

Keep the article context from crowding out the conversation. Preserve the
source link, distinguish the reader's messages from AI analysis, keep the
transcript keyboard reachable, and retain an unsent question when a request
fails without adding a failed turn to the next request's conversation history.