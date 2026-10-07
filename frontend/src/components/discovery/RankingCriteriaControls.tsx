"use client";

import { CINEMATIC } from "@/lib/cinematic-theme";
import { CRITERIA, CRITERION_COLOR, criteriaError, criteriaShares } from "@/lib/ranking";
import { publishersPhrase, useSavedPublishers } from "@/lib/publishers";
import type { RankingCriteria } from "@/lib/api/types";

const C = CINEMATIC;

/** The ranking criteria as sliders, each with its share of the score.
 * Controlled: the caller decides when the criteria are saved or applied.
 * `columns`: 2 lays them out side by side where there is room. */
export function RankingCriteriaControls({
  value,
  onChange,
  idPrefix,
  columns = 1,
}: {
  value: RankingCriteria;
  onChange: (next: RankingCriteria) => void;
  idPrefix: string;
  columns?: 1 | 2;
}) {
  const shares = criteriaShares(value);
  const error = criteriaError(value);
  const preferred = useSavedPublishers();
  return (
    <div data-testid="ranking-criteria">
      <ul className={columns === 2 ? "grid gap-x-10 gap-y-3 md:grid-cols-2" : "space-y-3"}>
        {CRITERIA.map(({ key, label, hint }) => {
          const id = `${idPrefix}-${key}`;
          return (
            <li key={key}>
              <div className="flex items-baseline justify-between gap-3">
                <label htmlFor={id} className="flex items-center gap-2 text-[13px] font-semibold" style={{ color: C.ink }}>
                  <span className="size-2.5 shrink-0 rounded-sm" style={{ background: CRITERION_COLOR[key] }} aria-hidden />
                  {label}
                </label>
                <span className="font-mono text-xs tabular-nums" style={{ color: value[key] === 0 ? C.muted2 : C.muted }}>
                  {value[key] === 0 ? "off" : `${shares[key]}% of the score`}
                </span>
              </div>
              <input
                id={id}
                type="range"
                min={0}
                max={100}
                step={1}
                value={value[key]}
                onChange={(e) => onChange({ ...value, [key]: Number(e.target.value) })}
                aria-describedby={`${id}-hint`}
                aria-valuetext={value[key] === 0 ? `${label}: off` : `${label}: ${value[key]}, ${shares[key]}% of the score`}
                className="rn-range mt-1.5 w-full"
                style={{ ["--rn-range-color" as string]: CRITERION_COLOR[key] }}
              />
              <p id={`${id}-hint`} className="text-[12px]" style={{ color: C.muted2 }}>
                {key === "publisher" ? (preferred.length ? `Published by ${publishersPhrase(preferred)}` : "No publisher is preferred") : hint}
              </p>
            </li>
          );
        })}
      </ul>
      {error && (
        <p role="alert" className="mt-3 text-sm" style={{ color: C.danger }}>
          {error}
        </p>
      )}
    </div>
  );
}
