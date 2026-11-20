// Proof of Sweat: a player's own Oura workouts in one challenge, each with its verification receipt.
// Everything here is private to the signed-in player. Points and checks are worked out on the server
// (api/sweat.py); this file only explains them.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  Bike,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleMinus,
  Dumbbell,
  Footprints,
  Lock,
  Mountain,
  PersonStanding,
  RefreshCw,
  ShieldCheck,
  Waves,
  type LucideIcon,
} from "lucide-react";
import { ApiError, type Call } from "./api";
import type { Session } from "./App";
import { EmptyState, Eyebrow, Skeleton } from "./ui";

type Result = "passed" | "limited" | "failed" | "pending";
type CheckRow = { code: string; result: Result; reason: string | null };

/** One workout as the server describes it to its owner. */
export type Workout = {
  key: number | string;
  activity: string | null;
  provider_activity?: string | null;
  provider_source?: string | null;
  start?: string | null;
  duration_minutes: number;
  result: "verified" | "rejected" | "pending";
  assurance: "strong" | "limited" | null;
  reason: string | null;
  eligible_minutes: number | null;
  points: number | null;
  heart_rate_coverage_pct?: number | null;
  checks: CheckRow[];
  commitment?: string; // final receipts only: the hash listed in the score sheet
  v2?: V2Detail | null; // Proof of Sweat v2: Evidence Index and Sweat Score breakdown
};

type FactorView = {
  value: string;
  state: "measured" | "provider_estimated" | "unavailable";
  reason: string | null;
  bonus?: string; // this signal's part of the potential effort bonus, in points
  relative_percent?: number; // heart: this session against the player's own reference
  reference_workouts?: number;
  speed_kmh?: number;
};

type EvidencePart = {
  key: "provenance" | "integrity" | "movement" | "physiological";
  max: number;
  points: number;
  state: "full" | "partial" | "unavailable" | "failed" | "pending";
  reason: string | null;
  sub?: Record<string, number>;
};

/** What the server works out for one workout under the effort-weighted rules (api/sweat2.py, api/sweat3.py). No heart-rate readings. */
export type V2Detail = {
  intensity: string | null;
  distance_km: number | null;
  evidence: {
    index: number;
    parts: EvidencePart[];
    label: "strong" | "limited" | "pending" | "rejected";
    limits: string[];
    reliability?: string; // share of the effort bonus this index supports, e.g. "0.85"
  };
  score: {
    eligible_minutes: number;
    band_minutes: number[]; // this workout's minutes in each daily band; the last entry is past the cap
    band_weights: string[];
    effective_minutes: string;
    factors: { provider: FactorView; heart: FactorView; movement: FactorView };
    weights: { provider: string; heart: string; movement: string };
    multiplier_range?: string[]; // lowest and highest effort multiplier under this challenge's rules
    multiplier: string;
    base_points?: string; // effective minutes: what duration alone earns
    potential_bonus?: string; // what the effort signals suggest on top (can be negative)
    reliability?: string;
    adjusted_bonus?: string; // potential bonus x reliability: what actually counts
    contribution: string;
  };
};

type FinalReceipt = {
  commitment: string;
  canonical: string;
  // v2 receipts (schema 2) carry the breakdown at the top level and points as an exact decimal string.
  receipt: Omit<Workout, "key" | "start" | "commitment" | "points" | "v2"> & {
    rules_version: string;
    schema?: number;
    points: number | string;
  } & Partial<V2Detail>;
};

export type SweatReply = {
  connected: boolean;
  available: boolean;
  last_sync_at: string | null;
  last_sync_error: string | null;
  rules: { version: string; sha256: string | null; summary: string; generation?: number } | null;
  /** v2: whether the player's personal heart-rate reference exists for this challenge. Never its value. */
  reference?: { frozen: boolean; available: boolean; workouts: number };
  days?: { day: number; minutes: number; points: number; effective_minutes: string }[];
  final: boolean;
  eligible_minutes: number | null;
  points: number | null;
  workouts: Workout[];
  receipts: FinalReceipt[];
};

const ICON: Record<string, LucideIcon> = {
  run: PersonStanding,
  walk: Footprints,
  hike: Mountain,
  ride: Bike,
  swim: Waves,
  workout: Dumbbell,
};

const ACTIVITY_NAME: Record<string, string> = {
  run: "Run",
  walk: "Walk",
  hike: "Hike",
  ride: "Ride",
  swim: "Swim",
  workout: "Workout",
};

/** Why a workout was not counted, or why its evidence is limited, in plain words. */
const REASON: Record<string, string> = {
  manual_entry: "It was entered by hand in Oura, so there is no recording to check.",
  unknown_source: "Oura didn't say how this workout was recorded.",
  unauthorized_provider: "It didn't come through your connected Oura account.",
  unsupported_activity: "This type of activity isn't counted yet.",
  activity_not_in_challenge: "This event counts one sport, and Oura recorded this workout as a different activity.",
  missing_time: "Oura sent it without a usable start and end time.",
  ends_before_start: "Its end time is before its start time.",
  too_long: "It runs for more than 24 hours.",
  in_the_future: "It ends in the future.",
  under_minimum: "It is shorter than 10 minutes.",
  under_minimum_in_window: "Fewer than 10 minutes of it fall inside this challenge.",
  invalid_distance: "Its distance isn't a valid number.",
  too_fast: "Its distance and time give a speed that isn't believable for this activity.",
  duplicate_time: "Another workout already covers this whole time.",
  partly_overlapping: "Part of it overlaps another workout. Each minute counts once.",
  removed_at_provider: "It no longer appears in your Oura account.",
  no_heart_rate: "Oura returned no heart-rate measurements for this workout.",
  low_coverage: "Heart-rate measurements were unavailable for much of this workout.",
  background_only: "Only background heart-rate readings were available, none recorded as exercise.",
  heart_rate_unavailable: "Heart-rate measurements couldn't be read from Oura.",
  third_party_source: "Its heart rate came from a third-party device, which we rate cautiously.",
  quality_warning: "Some heart-rate readings were unusable and were left out.",
  no_distance: "No distance was recorded, which is fine.",
};

