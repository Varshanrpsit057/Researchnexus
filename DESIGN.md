---
name: ResearchNexus
description: A library card-catalog system for evidence-grounded literature review, not another AI dashboard
colors:
  surface: "#f5f6f3"
  surface-raised: "#fdfdfb"
  surface-sunken: "#e8e9e4"
  ink: "#1a1c19"
  ink-muted: "#52564e"
  ink-subtle: "#6d716a"
  border: "#dcddd6"
  border-strong: "#b5b9b0"
  accent: "#0c655e"
  accent-strong: "#084d47"
  accent-foreground: "#f2fbfa"
  accent-wash: "#e0efec"
  verified: "#3d7a41"
  verified-wash: "#e6f1e5"
  warning: "#8a5c14"
  warning-wash: "#f5eeda"
  danger: "#96393a"
  danger-wash: "#f5e8e7"
typography:
  display:
    fontFamily: "Libre Franklin, ui-sans-serif, system-ui, sans-serif"
    fontWeight: 600
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Libre Franklin, ui-sans-serif, system-ui, sans-serif"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Courier Prime, ui-monospace, monospace"
    fontSize: "0.6875rem"
    letterSpacing: "0.05em"
  data:
    fontFamily: "Courier Prime, ui-monospace, monospace"
    fontVariation: "tabular-nums"
rounded:
  xs: "0.125rem"
  sm: "0.125rem"
  md: "0"
  lg: "0"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    rounded: "{rounded.sm}"
    padding: "0 1rem"
    height: "2.5rem"
  button-primary-hover:
    backgroundColor: "{colors.accent-strong}"
  button-secondary:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
  badge:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.accent-strong}"
    rounded: "{rounded.xs}"
    padding: "0.125rem 0.375rem"
---

# Design System: ResearchNexus

## Overview

**Creative North Star: "The Card Catalog"**

ResearchNexus reads like a library's card-catalog drawer, not a chatbot wrapped in a dashboard template. Every ranked result, typed relationship, and generated claim carries the receipts that produced it: the per-signal score, the fired rule, the verbatim evidence span, filed the way a cataloger's tracing or stamp is filed. The system deliberately rejects two adjacent aesthetics: the soft, purple-glowing "AI product" look (no gradients, no glow, no chat-bubble whimsy), and the dense, chart-heavy analytics-dashboard look (no gauges, no decorative sparklines, no color-coded KPI tiles standing in for real numbers). What replaces both is an index card: a cool paper-white/bone ground (never warm cream), graphite ink, ruled hairlines doing the separating work borders and shadows used to do elsewhere, sharp square corners on every card and container, and one committed accent — a deep stamp-ink teal — used only the way a cataloger's stamp or colored pencil is used, on specific typed marks, never as decoration.

Density follows the surface's job. The landing page (the one Persuade-mode surface) is spacious and editorial, built to be read once and acted on. Everything behind login (Operate mode: upload, profile, discovery, trail, and the ten workspace tabs) is dense and scannable by design, favoring information density and consistent, learnable patterns over expressive flourish. The same card anatomy (a header line, a ruled body, and a tracings footer), the same specimen-label badge, and the same evidence-disclosure pattern recur across every Operate screen so a researcher who learns one tab already knows the other nine.

**Key Characteristics:**
- Cool paper-white/bone ground with a single stamp-ink teal accent, never blue or purple
- Every numeric or identifying value (scores, ids, timestamps, counts) set in Courier Prime with tabular figures
- A separate functional color layer (verified / warning / danger) exists only to mark evidence status, never as brand decoration
- Sharp square corners everywhere except small interactive controls, which keep a hairline 2px softening so they still read as pressable
- Specimen-label badges: mono, uppercase, letter-spaced, bordered-with-wash, never a filled pill

## Colors

A restrained cool-neutral ground carries almost the whole interface; the one accent and the three semantic tones are reserved for moments that are actually informative.

### Primary
- **Stamp-Ink Teal** (`#0c655e`, `accent`): the single brand accent. Primary buttons, active tab underline, focus rings, links, badge accents, and the confidence-band mark. Deliberately a deep teal, not blue or purple, so it reads as a cataloger's ink stamp rather than an "AI product" hue. Never used decoratively (no gradients, no glows). Lightens to `#55b8ad` in dark mode.

### Neutral
- **Paper** (`#f5f6f3`, `surface`): the page ground — cool bone, never warm cream.
- **Card Stock** (`#fdfdfb`, `surface-raised`): cards, the app header, dialogs, anything that sits one level above the page.
- **Recessed Drawer** (`#e8e9e4`, `surface-sunken`): hover rows, drag-active states, anything one level below the page.
- **Ink** (`#1a1c19`, `ink`): primary text.
- **Ink Muted** (`#52564e`, `ink-muted`): secondary text, descriptions, body copy in cards.
- **Ink Subtle** (`#6d716a`, `ink-subtle`): de-emphasized but real content — ids, timestamps, hint text, the tracings footer.
- **Border** (`#dcddd6`) / **Border Strong** (`#b5b9b0`): hairline dividers vs. input/card outlines that need to read as interactive.

