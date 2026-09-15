---
name: ResearchNexus
description: A precision research instrument for evidence-grounded literature review, not another AI dashboard
colors:
  surface: "#fafaf9"
  surface-raised: "#ffffff"
  surface-sunken: "#f2f1ee"
  ink: "#1c1b19"
  ink-muted: "#57534e"
  ink-subtle: "#6b6660"
  border: "#e4e1db"
  border-strong: "#c8c3ba"
  accent: "#1e4b8f"
  accent-strong: "#163a70"
  accent-foreground: "#f5f8ff"
  accent-wash: "#e8eefb"
  verified: "#2f6f4e"
  verified-wash: "#e7f2ec"
  warning: "#92620c"
  warning-wash: "#f8eedc"
  danger: "#9a3b3b"
  danger-wash: "#f7e9e7"
typography:
  display:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontWeight: 600
    letterSpacing: "-0.04em"
  body:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "0.6875rem"
    letterSpacing: "0.05em"
  data:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontVariation: "tabular-nums"
rounded:
  xs: "0.25rem"
  sm: "0.375rem"
  md: "0.5rem"
  lg: "0.75rem"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    rounded: "{rounded.md}"
    padding: "0 1rem"
    height: "2.5rem"
  button-primary-hover:
    backgroundColor: "{colors.accent-strong}"
  button-secondary:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
---

# Design System: ResearchNexus

## Overview

**Creative North Star: "The Precision Instrument"**

ResearchNexus reads like a measurement device, not a chatbot wrapped in a dashboard template. Every ranked result, typed relationship, and generated claim carries the receipts that produced it: the per-signal score, the fired rule, the verbatim evidence span. The interface's job is to make that evidence legible at a glance, so nothing here can be mistaken for a generic AI-assistant skin. The system deliberately rejects two adjacent aesthetics: the soft, purple-glowing "AI product" look (no gradients, no glow, no chat-bubble whimsy), and the dense, chart-heavy analytics-dashboard look (no gauges, no decorative sparklines, no color-coded KPI tiles standing in for real numbers). What replaces both is closer to a lab instrument's read-out: a restrained neutral ground, one calibrated accent used sparingly, and numeric or identifying data always set in a monospaced, tabular face so it reads as a measurement rather than prose.

Density follows the surface's job. The landing page (the one Persuade-mode surface) is spacious and editorial, built to be read once and acted on. Everything behind login (Operate mode: upload, profile, discovery, trail, and the ten workspace tabs) is dense and scannable by design, favoring information density and consistent, learnable patterns over expressive flourish. The same specimen-label badge, the same accept/reject pair, and the same evidence-disclosure pattern recur across every Operate screen so a researcher who learns one tab already knows the other nine.

**Key Characteristics:**
- Neutral zinc/stone ground with a single calibrated ink-blue accent, never violet or purple
- Every numeric or identifying value (scores, ids, timestamps, counts) set in JetBrains Mono with tabular figures
- A separate functional color layer (verified / warning / danger) exists only to mark evidence status, never as brand decoration
- Specimen-label badges: mono, uppercase, letter-spaced, bordered, never a filled pill
- One small, consistent radius scale used everywhere; no mixed rounding

## Colors

A restrained neutral (zinc/stone) ground carries almost the whole interface; the one accent and the three semantic tones are reserved for moments that are actually informative.

### Primary
- **Signal Blue** (`#1e4b8f`, `accent`): the single brand accent. Primary buttons, active tab underline, focus rings, links, and the confidence-band dot on badges. Deliberately desaturated so it reads as "instrument calibration," not "AI purple." Never used decoratively (no gradients, no glows).

### Neutral
- **Paper** (`#fafaf9`, `surface`): the page ground.
- **Card White** (`#ffffff`, `surface-raised`): cards, the app header, dialogs, anything that sits one level above the page.
- **Recessed Stone** (`#f2f1ee`, `surface-sunken`): hover rows, drag-active states, anything one level below the page.
- **Ink** (`#1c1b19`, `ink`): primary text.
- **Ink Muted** (`#57534e`, `ink-muted`): secondary text, descriptions, body copy in cards (7.6:1 on white).
- **Ink Subtle** (`#6b6660`, `ink-subtle`): de-emphasized but real content — ids, timestamps, hint text (5.7:1 on white; darkened this phase from an earlier `#8a8580` that measured 3.65:1 and failed WCAG AA for the small mono text it is actually used for).
- **Border** (`#e4e1db`) / **Border Strong** (`#c8c3ba`): hairline dividers vs. input/card outlines that need to read as interactive.

