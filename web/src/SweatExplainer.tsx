// "How Proof of Sweat works": the five-step story, three short cards, then a calculator that fills in a
// sample receipt. Everything here uses made-up numbers and runs only in the browser.
//
// The arithmetic is the server's: sweatMath.ts reads every scoring number from sweatRules.json (generated
// from api/sweat3.py) and `npm run check:sweat` compares its answers with the server's. No scoring number
// is written in this file; the ones shown in the cards are read from the same rules.

import { useState } from "react";
import { Activity, ChevronRight, Gauge, Link2, ShieldCheck, Trophy, Watch, type LucideIcon } from "lucide-react";
import { SampleReceipt, type Workout } from "./Sweat";
import { RULES, RULES_VERSION, scoreSample } from "./sweatMath";

/* ---------- what a visitor can choose (inputs only; the rules decide what they are worth) ---------- */

const SPORTS = [
  { id: "run", label: "Run", speeds: [7, 9, 11, 13] },
  { id: "walk", label: "Walk", speeds: [3.5, 4.8, 6, 7] },
  { id: "ride", label: "Ride", speeds: [13, 18, 25, 30] },
  { id: "workout", label: "Strength", speeds: [] },
];
const MINUTES = [20, 40, 60, 90, 150];
const HEART = [
  { id: "none", label: "No data", pct: null as number | null },
  { id: "low", label: "8% below usual", pct: -8 },
  { id: "same", label: "Your usual", pct: 0 },
  { id: "up", label: "5% above", pct: 5 },
  { id: "high", label: "10% above", pct: 10 },
  { id: "max", label: "18% above", pct: 18 },
];
const PACES = ["No distance", "Relaxed", "Steady", "Brisk", "Fast"];
const COVERAGE = [
  { id: 1, label: "A third", share: 0.33, quarters: 2 },
  { id: 2, label: "Most", share: 0.7, quarters: 3 },
  { id: 3, label: "All of it", share: 1, quarters: 4 },
];

const percent = (weight: string) => Math.round(Number(weight) * 100);
const WEIGHTS = (
  [
    ["heart", "Heart rate"],
    ["movement", "Movement"],
    ["provider", "Oura intensity"],
  ] as const
).map(([key, label]) => ({ key, label, pct: percent(RULES.weights[key]) }));
const TOP = Number(RULES.multiplier_range[1]);