### Functional (status, not brand)
- **Verified Green** (`#3d7a41` on `#e6f1e5` wash): a claim, edge, or gap the user has accepted, or a "high" confidence read.
- **Warning Amber** (`#8a5c14` on `#f5eeda` wash): a partial failure (a discovery strategy that failed, an unresolved citation) — informative, not blocking.
- **Danger Red** (`#96393a` on `#f5e8e7` wash): a rejected edge/gap/direction, or a destructive action.

### Named Rules
**The One Accent Rule.** Stamp-Ink Teal is the only brand color in the system. If a screen needs a second color, it is one of the three functional tones above, applied only to mark real evidence status, never as decoration.

**The Never-a-Percentage-Alone Rule.** Confidence is always a labeled band (high/medium/low) paired with its glyph (● / ◐ / ○), never a bare number dressed up as a percentage. Real per-signal scores appear in mono next to their name; nothing is ever fabricated to fill a visual slot.

## Typography

**Display / UI Font:** Libre Franklin (with `ui-sans-serif, system-ui, sans-serif` fallback)
**Label / Mono Font:** Courier Prime (with `ui-monospace, monospace` fallback)

**Character:** Libre Franklin is a clean, slightly condensed grotesque that carries both the landing page's headlines and every Operate-mode label without switching families. Courier Prime is a true typewriter face, chosen deliberately over a coder-monospace like JetBrains Mono to reinforce the card-catalog metaphor: every value it sets (a similarity score, a paper id, a timestamp, a token count) looks struck on the same typewriter that typed the rest of the card, and tabular figures keep columns of numbers from jittering as they update.

### Hierarchy
- **Display** (600 weight, `text-4xl`–`text-5xl`, tracking `-0.025em`): the landing page's hero headline only.
- **Headline** (600 weight, `text-xl`–`text-2xl`, tracking `-0.025em`): page and section titles (paper title, workspace title, section headers). Every `h1`–`h4` gets `-0.025em` tracking globally via `--tracking-tightest`; do not re-tighten with a second utility class.
- **Body** (400 weight, `text-sm`, line-height 1.6): all prose — descriptions, explanations, chat messages.
- **Label** (500 weight, `0.6875rem`, `0.05em` tracking, uppercase, mono): badges and specimen labels — relationship types, discovery methods, provenance status, gap/direction kinds.
- **Data** (mono, tabular-nums): scores, ids, counts, costs, timestamps, token budgets.

### Named Rules
**The Mono-Is-Measurement Rule.** Courier Prime is reserved for values that are literally measured or identified (scores, ids, counts, timestamps). It never appears on prose or headings; that boundary is what keeps it reading as instrumentation rather than a costume.

## Layout

Operate-mode pages sit inside the app shell's `max-w-[1400px]` container with `px-4 py-6`; individual pages narrow further where the content is read top-to-bottom rather than scanned (the upload flow and paper-profile grid cap around `max-w-2xl`–`max-w-5xl`). The workspace tab shell reuses one `layout.tsx` (header, budget bar, tab strip) so none of the ten tabs re-implements chrome. Two-column data (the research-profile field grid, the landing page's mechanism section) collapses to one column below `lg:`/`sm:` respectively; nothing depends on a wide viewport to remain usable. Wide tabular content (the comparison table, the activity log) scrolls horizontally inside its own container rather than the page.

The app header is the one place that needed an explicit narrow-viewport pass this phase: below `sm:`, the wordmark collapses to its icon alone and the "Upload paper" button collapses to icon-only, both keeping an explicit `aria-label` so nothing loses its accessible name; "Papers" and "Workspaces" stay as visible text links at every width since neither has an alternate path.

## Elevation & Depth

Flat by default. Cards are distinguished from the page by a hairline border and background-tone shift (`surface-raised` vs `surface`), not a shadow. The one exception is genuinely floating content — the Dialog's surface and its `open` animation — which gets a real shadow because it is actually elevated above the page.

### Shadow Vocabulary
- **Skip-link lift** (`0 4px 16px rgb(var(--shadow-color) / 0.16)`): the barely-there lift under the keyboard-only skip-to-content link when it becomes visible on focus.
- **Dialog lift** (`0 16px 40px rgb(var(--shadow-color) / 0.22)`): the one true elevated surface in the system.

### Named Rules
**The Flat-Unless-Floating Rule.** A shadow appears only on content that is actually above the page in z-order (a dialog, a focused skip-link). A card sitting in the document flow gets a border and a tone shift, never a shadow standing in for one.

## Shapes

Sharp square corners by default — `--radius-md` and `--radius-lg` are both `0`. Cards, dialogs, and every larger container stay fully square, following the system's own stated logic: "an index card has corners, not curves." The one documented exception is small interactive controls — buttons, inputs, and the badge/stamp glyph — which keep a hairline-soft `0.125rem` (`--radius-xs` / `--radius-sm`) so they still read as pressable at their size. Nothing in the system uses a pill/full radius; that would break the card-catalog metaphor.

