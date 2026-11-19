// Rival's graphic language for the public site: lane boards, a head-to-head scoreline, a rules
// strip and small product-native compositions. They are drawn in code, use the real scoring rules,
// and every one that shows players is labelled as sample data.

import { Reveal } from "./ui";

const DAYS = ["M", "T", "W", "T", "F", "S", "S"];

/** A sample week as pips per day. Each pip stands for about 20 Sweat Points (roughly 20 verified minutes). */
export const PIP_POINTS = 20;
export const WEEK: { name: string; you?: boolean; days: number[] }[] = [
  { name: "Maya", days: [2, 2, 0, 3, 2, 1, 2] },
  { name: "You", you: true, days: [2, 1, 2, 0, 2, 2, 2] },
  { name: "Jordan", days: [1, 0, 2, 2, 1, 0, 3] },
  { name: "Sam", days: [0, 1, 2, 0, 2, 0, 1] },
  { name: "Priya", days: [1, 0, 0, 2, 0, 1, 0] },
];

const sum = (list: number[]) => list.reduce((a, b) => a + b, 0);

/** One lane: seven day cells, each holding up to three pips (points earned that day). */
export function LaneRow(props: {
  n: number;
  name: string;
  days: number[];
  you?: boolean;
  lead?: boolean;
  upto?: number; // only count and show the first this-many days (the scroll story reveals the week)
  per?: number; // points each pip stands for (default PIP_POINTS)
  total?: number; // show this total instead of pips x per (when the day's taper applies)
}) {
  const upto = props.upto ?? props.days.length;
  return (
    <div className={`lane-row${props.you ? " you" : ""}${props.lead ? " lead" : ""}`}>
      <b className="lane-n">{String(props.n).padStart(2, "0")}</b>
      <span className="lane-name">{props.name}</span>
      <span className="lane-days">
        {props.days.map((points, d) => (
          <span key={d} className={`lane-day${d === upto - 1 ? " today" : ""}`} style={{ "--d": d } as React.CSSProperties}>
            {[2, 1, 0].map((pip) => (
              <i key={pip} className={d < upto && pip < points ? "on" : ""} />
            ))}
          </span>
        ))}
      </span>
      <span className="lane-total">{props.total ?? sum(props.days.slice(0, upto)) * (props.per ?? PIP_POINTS)}</span>
    </div>
  );
}

/** A week of competition as a lane board: one lane per player, one column per day. */
export function LaneBoard() {
  const ranked = [...WEEK].sort((a, b) => sum(b.days) - sum(a.days));
  return (
    <Reveal className="graphic lane-board">
      <div className="graphic-head">
        <span>Weekly race</span>
        <span className="live-tag">
          <i /> Day 7
        </span>
      </div>
      <div className="lane-axis" aria-hidden>
        <b />
        <span />
        <span className="lane-days">
          {DAYS.map((day, d) => (
            <span key={d}>{day}</span>
          ))}
        </span>
        <span>Pts</span>
      </div>
      {ranked.map((player, i) => (
        <LaneRow key={player.name} n={i + 1} name={player.name} days={player.days} you={player.you} lead={i === 0} />
      ))}
      <div className="graphic-foot">
        <span>Each pip is about 20 Sweat Points</span>
        <span>Sample data</span>
      </div>
    </Reveal>
  );
}

/** You against the leader: the scoreline that makes tomorrow's workout matter. */
export function Matchup() {
  const you = WEEK[1];
  const rival = WEEK[0];
  return (
    <Reveal className="graphic matchup">
      <div className="graphic-head">
        <span>Head to head</span>
        <span className="live-tag">
          <i /> Live
        </span>
      </div>
      <div className="matchup-score">
        <div className="matchup-side you">
          <small>You</small>
          <b>{sum(you.days) * PIP_POINTS}</b>
        </div>
        <div className="matchup-vs" aria-hidden>
          <i />
          <span>vs</span>
          <i />
        </div>
        <div className="matchup-side">
          <small>{rival.name}</small>
          <b>{sum(rival.days) * PIP_POINTS}</b>
        </div>
      </div>
      <div className="matchup-gap">
        <span>20 pts behind</span>
        <span>2d 14h left</span>
      </div>
      <div className="matchup-lanes">
        <LaneRow n={2} name="You" days={you.days} you />
        <LaneRow n={1} name={rival.name} days={rival.days} lead />
      </div>
      <div className="graphic-foot">
        <span>One workout changes the order</span>
        <span>Sample data</span>
      </div>
    </Reveal>
  );
}

