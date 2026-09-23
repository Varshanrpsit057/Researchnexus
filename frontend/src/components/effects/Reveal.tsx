"use client";

import type { ReactNode } from "react";
import { motion, useReducedMotion, type Variants } from "motion/react";

const fadeUp: Variants = { hidden: { opacity: 0, y: 18 }, show: { opacity: 1, y: 0 } };

/** Shared staggered fade-up used by every dashboard-shaped cinematic page
 * (home, seed paper, and beyond) -- animates once on mount rather than on
 * scroll-into-view, since these are short, task-first pages a researcher
 * reads top to bottom immediately, not a long marketing scroll. Collapses
 * to an instant, un-animated reveal under prefers-reduced-motion. */
export function Reveal({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? "show" : "hidden"}
      animate="show"
      variants={fadeUp}
      transition={{ duration: reduce ? 0 : 0.5, delay: reduce ? 0 : delay, ease: [0.22, 0.7, 0.2, 1] }}
    >
      {children}
    </motion.div>
  );
}