### Named Rules
**The Index-Card Rule.** Radius is earned only by small controls that need to read as pressable. Every card, dialog, and container is square; only buttons, inputs, and badges get the `0.125rem` softening.

## Components

### Buttons
- **Shape:** `0.125rem` radius (`rounded-xs`, via `rounded-sm` Tailwind utility mapped to the token), `h-8` (sm) / `h-10` (md).
- **Primary:** Stamp-Ink Teal background, `accent-foreground` text; hover darkens to `accent-strong`.
- **Secondary:** `surface-raised` background, `border-strong` outline, hover darkens the border only (no fill change).
- **Ghost:** no background or border at rest; hover gets a `surface-sunken` wash.
- **Danger:** filled with the danger tone, for destructive actions only.
- **Press feedback:** every button scales to `0.97` on `:active`.

### Badges (the signature component)
- **Style:** mono, uppercase, `0.6875rem`, `0.05em` tracking, `0.125rem` radius (`rounded-xs`), always bordered with a matching wash background — never a solid filled pill. This is the one component that is genuinely distinctive to this product: it is how every typed, classified, or scored value in the system announces itself as data rather than decoration.
- **Tones:** neutral (border-strong/ink-muted), accent (Stamp-Ink Teal wash), verified/warning/danger (the functional layer). `ConfidenceBadge` is a separate, lighter mark — plain mono text with a ●/◐/○ glyph, no border or fill, "the way a cataloger's pencil mark sits directly on the card rather than in its own little box."

### Cards / Containers
- **Corner Style:** sharp square (`0` radius) — no exception for cards.
- **Background:** `surface-raised` on `surface`.
- **Shadow Strategy:** none (see Elevation) — separation is a hairline border and tone shift only.
- **Border:** 1px `border`.
- **Internal Padding:** `CardHeader`/`CardBody` at `px-4 py-3`.
- **Card anatomy (system-wide pattern):** a header line, a ruled body, and — where the entity carries real cross-references — a `CardTracings` footer, present even when empty ("no tracings filed" rather than omitting the line). Used identically for papers, trail edges, gaps, and directions so absence of evidence is never silent.

### Inputs / Fields
- **Style:** `border-strong` outline, `surface-raised` fill, `0.125rem` radius.
- **Focus:** 2px `accent`-colored outline, offset (browser-native `:focus-visible`, not a custom ring shadow).
- **Error:** `user-invalid` variant swaps the border and background to the danger wash the moment a field is both touched and invalid.

### Navigation
- **App header:** `surface-raised` on a hairline bottom border, icon+wordmark home link, text links for Papers/Workspaces, icon-only secondary actions (upload, settings, sign out) each carrying their own `aria-label`.
- **Workspace tab strip:** underline-style tabs (accent underline on the active tab, transparent otherwise), not filled pills — consistent with the badge system's "border and wash, not fill" language.

### Evidence Disclosure (signature pattern)
A `<details>`/`<summary>` pair used identically everywhere a quoted source span backs a claim (profile fields, trail edges, gaps): a small quote-icon summary line that expands into a left-bordered, mono-adjacent quote block with its section/page. Native, keyboard-operable, zero extra state. This pattern, more than any single color or font, is what makes the "never show a claim without its source" product principle a real, everyday interaction rather than a slogan.

## Do's and Don'ts

### Do:
- **Do** set every score, id, timestamp, and count in Courier Prime with tabular figures.
- **Do** use the bordered-badge-with-wash pattern for every typed/classified value (relationship type, discovery method, gap type, provenance status).
- **Do** keep cards, dialogs, and containers sharp-cornered; reserve the `0.125rem` radius exception for buttons, inputs, and badges only.
- **Do** show a real per-signal score or leave it absent; never fill an empty signal with a zero or a placeholder number.
- **Do** give every icon-only button an explicit `aria-label`, especially where responsive layout hides its text label.
- **Do** keep Operate-mode screens dense and pattern-consistent; save spacious, editorial layout for the landing page only.

### Don't:
- **Don't** introduce a second accent color. If a screen feels like it needs one, reach for the functional verified/warning/danger layer instead.
- **Don't** use a filled, pill-shaped badge. The specimen-label look (border + wash + mono) is load-bearing for this product's "this is data, not decoration" stance.
- **Don't** add a drop shadow to content that sits in the normal document flow. Shadows are reserved for content that is actually elevated (dialogs, the focused skip-link).
- **Don't** round a card, dialog, or container corner. The `0.125rem` softening is reserved for small interactive controls only.
- **Don't** write an em dash or an eyebrow/kicker line on the landing page; its copy follows a plainer, more declarative register than typical marketing pages.
- **Don't** call a synchronous, LLM-backed action (chat, gaps, directions, compare) without handling `llm_key_required` with the same friendly, specific message ("No working LLM provider key is saved yet. Add one in Settings...") used everywhere else it appears — a bare backend error string is a regression, not a shortcut.