/** A few words for the workout list, where the full sentence would not fit. */
const SHORT_REASON: Record<string, string> = {
  activity_not_in_challenge: "different activity",
  unsupported_activity: "activity not supported",
  manual_entry: "entered by hand",
  too_fast: "speed not believable",
  under_minimum: "under 10 minutes",
  under_minimum_in_window: "under 10 minutes in this event",
  duplicate_time: "overlaps another workout",
};

const worst = (results: (Result | undefined)[]): Result | null => {
  const found = results.filter(Boolean) as Result[];
  if (!found.length) return null;
  for (const level of ["failed", "pending", "limited", "passed"] as Result[]) if (found.includes(level)) return level;
  return null;
};

type Line = { label: string; result: Result | null; detail: string };

/** The eight lines of a receipt, built from the server's check codes. */
function receiptLines(w: Workout): Line[] {
  const by = Object.fromEntries(w.checks.map((c) => [c.code, c])) as Record<string, CheckRow | undefined>;
  const why = (...codes: string[]) => {
    const failed = codes.map((c) => by[c]).find((c) => c && c.result !== "passed" && c.reason);
    return failed?.reason ? (REASON[failed.reason] ?? failed.reason) : null;
  };
  const source = worst([by.provider?.result, by.provenance?.result]);
  const timing = worst([by.timestamps?.result, by.window?.result]);
  const evidence = by.evidence?.result ?? null;
  const coverage = w.heart_rate_coverage_pct;
  return [
    {
      label: "Oura source authenticated",
      result: source,
      detail: why("provider", "provenance") ?? "Fetched through your authorized Oura connection, from a recorded (not hand-entered) workout.",
    },
    {
      label: "Eligible activity type",
      result: by.activity?.result ?? null,
      detail: why("activity") ?? "Its activity type maps to one Rival counts.",
    },
    {
      label: "Challenge time window valid",
      result: timing,
      detail: why("timestamps", "window") ?? "Valid start and end times. Only minutes inside the challenge are counted.",
    },
    {
      label: "Minimum duration passed",
      result: by.window?.reason === "under_minimum_in_window" ? "failed" : (by.duration?.result ?? null),
      detail: why("duration") ?? (by.window?.reason === "under_minimum_in_window" ? REASON.under_minimum_in_window : "At least 10 minutes long."),
    },
    {
      label: "Plausibility checks passed",
      result: by.plausibility?.result ?? null,
      detail:
        by.plausibility?.result === "failed"
          ? (why("plausibility") ?? "Not believable.")
          : by.plausibility?.reason === "no_distance"
            ? "No distance was recorded, so there was no speed to check. That is not held against it."
            : "Distance and time give a believable speed for this activity.",
    },
    {
      label: "Duplicate check passed",
      result: by.duplicate?.result ?? null,
      detail: why("duplicate") ?? "No other workout of yours covers the same time, and it is counted once in this challenge.",
    },
    {
      label: "Physiological evidence assessed",
      result: evidence,
      detail:
        evidence === "passed"
          ? `Heart-rate measurements recorded as exercise cover ${coverage != null ? `${coverage}% of` : "most of"} this workout.` +
            (by.evidence?.reason === "quality_warning" ? ` ${REASON.quality_warning}` : "")
          : evidence === "limited"
            ? `${REASON[by.evidence?.reason ?? ""] ?? "The heart-rate evidence is limited."} The activity remains eligible because its Oura recording and the other required checks passed.`
            : evidence === "pending"
              ? "Waiting to read heart-rate coverage from Oura."
              : "Not assessed, because a required check failed first.",
    },
    {
      label: "Scoring rules applied",
      result: by.scoring?.result ?? (w.result === "rejected" ? "failed" : null),
      detail:
        w.result === "verified"
          ? w.v2
            ? `${w.eligible_minutes ?? 0} eligible minutes, weighted by the day's bands and this workout's effort multiplier. See the breakdown above.`
            : `${w.eligible_minutes ?? 0} eligible minutes. 1 point per 10 minutes, up to 6 a day across all your workouts.`
          : w.result === "pending"
            ? "Points are added once the checks finish."
            : "No points: a required check did not pass.",
    },
  ];
}

const RESULT_WORD: Record<Result, string> = { passed: "Passed", limited: "Limited evidence", failed: "Failed", pending: "Pending" };

function ResultIcon({ result }: { result: Result | null }) {
  if (result === "passed") return <CircleCheck size={16} aria-hidden />;
  if (result === "limited") return <CircleMinus size={16} aria-hidden />;
  if (result === "failed") return <CircleAlert size={16} aria-hidden />;
  return <CircleDashed size={16} aria-hidden />;
}

