import { useEffect, useState } from "react";
import type { StatWeights } from "./api";
import { usdc } from "./format";

/**
 * "How it works": three short screens shown every time someone taps Join, before any money moves.
 * Next, Next, then "I'm ready" starts the deposit. The wording follows the event's own settings.
 */
export type JoinIntroProps = {
  scoring: "fitness" | "league_stats";
  weights: StatWeights | null;
  hasPicks: boolean;
  lengthMs: number;
  buyIn: number;
  playersAfterJoin: number;
  busy: boolean;
  onReady: () => void;
  onClose: () => void;
};

const STAT_LINES: { key: keyof StatWeights; icon: string; one: string }[] = [
  { key: "goals", icon: "🥅", one: "goal" },
  { key: "assists", icon: "🤝", one: "assist" },
  { key: "points", icon: "📋", one: "stat point" },
];

/** "15 minutes", "1 day", "1 week", "1 month", "3 days"... */
export function termLabel(ms: number): string {
  const minutes = Math.round(ms / 60000);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"}`;
  const days = Math.round(hours / 24);
  if (days === 7) return "1 week";
  if (days >= 28 && days <= 31) return "1 month";
  if (days % 7 === 0) return `${days / 7} weeks`;
  return `${days} day${days === 1 ? "" : "s"}`;
}

const pts = (n: number) => `${n} pt${n === 1 ? "" : "s"}`;

export default function JoinIntro(props: JoinIntroProps) {
  const [step, setStep] = useState(0);
  const stats = props.scoring === "league_stats";
  const pool = props.buyIn * props.playersAfterJoin;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !props.busy && props.onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props]);

  const rules = stats
    ? STAT_LINES.filter(({ key }) => (props.weights?.[key] ?? 0) > 0).map(({ key, icon, one }) => ({
        icon,
        text: `1 ${one} = ${pts(props.weights![key])}`,
      }))
    : [
        { icon: "⏱", text: "20 active min = 1 pt" },
        { icon: "📍", text: "Every 5 km = 1 pt" },
        { icon: "🔝", text: "Up to 3 pts a day" },
      ];

  const screens = [
    {
      art: stats ? <ScoreArt /> : <RunArt />,
      title: stats ? "Score to earn points" : "Move to earn points",
      body: (
        <ul className="intro-rules">
          {rules.map((r) => (
            <li key={r.text}>
              <span aria-hidden>{r.icon}</span> {r.text}
            </li>
          ))}
          {props.hasPicks && (
            <li>
              <span aria-hidden>🎯</span> + prediction picks
            </li>
          )}
        </ul>
      ),
    },
    {
      art: <ClimbArt />,
      title: "Climb the table",
      body: <p>Points move you up the table. Top spot wears the crown.</p>,
    },
    {
      art: <WinArt />,
      title: "First place takes the pot",
      body: (
        <>
          <p>
            After {termLabel(props.lengthMs)}, #1 wins the whole pool: <b>{usdc(pool)}</b>. Ties split it.
          </p>
          <p className="intro-fine">Joining shares your points (never your activities) with this group.</p>
        </>
      ),
    },
  ];
  const screen = screens[step];
  const last = step === screens.length - 1;

  return (
    <div className="intro-backdrop" onClick={() => !props.busy && props.onClose()}>
      <div
        className="intro"
        role="dialog"
        aria-modal="true"
        aria-labelledby="intro-title"
        onClick={(e) => e.stopPropagation()}
      >
        <button className="intro-close" onClick={props.onClose} disabled={props.busy} aria-label="Close">
          ✕
        </button>
        <div className="intro-art" key={step}>
          {screen.art}
        </div>
        <h2 id="intro-title" className="intro-title">
          {screen.title}
        </h2>
        <div className="intro-body">{screen.body}</div>
        <div className="intro-dots" aria-label={`Step ${step + 1} of ${screens.length}`}>
          {screens.map((_, i) => (
            <i key={i} className={i === step ? "on" : ""} />
          ))}
        </div>
        <button
          className="primary"
          onClick={() => (last ? props.onReady() : setStep(step + 1))}
          disabled={props.busy}
          autoFocus
        >
          {last ? (props.busy ? "Joining..." : `I'm ready · Join for ${usdc(props.buyIn)}`) : "Next"}
        </button>
      </div>
    </div>
  );
}

/* ---------- Pictures, drawn in code so they stay sharp and match the theme ---------- */

function Figure(props: { x: number; y: number; className?: string; children?: React.ReactNode }) {
  // A simple stick figure standing at (x, y) = feet; children draw the limbs.
  return (
    <g className={props.className} transform={`translate(${props.x} ${props.y})`}>
      <circle cx="0" cy="-58" r="9" className="art-head" />
      <line x1="0" y1="-49" x2="0" y2="-22" className="art-limb" />
      {props.children}
    </g>
  );
}

