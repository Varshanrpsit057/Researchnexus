"use client";

/*
 * DecryptedText -- adapted from React Bits (https://github.com/DavidHDev/react-bits,
 * src/ts-tailwind/TextAnimations/DecryptedText). Copyright (c) 2026 David Haz.
 * MIT + Commons Clause; see THIRD_PARTY_NOTICES.md.
 *
 * Kept: the sequential reveal from the start, with not-yet-revealed
 * characters cycling through a character set, and the real text kept for
 * screen readers beside the animated copy. Trimmed to the one mode used
 * here -- play once when shown -- with the interval always cleared, spaces
 * and the "@" left in place, and the plain text under prefers-reduced-motion.
 */

import { useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

interface DecryptedTextProps {
  text: string;
  /** ms per step */
  speed?: number;
  className?: string;
  encryptedClassName?: string;
}

const CHARACTERS = "abcdefghijklmnopqrstuvwxyz0123456789";
const FIXED = new Set([" ", "@", "."]);

function scrambled(text: string, revealed: number): string {
  return text
    .split("")
    .map((char, i) => (i < revealed || FIXED.has(char) ? char : CHARACTERS[Math.floor(Math.random() * CHARACTERS.length)]))
    .join("");
}

export default function DecryptedText({ text, speed = 28, className = "", encryptedClassName = "" }: DecryptedTextProps) {
  const reduced = useReducedMotion();
  const [revealed, setRevealed] = useState(0);
  const [shown, setShown] = useState(text);

  useEffect(() => {
    if (reduced) return;
    let step = 0;
    const timer = setInterval(() => {
      step += 1;
      setRevealed(step);
      setShown(scrambled(text, step));
      if (step >= text.length) clearInterval(timer);
    }, speed);
    return () => clearInterval(timer);
  }, [text, speed, reduced]);

  if (reduced) return <span className={className}>{text}</span>;
  return (
    <span className="whitespace-nowrap">
      <span className="sr-only">{text}</span>
      <span aria-hidden>
        {shown.split("").map((char, i) => (
          <span key={i} className={i < revealed || FIXED.has(char) ? className : encryptedClassName}>
            {char}
          </span>
        ))}
      </span>
    </span>
  );
}
