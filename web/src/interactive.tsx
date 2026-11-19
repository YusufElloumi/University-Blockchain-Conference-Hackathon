// The public site's interactive pieces: a playable scoring demo, a week-long race that plays out
// as you scroll, a ways-to-play selector and a ticker band. All of them run on sample data in the
// browser. Nothing here talks to the server, and nothing a visitor does is saved.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowRight, Bike, Footprints, PersonStanding, RotateCcw, type LucideIcon } from "lucide-react";
import type { PlayerRow } from "./api";
import { LaneRow, ModeGraphic, WEEK } from "./graphics";
import Leaderboard from "./Leaderboard";
import { prefersReducedMotion, useFlip } from "./ui";

/* ---------- 1. Playable scoring demo ---------- */

const ACTIVITIES: { id: string; label: string; Icon: LucideIcon }[] = [
  { id: "run", label: "Run", Icon: Footprints },
  { id: "ride", label: "Ride", Icon: Bike },
  { id: "walk", label: "Walk", Icon: PersonStanding },
];
const MINUTES = [10, 30, 60];
const DAILY_CAP = 6;
const START_SCORES = [
  { name: "Maya", points: 11, ticks: [true, true, false, true, true, true, false] },
  { name: "Jordan", points: 10, ticks: [true, false, true, true, true, false, false] },
  { name: "You", points: 9, ticks: [true, true, true, false, true, true, false], you: true },
  { name: "Sam", points: 7, ticks: [false, true, true, false, true, false, false] },
  { name: "Priya", points: 5, ticks: [true, false, false, true, false, true, false] },
];

/** The app's real fitness rule (Proof of Sweat v1): one point for every 10 verified minutes. Distance adds nothing. */
const workoutPoints = (minutes: number) => Math.floor(minutes / 10);

/** Log a pretend workout and watch the sample leaderboard react. */
export function WorkoutDemo() {
  const [activity, setActivity] = useState("run");
  const [minutes, setMinutes] = useState(30);
  const [earned, setEarned] = useState(0); // points you have logged "today" in the demo
  const [note, setNote] = useState("");

  const worth = workoutPoints(minutes);
  const room = DAILY_CAP - earned;
  const players: PlayerRow[] = START_SCORES.map((p) => ({
    ...p,
    points: p.points + (p.you ? earned : 0),
    ticks: p.you && earned > 0 ? [...p.ticks.slice(0, 6), true] : p.ticks,
  }))
    .sort((a, b) => b.points - a.points || (a.you ? -1 : 1))
    .map((p, i) => ({
      rank: i + 1,
      name: p.name,
      points: p.points,
      base_points: p.points,
      pick_points: 0,
      team: null,
      projected_share: 0,
      goal_progress: null,
      ticks: p.ticks,
      is_you: !!p.you,
    }));
  const rank = players.findIndex((p) => p.is_you) + 1;

  function log() {
    const gained = Math.min(worth, room);
    if (worth === 0) return setNote("Under 10 minutes doesn't score. Go a little longer.");
    if (gained === 0) return setNote("That's today's 6-point cap. The rest of the week is still open.");
    setEarned(earned + gained);
    const capped = gained < worth ? " (capped at 6 a day)" : "";
    const yours = players.find((p) => p.is_you)!.points + gained;
    const ahead = players.filter((p) => !p.is_you && p.points > yours).length;
    const standing = ahead === 0 ? "You take the lead." : ahead === 1 ? "One more and you're level with the leader." : "You're closing in.";
    setNote(`+${gained} point${gained === 1 ? "" : "s"}${capped}. ${standing}`);
  }

  return (
    <div className="demo">
      <div className="demo-controls">
        <div className="demo-tag">
          <i /> Interactive preview · sample data
        </div>
        <div className="demo-field">
          <span>Activity</span>
          <div className="chips">
            {ACTIVITIES.map(({ id, label, Icon }) => (
              <button key={id} type="button" className={activity === id ? "chip on" : "chip"} aria-pressed={activity === id} onClick={() => setActivity(id)}>
                <Icon size={15} strokeWidth={1.75} aria-hidden /> {label}
              </button>
            ))}
          </div>
        </div>
        <div className="demo-field">
          <span>Minutes</span>
          <div className="chips">
            {MINUTES.map((m) => (
              <button key={m} type="button" className={minutes === m ? "chip on" : "chip"} aria-pressed={minutes === m} onClick={() => setMinutes(m)}>
                {m}
              </button>
            ))}
          </div>
        </div>
        <div className="demo-worth">
          <b>{worth}</b>
          <span>
            point{worth === 1 ? "" : "s"} for this workout
            <small>
              1 point per 10 minutes · in the app, workouts come from your Oura Ring
            </small>
          </span>
        </div>
        <div className="demo-actions">
          <button className="btn btn-primary" onClick={log}>
            Log workout
          </button>
          {earned > 0 && (
            <button
              className="btn btn-text"
              onClick={() => {
                setEarned(0);
                setNote("");
              }}
            >
              <RotateCcw size={15} aria-hidden /> Reset
            </button>
          )}
        </div>
        <p className="demo-note" role="status">
          {note || "Try it: pick a workout and log it."}
        </p>
      </div>

      <div className="demo-board">
        <div className="demo-board-top">
          <div>
            <div className="eyebrow">Private game · sample</div>
            <div className="demo-board-title">Sunday Run Club</div>
          </div>
          <div className="demo-board-rank">
            <small>You are</small>
            <b key={rank}>{String(rank).padStart(2, "0")}</b>
          </div>
        </div>
        <Leaderboard players={players} form picks={false} />
        <div className="demo-cap" aria-label={`${earned} of ${DAILY_CAP} points earned today`}>
          <span>Today</span>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <i key={i} className={i < earned ? "on" : ""} />
          ))}
          <span>{earned}/6 pts</span>
        </div>
      </div>
    </div>
  );
}

