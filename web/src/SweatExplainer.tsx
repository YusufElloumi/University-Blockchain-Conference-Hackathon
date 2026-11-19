// "How Sweat Points are calculated": three plain steps, then a calculator that fills in a sample receipt.
// Everything here uses made-up numbers and runs only in the browser. The arithmetic mirrors the server's
// rules (api/sweat2.py, proof-of-sweat-v2): if a constant changes there, change it here too.

import { useState } from "react";
import { Activity, Gauge, ShieldCheck, Timer } from "lucide-react";
import { SampleReceipt, type V2Detail, type Workout } from "./Sweat";

/* ---------- the rules, as the server has them ---------- */

const BANDS = [1, 0.6, 0.25]; // weight of the day's 1st, 2nd and 3rd hour
const PROVIDER: Record<string, number> = { easy: 0.9, moderate: 1.0, hard: 1.12 };
const PACE = [0.95, 1.0, 1.05, 1.1]; // relaxed, steady, brisk, fast (hike differs; not offered here)
const RELIABILITY: [number, number][] = [[90, 1], [75, 0.85], [50, 0.65], [0, 0.4]];

const SPORTS = [
  { id: "run", label: "Run", pace: true, speeds: [7, 9, 11, 13] },
  { id: "walk", label: "Walk", pace: true, speeds: [3.5, 4.8, 6, 7] },
  { id: "ride", label: "Ride", pace: true, speeds: [13, 18, 25, 30] },
  { id: "workout", label: "Strength", pace: false, speeds: [] },
];
const MINUTES = [20, 40, 60, 90, 150];
const HEART = [
  { id: "none", label: "No data", pct: null as number | null },
  { id: "low", label: "8% below usual", pct: -8 },
  { id: "same", label: "Your usual", pct: 0 },
  { id: "up", label: "5% above", pct: 5 },
  { id: "high", label: "10% above", pct: 10 },
];
const PACES = ["No distance", "Relaxed", "Steady", "Brisk", "Fast"];
const COVERAGE = [
  { id: 0, label: "None", share: 0, quarters: 0 },
  { id: 1, label: "A third", share: 0.33, quarters: 2 },
  { id: 2, label: "Most", share: 0.7, quarters: 3 },
  { id: 3, label: "All of it", share: 1, quarters: 4 },
];

const round = (n: number, places: number) => (Math.round((n + Number.EPSILON) * 10 ** places) / 10 ** places).toFixed(places);
const clamp = (lo: number, hi: number, n: number) => Math.min(hi, Math.max(lo, n));