function statusOf(w: Workout): { tone: "strong" | "limited" | "rejected" | "pending"; label: string; line: string } {
  if (w.result === "pending") return { tone: "pending", label: "Checking", line: "Checking your activity." };
  if (w.result === "rejected")
    return { tone: "rejected", label: "Not counted", line: REASON[w.reason ?? ""] ?? "A required check did not pass." };
  if (w.assurance === "strong") return { tone: "strong", label: "Verified", line: "Proof of Sweat verified." };
  return { tone: "limited", label: "Verified · limited evidence", line: "Verified. Limited heart-rate evidence." };
}

const when = (iso: string) =>
  new Date(iso).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

const ago = (iso: string) => {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
};

const SYNC_ERROR: Record<string, string> = {
  reconnect: "Oura needs to be reconnected. Disconnect and connect it again from your dashboard.",
  permission: "Oura refused access to workouts. Reconnect and allow workouts and heart rate.",
  rate_limited: "Oura is busy. The last sync didn't finish; try again in a few minutes.",
  unreachable: "Oura couldn't be reached on the last sync. Your points are unchanged.",
  error: "The last sync didn't finish. Your points are unchanged.",
};

const fmtPoints = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

const PART_INFO: Record<EvidencePart["key"], { label: string; what: string }> = {
  provenance: {
    label: "Source authentication",
    what: "An authorized Oura record from a recorded source. Full marks for Oura's own sources; fewer for a third-party heart-rate source.",
  },
  integrity: {
    label: "Timing and duplicates",
    what: "Valid times, inside this challenge, at least 10 minutes, and not counted twice. A partly overlapping workout scores a little lower.",
  },
  movement: {
    label: "Movement plausibility",
    what: "Distance and time agree with the activity type. With no usable distance this is \"not observed\" (7 of 15), which is not a mark against you.",
  },
  physiological: {
    label: "Physiological evidence",
    what: "How much of the workout has usable heart-rate samples (15), whether any were recorded as exercise (5), how well they are spread (3), and whether all were clean (2). No samples is \"not observed\" (0 of 25), not evidence of anything.",
  },
};

const FACTOR_REASON: Record<string, string> = {
  easy: "Oura labelled this session easy.",
  moderate: "Oura labelled this session moderate. Oura can use this label by default when it has little to go on.",
  hard: "Oura labelled this session hard.",
  no_intensity: "Oura gave no intensity label, so this factor is neutral.",
  no_heart_rate: "No heart-rate samples for this workout, so this factor is neutral.",
  not_enough_heart_rate: "Too few heart-rate samples recorded as exercise to say anything, so this factor is neutral.",
  no_personal_reference: "You don't have enough earlier workouts with heart rate to compare against yet, so this factor is neutral.",
  no_pace_for_category: "Pace doesn't mean much for this kind of activity, so this factor is neutral.",
  no_distance: "No distance was recorded, so this factor is neutral.",
};

const STATE_WORD: Record<FactorView["state"], string> = {
  measured: "Measured",
  provider_estimated: "Oura's estimate",
  unavailable: "Neutral fallback",
};

function factorLine(key: "provider" | "heart" | "movement", f: FactorView): string {
  if (key === "heart" && f.state === "measured") {
    const pct = f.relative_percent ?? 0;
    const side = pct === 0 ? "level with" : pct > 0 ? `${pct}% above` : `${-pct}% below`;
    return `Your heart rate this session was ${side} your own usual workout level (from ${f.reference_workouts} earlier workouts). Never an absolute pulse target.`;
  }
  if (key === "movement" && f.state === "measured") return `Average ${f.speed_kmh} km/h, placed in this activity's own pace bands.`;
  return FACTOR_REASON[f.reason ?? ""] ?? "";
}