/** The scoring rules as a scoreboard strip. These are the app's real numbers. */
const RULES = [
  { value: "1", unit: "pt", label: "About a point per verified minute", short: "per verified minute" },
  { value: "1.25", unit: "×", label: "Most that effort can add", short: "effort weighting, at most" },
  { value: "60", unit: "min", label: "Count in full each day, then taper", short: "a day count in full" },
  { value: "8", unit: "max", label: "Players in one event", short: "players" },
];

/** The first three rules as a compact scorecard that sits on the hero film (wide screens only). */
export function HeroRules() {
  return (
    <dl className="hero-rules" aria-label="How points are scored">
      {RULES.slice(0, 3).map((rule) => (
        <div key={rule.label}>
          <dt>
            {rule.value}
            <span>{rule.unit}</span>
          </dt>
          <dd>{rule.short}</dd>
        </div>
      ))}
    </dl>
  );
}

export function RuleStrip() {
  const rules = RULES;
  return (
    <section className="rule-strip" aria-label="How scoring works">
      {rules.map((rule, i) => (
        <Reveal key={rule.label} className="rule-cell" delay={i * 70}>
          <small>0{i + 1}</small>
          <b>
            {rule.value}
            <span>{rule.unit}</span>
          </b>
          <p>{rule.label}</p>
        </Reveal>
      ))}
    </section>
  );
}

/** Why the daily cap matters: one huge day against a steady week. */
export function CapGraphic() {
  return (
    <Reveal className="graphic cap-graphic">
      <div className="graphic-head">
        <span>Long days taper</span>
        <span>1st hour ×1 · 2nd ×0.6 · 3rd ×0.25</span>
      </div>
      <div className="cap-rows">
        <div>
          <small>One heroic Sunday</small>
          <LaneRow n={2} name="3 hours, once" days={[0, 0, 0, 0, 0, 0, 3]} total={111} />
        </div>
        <div>
          <small>A steady week</small>
          <LaneRow n={1} name="A little, daily" days={[2, 1, 2, 2, 1, 2, 2]} you lead />
        </div>
      </div>
      <div className="graphic-foot">
        <span>3 hours in one day earns 111 · the habit wins, not the highlight</span>
        <span>Illustration</span>
      </div>
    </Reveal>
  );
}

/** A small composition for each way to play. */
export function ModeGraphic({ mode }: { mode: "private" | "public" | "league" }) {
  if (mode === "private")
    return (
      <div className="graphic ticket" aria-hidden>
        <div className="ticket-main">
          <small>Private game · invite only</small>
          <div className="ticket-code">K7M2QX</div>
          <div className="ticket-seats">
            {["M", "J", "S", "P", "Y"].map((initial) => (
              <span key={initial} className="on">
                {initial}
              </span>
            ))}
            {[0, 1, 2].map((seat) => (
              <span key={seat} />
            ))}
          </div>
        </div>
        <div className="ticket-stub">
          <small>Players</small>
          <b>
            5<span>/8</span>
          </b>
        </div>
      </div>
    );

  if (mode === "public")
    return (
      <div className="graphic open-list" aria-hidden>
        <div className="graphic-head">
          <span>Open to join</span>
          <span>3 events</span>
        </div>
        {[
          { name: "City 10K Week", players: 6, starts: "2h 10m" },
          { name: "Community step-up", players: 4, starts: "6h 45m" },
          { name: "November Miles", players: 2, starts: "1d 3h" },
        ].map((event) => (
          <div key={event.name} className="open-row">
            <span className="open-name">{event.name}</span>
            <span className="open-meter">
              <i style={{ width: `${(event.players / 8) * 100}%` }} />
            </span>
            <span className="open-count">{event.players}/8</span>
            <span className="open-starts">Starts {event.starts}</span>
          </div>
        ))}
        <div className="graphic-foot">
          <span>Anyone can join before the start</span>
          <span>Sample data</span>
        </div>
      </div>
    );

  return (
    <div className="graphic stat-sheet" aria-hidden>
      <div className="graphic-head">
        <span>League stat sheet</span>
        <span>Goal ×2 · Assist ×1</span>
      </div>
      <div className="sheet-row sheet-head">
        <span>Player</span>
        <span>G</span>
        <span>A</span>
        <span>Pts</span>
      </div>
      {[
        { name: "Okafor", g: 3, a: 1 },
        { name: "Lindqvist", g: 2, a: 2 },
        { name: "Reyes", g: 1, a: 3 },
        { name: "Tanaka", g: 0, a: 2 },
      ].map((row, i) => (
        <div key={row.name} className={`sheet-row${i === 0 ? " lead" : ""}`}>
          <span>{row.name}</span>
          <span>{row.g}</span>
          <span>{row.a}</span>
          <span>{row.g * 2 + row.a}</span>
        </div>
      ))}
      <div className="graphic-foot">
        <span>The organizer sets what each stat is worth</span>
        <span>Sample data</span>
      </div>
    </div>
  );
}