/** One workout on its own day, scored the way the server scores it. */
function sample(sport: (typeof SPORTS)[number], minutes: number, intensity: string, heart: (typeof HEART)[number], pace: number, coverage: (typeof COVERAGE)[number]): Workout {
  const bandMinutes = [Math.min(minutes, 60), clamp(0, 60, minutes - 60), clamp(0, 60, minutes - 120), Math.max(0, minutes - 180)];
  const base = bandMinutes.slice(0, 3).reduce((sum, m, i) => sum + m * BANDS[i], 0);

  const provider = PROVIDER[intensity];
  // Heart rate counts only with exercise-tagged samples across at least half the workout (and 10 minutes of them).
  const heartUsable = heart.pct !== null && coverage.share >= 0.5 && minutes * coverage.share >= 10;
  const heartValue = heartUsable ? clamp(0.9, 1.15, 1 + 1.25 * (heart.pct! / 100)) : 1;
  const paced = sport.pace && pace > 0;
  const movement = paced ? PACE[pace - 1] : 1;
  const multiplier = Number(round(clamp(0.85, 1.25, 0.4 * provider + 0.4 * heartValue + 0.2 * movement), 3));

  const physio = coverage.share > 0 ? Math.floor(15 * coverage.share) + 5 + (coverage.quarters >= 3 ? 3 : 0) + 2 : 0;
  const index = 35 + 25 + (paced ? 15 : 7) + physio;
  const reliability = RELIABILITY.find(([low]) => index >= low)![1];
  const strong = coverage.share >= 0.5 && index >= 80;

  const potential = base * (multiplier - 1);
  const adjusted = potential * reliability;
  const part = (weight: number, value: number) => round(base * weight * (value - 1), 2);

  const v2: V2Detail = {
    intensity,
    distance_km: paced ? Number(round((sport.speeds[pace - 1] * minutes) / 60, 1)) : null,
    evidence: {
      index,
      label: strong ? "strong" : "limited",
      limits: [],
      reliability: String(reliability),
      parts: [
        { key: "provenance", max: 35, points: 35, state: "full", reason: null },
        { key: "integrity", max: 25, points: 25, state: "full", reason: null },
        { key: "movement", max: 15, points: paced ? 15 : 7, state: paced ? "full" : "unavailable", reason: paced ? null : "not_observed" },
        coverage.share > 0
          ? {
              key: "physiological", max: 25, points: physio, state: physio === 25 ? "full" : "partial", reason: null,
              sub: { coverage: Math.floor(15 * coverage.share), exercise_tagged: 5, distribution: coverage.quarters >= 3 ? 3 : 0, validity: 2 },
            }
          : { key: "physiological", max: 25, points: 0, state: "unavailable", reason: "not_observed" },
      ],
    },
    score: {
      eligible_minutes: minutes,
      band_minutes: bandMinutes,
      band_weights: ["1.00", "0.60", "0.25", "0"],
      effective_minutes: round(base, 2),
      base_points: round(base, 2),
      weights: { provider: "0.40", heart: "0.40", movement: "0.20" },
      multiplier: round(multiplier, 3),
      potential_bonus: round(potential, 2),
      reliability: String(reliability),
      adjusted_bonus: round(adjusted, 2),
      contribution: round(base + adjusted, 2),
      factors: {
        provider: { value: round(provider, 2), state: "provider_estimated", reason: intensity, bonus: part(0.4, provider) },
        heart: heartUsable
          ? { value: round(heartValue, 3), state: "measured", reason: "relative_to_reference", relative_percent: heart.pct!, reference_workouts: 6, bonus: part(0.4, heartValue) }
          : { value: "1.00", state: "unavailable", reason: heart.pct === null || coverage.share === 0 ? "no_heart_rate" : "not_enough_heart_rate", bonus: "0.00" },
        movement: paced
          ? { value: round(movement, 2), state: "measured", reason: "pace_band", speed_kmh: sport.speeds[pace - 1], bonus: part(0.2, movement) }
          : { value: "1.00", state: "unavailable", reason: sport.pace ? "no_distance" : "no_pace_for_category", bonus: "0.00" },
      },
    },
  };
  const ok = (code: string) => ({ code, result: "passed" as const, reason: null });
  return {
    key: "sample",
    activity: sport.id,
    duration_minutes: minutes,
    result: "verified",
    assurance: strong ? "strong" : "limited",
    reason: null,
    eligible_minutes: minutes,
    points: Number(v2.score.contribution),
    checks: ["provider", "provenance", "activity", "timestamps", "duration", "plausibility", "window", "duplicate", "scoring"].map(ok),
    v2,
  };
}

function Chips<T extends string | number>(props: { label: string; value: T; options: { id: T; label: string }[]; onChange: (id: T) => void; note?: string }) {
  return (
    <div className="demo-field">
      <span>{props.label}</span>
      <div className="chips">
        {props.options.map((o) => (
          <button key={String(o.id)} type="button" className={props.value === o.id ? "chip on" : "chip"} aria-pressed={props.value === o.id} onClick={() => props.onChange(o.id)}>
            {o.label}
          </button>
        ))}
      </div>
      {props.note && <small className="explain-note">{props.note}</small>}
    </div>
  );
}

