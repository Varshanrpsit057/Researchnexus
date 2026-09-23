"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { motion, useReducedMotion, type Variants } from "motion/react";
import { ArrowRight, FlaskIcon, MagnifyingGlass } from "@phosphor-icons/react/dist/ssr";
import { ConfidenceBadge } from "@/components/ui/Badge";
import { LeaderRow } from "@/components/ui/ConfidenceBasis";

// A fixed, always-dark cinematic palette for this one Persuade-mode surface
// only -- scoped to this page's own wrapper, never touching the app's
// light/dark-adaptive `--surface`/`--accent` tokens the authenticated
// screens rely on. DESIGN.md already permits a bolder color strategy for
// Persuade surfaces; this commits to one deliberately, the way a landing
// page's atmosphere is chosen once rather than following the visitor's OS
// theme.
const INK = "#f3f6ff";
const MUTED = "#9aa6c4";
const MUTED_2 = "#6b7796";
const MINT = "#5df0a8";
const MINT_2 = "#2fd38a";
const MINT_INK = "#032018";
const GLASS = "rgba(12,18,38,.55)";
const GLASS_2 = "rgba(16,24,48,.65)";
const LINE = "rgba(150,175,230,.12)";
const LINE_STRONG = "rgba(150,175,230,.22)";

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 26 },
  show: { opacity: 1, y: 0 },
};

function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? "show" : "hidden"}
      whileInView="show"
      viewport={{ once: true, margin: "0px 0px -8% 0px", amount: 0.18 }}
      variants={fadeUp}
      transition={{ duration: reduce ? 0 : 0.7, delay: reduce ? 0 : delay, ease: [0.22, 0.7, 0.2, 1] }}
    >
      {children}
    </motion.div>
  );
}

function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <span
      className="mb-4 inline-block text-xs font-semibold uppercase tracking-[0.18em]"
      style={{ color: MINT }}
    >
      {children}
    </span>
  );
}

function SectionHead({ eyebrow, title, body }: { eyebrow: string; title: ReactNode; body: string }) {
  return (
    <div className="mx-auto mb-14 max-w-[680px] text-center sm:mb-20">
      <Reveal>
        <Eyebrow>{eyebrow}</Eyebrow>
      </Reveal>
      <Reveal delay={0.08}>
        <h2
          className="text-[clamp(30px,4.4vw,50px)] font-extrabold leading-[1.05] tracking-[-0.02em]"
          style={{ color: INK, textShadow: "0 2px 40px rgba(0,0,0,.6)" }}
        >
          {title}
        </h2>
      </Reveal>
      <Reveal delay={0.16}>
        <p className="mt-4 text-lg leading-relaxed" style={{ color: MUTED, textShadow: "0 1px 24px rgba(0,0,0,.55)" }}>
          {body}
        </p>
      </Reveal>
    </div>
  );
}

function GlassCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-[18px] p-7 backdrop-blur-[14px] transition-colors duration-300 ${className}`}
      style={{ background: GLASS, border: `1px solid ${LINE}` }}
    >
      {children}
    </div>
  );
}

function PrimaryButton({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-2 rounded-full px-6 py-3.5 text-sm font-semibold transition-transform duration-200 hover:-translate-y-0.5"
      style={{
        color: MINT_INK,
        background: `linear-gradient(180deg, ${MINT}, ${MINT_2})`,
        boxShadow: "0 10px 30px -8px rgba(93,240,168,.55), inset 0 1px 0 rgba(255,255,255,.4)",
      }}
    >
      {children}
      <ArrowRight className="size-4" aria-hidden />
    </Link>
  );
}

function OutlineButton({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      className="inline-flex items-center gap-2 rounded-full px-6 py-3.5 text-sm font-semibold backdrop-blur-[10px] transition-transform duration-200 hover:-translate-y-0.5"
      style={{ color: INK, background: "rgba(255,255,255,.04)", border: `1px solid ${LINE_STRONG}` }}
    >
      {children}
    </a>
  );
}

const SIGNALS = [
  { name: "semantic", value: 0.91 },
  { name: "problem", value: 0.78 },
  { name: "method", value: 0.64 },
  { name: "citation", value: 1.0 },
  { name: "recency", value: 0.47 },
];

const RELATIONSHIP_TYPES = ["similar", "foundational", "competing", "method-extension", "dataset-related", "contradictory", "recent"];

export default function LandingPage() {
  return (
    <div style={{ color: INK }} className="min-h-dvh">
      {/* ---------------------------------------------------------------- HERO */}
      {/* No background of its own and no local Constellation mount: the
          globally-mounted instance in the root layout shows through this
          whole page (and every other transparent cinematic page) so it
          never restarts or flashes on navigation. */}
      <header className="relative flex min-h-dvh flex-col overflow-hidden">
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(125% 62% at 50% -10%, rgba(4,6,15,.82) 0%, rgba(4,6,15,.28) 44%, transparent 68%)",
          }}
        />

        <nav className="relative z-10 mx-auto flex w-full max-w-[1180px] items-center justify-between px-6 py-[22px]">
          <span className="inline-flex items-center gap-[9px] text-[19px] font-extrabold tracking-[0.16em]">
            <FlaskIcon className="size-[18px] -translate-y-px" style={{ color: MINT }} weight="duotone" aria-hidden />
            RESEARCHNEXUS
          </span>
          <div className="hidden items-center gap-[30px] text-[14.5px] sm:flex" style={{ color: MUTED }}>
            <a href="#workflow" className="transition-colors hover:text-white">
              Workflow
            </a>
            <a href="#evidence" className="transition-colors hover:text-white">
              Evidence
            </a>
            <a href="#gaps" className="transition-colors hover:text-white">
              Gaps &amp; directions
            </a>
          </div>
          <Link
            href="/sign-in"
            className="rounded-full px-[18px] py-[9px] text-sm font-semibold backdrop-blur-[10px] transition-colors"
            style={{ background: "rgba(255,255,255,.05)", border: `1px solid ${LINE_STRONG}` }}
          >
            Sign in
          </Link>
        </nav>

        <div className="relative z-10 flex flex-1 flex-col items-center justify-center px-6 text-center" style={{ transform: "translateY(-6vh)" }}>
          <motion.h1
            initial={{ opacity: 0, y: 26 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.06, ease: [0.22, 0.7, 0.2, 1] }}
            className="max-w-[15ch] text-[clamp(34px,5.2vw,64px)] font-extrabold leading-[1.04] tracking-[-0.03em]"
            style={{ textShadow: "0 2px 50px rgba(0,0,0,.55)" }}
          >
            From Questions
            <br />
            to{" "}
            <span
              style={{
                backgroundImage: `linear-gradient(180deg, ${MINT}, ${MINT_2})`,
                backgroundClip: "text",
                WebkitBackgroundClip: "text",
                color: "transparent",
              }}
            >
              Evidence
            </span>
            .
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 26 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.18, ease: [0.22, 0.7, 0.2, 1] }}
            className="mt-6 max-w-[560px] text-[clamp(16px,2vw,19px)] leading-relaxed"
            style={{ color: MUTED }}
          >
            Discover, understand, connect, compare, and identify research gaps through an
            evidence-grounded research intelligence workflow — every score, relationship, and claim
            traces back to real text you can check.
          </motion.p>
          <motion.div
            initial={{ opacity: 0, y: 26 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.3, ease: [0.22, 0.7, 0.2, 1] }}
            className="mt-9 flex flex-wrap items-center justify-center gap-3.5"
          >
            <PrimaryButton href="/sign-in">Start Research</PrimaryButton>
            <OutlineButton href="#workflow">Explore the Workflow</OutlineButton>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 26 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.42, ease: [0.22, 0.7, 0.2, 1] }}
          className="relative z-10 px-6 pb-12 text-center"
        >
          <p className="text-xs uppercase tracking-[0.16em]" style={{ color: MUTED_2 }}>
            Bring your own OpenAI, Groq, DeepSeek, OpenRouter, Together, or Gemini key
          </p>
        </motion.div>
      </header>

      {/* ------------------------------------------------------------ DISCOVER */}
      <section id="workflow" className="mx-auto max-w-[1180px] px-6 py-[clamp(80px,12vw,160px)]">
        <SectionHead
          eyebrow="Step one · Discover"
          title="Find the papers that actually matter"
          body="Semantic similarity, citation-graph traversal, keyword search, and LLM query expansion run in parallel against arXiv, OpenAlex, Semantic Scholar, and Crossref, then fuse into one ranked list."
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: "Semantic", detail: "Embedding similarity over each paper's extracted profile." },
            { label: "Citation graph", detail: "Direct citations, co-citations, and one extra hop when signal is thin." },
            { label: "Keyword & expansion", detail: "Literal terms plus LLM-expanded queries and perspective questions." },
            { label: "Fused ranking", detail: "Every strategy's hits merge into one transparent, explainable score." },
          ].map((item, i) => (
            <Reveal key={item.label} delay={i * 0.08}>
              <GlassCard className="h-full">
                <div
                  className="mb-4 flex size-11 items-center justify-center rounded-xl"
                  style={{ background: "rgba(93,240,168,.1)", border: "1px solid rgba(93,240,168,.18)", color: MINT }}
                >
                  <MagnifyingGlass className="size-5" aria-hidden />
                </div>
                <h3 className="text-[17px] font-bold">{item.label}</h3>
                <p className="mt-2 text-[14.5px] leading-relaxed" style={{ color: MUTED }}>
                  {item.detail}
                </p>
              </GlassCard>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ----------------------------------------------------------- UNDERSTAND */}
      <section id="evidence" className="mx-auto max-w-[1180px] px-6 py-[clamp(80px,12vw,160px)]">
        <div className="grid grid-cols-1 items-center gap-[clamp(36px,6vw,72px)] lg:grid-cols-[1fr_1.05fr]">
          <div>
            <Reveal>
              <Eyebrow>Step two · Understand</Eyebrow>
            </Reveal>
            <Reveal delay={0.08}>
              <h2 className="text-[clamp(28px,4vw,42px)] font-extrabold leading-[1.08] tracking-[-0.02em]">
                Turn papers into usable evidence
              </h2>
            </Reveal>
            <Reveal delay={0.16}>
              <p className="mt-5 text-[17px] leading-relaxed" style={{ color: MUTED }}>
                Every PDF is parsed into sections, tables, and references, then distilled into a
                structured research profile — problem, methods, datasets, findings, and
                limitations — each field carrying the exact quote and page it came from. Chat
                answers are built the same way: no evidence span, no claim.
              </p>
            </Reveal>
            <Reveal delay={0.24} className="mt-7">
              <OutlineButton href="/sign-in">See a real profile</OutlineButton>
            </Reveal>
          </div>
          <Reveal delay={0.16}>
            <GlassCard className="!p-6">
              <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: LINE }}>
                <p className="text-sm font-semibold">Research problem</p>
                <ConfidenceBadge confidence="high" />
              </div>
              <p className="mt-3 text-sm leading-relaxed" style={{ color: MUTED }}>
                &ldquo;Reducing hallucination in knowledge-intensive question answering by grounding
                generation in retrieved passages rather than parametric memory alone.&rdquo;
              </p>
              <div className="mt-4 border-l-2 pl-3 text-xs italic" style={{ borderColor: MINT, color: MUTED_2 }}>
                &ldquo;...combining a parametric seq2seq model with a non-parametric memory...&rdquo;
                <span className="ml-1.5 not-italic">§Abstract, p.1</span>
              </div>
            </GlassCard>
          </Reveal>
        </div>
      </section>

      {/* ---------------------------------------------------------------- RANK */}
      <section className="mx-auto max-w-[1180px] px-6 py-[clamp(80px,12vw,160px)]">
        <SectionHead
          eyebrow="Step three · Rank"
          title="See why a paper was selected"
          body="Never a single fabricated percentage. Every ranked result shows the real per-signal scores that produced it, in plain sight — not one disclosure-click below the fold."
        />
        <Reveal>
          <GlassCard className="mx-auto max-w-[640px]">
            <p className="text-sm font-medium">Query Rewriting in Retrieval-Augmented LLMs</p>
            <p className="mt-1 text-xs" style={{ color: MUTED_2 }}>
              Ma, Gong, He, Zhao, Duan · 2023
            </p>
            <div className="mt-5 space-y-3">
              {SIGNALS.map((s, i) => (
                <div key={s.name}>
                  <div className="mb-1 flex items-center justify-between text-xs" style={{ color: MUTED }}>
                    <span>{s.name}</span>
                    <LeaderRow label="" value={s.value.toFixed(2)} />
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,.06)" }}>
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: `linear-gradient(90deg, ${MINT_2}, ${MINT})` }}
                      initial={{ width: 0 }}
                      whileInView={{ width: `${s.value * 100}%` }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.6, delay: 0.3 + i * 0.09, ease: [0.22, 0.7, 0.2, 1] }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </GlassCard>
        </Reveal>
      </section>

      {/* ------------------------------------------------------------- CONNECT */}
      <section className="mx-auto max-w-[1180px] px-6 py-[clamp(80px,12vw,160px)]">
        <SectionHead
          eyebrow="Step four · Connect"
          title="See the research landscape, not just a list"
          body={`Every accepted relationship is one of ${RELATIONSHIP_TYPES.length} typed categories — a fired rule plus a verbatim evidence span, not an unlabeled similarity score.`}
        />
        <div className="flex flex-wrap justify-center gap-2.5">
          {RELATIONSHIP_TYPES.map((t, i) => (
            <Reveal key={t} delay={i * 0.06}>
              <span
                className="inline-flex items-center rounded-full px-4 py-2 font-mono text-xs uppercase tracking-wider"
                style={{ background: "rgba(93,240,168,.08)", border: `1px solid rgba(93,240,168,.2)`, color: MINT }}
              >
                {t}
              </span>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------- COMPARE */}
      <section className="mx-auto max-w-[1180px] px-6 py-[clamp(80px,12vw,160px)]">
        <SectionHead
          eyebrow="Step five · Compare"
          title="Compare evidence, not just titles"
          body="A shared comparison schema puts your workspace papers side by side — methods, datasets, findings — every cell traceable to the source that supports it, or marked unsupported."
        />
        <Reveal>
          <div className="mx-auto max-w-[760px] overflow-x-auto">
            <table className="w-full min-w-[560px] border-separate" style={{ borderSpacing: 0 }}>
              <thead>
                <tr>
                  <th className="p-3 text-left text-xs uppercase tracking-wider" style={{ color: MUTED_2 }}>
                    Field
                  </th>
                  <th className="p-3 text-left text-xs uppercase tracking-wider" style={{ color: MUTED_2 }}>
                    RAG (Lewis et al.)
                  </th>
                  <th className="p-3 text-left text-xs uppercase tracking-wider" style={{ color: MUTED_2 }}>
                    DPR (Karpukhin et al.)
                  </th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["Method", "Seq2seq + non-parametric memory", "Dense dual-encoder retrieval"],
                  ["Dataset", "Natural Questions, TriviaQA", "Natural Questions"],
                  ["Finding", "Reduces hallucination on open-domain QA", "Outperforms BM25 on retrieval accuracy"],
                ].map((row) => (
                  <tr key={row[0]}>
                    {row.map((cell, ci) => (
                      <td
                        key={ci}
                        className="p-3 text-sm"
                        style={{ borderTop: `1px solid ${LINE}`, color: ci === 0 ? INK : MUTED, fontWeight: ci === 0 ? 600 : 400 }}
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>
      </section>

      {/* ----------------------------------------------------------------- GAPS */}
      <section id="gaps" className="mx-auto max-w-[1180px] px-6 py-[clamp(80px,12vw,160px)]">
        <SectionHead
          eyebrow="Step six · Find gaps"
          title="Turn evidence into research opportunities"
          body="A gap needs at least two supporting papers and a passed self-support check before it's ever shown — reviewed with the same accept/reject rhythm as the trail."
        />
        <Reveal>
          <GlassCard className="mx-auto max-w-[640px]">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium">
                Few-shot RAG methods are rarely evaluated under adversarial or out-of-domain retrieval noise.
              </p>
              <ConfidenceBadge confidence="medium" />
            </div>
            <p className="mt-2 text-xs" style={{ color: MUTED_2 }}>
              knowledge-gap · 2 supporting papers · 61% evidence coverage ·{" "}
              <span style={{ color: MINT }}>self-support passed</span>
            </p>
            <div className="mt-4 flex items-center gap-3 border-t pt-3" style={{ borderColor: LINE }}>
              <span
                className="rounded-full px-3 py-1 text-xs font-medium"
                style={{ background: "rgba(93,240,168,.12)", color: MINT }}
              >
                Accepted
              </span>
              <span className="text-xs" style={{ color: MUTED_2 }}>
                filed to the workspace trail
              </span>
            </div>
          </GlassCard>
        </Reveal>
      </section>

      {/* ------------------------------------------------------------ DIRECTIONS */}
      <section className="mx-auto max-w-[1180px] px-6 py-[clamp(80px,12vw,160px)]">
        <SectionHead
          eyebrow="Step seven · Develop directions"
          title="Move from gap to research direction"
          body="An accepted gap becomes a concrete, evidence-grounded direction — the chain from paper to evidence to gap to direction stays inspectable at every link."
        />
        <div className="mx-auto flex max-w-[900px] flex-wrap items-center justify-center gap-3 text-sm" style={{ color: MUTED }}>
          {["Paper", "Evidence span", "Gap", "Direction"].map((step, i, arr) => (
            <Reveal key={step} delay={i * 0.1} className="flex items-center gap-3">
              <span
                className="rounded-full px-4 py-2 font-medium"
                style={{ background: GLASS_2, border: `1px solid ${LINE_STRONG}`, color: INK }}
              >
                {step}
              </span>
              {i < arr.length - 1 && <ArrowRight className="size-4 shrink-0" style={{ color: MINT }} aria-hidden />}
            </Reveal>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------------ CTA */}
      <section className="mx-auto max-w-[1180px] px-6 py-[clamp(80px,12vw,160px)]">
        <Reveal>
          <div
            className="mx-auto max-w-[760px] rounded-[26px] px-[clamp(28px,5vw,64px)] py-[clamp(48px,7vw,80px)] text-center backdrop-blur-[18px]"
            style={{
              background: `radial-gradient(120% 140% at 50% 0%, rgba(93,240,168,.12), transparent 55%), ${GLASS_2}`,
              border: `1px solid ${LINE_STRONG}`,
              boxShadow: "0 30px 80px -30px rgba(0,0,0,.75)",
            }}
          >
            <Eyebrow>Ready when you are</Eyebrow>
            <h2 className="text-[clamp(30px,4.4vw,50px)] font-extrabold leading-[1.05] tracking-[-0.02em]">
              Research deeper. Reason from evidence.
            </h2>
            <p className="mx-auto mt-4 max-w-[46ch] text-[17px] leading-relaxed" style={{ color: MUTED }}>
              Bring your own model key. Upload a seed paper. See the whole surrounding literature —
              and a defensible gap — in one session.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3.5">
              <PrimaryButton href="/sign-in">Start Research</PrimaryButton>
              <OutlineButton href="#workflow">Explore ResearchNexus</OutlineButton>
            </div>
          </div>
        </Reveal>

        <footer
          className="mt-[clamp(64px,9vw,110px)] flex flex-wrap items-start justify-between gap-12 border-t pt-12"
          style={{ borderColor: LINE }}
        >
          <div className="max-w-[280px]">
            <span className="inline-flex items-center gap-[9px] text-[16px] font-extrabold tracking-[0.14em]">
              <FlaskIcon className="size-4" style={{ color: MINT }} weight="duotone" aria-hidden />
              RESEARCHNEXUS
            </span>
            <p className="mt-3 text-sm" style={{ color: MUTED_2 }}>
              The evidence-grounded research intelligence workflow for ambitious literature reviews.
            </p>
          </div>
          <div className="flex flex-wrap gap-16">
            {[
              { head: "Product", links: ["Discovery", "Ranking", "Comparison"] },
              { head: "Workflow", links: ["Trail", "Graph", "Gaps"] },
              { head: "Account", links: ["Sign in", "Settings"] },
            ].map((col) => (
              <div key={col.head}>
                <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: MUTED_2 }}>
                  {col.head}
                </p>
                <ul className="mt-3 space-y-2 text-sm" style={{ color: MUTED }}>
                  {col.links.map((l) => (
                    <li key={l}>{l}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </footer>
        <p className="mt-14 text-center text-xs" style={{ color: MUTED_2 }}>
          © {new Date().getFullYear()} ResearchNexus — evidence, not assertions.
        </p>
      </section>
    </div>
  );
}
