---
name: ResearchNexus
description: A dark, quiet instrument for evidence-grounded literature review -- one navy-and-mint world from the landing page to the last workspace pane
colors:
  ground: "#04060f"
  ink: "#f3f6ff"
  muted: "#9aa6c4"
  muted-2: "#6b7796"
  mint: "#5df0a8"
  mint-2: "#2fd38a"
  mint-ink: "#032018"
  glass: "rgba(12,18,38,.55)"
  glass-2: "rgba(16,24,48,.65)"
  line: "rgba(150,175,230,.12)"
  line-strong: "rgba(150,175,230,.22)"
  warning: "#e8c15c"
  danger: "#ff9b9b"
typography:
  sans:
    fontFamily: "Libre Franklin, ui-sans-serif, system-ui, sans-serif"
  display:
    fontFamily: "Libre Franklin"
    fontWeight: 800
    letterSpacing: "-0.025em"
    fontSize: "clamp(26px, 3.6vw, 40px)"
  body:
    fontFamily: "Libre Franklin"
    fontWeight: 400
    fontSize: "13.5px-15px"
    lineHeight: 1.6
  data:
    fontFamily: "Courier Prime, ui-monospace, monospace"
    fontVariation: "tabular-nums"
rounded:
  control: "9999px"
  field: "0.75rem"
  panel: "1rem"
components:
  button-primary:
    background: "linear-gradient(180deg, {colors.mint}, {colors.mint-2})"
    textColor: "{colors.mint-ink}"
    rounded: "{rounded.control}"
  button-quiet:
    background: "rgba(255,255,255,.05)"
    border: "1px solid {colors.line-strong}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
  panel:
    background: "{colors.glass}"
    border: "1px solid {colors.line}"
    rounded: "{rounded.panel}"
---

# Design System: ResearchNexus

## Overview

**North star: "Evidence in a dark room."** ResearchNexus is used for long, focused reading sessions, often at night, by people checking claims against sources. The whole app sits in one committed atmosphere: a deep navy ground, a living background (a neural network, light fibers, or a still field, chosen by the device), and translucent glass panels that hold the work. One accent, mint, marks what the reader can act on and what the system has verified. Nothing else is coloured unless it means something.

The app is one world, end to end. The landing and sign-in pages (Persuade) are spacious and atmospheric; everything behind sign-in (Operate: papers, discovery, workspaces, settings) is denser and scannable, built from the same few parts so a reader who learns one page knows the rest.

**Key characteristics**
- A navy ground (`#04060f`) under every page, painted before anything else so nothing ever flashes light.
- One accent, mint (`#5df0a8` to `#2fd38a`), for primary actions, the current place and verified states.
- Glass panels with hairline borders carry content; rows inside them are separated by hairlines, not cards.
- Pills for actions and filters, softly rounded panels and fields.
- Numbers, ids and scores in Courier Prime with tabular figures; everything else in Libre Franklin.

## Colors

- **Ground** `#04060f`: the page, always. A fixed scrim over the background (`rgba(4,6,15,.55)` to `.9`) keeps dense pages legible.
- **Ink** `#f3f6ff`, **Muted** `#9aa6c4`, **Muted 2** `#6b7796`: text, secondary text, and tertiary marks (ids, hints, timestamps).
- **Mint** `#5df0a8` / `#2fd38a` on **Mint ink** `#032018`: the primary button's gradient and text; the current navigation item; "Full text", "Research profile", "Answered", "Done".
- **Glass** `rgba(12,18,38,.55)` (panels), **Glass 2** `rgba(16,24,48,.65)` (dialogs).
- **Line** `rgba(150,175,230,.12)`, **Line strong** `.22`: hairlines between rows, panel and field borders.
- **Warning** `#e8c15c`: partial states (limited sources, a default whose key fails, a new account). **Danger** `#ff9b9b`: failures and destructive actions (delete, remove).
- **Ranking criteria** (validated on the dark surface): topic `#3987e5`, problem `#d95926`, methods `#199e70`, datasets `#c98500`, citations `#d55181`, recency `#008300`, preferred publisher `#9085e9`. Used only to tie a criterion's slider to its share of a score.