/** The three steps and the calculator. `compact` drops the big heading (the signed-in help page has its own). */
export default function SweatExplainer({ compact = false }: { compact?: boolean }) {
  const [sport, setSport] = useState("run");
  const [minutes, setMinutes] = useState(40);
  const [intensity, setIntensity] = useState("hard");
  const [heart, setHeart] = useState("high");
  const [pace, setPace] = useState(3);
  const [coverage, setCoverage] = useState(2);

  const chosen = SPORTS.find((s) => s.id === sport)!;
  const w = sample(chosen, minutes, intensity, HEART.find((h) => h.id === heart)!, chosen.pace ? pace : 0, COVERAGE[coverage]);
  const score = w.v2!.score;

  return (
    <div className={`explain${compact ? " compact" : ""}`}>
      {!compact && (
        <div className="explain-head">
          <span className="kicker">Proof of Sweat</span>
          <h2 className="headline">
            How your points are <em className="serif">worked out.</em>
          </h2>
          <p className="lede">
            Points come from workouts your Oura Ring records, never from anything typed in. Three things decide the number, and you
            can open any workout to see all three.
          </p>
        </div>
      )}

      <ol className="explain-steps">
        <li>
          <span className="explain-n">
            <Timer size={16} aria-hidden /> 01 · Move
          </span>
          <h3>Minutes become base points</h3>
          <div className="explain-art bands" aria-hidden>
            <i style={{ height: "100%" }}>
              <b>×1</b>
            </i>
            <i style={{ height: "60%" }}>
              <b>×0.6</b>
            </i>
            <i style={{ height: "25%" }}>
              <b>×0.25</b>
            </i>
          </div>
          <p>
            About a point a minute. Each day your first hour counts in full, the second hour a bit over half, the third a quarter,
            so 30 minutes is 30 points and 90 minutes is 78. Showing up most days beats one giant session.
          </p>
        </li>
        <li>
          <span className="explain-n">
            <Gauge size={16} aria-hidden /> 02 · Effort
          </span>
          <h3>Harder sessions can earn a bonus</h3>
          <div className="explain-art signals" aria-hidden>
            <span>
              <b>40%</b> Oura's intensity
            </span>
            <span>
              <b>40%</b> Heart rate vs your usual
            </span>
            <span>
              <b>20%</b> Pace for the sport
            </span>
          </div>
          <p>
            Three signals nudge the score up or down, by 25% at the very most. Your heart rate is only ever compared with your own
            earlier workouts, never with anyone else's. If a signal is missing it simply counts as neutral.
          </p>
        </li>
        <li>
          <span className="explain-n">
            <ShieldCheck size={16} aria-hidden /> 03 · Evidence
          </span>
          <h3>Better evidence unlocks more of the bonus</h3>
          <div className="explain-art ladder" aria-hidden>
            {[
              ["90+", "100%"],
              ["75+", "85%"],
              ["50+", "65%"],
              ["<50", "40%"],
            ].map(([index, share]) => (
              <span key={index}>
                <b>{share}</b> {index}
              </span>
            ))}
          </div>
          <p>
            Each workout gets an Evidence Index out of 100 for how complete its recording is. The higher it is, the more of the
            effort bonus counts. Your base points never depend on it, so a workout with no heart rate still earns its minutes.
          </p>
        </li>
      </ol>

      <p className="explain-formula">
        <span>Sweat Points</span> = <b>base</b> + <b>effort bonus</b> × <b>evidence</b>
      </p>

      <div className="explain-try">
        <div className="explain-controls">
          <div className="demo-tag">
            <i /> Try it · made-up numbers
          </div>
          <div className="explain-result" role="status">
            <Activity size={18} aria-hidden />
            <span>
              <b>{score.contribution}</b> Sweat Points
              <small>
                {score.base_points} base {Number(score.adjusted_bonus) >= 0 ? "+" : "−"} {Math.abs(Number(score.adjusted_bonus)).toFixed(2)} effort · Evidence{" "}
                {w.v2!.evidence.index}/100
              </small>
            </span>
          </div>
          <Chips label="Activity" value={sport} options={SPORTS} onChange={setSport} />
          <Chips label="Minutes" value={minutes} options={MINUTES.map((m) => ({ id: m, label: String(m) }))} onChange={setMinutes} />
          <Chips
            label="Oura's intensity label"
            value={intensity}
            options={[
              { id: "easy", label: "Easy" },
              { id: "moderate", label: "Moderate" },
              { id: "hard", label: "Hard" },
            ]}
            onChange={setIntensity}
          />
          <Chips label="Heart rate, against your usual" value={heart} options={HEART} onChange={setHeart} />
          {chosen.pace && <Chips label="Pace" value={pace} options={PACES.map((label, id) => ({ id, label }))} onChange={setPace} />}
          <Chips
            label="How much of the workout has heart-rate data"
            value={coverage}
            options={COVERAGE}
            onChange={setCoverage}
            note="Under half, the heart-rate signal can't be trusted for effort and stays neutral. It still counts a little as evidence."
          />
          <p className="fine">
            This is one workout on its own day. A day's total is rounded to a whole number, and a required check that fails
            (for example a workout typed into Oura by hand) always means zero.
          </p>
        </div>
        <div className="explain-receipt">
          <span className="explain-sample">Sample receipt · not a real workout</span>
          <div className="sweat-item open">
            <SampleReceipt w={w} />
          </div>
        </div>
      </div>
    </div>
  );
}
