"use client";

import { useSyncExternalStore } from "react";
import type { CitationFormat } from "@/lib/api/types";

/** Preferences kept in this browser only: how the app looks and reads here. */
export interface Preferences {
  /** The global neural background: moving, or one still frame. */
  backgroundMotion: "moving" | "still";
  /** The reference style the citations page opens in. */
  referenceStyle: CitationFormat;
}

export const DEFAULT_PREFERENCES: Preferences = { backgroundMotion: "moving", referenceStyle: "apa" };

const KEY: Record<keyof Preferences, string> = {
  backgroundMotion: "researchnexus.pref.backgroundMotion",
  referenceStyle: "researchnexus.pref.referenceStyle",
};
const ALLOWED: { [K in keyof Preferences]: readonly Preferences[K][] } = {
  backgroundMotion: ["moving", "still"],
  referenceStyle: ["apa", "ieee", "bibtex"],
};
const EVENT = "researchnexus:preferences";

export function readPreference<K extends keyof Preferences>(key: K): Preferences[K] {
  try {
    const v = window.localStorage.getItem(KEY[key]) as Preferences[K] | null;
    return v != null && ALLOWED[key].includes(v) ? v : DEFAULT_PREFERENCES[key];
  } catch {
    return DEFAULT_PREFERENCES[key]; // storage blocked: the default, quietly
  }
}

/** Saves the preference and tells every open page, this tab included. */
export function writePreference<K extends keyof Preferences>(key: K, value: Preferences[K]): boolean {
  try {
    window.localStorage.setItem(KEY[key], value);
  } catch {
    return false;
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: key }));
  return true;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange); // other tabs
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function usePreference<K extends keyof Preferences>(key: K): Preferences[K] {
  return useSyncExternalStore(subscribe, () => readPreference(key), () => DEFAULT_PREFERENCES[key]);
}
