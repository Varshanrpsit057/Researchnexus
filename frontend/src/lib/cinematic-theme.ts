/** The one dark/mint palette shared by every cinematic (Persuade-and-beyond)
 * surface -- landing, sign-in, home, seed paper, and whatever follows. Kept
 * as plain string constants (not CSS variables) because these pages are
 * deliberately NOT theme-adaptive like the rest of the authenticated app:
 * this world commits to one atmosphere regardless of system light/dark
 * preference, the way a film keeps its own color grade. */
export const CINEMATIC = {
  ink: "#f3f6ff",
  muted: "#9aa6c4",
  muted2: "#6b7796",
  mint: "#5df0a8",
  mint2: "#2fd38a",
  mintInk: "#032018",
  glass: "rgba(12,18,38,.55)",
  glass2: "rgba(16,24,48,.65)",
  line: "rgba(150,175,230,.12)",
  lineStrong: "rgba(150,175,230,.22)",
  warning: "#e8c15c",
  danger: "#ff9b9b",
} as const;
