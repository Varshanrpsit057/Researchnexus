import { CINEMATIC as C } from "@/lib/cinematic-theme";

/** A passage exactly as the paper words it: "…" where it was cut, and the
 * sentence a claim rests on marked -- the rest is its context. Never edited:
 * the mark is a view on the text, not a change to it. */
export function VerbatimQuote({
  quote,
  cutBefore = false,
  cutAfter = false,
  highlight = null,
}: {
  quote: string;
  cutBefore?: boolean;
  cutAfter?: boolean;
  /** [start, end) offsets into `quote` */
  highlight?: [number, number] | null;
}) {
  const marked = highlight && highlight[1] > highlight[0] && highlight[0] >= 0 && highlight[1] <= quote.length ? highlight : null;
  return (
    <>
      &ldquo;{cutBefore ? "…" : ""}
      {marked ? (
        <>
          {quote.slice(0, marked[0])}
          <mark
            className="rounded-[3px] px-0.5 [box-decoration-break:clone]"
            style={{ background: "rgba(93,240,168,.16)", color: C.ink }}
            data-testid="supporting-sentence"
          >
            {quote.slice(marked[0], marked[1])}
          </mark>
          {quote.slice(marked[1])}
        </>
      ) : (
        <span style={{ color: C.ink }}>{quote}</span>
      )}
      {cutAfter ? "…" : ""}&rdquo;
    </>
  );
}
