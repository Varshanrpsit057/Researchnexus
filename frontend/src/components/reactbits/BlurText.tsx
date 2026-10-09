"use client";

/*
 * BlurText -- adapted from React Bits (https://github.com/DavidHDev/react-bits,
 * src/ts-tailwind/TextAnimations/BlurText). Copyright (c) 2026 David Haz.
 * MIT + Commons Clause; see THIRD_PARTY_NOTICES.md.
 *
 * Changes for ResearchNexus: a restrained default (a short 10 px rise from
 * a light blur, not 50 px); any heading level; the sentence is read once by
 * screen readers (the animated words are hidden from them); under
 * prefers-reduced-motion the text is simply there; and it starts when it
 * scrolls into view, once, with the observer disconnected after.
 */

import { motion, useReducedMotion, type Transition } from "motion/react";
import { useEffect, useRef, useState, type ElementType } from "react";

interface BlurTextProps {
  text: string;
  as?: ElementType;
  className?: string;
  /** ms between words */
  delay?: number;
  stepDuration?: number;
  onAnimationComplete?: () => void;
}

const FROM = { filter: "blur(8px)", opacity: 0, y: 10 };
const TO = { filter: ["blur(8px)", "blur(3px)", "blur(0px)"], opacity: [0, 0.6, 1], y: [10, -1, 0] };

export default function BlurText({ text, as: Tag = "p", className = "", delay = 70, stepDuration = 0.32, onAnimationComplete }: BlurTextProps) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLElement>(null);
  const [inView, setInView] = useState(false);
  const words = text.split(" ");

  useEffect(() => {
    const node = ref.current;
    if (!node || reduced) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { threshold: 0.1 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [reduced]);

  if (reduced) return <Tag className={className}>{text}</Tag>;

  return (
    <Tag ref={ref} className={className} aria-label={text}>
      {words.map((word, i) => {
        const transition: Transition = { duration: stepDuration * 2, times: [0, 0.5, 1], delay: (i * delay) / 1000, ease: [0.22, 0.7, 0.2, 1] };
        return (
          <motion.span
            key={`${word}-${i}`}
            aria-hidden
            initial={FROM}
            animate={inView ? TO : FROM}
            transition={transition}
            onAnimationComplete={i === words.length - 1 ? onAnimationComplete : undefined}
            className="inline-block will-change-[transform,filter,opacity]"
          >
            {word}
            {i < words.length - 1 && " "}
          </motion.span>
        );
      })}
    </Tag>
  );
}
