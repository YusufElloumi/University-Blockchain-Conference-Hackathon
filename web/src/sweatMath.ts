// The server's Proof of Sweat scoring (api/sweat3.py), written again for the browser so the public
// sample receipt can be worked out without calling the server.
//
// Two things keep this the same arithmetic as the server and not an approximation:
//   1. No scoring number is written in this file. Every weight, band and limit is read from
//      sweatRules.json, which is generated from the server's rules (api/sweat_sample.py write).
//   2. `npm run check:sweat` scores several hundred made-up workouts with this file and compares each
//      answer with the server's (scripts/sweat-vectors.json). The server's own tests fail if those
//      files are out of date.
//
// Whole numbers only (hundredths and thousandths), so there is no floating-point drift from the
// server's exact decimals. Plain TypeScript with no imports besides the rules, so Node can run it.

import file from "./sweatRules.json" with { type: "json" };
import type { V2Detail } from "./Sweat";

const R = file.rules;
export const RULES = R;
export const RULES_VERSION: string = R.version;
export const RULES_SHA256: string = file.sha256;

/** One made-up workout on its own challenge day, recorded by Oura, with every required check passed. */
export type SampleInput = {
  activity: string;
  minutes: number; // whole minutes
  intensity: string | null; // Oura's label
  heartPct: number | null; // session heart rate against the player's own usual level, %; null = no reference
  distanceKm: number | null;
  hrMinutes: number; // minutes holding a heart-rate sample recorded as exercise (0 = none)
  quarters: number; // how many quarters of the workout those samples fall in
};

const hundredths = (text: string) => Math.round(Number(text) * 100);
const thousandths = (text: string) => Math.round(Number(text) * 1000);
/** Whole-number division, halves rounded away from zero (the server's ROUND_HALF_UP). */
const div = (n: number, d: number) => {
  const q = Math.floor((2 * Math.abs(n) + d) / (2 * d));
  return n < 0 ? -q : q;
};
const show = (n: number, places: number) => (n / 10 ** places).toFixed(places);
const clamp = (lo: number, hi: number, n: number) => Math.min(hi, Math.max(lo, n));

type Factor = V2Detail["score"]["factors"]["provider"];
const neutral = (reason: string): Factor & { milli: number } => ({ value: "1.00", state: "unavailable", reason, milli: 1000 });

function providerFactor(intensity: string | null) {
  const table = R.provider_factor as Record<string, string>;
  if (intensity === null || !(intensity in table)) return neutral("no_intensity");
  return { value: table[intensity], state: "provider_estimated" as const, reason: intensity, milli: thousandths(table[intensity]) };
}

function heartFactor(input: SampleInput) {
  if (input.hrMinutes <= 0) return neutral("no_heart_rate");
  if (input.hrMinutes < R.heart.min_bins || input.hrMinutes / input.minutes < R.heart.min_coverage) return neutral("not_enough_heart_rate");
  if (input.heartPct === null) return neutral("no_personal_reference");
  // 1 + slope x (session / reference - 1), where the ratio is (100 + pct) / 100.
  const raw = 1000 + div(hundredths(R.heart.slope) * input.heartPct, 10);
  const milli = clamp(thousandths(R.heart.range[0]), thousandths(R.heart.range[1]), raw);
  return {
    value: show(milli, 3), state: "measured" as const, reason: "relative_to_reference", milli,
    relative_percent: input.heartPct, reference_workouts: 6,
  };
}

function movementFactor(input: SampleInput) {
  const bands = (R.movement_bands as Record<string, (number | string)[][]>)[input.activity];
  if (!bands) return neutral("no_pace_for_category");
  if (input.distanceKm === null || !(input.distanceKm > 0) || input.minutes <= 0) return neutral("no_distance");
  const speed = input.distanceKm / (input.minutes / 60);
  let value = bands[0][1] as string;
  for (const [low, factor] of bands) if (speed >= (low as number)) value = factor as string;
  return { value, state: "measured" as const, reason: "pace_band", milli: thousandths(value), speed_kmh: Math.round(speed * 10) / 10 };
}

