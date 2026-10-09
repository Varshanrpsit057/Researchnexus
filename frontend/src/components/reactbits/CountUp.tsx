"use client";

/*
 * CountUp -- adapted from React Bits (https://github.com/DavidHDev/react-bits,
 * src/ts-tailwind/TextAnimations/CountUp). Copyright (c) 2026 David Haz.
 * MIT + Commons Clause; see THIRD_PARTY_NOTICES.md.
 *
 * Changes for ResearchNexus: the real number is in the page from the start
 * (server-rendered, and what screen readers read) -- only a hidden copy
 * counts; a changed value counts on from the last one shown instead of from
 * zero; under prefers-reduced-motion the number is simply there; and it is
 * shorter (0.9 s) so a figure never looks unsettled.
 */

import { useInView, useMotionValue, useReducedMotion, useSpring } from "motion/react";
import { useEffect, useRef } from "react";

interface CountUpProps {
  to: number;
  /** seconds */
  duration?: number;
  className?: string;
}

const format = (n: number) => Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);

export default function CountUp({ to, duration = 0.9, className = "" }: CountUpProps) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const motionValue = useMotionValue(0);
  const spring = useSpring(motionValue, { damping: 20 + 40 / duration, stiffness: 100 / duration });
  const inView = useInView(ref, { once: true });

  useEffect(() => {
    if (inView && !reduced) motionValue.set(to);
  }, [inView, reduced, to, motionValue]);

  useEffect(
    () =>
      spring.on("change", (latest) => {
        if (ref.current) ref.current.textContent = format(Math.round(latest));
      }),
    [spring],
  );

  if (reduced) return <span className={className}>{format(to)}</span>;
  return (
    <span className={className}>
      <span className="sr-only">{format(to)}</span>
      <span ref={ref} aria-hidden className="tabular-nums">
        {format(0)}
      </span>
    </span>
  );
}
