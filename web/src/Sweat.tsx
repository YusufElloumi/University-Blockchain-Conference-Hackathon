// Proof of Sweat: a player's own Oura workouts in one challenge, each with its verification receipt.
// Everything here is private to the signed-in player. Points and checks are worked out on the server
// (api/sweat.py); this file only explains them.

import { useCallback, useEffect, useState } from "react";
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

/** What the server works out for one workout under v2 rules (api/sweat2.py). No heart-rate readings. */
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
    label: "Provenance",
    what: "An authorized Oura record from a recorded source. Full marks for Oura's own sources; fewer for a third-party heart-rate source.",
  },
  integrity: {
    label: "Timing and integrity",
    what: "Valid times, inside this challenge, at least 10 minutes, and not counted twice. A partly overlapping workout scores a little lower.",
  },
  movement: {
    label: "Movement",
    what: "Distance and time agree with the activity type. With no usable distance this is \"not observed\" (7 of 15), which is not a mark against you.",
  },
  physiological: {
    label: "Heart-rate signal",
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
function Gauge({ label, weight, f, line }: { label: string; weight: string; f: FactorView; line: string }) {
  const [lo, hi] = [0.85, 1.25];
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

/** The v2 receipt: evidence on one side, score on the other, never mixed. */
function ReceiptV2(props: {
  w: Workout;
  name: string;
  status: ReturnType<typeof statusOf>;
  lines: Line[];
  rulesVersion: string | null;
  sample?: boolean; // made-up numbers (the explainer), not a real workout
}) {
  const { w, name, status, lines } = props;
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
  return (
    <div className="sweat-receipt v2">
      <div className="sweat-receipt-head">
        <span className="sweat-wordmark">
          Proof of <em className="serif">sweat.</em>
        </span>
        <span className="sweat-head-tags">
          <span className="sweat-badge">{name}</span>
          <span className="sweat-badge">Oura</span>
          <span className={`sweat-badge ${status.tone}`}>{status.label}</span>
        </span>
      </div>

      <dl className="sweat-ribbon">
        <div>
          <dt>Eligible</dt>
          <dd>
            {w.eligible_minutes ?? 0}
            <small>min</small>
          </dd>
        </div>
        {w.v2!.distance_km != null && w.v2!.distance_km > 0 && (
          <div>
            <dt>Distance</dt>
            <dd>
              {w.v2!.distance_km}
              <small>km</small>
            </dd>
          </div>
        )}
        <div>
          <dt>Oura intensity</dt>
          <dd className="word">{w.v2!.intensity ?? "none"}</dd>
        </div>
        <div>
          <dt>Evidence Index</dt>
          <dd>
            {evidence.index}
            <small>/100</small>
          </dd>
        </div>
        <div className="pts">
          <dt>Sweat Points</dt>
          <dd>{verified ? score.contribution : "0"}</dd>
        </div>
      </dl>

      <section className="sweat-block">
        <h4>
          Evidence assessment <span>how complete the recording is</span>
        </h4>
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
                  <span>{PART_INFO[p.key].label}</span>
                  <em>
                    {p.state === "unavailable" ? "Not observed" : p.state === "failed" ? "Failed" : p.state === "pending" ? "Pending" : ""}
                  </em>
                  <b>
                    {p.points}
                    <small>/{p.max}</small>
                  </b>
                </summary>
                <p>
                  {PART_INFO[p.key].what}
                  {p.sub && ` Here: coverage ${p.sub.coverage}/15, exercise-tagged ${p.sub.exercise_tagged}/5, spread ${p.sub.distribution}/3, clean ${p.sub.validity}/2.`}
                  {p.reason && REASON[p.reason] ? ` ${REASON[p.reason]}` : ""}
                </p>
              </details>
            </li>
          ))}
        </ul>
        <p className="fine">
          The index adds up rule-based evidence. It is not a probability that the workout happened, and it can't rescue a workout
          that fails a required check. It never touches your base points: it only sets how much of the effort bonus counts
          {evidence.reliability ? ` (here ${Math.round(Number(evidence.reliability) * 100)}%)` : ""}.
        </p>
      </section>

      {verified && (
        <section className="sweat-block">
          <h4>
            Sweat Score <span>base + evidence-adjusted effort</span>
          </h4>
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
            <div className="sweat-band-total">
              <small>Base activity points</small>
              <b>{base}</b>
            </div>
          </div>
          <p className="fine">
            Each day's first hour of exercise counts in full, the second at 0.6 and the third at 0.25, in time order across all your
            workouts that day. A game rule to keep long days from deciding everything, not exercise advice.
          </p>

          <div className="sweat-gauges">
            <Gauge label="Oura intensity" weight={score.weights.provider} f={f.provider} line={factorLine("provider", f.provider)} />
            <Gauge label="Heart rate" weight={score.weights.heart} f={f.heart} line={factorLine("heart", f.heart)} />
            <Gauge label="Movement" weight={score.weights.movement} f={f.movement} line={factorLine("movement", f.movement)} />
          </div>

          <div className="sweat-stack" role="img" aria-label={`Base ${base}, effort bonus counted ${adjusted} of ${potential}`}>
            <i className="base" style={{ width: `${(Number(base) / scale) * 100}%` }} />
            {Number(adjusted) > 0 && <i className="bonus" style={{ width: `${(Number(adjusted) / scale) * 100}%` }} />}
            {Number(potential) > 0 && withheld > 0.004 && <i className="held" style={{ width: `${(withheld / scale) * 100}%` }} />}
          </div>
          <dl className="sweat-steps">
            <div>
              <dt>Base activity points</dt>
              <dd>{base}</dd>
            </div>
            <div className="sub">
              <dt>Oura intensity</dt>
              <dd>{signed(f.provider.bonus ?? "0.00")}</dd>
            </div>
            <div className="sub">
              <dt>Heart-rate exertion</dt>
              <dd>{signed(f.heart.bonus ?? "0.00")}</dd>
            </div>
            <div className="sub">
              <dt>Movement</dt>
              <dd>{signed(f.movement.bonus ?? "0.00")}</dd>
            </div>
            <div>
              <dt>Potential effort bonus</dt>
              <dd>{signed(potential)}</dd>
            </div>
            <div className="rel">
              <dt>
                Evidence reliability <small>Evidence Index {evidence.index}/100</small>
              </dt>
              <dd>× {share}%</dd>
            </div>
            <div>
              <dt>Evidence-adjusted bonus</dt>
              <dd>{signed(adjusted)}</dd>
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
            {fallbacks > 0 && ` ${fallbacks} of 3 signals had no usable data and sit at neutral.`}
          </p>
          <p className="fine">
            Reliability steps: Evidence Index 90+ counts 100% of the effort bonus, 75+ counts 85%, 50+ counts 65%, below that 40%.
            Base points never depend on the index. Your day's total is rounded to a whole number once, after adding its workouts.
            Scoring rules for a friendly game, not a measure of fitness or calories.
          </p>
        </section>
      )}

      <section className="sweat-block">
        <h4>
          Rules checklist <span>required to count</span>
        </h4>
        <ul className="sweat-checks">
          {lines
            .filter((line) => line.label !== "Physiological evidence assessed")
            .map((line) => (
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
      </section>

      <p className="fine sweat-foot">
        {props.rulesVersion ? `Rules ${props.rulesVersion}. ` : ""}
        {props.sample
          ? "A sample with made-up numbers, worked out with the same formula the app uses. A real receipt comes from a workout your Oura Ring recorded."
          : "Rival's server checked this record from Oura against published rules. That doesn't prove a workout happened."}
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

/** The v2 receipt on its own, for the "how points work" explainer. Always made-up data. */
export function SampleReceipt({ w }: { w: Workout }) {
  const name = ACTIVITY_NAME[w.activity ?? ""] ?? "Activity";
  return <ReceiptV2 w={w} name={name} status={statusOf(w)} lines={receiptLines(w)} rulesVersion="proof-of-sweat-v2" sample />;
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
            {w.v2 && w.result !== "pending" ? ` · Evidence ${w.v2.evidence.index}` : ""}
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
  onScored: () => void;
}) {
  const { call, go } = props.session;
  const [data, setData] = useState<SweatReply | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [note, setNote] = useState<{ good: boolean; text: string } | null>(null);

  const load = useCallback(
    () =>
      call<SweatReply>("GET", `/me/sweat?challenge=${props.address}`)
        .then(setData)
        .catch(() => setData(null)),
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

  if (data === null) return <Skeleton rows={3} height={64} />;

  const workouts: Workout[] = data.final
    ? data.receipts.map((r, i) => {
        const { evidence, score, intensity, distance_km, points, ...rest } = r.receipt;
        const v2 = evidence && score ? { evidence, score, intensity: intensity ?? null, distance_km: distance_km ?? null } : null;
        return { ...rest, points: Number(points), v2, key: i, commitment: r.commitment } as Workout;
      })
    : data.workouts;
  const counted = workouts.filter((w) => w.result === "verified");
  const isV2 = data.rules?.generation === 2;
  const topDay = Math.max(1, ...(data.days ?? []).map((d) => d.points));

  return (
    <div className="workouts sweat">
      <section className="card sweat-summary">
        <div className="sweat-summary-top">
          <div>
            <Eyebrow>Proof of Sweat</Eyebrow>
            <p className="sweat-rule">{data.rules?.summary}</p>
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