### Functional (status, not brand)
- **Verified Green** (`#2f6f4e` on `#e7f2ec` wash): a claim, edge, or gap the user has accepted, or a "high" confidence read.
- **Warning Amber** (`#92620c` on `#f8eedc` wash): a partial failure (a discovery strategy that failed, an unresolved citation) — informative, not blocking.
- **Danger Red** (`#9a3b3b` on `#f7e9e7` wash): a rejected edge/gap/direction, or a destructive action.

### Named Rules
**The One Accent Rule.** Signal Blue is the only brand color in the system. If a screen needs a second color, it is one of the three functional tones above, applied only to mark real evidence status, never as decoration.

**The Never-a-Percentage-Alone Rule.** Confidence is always a labeled band (high/medium/low) paired with its glyph (● / ◐ / ○), never a bare number dressed up as a percentage. Real per-signal scores appear in mono next to their name; nothing is ever fabricated to fill a visual slot.

## Typography

**Display / UI Font:** Archivo (with `ui-sans-serif, system-ui, sans-serif` fallback)
**Label / Mono Font:** JetBrains Mono (with `ui-monospace, monospace` fallback)

**Character:** Archivo is a clean, slightly technical grotesque that carries both the landing page's headlines and every Operate-mode label without switching families. JetBrains Mono is not a "coder aesthetic" flourish here — every value it sets (a similarity score, a paper id, a timestamp, a token count) is a real measurement, and tabular figures keep columns of numbers from jittering as they update.

### Hierarchy
- **Display** (600 weight, `text-4xl`–`text-5xl`, tracking `-0.04em`): the landing page's hero headline only.
- **Headline** (600 weight, `text-xl`–`text-2xl`, tracking `-0.04em`): page and section titles (paper title, workspace title, section headers). Every `h1`–`h4` gets `-0.04em` tracking globally; do not re-tighten with a second utility class.
- **Body** (400 weight, `text-sm`, line-height 1.6): all prose — descriptions, explanations, chat messages.
- **Label** (500 weight, `0.6875rem`, `0.05em` tracking, uppercase, mono): badges and specimen labels — relationship types, discovery methods, provenance status, gap/direction kinds.
- **Data** (mono, tabular-nums): scores, ids, counts, costs, timestamps, token budgets.

### Named Rules
**The Mono-Is-Measurement Rule.** JetBrains Mono is reserved for values that are literally measured or identified (scores, ids, counts, timestamps). It never appears on prose or headings; that boundary is what keeps it reading as instrumentation rather than a costume.

## Layout

Operate-mode pages sit inside the app shell's `max-w-[1400px]` container with `px-4 py-6`; individual pages narrow further where the content is read top-to-bottom rather than scanned (the upload flow and paper-profile grid cap around `max-w-2xl`–`max-w-5xl`). The workspace tab shell reuses one `layout.tsx` (header, budget bar, tab strip) so none of the ten tabs re-implements chrome. Two-column data (the research-profile field grid, the landing page's mechanism section) collapses to one column below `lg:`/`sm:` respectively; nothing depends on a wide viewport to remain usable. Wide tabular content (the comparison table, the activity log) scrolls horizontally inside its own container rather than the page.

The app header is the one place that needed an explicit narrow-viewport pass this phase: below `sm:`, the wordmark collapses to its flask icon alone and the "Upload paper" button collapses to icon-only, both keeping an explicit `aria-label` so nothing loses its accessible name; "Papers" and "Workspaces" stay as visible text links at every width since neither has an alternate path.

## Elevation & Depth

Flat by default. Cards are distinguished from the page by a hairline border and background-tone shift (`surface-raised` vs `surface`), not a shadow. The one exception is genuinely floating content — the Dialog's surface and its `open` animation — which gets a real shadow because it is actually elevated above the page.

### Shadow Vocabulary
- **Card ambient** (`0 1px 3px rgb(var(--shadow-color) / 0.08)`): the barely-there separation under `Card`. Present so cards don't look glued to the page, not to imply floating.
- **Dialog lift** (`0 16px 48px rgb(var(--shadow-color) / 0.24)`): the one true elevated surface in the system.

### Named Rules
**The Flat-Unless-Floating Rule.** A shadow appears only on content that is actually above the page in z-order (a dialog, a dropdown). A card sitting in the document flow gets a border and a tone shift, never a shadow standing in for one.