/** One made-up workout on its own day, as the app would show it to its owner. */
function sample(sport: (typeof SPORTS)[number], minutes: number, intensity: string, heart: (typeof HEART)[number], pace: number, coverage: (typeof COVERAGE)[number]): Workout {
  const hrMinutes = heart.pct === null ? 0 : Math.round(minutes * coverage.share);
  const v2 = scoreSample({
    activity: sport.id,
    minutes,
    intensity,
    heartPct: heart.pct,
    distanceKm: pace > 0 && sport.speeds.length ? Math.round((sport.speeds[pace - 1] * minutes * 100) / 60) / 100 : null,
    hrMinutes,
    quarters: hrMinutes > 0 ? coverage.quarters : 0,
  });
  const ok = (code: string) => ({ code, result: "passed" as const, reason: null });
  return {
    key: "sample",
    activity: sport.id,
    duration_minutes: minutes,
    result: "verified",
    assurance: v2.evidence.label === "strong" ? "strong" : "limited",
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

const FLOW: { Icon: LucideIcon; who: string; does: string; line: string; key?: boolean }[] = [
  { Icon: Watch, who: "Oura", does: "records", line: "Your ring logs the workout. Nothing is typed in." },
  { Icon: ShieldCheck, who: "Proof of Sweat", does: "verifies", line: "The recording is checked five ways before it can count.", key: true },
  { Icon: Gauge, who: "Rival", does: "analyses effort", line: "Heart rate, movement and intensity, weighed together." },
  { Icon: Trophy, who: "Sweat Points", does: "enter the competition", line: "Only verified points reach the leaderboard." },
  { Icon: Link2, who: "Solana", does: "secures the outcome", line: "Rules locked at the start. Payout enforced at the end." },
];

const CHECKS = ["Source", "Timing", "Duplicates", "Movement", "Heart rate"];

/** The story, the three cards and the calculator. `compact` drops the big heading (the signed-in help page has its own). */
export default function SweatExplainer({ compact = false }: { compact?: boolean }) {
  const [sport, setSport] = useState("run");
  const [minutes, setMinutes] = useState(40);
  const [intensity, setIntensity] = useState("hard");
  const [heart, setHeart] = useState("high");
  const [pace, setPace] = useState(3);
  const [coverage, setCoverage] = useState(2);

  const chosen = SPORTS.find((s) => s.id === sport)!;
  const heartChoice = HEART.find((h) => h.id === heart)!;
  const w = sample(chosen, minutes, intensity, heartChoice, chosen.speeds.length ? pace : 0, COVERAGE.find((c) => c.id === coverage)!);
  const score = w.v2!.score;

  return (
    <div className={`explain${compact ? " compact" : ""}`}>
      <div className="explain-head">
        <span className="kicker">How your score is decided</span>
        <h2 className="explain-title">
          Proof of <em className="serif">Sweat.</em>
        </h2>
        <p className="explain-sub">Verified first. Scored second.</p>
        <p className="lede">
          Proof of Sweat is how Rival confirms you really exercised and turns it into one number. It takes what your Oura Ring
          recorded, checks it, measures how hard you worked, and gives you your Sweat Points.
        </p>
      </div>

      <h3 className="explain-h">
        <span>1</span> From your ring to the leaderboard
      </h3>
      <ol className="explain-flow">
        {FLOW.map(({ Icon, who, does, line, key }, i) => (
          <li key={who} className={key ? "key" : undefined}>
            <span className="explain-flow-icon">
              <Icon size={18} strokeWidth={1.75} aria-hidden />
            </span>
            <b>
              {who} <span>{does}</span>
            </b>
            <small>{line}</small>
            {i < FLOW.length - 1 && <ChevronRight className="explain-flow-next" size={16} aria-hidden />}
          </li>
        ))}
      </ol>

      <h3 className="explain-h">
        <span>2</span> What goes into your score
      </h3>
      <ol className="explain-steps">
        <li>
          <span className="explain-n">
            <ShieldCheck size={16} aria-hidden /> Verify
          </span>
          <h4>Checked five ways before a point counts</h4>
          <div className="explain-art checks" aria-hidden>
            {CHECKS.map((c) => (
              <span key={c}>
                <i /> {c}
              </span>
            ))}
          </div>
          <p>Where it came from, when it happened, whether it was already counted, and whether the movement and heart rate fit.</p>
        </li>
        <li>
          <span className="explain-n">
            <Gauge size={16} aria-hidden /> Measure
          </span>
          <h4>Harder sessions earn up to ×{TOP}</h4>
          <div className="explain-art split" aria-hidden>
            <div className="explain-weightbar">
              {WEIGHTS.map((x) => (
                <i key={x.key} className={x.key} style={{ flexGrow: x.pct }} />
              ))}
            </div>
            <div className="explain-weightkey">
              {WEIGHTS.map((x) => (
                <span key={x.key} className={x.key}>
                  <b>{x.pct}%</b> {x.label}
                </span>
              ))}
            </div>
          </div>
          <p>Your heart rate is compared only with your own earlier workouts. A missing signal counts as neutral.</p>
        </li>
        <li>
          <span className="explain-n">
            <Activity size={16} aria-hidden /> Score
          </span>
          <h4>Minutes, lifted by proven effort</h4>
          <div className="explain-art sum" aria-hidden>
            <span>
              <b>Base</b> ≈ 1 per minute
            </span>
            <em>+</em>
            <span>
              <b>Effort</b> bonus
            </span>
            <em>×</em>
            <span>
              <b>Evidence</b> behind it
            </span>
          </div>
          <p>The better the recording, the more of the effort bonus counts. Your minutes always keep their base points.</p>
        </li>
      </ol>

      <h3 className="explain-h">
        <span>3</span> See a Proof of Sweat receipt
        <small>Every workout gets one. Change the workout and watch the score move.</small>
      </h3>
      <div className="explain-try">
        <div className="explain-controls">
          <div className="demo-tag">
            <i /> Change the workout · illustrative numbers
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
          <Chips label="Heart rate, against your usual" value={heart} options={HEART} onChange={setHeart} />
          {heartChoice.pct !== null && (
            <Chips
              label="Heart-rate data covers"
              value={coverage}
              options={COVERAGE}
              onChange={setCoverage}
              note="Under half the workout, heart rate is too thin to judge effort and stays neutral."
            />
          )}
          {chosen.speeds.length > 0 && <Chips label="Pace" value={pace} options={PACES.map((label, id) => ({ id, label }))} onChange={setPace} />}
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
        </div>
        <div className="explain-receipt">
          <span className="explain-sample">Sample receipt · illustrative data, the app's real scoring rules</span>
          <div className="sweat-item open">
            <SampleReceipt w={w} rulesVersion={RULES_VERSION} />
          </div>
        </div>
      </div>

      <p className="fine explain-honest">
        What this does and doesn't claim: Oura's record is a device recording that Rival's server checks against published rules, not
        cryptographic proof from the sensor. Solana never sees or judges health data. It holds the entry fees, the rules everyone
        agreed to and a fingerprint of the final score sheet, and it pays out by them.
      </p>
    </div>
  );
}