/* ---------- 2. A week-long race that plays out as you scroll ---------- */

const STORY = [
  { title: "Monday morning.", text: "Five friends, one leaderboard. Everyone starts level." },
  { title: "Day one.", text: "You and Maya both bank two points. Game on." },
  { title: "Day two.", text: "Maya edges ahead by one." },
  { title: "Day three.", text: "She takes a rest day. You don't, and the lead is yours." },
  { title: "Day four.", text: "You skip one. She has a big day and takes it straight back." },
  { title: "Day five.", text: "The gap holds at two. Jordan is closing." },
  { title: "Day six.", text: "One point in it, with a day to go." },
  { title: "Final day.", text: "Maya wins the week by a single point. Rematch?" },
];

const total = (days: number[], upto: number) => days.slice(0, upto).reduce((a, b) => a + b, 0);

/**
 * A pinned section: the page holds still while scrolling moves the week forward one day at a time.
 * People who prefer reduced motion see the finished week without the pinning.
 */
export function RaceStory({ children }: { children?: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  const still = prefersReducedMotion();
  const [day, setDay] = useState(still ? 7 : 0);
  const flip = useFlip();

  useEffect(() => {
    if (still) return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const travel = rect.height - window.innerHeight;
      const progress = travel <= 0 ? 1 : Math.min(1, Math.max(0, -rect.top / travel));
      setDay(Math.round(progress * 7));
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      cancelAnimationFrame(frame);
    };
  }, [still]);

  const ranked = WEEK.map((p, order) => ({ ...p, order, score: total(p.days, day) })).sort(
    (a, b) => b.score - a.score || a.order - b.order,
  );
  const lead = ranked[0].score;
  const scene = STORY[day];

  return (
    <section ref={ref} className={`race${still ? " race-still" : ""}`} aria-label="A week of competition, day by day">
      <div className="race-pin">
        <div className="race-copy">
          {children}
          <div className="race-day">
            <b>{String(day).padStart(2, "0")}</b>
            <span>/ 07 days</span>
          </div>
          <p className="race-scene" key={day}>
            <em className="serif">{scene.title}</em> {scene.text}
          </p>
          <div className="race-rail" aria-hidden>
            {Array.from({ length: 7 }, (_, i) => (
              <i key={i} className={i < day ? "on" : ""} />
            ))}
          </div>
          <p className="race-hint">{still ? "Sample data" : "Scroll to run the week · sample data"}</p>
        </div>

        <div className="race-board graphic">
          <div className="graphic-head">
            <span>Weekly race</span>
            <span className="live-tag">
              <i /> {day === 7 ? "Final" : day === 0 ? "Start" : `Day ${day}`}
            </span>
          </div>
          <div className="lane-axis" aria-hidden>
            <b />
            <span />
            <span className="lane-days">
              {["M", "T", "W", "T", "F", "S", "S"].map((label, d) => (
                <span key={d} className={d === day - 1 ? "today" : ""}>
                  {label}
                </span>
              ))}
            </span>
            <span>Pts</span>
          </div>
          {ranked.map((player, i) => (
            <div key={player.name} ref={flip(player.name)}>
              <LaneRow
                n={i + 1}
                name={player.name}
                days={player.days}
                upto={day}
                you={player.you}
                lead={day > 0 && player.score === lead && i === 0}
              />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------- 3. Ways to play: choose one, the preview follows ---------- */

const WAYS = [
  {
    id: "private",
    name: "Private play",
    text: "Your friends, team or office. Start a game, share a six-letter code, and settle who's actually been training.",
  },
  {
    id: "public",
    name: "Public events",
    text: "Open to anyone on Rival. Join a community challenge that's about to start, or create one and let the field come to you.",
  },
  {
    id: "league",
    name: "Leagues",
    text: "Hosted by a gym, club or tournament. Scored by fitness, or by the league's own stat sheet.",
  },
  {
    id: "picks",
    name: "Prediction rounds",
    text: "An optional side game. Each round, call the result of a real sports game for bonus points.",
  },
] as const;

export function WaysSelector({ onMore }: { onMore: () => void }) {
  const [active, setActive] = useState<(typeof WAYS)[number]["id"]>("private");
  return (
    <div className="ways-select">
      <div className="ways-tabs" role="tablist" aria-label="Ways to play">
        {WAYS.map((way, i) => (
          <button
            key={way.id}
            role="tab"
            aria-selected={active === way.id}
            className={`ways-tab${active === way.id ? " on" : ""}`}
            onClick={() => setActive(way.id)}
            onMouseEnter={() => setActive(way.id)}
          >
            <b>0{i + 1}</b>
            <span className="ways-tab-name">{way.name}</span>
            <span className="ways-tab-text">{way.text}</span>
          </button>
        ))}
        <button className="text-link" onClick={onMore}>
          Compare the ways to play <ArrowRight size={16} aria-hidden />
        </button>
      </div>
      <div className="ways-stage" role="tabpanel" key={active}>
        {active === "picks" ? (
          <div className="graphic pick-card" aria-hidden>
            <div className="graphic-head">
              <span>Prediction pick · sample round</span>
              <span>Locks in 2h 10m</span>
            </div>
            <div className="pick-card-title">Home vs Away</div>
            <div className="demo-pick">
              <div className="on">
                <em>Your pick</em>
                <span>Home</span>
                <b>1.6 pts</b>
              </div>
              <div>
                <em>&nbsp;</em>
                <span>Away</span>
                <b>2.7 pts</b>
              </div>
            </div>
            <div className="graphic-foot">
              <span>The bolder the call, the more it's worth</span>
              <span>Sample data</span>
            </div>
          </div>
        ) : (
          <ModeGraphic mode={active} />
        )}
      </div>
    </div>
  );
}

/* ---------- 4. Ticker: the one light band on the page ---------- */

export function Ticker() {
  const words = ["Show up", "Keep score", "Win the week", "Find your rival", "Earn your edge"];
  const run = (
    <span>
      {words.map((word) => (
        <span key={word}>
          {word} <i />
        </span>
      ))}
    </span>
  );
  return (
    <div className="ticker" aria-hidden>
      <div className="ticker-track">
        {run}
        {run}
        {run}
        {run}
      </div>
    </div>
  );
}