## Shapes

One small radius scale, applied by role rather than mixed per component: `0.25rem` (badges), `0.375rem` (buttons, inputs, most cards), `0.5rem` (larger cards), `0.75rem` (rare, larger containers). Nothing in the system uses a pill/full radius or a sharp 0 radius; both would read as a different, louder system than the restrained one here.

## Components

### Buttons
- **Shape:** `0.375rem` radius, `h-8` (sm) / `h-10` (md).
- **Primary:** Signal Blue background, `accent-foreground` text; hover darkens to `accent-strong`.
- **Secondary:** `surface-raised` background, `border-strong` outline, hover darkens the border only (no fill change).
- **Ghost:** no background or border at rest; hover gets a `surface-sunken` wash.
- **Danger:** filled with the danger tone, for destructive actions only (none shipped yet in this phase beyond rejects, which use ghost/secondary, not danger, since reject is reversible).
- **Press feedback:** every button scales to `0.97` on `:active`.

### Badges (the signature component)
- **Style:** mono, uppercase, `0.6875rem`, `0.05em` tracking, `0.25rem` radius, always bordered with a matching wash background — never a solid filled pill. This is the one component that is genuinely distinctive to this product: it is how every typed, classified, or scored value in the system announces itself as data rather than decoration.
- **Tones:** neutral (border-strong/ink-muted), accent (Signal Blue), verified/warning/danger (the functional layer). `ConfidenceBadge` adds the ●/◐/○ glyph ahead of the band name.

### Cards / Containers
- **Corner Style:** `0.5rem`.
- **Background:** `surface-raised` on `surface`.
- **Shadow Strategy:** ambient card shadow only (see Elevation).
- **Border:** 1px `border`.
- **Internal Padding:** `CardHeader`/`CardBody` at `px-4 py-3`.

### Inputs / Fields
- **Style:** `border-strong` outline, `surface-raised` fill, `0.375rem` radius.
- **Focus:** 2px `accent` outline, 2px offset (browser-native `:focus-visible`, not a custom ring shadow).
- **Error:** `user-invalid` variant swaps the border and background to the danger wash the moment a field is both touched and invalid.

### Navigation
- **App header:** `surface-raised` on a hairline bottom border, icon+wordmark home link, text links for Papers/Workspaces, icon-only secondary actions (upload, settings, sign out) each carrying their own `aria-label`.
- **Workspace tab strip:** underline-style tabs (2px `accent` underline on the active tab, transparent otherwise), not filled pills — consistent with the badge system's "border and wash, not fill" language.

### Evidence Disclosure (signature pattern)
A `<details>`/`<summary>` pair used identically everywhere a quoted source span backs a claim (profile fields, trail edges, gaps): a small quote-icon summary line that expands into a left-bordered, mono-adjacent quote block with its section/page. Native, keyboard-operable, zero extra state. This pattern, more than any single color or font, is what makes the "never show a claim without its source" product principle a real, everyday interaction rather than a slogan.

## Do's and Don'ts

### Do:
- **Do** set every score, id, timestamp, and count in JetBrains Mono with tabular figures.
- **Do** use the bordered-badge-with-wash pattern for every typed/classified value (relationship type, discovery method, gap type, provenance status).
- **Do** show a real per-signal score or leave it absent; never fill an empty signal with a zero or a placeholder number.
- **Do** give every icon-only button an explicit `aria-label`, especially where responsive layout hides its text label.
- **Do** keep Operate-mode screens dense and pattern-consistent; save spacious, editorial layout for the landing page only.

### Don't:
- **Don't** introduce a second accent color. If a screen feels like it needs one, reach for the functional verified/warning/danger layer instead.
- **Don't** use a filled, pill-shaped badge. The specimen-label look (border + wash + mono) is load-bearing for this product's "this is data, not decoration" stance.
- **Don't** add a drop shadow to content that sits in the normal document flow. Shadows are reserved for content that is actually elevated (dialogs).
- **Don't** write an em dash or an eyebrow/kicker line on the landing page; its copy follows a plainer, more declarative register than typical marketing pages.
- **Don't** call a synchronous, LLM-backed action (chat, gaps, directions, compare) without handling `llm_key_required` with the same friendly, specific message ("No working LLM provider key is saved yet. Add one in Settings...") used everywhere else it appears — a bare backend error string is a regression, not a shortcut.