function evidenceIndex(input: SampleInput, movementObserved: boolean): V2Detail["evidence"] {
  const E = R.evidence_index;
  const strong = R.strong_evidence;
  const parts: V2Detail["evidence"]["parts"] = [
    { key: "provenance", max: E.provenance.max, points: E.provenance.native, state: "full", reason: null },
    { key: "integrity", max: E.integrity.max, points: E.integrity.clean, state: "full", reason: null },
    movementObserved
      ? { key: "movement", max: E.movement.max, points: E.movement.observed, state: "full", reason: null }
      : { key: "movement", max: E.movement.max, points: E.movement.unobserved, state: "unavailable", reason: "not_observed" },
  ];
  const limits: string[] = [];
  const coverage = input.minutes > 0 ? input.hrMinutes / input.minutes : 0;
  const P = E.physiological;
  if (input.hrMinutes <= 0) {
    parts.push({ key: "physiological", max: P.max, points: 0, state: "unavailable", reason: "not_observed" });
    limits.push("no_heart_rate");
  } else {
    const sub = {
      coverage: Math.floor(P.coverage * Math.min(1, coverage)),
      exercise_tagged: P.exercise_tagged,
      distribution: input.quarters >= 3 ? P.distribution : 0,
      validity: P.validity,
    };
    const points = sub.coverage + sub.exercise_tagged + sub.distribution + sub.validity;
    parts.push({
      key: "physiological", max: P.max, points, state: points === P.max ? "full" : "partial", sub,
      reason: points === P.max ? null : coverage < strong.min_coverage ? "low_coverage" : "partial_signal",
    });
    if (coverage < strong.min_coverage || input.hrMinutes < strong.min_bins) limits.push("low_coverage");
    if (input.hrMinutes < strong.min_samples) limits.push("few_samples");
  }
  const index = parts.reduce((sum, p) => sum + p.points, 0);
  if (!limits.length && index < strong.min_index) limits.push("index_below_strong");
  const share = (R.reliability as (number | string)[][]).find(([low]) => index >= (low as number))![1] as string;
  return { index, parts, label: limits.length ? "limited" : "strong", limits, reliability: share };
}

/** The receipt breakdown the server would produce for this workout (scores.sweat2_detail). */
export function scoreSample(input: SampleInput): V2Detail {
  // Base: the day's minutes laid onto the diminishing bands. One workout, so it starts at the day's first minute.
  const bandMinutes: number[] = [];
  let left = input.minutes;
  let base = 0; // hundredths of a point
  for (const [size, weight] of R.bands as (number | string)[][]) {
    const used = Math.min(left, size as number);
    bandMinutes.push(used);
    base += used * hundredths(weight as string);
    left -= used;
  }
  bandMinutes.push(left);

  const { milli: pm, ...provider } = providerFactor(input.intensity);
  const { milli: hm, ...heart } = heartFactor(input);
  const { milli: mm, ...movement } = movementFactor(input);
  const W = R.weights;
  const raw = hundredths(W.provider) * pm + hundredths(W.heart) * hm + hundredths(W.movement) * mm; // x 100,000
  const multiplier = clamp(thousandths(R.multiplier_range[0]), thousandths(R.multiplier_range[1]), div(raw, 100));

  const evidence = evidenceIndex(input, movement.state === "measured");
  const share = hundredths(evidence.reliability!);
  const lift = multiplier - 1000;
  const part = (weight: string, milli: number) => show(div(base * hundredths(weight) * (milli - 1000), 100000), 2);

  return {
    intensity: input.intensity,
    distance_km: input.distanceKm,
    evidence,
    score: {
      eligible_minutes: input.minutes,
      band_minutes: bandMinutes,
      band_weights: [...(R.bands as (number | string)[][]).map(([, weight]) => weight as string), "0"],
      effective_minutes: show(base, 2),
      base_points: show(base, 2),
      factors: {
        provider: { ...provider, bonus: part(W.provider, pm) },
        heart: { ...heart, bonus: part(W.heart, hm) },
        movement: { ...movement, bonus: part(W.movement, mm) },
      },
      weights: W,
      multiplier_range: R.multiplier_range,
      multiplier: show(multiplier, 3),
      potential_bonus: show(div(base * lift, 1000), 2),
      reliability: evidence.reliability,
      adjusted_bonus: show(div(base * lift * share, 100000), 2),
      contribution: show(div(base * (100000 + lift * share), 100000), 2),
    },
  };
}