function ScoreArt() {
  return (
    <svg viewBox="0 36 240 108" className="art" aria-hidden>
      <line x1="0" y1="132" x2="240" y2="132" className="art-ground" />
      {/* goal and net */}
      <g className="art-net">
        <rect x="178" y="62" width="52" height="70" className="art-goal" />
        {[0, 1, 2, 3].map((i) => (
          <line key={`v${i}`} x1={188 + i * 11} y1="62" x2={188 + i * 11} y2="132" className="art-mesh" />
        ))}
        {[0, 1, 2, 3, 4].map((i) => (
          <line key={`h${i}`} x1="178" y1={74 + i * 12} x2="230" y2={74 + i * 12} className="art-mesh" />
        ))}
      </g>
      {/* goalie, diving the wrong way */}
      <g transform="rotate(-25 172 132)">
        <Figure x={172} y={132} className="art-goalie">
          <line x1="0" y1="-42" x2="-18" y2="-60" className="art-limb" />
          <line x1="0" y1="-42" x2="16" y2="-56" className="art-limb" />
          <line x1="0" y1="-22" x2="-8" y2="0" className="art-limb" />
          <line x1="0" y1="-22" x2="9" y2="0" className="art-limb" />
        </Figure>
      </g>
      {/* striker */}
      <Figure x={52} y={132} className="art-player">
        <line x1="0" y1="-42" x2="-16" y2="-30" className="art-limb" />
        <line x1="0" y1="-42" x2="15" y2="-50" className="art-limb" />
        <line x1="0" y1="-22" x2="-10" y2="0" className="art-limb" />
        <line x1="0" y1="-22" x2="20" y2="-10" className="art-limb kick" />
      </Figure>
      <circle cx="76" cy="124" r="7" className="art-ball" />
    </svg>
  );
}

function RunArt() {
  return (
    <svg viewBox="0 36 240 108" className="art" aria-hidden>
      <line x1="0" y1="132" x2="240" y2="132" className="art-ground" />
      <line x1="190" y1="132" x2="190" y2="60" className="art-pole" />
      <rect x="190" y="60" width="30" height="20" className="art-flag" />
      {[0, 1, 2].map((i) => (
        <line key={i} x1={40 - i * 4} y1={80 + i * 14} x2={62 - i * 4} y2={80 + i * 14} className="art-speed" />
      ))}
      <g className="art-runner">
        <Figure x={100} y={132} className="art-player">
          <line x1="0" y1="-42" x2="-16" y2="-30" className="art-limb" />
          <line x1="0" y1="-42" x2="16" y2="-54" className="art-limb" />
          <line x1="0" y1="-22" x2="-16" y2="-4" className="art-limb" />
          <line x1="0" y1="-22" x2="14" y2="0" className="art-limb" />
        </Figure>
      </g>
    </svg>
  );
}

function ClimbArt() {
  const rows = [
    { cls: "art-row r1", name: "A" },
    { cls: "art-row r2", name: "B" },
    { cls: "art-row you", name: "You" },
    { cls: "art-row r4", name: "D" },
  ];
  return (
    <svg viewBox="0 0 240 164" className="art" aria-hidden>
      {rows.map((r, i) => (
        <g key={r.name} className={r.cls} style={{ transform: `translateY(${28 + i * 34}px)` }}>
          <rect x="30" y="0" width="180" height="26" rx="7" />
          <circle cx="48" cy="13" r="7" className="art-dot" />
          <rect x="62" y="9" width={r.name === "You" ? 46 : 60} height="8" rx="4" className="art-bar" />
          <rect x="178" y="9" width="20" height="8" rx="4" className="art-bar" />
        </g>
      ))}
      <g className="art-crown">
        <path d="M36 -3 L40 -17 L48 -9 L54 -20 L60 -9 L68 -17 L72 -3 Z" />
      </g>
    </svg>
  );
}

function WinArt() {
  const falling = Array.from({ length: 12 }, (_, i) => i);
  return (
    <svg viewBox="0 0 240 150" className="art" aria-hidden>
      {falling.map((i) => {
        const x = 18 + ((i * 53) % 210);
        const bill = i % 3 !== 0;
        return (
          <g key={i} className="art-fall" style={{ animationDelay: `${(i * 0.23) % 2.2}s`, transformOrigin: `${x}px 0` }}>
            {bill ? (
              <rect x={x} y="-14" width="16" height="9" rx="2" className="art-bill" />
            ) : (
              <circle cx={x} cy="-10" r="5" className="art-coin" />
            )}
          </g>
        );
      })}
      <line x1="0" y1="140" x2="240" y2="140" className="art-ground" />
      {/* trophy held overhead */}
      <g className="art-trophy">
        <path d="M108 26 h24 v10 a12 12 0 0 1 -24 0 Z" />
        <path d="M108 30 h-6 a6 6 0 0 0 6 8 M132 30 h6 a6 6 0 0 1 -6 8" className="art-handle" />
        <rect x="117" y="47" width="6" height="7" />
        <rect x="111" y="54" width="18" height="4" rx="1" />
      </g>
      <Figure x={120} y={140} className="art-player">
        <line x1="0" y1="-42" x2="-10" y2="-80" className="art-limb" />
        <line x1="0" y1="-42" x2="10" y2="-80" className="art-limb" />
        <line x1="0" y1="-22" x2="-9" y2="0" className="art-limb" />
        <line x1="0" y1="-22" x2="9" y2="0" className="art-limb" />
      </Figure>
    </svg>
  );
}