**The one-accent rule.** Mint is the only brand colour. A second colour appears only to report a state (warning, danger) or to identify a ranking criterion.

## Typography

- **Libre Franklin** for all prose and UI. Page titles: 800 weight, `clamp(26px,3.6vw,40px)`, tracking `-0.025em`. Section headings: 700, 16-22px. Body: 13.5-15px, line-height ~1.6, measure capped near 70ch.
- **Courier Prime** with tabular figures for measured or identifying values: paper and account ids, token counts, scores, latencies.
- Headings balance their lines; paragraphs avoid orphans (`text-wrap: balance | pretty`).

## Layout

- One header for every signed-in page: wordmark, Papers, Workspaces, the mint "Upload paper", Settings, Sign out. The current section is white with a mint underline (`aria-current="page"`).
- Content column up to 1180px with 16-24px gutters; pages open with a title, a one-sentence lead, and a hairline.
- Lists are single panels of rows (library, workspaces, providers, sources), not grids of cards. Each row: a title link, a byline, a status line, and one next action on the right.
- Settings: a 232px sidebar of sections (grouped by hairlines), one pane at a time, addressed by the URL hash; on narrow screens the sidebar becomes a horizontal strip.
- Workspace pages: a back link to the workspace, a title, then the work; the overview is the hub (research path, papers, go deeper, decisions, activity).

## Elevation & depth

Depth comes from the background behind glass, not from shadows. Panels sit flat with a hairline border. Only a dialog floats, with `0 30px 80px -30px rgba(0,0,0,.75)` over a dimmed, slightly blurred backdrop.

## Shapes

- Buttons, filters, chips: full pills.
- Fields: 12px radius (search and short fields may be pills).
- Panels and dialogs: 16px radius.

## Components

- **Primary button**: mint gradient, mint-ink text, pill; one per view where possible. Presses scale to 0.97.
- **Quiet button**: 5% white fill, strong hairline, ink text; hover lifts the fill.
- **Panel**: glass with a hairline; rows inside separated by hairlines.
- **Status line**: a coloured dot or icon plus words ("Full text", "Not analysed", "Limiting requests"); never a colour alone.
- **Inline error**: danger text with a warning icon, naming the problem and the way out, beside the thing that failed.
- **Dialog**: native `<dialog>`, glass 2, used only for confirmations that protect data (deleting a workspace) and short forms (creating a workspace).
- **Evidence**: verbatim passages with the supporting sentence marked and section/page beside them; a value without a passage is not shown.
- **Background**: Auto picks the animated neural network (dedicated GPU), GhostFibers (integrated graphics) or a still field (software rendering); the reader can override it in Settings > Appearance. The research graph page morphs the network into the graph.

## Motion

- Sections fade up 18px on arrival (0.5s, `cubic-bezier(0.22,0.7,0.2,1)`, small staggers); dialogs open in 180ms with `cubic-bezier(0.23,1,0.32,1)`.
- Buttons scale to 0.97 on press. Hover changes are colour only.
- Under `prefers-reduced-motion`, everything appears without movement and the background stays still.

## Browser surfaces

Text selection is mint at 28%, the caret is mint, placeholders are Muted 2, scrollbars are thin hairline-coloured thumbs, and focus rings are a 2px mint outline offset by 2px. Native dropdown lists use an opaque navy surface so their options stay readable.

## Do's and don'ts

**Do**
- Keep every page on the navy ground with the shared header.
- Give every list row one clear next action, and say why something is empty, failed or limited.
- Show real numbers in Courier Prime, and leave a value out rather than guess it.
- Confirm before anything that deletes the reader's work, and say what stays.

**Don't**
- Introduce a second accent, gradients on text, or decorative glow.
- Use grids of identical icon cards as page structure, or big-number stat tiles.
- Put a kicker label above a heading.
- Show a key, token or secret anywhere, even partly, beyond its last four characters.