/** A factor on its real scale, with the neutral 1.00 marked. */
function Gauge({ label, weight, f, line, scale }: { label: string; weight: string; f: FactorView; line: string; scale: [number, number] }) {
  const [lo, hi] = scale;
  const value = Number(f.value);
  const at = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100))}%`;
  const from = Math.min(1, value);
  const to = Math.max(1, value);
  return (
    <div className={`sweat-gauge ${f.state}${value > 1 ? " up" : value < 1 ? " down" : ""}`}>
      <div className="sweat-gauge-head">
        <span>
          {label} <small>weight {weight}</small>
        </span>
        <em>{STATE_WORD[f.state]}</em>
        <b>
          ×{f.value}
          {f.bonus != null && <small>{signed(f.bonus)} pts</small>}
        </b>
      </div>
      <div className="sweat-gauge-track" role="img" aria-label={`${label} factor ${f.value}; 1.00 is neutral`}>
        <i className="fill" style={{ left: at(from), width: `calc(${at(to)} - ${at(from)})` }} />
        <i className="neutral" style={{ left: at(1) }} />
        <i className="dot" style={{ left: at(value) }} />
      </div>
      <p>{line}</p>
    </div>
  );
}

const signed = (text: string) => (Number(text) > 0 ? `+${text}` : Number(text) === 0 ? "0.00" : text.replace("-", "−"));

const BAND_LABEL = ["Day's 1st hour", "2nd hour", "3rd hour", "Past 3 hours"];

/** A numbered part of the receipt: what it is, and its one-line result on the right. */
function Part(props: { n: string; title: string; hint: string; result?: ReactNode; tone?: string; children: ReactNode }) {
  return (
    <section className={`sweat-part${props.tone ? ` ${props.tone}` : ""}`}>
      <header>
        <span className="sweat-part-n">{props.n}</span>
        <h4>
          {props.title} <span>{props.hint}</span>
        </h4>
        {props.result != null && <b className="sweat-part-result">{props.result}</b>}
      </header>
      {props.children}
    </section>
  );
}

/** Secondary detail, closed until asked for. */
function More({ label, open, children }: { label: ReactNode; open?: boolean; children: ReactNode }) {
  return (
    <details className="sweat-more" open={open}>
      <summary>
        <ChevronDown size={14} aria-hidden /> {label}
      </summary>
      <div>{children}</div>
    </details>
  );
}

/** The effort-weighted receipt (rules v2 and later): result first, then Activity, Verification, Effort, Final score. */
function ReceiptV2(props: {
  w: Workout;
  name: string;
  status: ReturnType<typeof statusOf>;
  lines: Line[];
  rulesVersion: string | null;
  sample?: boolean; // made-up numbers (the explainer), not a real workout
}) {
  const { w, name, status } = props;
  const { evidence, score } = w.v2!;
  const verified = w.result === "verified";
  const f = score.factors;
  const maxBand = Math.max(1, ...score.band_minutes);
  const base = score.base_points ?? score.effective_minutes;
  const potential = score.potential_bonus ?? "0.00";
  const adjusted = score.adjusted_bonus ?? "0.00";
  const share = Math.round(Number(score.reliability ?? evidence.reliability ?? 1) * 100);
  const withheld = Math.abs(Number(potential)) - Math.abs(Number(adjusted));
  const scale = Math.max(1, Number(base) + Math.max(0, Number(potential)));
  const fallbacks = (["provider", "heart", "movement"] as const).filter((k) => f[k].state === "unavailable").length;
  const range = score.multiplier_range ?? ["0.85", "1.25"];
  const gaugeScale: [number, number] = score.multiplier_range ? [0.75, 1.7] : [0.85, 1.25];
  // The three signals' parts add up to the potential bonus unless the multiplier hit its limit.
  const signalSum = Number(f.provider.bonus ?? 0) + Number(f.heart.bonus ?? 0) + Number(f.movement.bonus ?? 0);
  const limited = verified && Math.abs(signalSum - Number(potential)) > 0.015;
  const tapered = score.band_minutes.slice(1).some((m) => m > 0);
  const checks = props.lines.filter((line) => line.label !== "Physiological evidence assessed");
  const passed = checks.filter((line) => line.result === "passed").length;
  const clean = passed === checks.length;
  const signals = (
    [
      ["heart", "Heart rate", "against your own usual"],
      ["movement", "Movement", "pace for the activity"],
      ["provider", "Oura intensity", "Oura's own label"],
    ] as const
  )
    .slice()
    .sort((a, b) => Number(score.weights[b[0]]) - Number(score.weights[a[0]]));
  const pct = (weight: string) => `${Math.round(Number(weight) * 100)}%`;

  return (
    <div className="sweat-receipt v2">
      <div className="sweat-receipt-head">
        <span className="sweat-wordmark">
          Proof of <em className="serif">sweat.</em>
        </span>
        <span className="sweat-head-tags">
          {props.sample && <span className="sweat-badge sample">Sample</span>}
          <span className="sweat-badge">Receipt · recorded by Oura</span>
        </span>
      </div>

      <div className={`sweat-hero ${status.tone}`}>
        <div className="sweat-hero-what">
          <span className={`sweat-verdict ${status.tone}`}>
            {status.tone === "rejected" ? <CircleAlert size={15} aria-hidden /> : status.tone === "pending" ? <CircleDashed size={15} aria-hidden /> : <ShieldCheck size={15} aria-hidden />}
            {status.label}
          </span>
          <strong>
            {name} · {w.duration_minutes} min
          </strong>
          <small>
            {verified
              ? `${passed} of ${checks.length} required checks passed before this could score.`
              : status.tone === "pending"
                ? "Checks are still running."
                : status.line}
          </small>
        </div>
        <div className="sweat-score">
          <span>Sweat Points</span>
          <b>{verified ? score.contribution : "0"}</b>
          <small>{verified ? "from this workout" : status.tone === "pending" ? "pending checks" : "not counted"}</small>
        </div>
      </div>

      <div className="sweat-into">
        <h4>What went into this score</h4>
        <dl>
          <div className="minutes">
            <dt>Minutes</dt>
            <dd>
              {verified ? base : "0"}
              <small>base points</small>
            </dd>
            <span className="meter">
              <i style={{ width: `${Math.min(100, ((w.eligible_minutes ?? 0) / 60) * 100)}%` }} />
            </span>
            <p>{w.eligible_minutes ?? 0} verified min, about a point each</p>
          </div>
          <div className="effort">
            <dt>Effort</dt>
            <dd>
              ×{verified ? score.multiplier : "1.000"}
              <small>{verified ? `${signed(potential)} pts` : "no bonus"}</small>
            </dd>
            <span className="meter">
              <i style={{ width: `${Math.min(100, Math.max(4, ((Number(score.multiplier) - Number(range[0])) / (Number(range[1]) - Number(range[0]))) * 100))}%` }} />
            </span>
            <p>Heart rate, movement and Oura intensity</p>
          </div>
          <div className="evidence">
            <dt>Evidence</dt>
            <dd>
              {evidence.index}
              <small>/100 index</small>
            </dd>
            <span className="meter">
              <i style={{ width: `${evidence.index}%` }} />
            </span>
            <p>{verified ? `${share}% of the effort bonus counts` : "How complete the recording is"}</p>
          </div>
        </dl>
      </div>

      <Part n="01" title="Activity" hint="what Oura recorded" result={verified ? `${base} base` : undefined}>
        <dl className="sweat-facts">
          <div>
            <dt>Counted</dt>
            <dd>{w.eligible_minutes ?? 0} min</dd>
          </div>
          {w.v2!.distance_km != null && w.v2!.distance_km > 0 && (
            <div>
              <dt>Distance</dt>
              <dd>{w.v2!.distance_km} km</dd>
            </div>
          )}
          <div>
            <dt>Oura intensity</dt>
            <dd className="word">{w.v2!.intensity ?? "none"}</dd>
          </div>
          {verified && (
            <div>
              <dt>Base points</dt>
              <dd>{base}</dd>
            </div>
          )}
        </dl>
        {verified && (
          <More label="How minutes become base points" open={tapered}>
            <div className="sweat-bands">
              {score.band_minutes.map((m, i) => (
                <div key={i} className={`sweat-band${m > 0 ? " on" : ""}${i === 3 ? " over" : ""}`}>
                  <span className="bar">
                    <i style={{ height: `${(m / maxBand) * 100}%` }} />
                  </span>
                  <b>{m > 0 ? `${m} min` : "–"}</b>
                  <span>{BAND_LABEL[i]}</span>
                  <small>×{score.band_weights[i]}</small>
                </div>
              ))}
            </div>
            <p className="fine">
              About a point a minute. Each day's first hour counts in full, the second at 0.6 and the third at 0.25, in time order
              across all your workouts that day. A game rule so one long day can't decide a week, not exercise advice.
            </p>
          </More>
        )}
      </Part>

      <Part
        n="02"
        title="Verification"
        hint="checked before it can score"
        tone={status.tone}
        result={
          <>
            {evidence.index}
            <small>/100</small>
          </>
        }
      >
        <div className="sweat-evidence-bar" role="img" aria-label={`Evidence Index ${evidence.index} of 100`}>
          {evidence.parts.map((p) => (
            <span key={p.key} className={`seg ${p.key} ${p.state}`} style={{ flexGrow: p.max }}>
              <i style={{ width: `${(p.points / p.max) * 100}%` }} />
            </span>
          ))}
        </div>
        <ul className="sweat-parts">
          {evidence.parts.map((p) => (
            <li key={p.key} className={`${p.key} ${p.state}`}>
              <details>
                <summary>
                  <i aria-hidden />
                  {/* A failed required check of any kind zeroes this part, so name it for what it is. */}
                  <span>{p.reason === "gate_failed" ? "Required checks" : PART_INFO[p.key].label}</span>
                  <em>
                    {p.state === "unavailable" ? "Not observed" : p.state === "failed" ? "Not passed" : p.state === "pending" ? "Pending" : ""}
                  </em>
                  <b>
                    {p.points}
                    <small>/{p.max}</small>
                  </b>
                </summary>
                <p>
                  {p.reason === "gate_failed"
                    ? "A required check below did not pass, so this part scores zero."
                    : PART_INFO[p.key].what}
                  {p.sub && ` Here: coverage ${p.sub.coverage}/15, recorded as exercise ${p.sub.exercise_tagged}/5, spread ${p.sub.distribution}/3, clean ${p.sub.validity}/2.`}
                  {p.reason && REASON[p.reason] ? ` ${REASON[p.reason]}` : ""}
                </p>
              </details>
            </li>
          ))}
        </ul>
        <More
          open={!clean}
          label={
            <>
              Required checks{" "}
              <em className={clean ? "ok" : "warn"}>
                {passed} of {checks.length} passed
              </em>
            </>
          }
        >
          <ul className="sweat-checks">
            {checks.map((line) => (
              <li key={line.label} className={line.result ?? "skipped"}>
                <ResultIcon result={line.result} />
                <details>
                  <summary>
                    <span>{line.label}</span>
                    <em>{line.result ? RESULT_WORD[line.result] : "Not assessed"}</em>
                  </summary>
                  <p>{line.detail}</p>
                </details>
              </li>
            ))}
          </ul>
        </More>
        <p className="fine">
          A failed required check always means zero. The Evidence Index then rates how complete the recording is; it is a rule-based
          score, not a probability that the workout happened.
        </p>
      </Part>

      {verified && (
        <Part n="03" title="Effort analysis" hint="how hard, from three signals" result={`×${score.multiplier}`}>
          <div className="sweat-gauges">
            {signals.map(([key, label]) => (
              <Gauge key={key} label={label} weight={pct(score.weights[key])} f={f[key]} line={factorLine(key, f[key])} scale={gaugeScale} />
            ))}
          </div>
          <p className="fine">
            Weighted together into one effort multiplier, kept between ×{range[0]} and ×{range[1]}
            {limited ? `; this workout reached that limit` : ""}. A signal with no usable data sits at a neutral ×1.00
            {fallbacks > 0 ? ` (${fallbacks} of 3 here)` : ""}, so missing data is never a bonus or a penalty.
          </p>
        </Part>
      )}

      {verified && (
        <Part n="04" title="Final score" hint="base + effort, as far as the evidence supports" result={score.contribution}>
          <div className="sweat-stack" role="img" aria-label={`Base ${base}, effort bonus counted ${adjusted} of ${potential}`}>
            <i className="base" style={{ width: `${(Number(base) / scale) * 100}%` }} />
            {Number(adjusted) > 0 && <i className="bonus" style={{ width: `${(Number(adjusted) / scale) * 100}%` }} />}
            {Number(potential) > 0 && withheld > 0.004 && <i className="held" style={{ width: `${(withheld / scale) * 100}%` }} />}
          </div>
          <dl className="sweat-steps">
            <div>
              <dt>Base points</dt>
              <dd>{base}</dd>
            </div>
            <div>
              <dt>
                Effort bonus <small>base × (×{score.multiplier} − 1)</small>
              </dt>
              <dd>{signed(potential)}</dd>
            </div>
            <div className="rel">
              <dt>
                Evidence supports <small>Evidence Index {evidence.index}/100</small>
              </dt>
              <dd>× {share}%</dd>
            </div>
            <div className="final">
              <dt>Sweat Points from this workout</dt>
              <dd>{score.contribution}</dd>
            </div>
          </dl>
          <p className="sweat-oneline">
            {Number(potential) === 0
              ? `Nothing in the effort signals moved this workout off its base of ${base}.`
              : share === 100
                ? `The recording backs the effort signals fully, so the whole ${signed(potential)} counts.`
                : `The evidence scored ${evidence.index}/100, so ${share}% of the ${signed(potential)} effort adjustment counts: ${signed(adjusted)}.`}
          </p>
          <More label="Every step of the calculation">
            <dl className="sweat-steps small">
              <div>
                <dt>Base points × heart-rate weight {pct(score.weights.heart)} × (×{f.heart.value} − 1)</dt>
                <dd>{signed(f.heart.bonus ?? "0.00")}</dd>
              </div>
              <div>
                <dt>Base points × movement weight {pct(score.weights.movement)} × (×{f.movement.value} − 1)</dt>
                <dd>{signed(f.movement.bonus ?? "0.00")}</dd>
              </div>
              <div>
                <dt>Base points × Oura intensity weight {pct(score.weights.provider)} × (×{f.provider.value} − 1)</dt>
                <dd>{signed(f.provider.bonus ?? "0.00")}</dd>
              </div>
              <div>
                <dt>
                  Effort bonus{limited ? ` (multiplier held at its ×${Number(potential) > 0 ? range[1] : range[0]} limit)` : ""}
                </dt>
                <dd>{signed(potential)}</dd>
              </div>
              <div>
                <dt>× evidence reliability {share}%</dt>
                <dd>{signed(adjusted)}</dd>
              </div>
              <div>
                <dt>Base {base} + counted bonus</dt>
                <dd>{score.contribution}</dd>
              </div>
            </dl>
            <p className="fine">
              Reliability steps: an Evidence Index of 90+ counts 100% of the effort bonus, 75+ counts 85%, 50+ counts 65%, below that
              40%. Base points never depend on the index. A day's total is rounded to a whole number once, after adding its workouts.
              Scoring rules for a friendly game, not a measure of fitness or calories.
            </p>
          </More>
        </Part>
      )}

      <p className="fine sweat-foot">
        {props.rulesVersion ? `Rules ${props.rulesVersion}. ` : ""}
        {props.sample
          ? "Illustrative numbers, worked out with the app's real scoring rules. A real receipt comes from a workout your Oura Ring recorded."
          : "Rival's server checked this record from Oura against published rules. That is evidence, not proof that a workout happened."}
        {props.sample ? null : w.commitment ? (
          <>
            {" "}
            Receipt fingerprint <code>{w.commitment.slice(0, 16)}…</code> is listed in this challenge's final score sheet, whose hash
            Solana stored at payout. Use "Check result" on this page to verify it.
          </>
        ) : (
          " After the challenge settles, this receipt's fingerprint goes into the signed score sheet whose hash Solana stores."
        )}
      </p>
    </div>
  );
}

/** The receipt on its own, for the "how points work" explainer. Always made-up data. */
export function SampleReceipt({ w, rulesVersion }: { w: Workout; rulesVersion: string }) {
  const name = ACTIVITY_NAME[w.activity ?? ""] ?? "Activity";
  return <ReceiptV2 w={w} name={name} status={statusOf(w)} lines={receiptLines(w)} rulesVersion={rulesVersion} sample />;
}

/** One workout row that opens into its receipt. */
function WorkoutReceipt({ w, rulesVersion }: { w: Workout; rulesVersion: string | null }) {
  const [open, setOpen] = useState(false);
  const Icon = ICON[w.activity ?? ""] ?? Activity;
  const status = statusOf(w);
  const name = ACTIVITY_NAME[w.activity ?? ""] ?? w.provider_activity ?? "Activity";
  const lines = receiptLines(w);
  return (
    <div className={`sweat-item ${status.tone}${open ? " open" : ""}`}>
      <button className="sweat-row" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="icon-tile icon-tile-sm">
          <Icon size={15} strokeWidth={1.75} aria-hidden />
        </span>
        <span className="sweat-row-main">
          <span className="sweat-row-title">
            <b>{name}</b> · {w.duration_minutes} min
          </span>
          <span className="fine">
            {w.start ? `${when(w.start)} · ` : ""}
            {status.label}
            {w.result === "rejected" && SHORT_REASON[w.reason ?? ""] ? ` · ${SHORT_REASON[w.reason ?? ""]}` : ""}
            {w.v2 && w.result === "verified" ? ` · Evidence ${w.v2.evidence.index}` : ""}
          </span>
        </span>
        <span className="sweat-row-points">
          {w.result === "verified" ? (
            <>
              <b>+{fmtPoints(w.points ?? 0)}</b>
              <small>pt{w.points === 1 ? "" : "s"}</small>
            </>
          ) : (
            <small>{w.result === "pending" ? "Pending" : "0 pts"}</small>
          )}
        </span>
        <ChevronDown className="sweat-chevron" size={16} aria-hidden />
      </button>

      {open && w.v2 && <ReceiptV2 w={w} name={name} status={status} lines={lines} rulesVersion={rulesVersion} />}
      {open && !w.v2 && (
        <div className="sweat-receipt">
          <div className="sweat-receipt-head">
            <span className="sweat-receipt-title">
              <ShieldCheck size={14} aria-hidden /> Proof of Sweat
            </span>
            <span className={`sweat-badge ${status.tone}`}>{status.label}</span>
          </div>
          <p className="sweat-receipt-line">{status.line}</p>
          <dl className="sweat-stats">
            <div>
              <dt>Workout</dt>
              <dd>{name}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{w.duration_minutes} min</dd>
            </div>
            <div>
              <dt>Eligible</dt>
              <dd>{w.eligible_minutes ?? 0} min</dd>
            </div>
            <div>
              <dt>Points</dt>
              <dd className="pts">{w.points ?? 0}</dd>
            </div>
          </dl>
          <ul className="sweat-checks">
            {lines.map((line) => (
              <li key={line.label} className={line.result ?? "skipped"}>
                <ResultIcon result={line.result} />
                <details>
                  <summary>
                    <span>{line.label}</span>
                    <em>{line.result ? RESULT_WORD[line.result] : "Not assessed"}</em>
                  </summary>
                  <p>{line.detail}</p>
                </details>
              </li>
            ))}
          </ul>
          <p className="fine sweat-foot">
            {rulesVersion ? `Rules ${rulesVersion}. ` : ""}
            These checks compare what Oura recorded with Rival's published rules. They don't prove a workout happened, and heart rate
            never changes your points.
            {w.commitment && (
              <>
                {" "}
                Receipt fingerprint <code>{w.commitment.slice(0, 16)}…</code> is listed in this challenge's final score sheet.
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

/** The "My workouts" tab of a Proof of Sweat challenge. */
export default function SweatWorkouts(props: {
  session: Session;
  address: string;
  live: boolean; // the challenge is running or waiting for final syncs
  sport?: string | null; // "Running" when the event counts one sport; null when all exercise counts
  onScored: () => void;
}) {
  const { call, go } = props.session;
  const [data, setData] = useState<SweatReply | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [note, setNote] = useState<{ good: boolean; text: string } | null>(null);
  // Why nothing could be shown: "not_player" (not in this event yet) or "error". Without this a failed
  // request looked the same as one still loading.
  const [failed, setFailed] = useState<"not_player" | "error" | null>(null);

  const load = useCallback(
    () =>
      call<SweatReply>("GET", `/me/sweat?challenge=${props.address}`)
        .then((reply) => {
          setData(reply);
          setFailed(null);
        })
        .catch((e) => setFailed(e instanceof ApiError && e.status === 404 ? "not_player" : "error")),
    [call, props.address],
  );
  useEffect(() => {
    load();
  }, [load]);

  async function sync() {
    setSyncing(true);
    setNote(null);
    try {
      const done = await syncOura(call);
      setNote({ good: true, text: done });
      await load();
      props.onScored();
    } catch (e) {
      setNote({ good: false, text: e instanceof ApiError ? e.message : "Couldn't sync. Try again." });
    } finally {
      setSyncing(false);
    }
  }

  if (data === null && failed === "not_player")
    return (
      <EmptyState
        icon={<Footprints size={20} strokeWidth={1.75} />}
        title="Your workouts show up here"
        text="Join this challenge and your Oura-recorded workouts appear here with their checks. Only you can see them."
      />
    );
  if (data === null && failed)
    return (
      <EmptyState icon={<Footprints size={20} strokeWidth={1.75} />} title="Couldn't load your workouts" text="Check your connection and try again.">
        <button className="btn btn-quiet btn-sm" onClick={load}>
          Try again
        </button>
      </EmptyState>
    );
  if (data === null) return <Skeleton rows={3} height={64} />;

  const workouts: Workout[] = data.final
    ? data.receipts.map((r, i) => {
        const { evidence, score, intensity, distance_km, points, ...rest } = r.receipt;
        const v2 = evidence && score ? { evidence, score, intensity: intensity ?? null, distance_km: distance_km ?? null } : null;
        return { ...rest, points: Number(points), v2, key: i, commitment: r.commitment } as Workout;
      })
    : data.workouts;
  const counted = workouts.filter((w) => w.result === "verified");
  const isV2 = (data.rules?.generation ?? 0) >= 2;
  const topDay = Math.max(1, ...(data.days ?? []).map((d) => d.points));

  return (
    <div className="workouts sweat">
      <section className="card sweat-summary">
        <div className="sweat-summary-top">
          <div>
            <h2 className="sweat-title">
              Proof of <em className="serif">Sweat.</em>
            </h2>
            <p className="sweat-rule">
              {data.rules?.summary}
              {props.sport && ` This event counts ${props.sport.toLowerCase()} only.`}
            </p>
          </div>
          <span className="icon-tile">
            <ShieldCheck size={18} strokeWidth={1.75} aria-hidden />
          </span>
        </div>
        {isV2 && (
          <button className="btn btn-text btn-sm sweat-how" onClick={() => go({ view: "help" })}>
            How Sweat Points are calculated
          </button>
        )}
        <div className="sweat-totals">
          <div>
            <b>{data.points ?? 0}</b>
            <span>{isV2 ? "Sweat Points" : "fitness points"}</span>
          </div>
          <div>
            <b>{data.eligible_minutes ?? 0}</b>
            <span>verified minutes</span>
          </div>
          <div>
            <b>{counted.length}</b>
            <span>workout{counted.length === 1 ? "" : "s"} counted</span>
          </div>
        </div>

        {isV2 && !!data.days?.length && (
          <div className="sweat-days" aria-label="Sweat Points by challenge day">
            {data.days.map((d) => (
              <div key={d.day} className="sweat-day" title={`${d.minutes} min, ${d.effective_minutes} effective`}>
                <i style={{ height: `${Math.max(6, (d.points / topDay) * 100)}%` }} />
                <b>{d.points}</b>
                <span>Day {d.day + 1}</span>
              </div>
            ))}
          </div>
        )}
        {isV2 && data.reference && !data.final && data.connected && (
          <p className="fine">
            {data.reference.available
              ? `Heart-rate effort is compared with your own ${data.reference.workouts} earlier workouts, fixed when this challenge started.`
              : data.reference.frozen
                ? "There weren't enough earlier workouts with heart rate to build your personal reference, so the heart-rate factor stays neutral (1.00) in this challenge."
                : "Your personal heart-rate reference is set once the challenge has started and your workouts have synced."}
          </p>
        )}

        {data.final ? (
          <p className="fine">Final. These receipts are fixed, and each one's fingerprint is in the settled score sheet.</p>
        ) : !data.connected ? (
          <div className="sweat-connect">
            <p>
              <b>Connect Oura to earn points.</b> This challenge only counts workouts recorded by your Oura Ring. Nothing typed in
              by hand scores.
            </p>
            <button className="btn btn-primary btn-sm" onClick={() => go({ view: "home" })}>
              Connect Oura on your dashboard
            </button>
          </div>
        ) : (
          <div className="sweat-sync">
            <button className="btn btn-quiet btn-sm" onClick={sync} disabled={syncing || !props.live}>
              <RefreshCw size={14} className={syncing ? "spin" : ""} aria-hidden /> {syncing ? "Checking Oura..." : "Sync workouts"}
            </button>
            <span className="fine">
              {data.last_sync_at ? `Last synced ${ago(data.last_sync_at)}.` : "Not synced yet."} New workouts appear after your ring
              syncs with the Oura app.
            </span>
          </div>
        )}
        {note && (
          <p className={`fine ${note.good ? "sweat-ok" : "warn"}`} role="status">
            {note.text}
          </p>
        )}
        {!note && data.connected && data.last_sync_error && !data.final && (
          <p className="fine warn">{SYNC_ERROR[data.last_sync_error] ?? SYNC_ERROR.error}</p>
        )}
      </section>

      <div className="section-head">
        <h2>Your workouts</h2>
        <span className="count with-icon">
          <Lock size={11} aria-hidden /> Only you can see these
        </span>
      </div>
      {workouts.length === 0 ? (
        <EmptyState
          icon={<Footprints size={20} strokeWidth={1.75} />}
          title={data.final ? "No workouts were recorded" : data.connected ? "Waiting for Oura to sync" : "No workouts yet"}
          text={
            data.final
              ? undefined
              : data.connected
                ? "Workouts you record during this challenge show up here once your ring has synced."
                : "Connect Oura and your recorded workouts will appear here with their checks."
          }
        />
      ) : (
        <section className="card sweat-list">
          {workouts.map((w) => (
            <WorkoutReceipt key={w.key} w={w} rulesVersion={data.rules?.version ?? null} />
          ))}
        </section>
      )}
    </div>
  );
}

type SyncSummary = { new: number; updated: number; verified: number; pending: number; rejected: number };

/** Runs a sync and returns a one-line result. Shared with the Oura card. */
export async function syncOura(call: Call): Promise<string> {
  const s = await call<SyncSummary>("POST", "/integrations/oura/sync");
  if (s.new === 0 && s.updated === 0) return s.pending ? "No new workouts. Some are still being checked." : "Up to date. No new workouts.";
  const found = s.new + s.updated;
  return `Workout${found === 1 ? "" : "s"} found: ${found}. ${s.pending ? "Still checking some." : "Checks complete."}`;
}
