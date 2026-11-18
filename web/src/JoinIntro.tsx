import { useEffect, useState } from "react";
import type { StatWeights } from "./api";
import { usdc } from "./format";
import {
  ChevronsUp,
  ClipboardList,
  Footprints,
  Goal,
  Handshake,
  Target,
  Timer,
  Trophy,
  X,
  type LucideIcon,
} from "lucide-react";

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

const STAT_LINES: { key: keyof StatWeights; Icon: LucideIcon; one: string }[] = [
  { key: "goals", Icon: Goal, one: "goal" },
  { key: "assists", Icon: Handshake, one: "assist" },
  { key: "points", Icon: ClipboardList, one: "stat point" },
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

  const rules: { Icon: LucideIcon; text: string }[] = stats
    ? STAT_LINES.filter(({ key }) => (props.weights?.[key] ?? 0) > 0).map(({ key, Icon, one }) => ({
        Icon,
        text: `1 ${one} = ${pts(props.weights![key])}`,
      }))
    : [
        { Icon: Timer, text: "20 active min = 1 pt" },
        { Icon: Footprints, text: "Every 5 km = 1 pt" },
        { Icon: ChevronsUp, text: "Up to 3 pts a day" },
      ];

  const screens = [
    {
      art: <RingArt Icon={stats ? Goal : Footprints} />,
      title: stats ? (
        <>
          Score to earn <em className="serif">points.</em>
        </>
      ) : (
        <>
          Move to earn <em className="serif">points.</em>
        </>
      ),
      body: (
        <ul className="modal-rules">
          {rules.map((r) => (
            <li key={r.text}>
              <r.Icon size={16} strokeWidth={1.75} aria-hidden /> {r.text}
            </li>
          ))}
          {props.hasPicks && (
            <li>
              <Target size={16} strokeWidth={1.75} aria-hidden /> Plus prediction picks
            </li>
          )}
        </ul>
      ),
    },
    {
      art: <ClimbArt />,
      title: (
        <>
          Climb the <em className="serif">leaderboard.</em>
        </>
      ),
      body: <p>Every point moves you up. Your group sees your points, and only your points.</p>,
    },
    {
      art: <WinArt amount={usdc(pool)} />,
      title: (
        <>
          First place takes the <em className="serif">pool.</em>
        </>
      ),
      body: (
        <>
          <p>
            After {termLabel(props.lengthMs)}, first place wins the whole prize pool: <b>{usdc(pool)}</b>. Ties split it.
          </p>
          <p className="fine">Joining shares your points (never your activities) with this group.</p>
        </>
      ),
    },
  ];
  const screen = screens[step];
  const last = step === screens.length - 1;

  return (
    <div className="modal-backdrop" onClick={() => !props.busy && props.onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="intro-title" onClick={(e) => e.stopPropagation()}>
        <button className="icon-btn modal-close" onClick={props.onClose} disabled={props.busy} aria-label="Close">
          <X size={16} aria-hidden />
        </button>
        <div className="modal-step" key={step}>
          <div className="modal-art">{screen.art}</div>
          <h2 id="intro-title" className="modal-title">
            {screen.title}
          </h2>
          <div className="modal-body">{screen.body}</div>
        </div>
        <div className="modal-dots" aria-label={`Step ${step + 1} of ${screens.length}`}>
          {screens.map((_, i) => (
            <i key={i} className={i === step ? "on" : ""} />
          ))}
        </div>
        <button
          className="btn btn-primary btn-block btn-lg"
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

/** A progress ring closing around an activity icon. */
function RingArt({ Icon }: { Icon: LucideIcon }) {
  return (
    <div className="art art-ring" aria-hidden>
      <svg viewBox="0 0 120 120">
        <circle cx="60" cy="60" r="50" className="art-ring-track" />
        <circle cx="60" cy="60" r="50" className="art-ring-fill" pathLength={100} />
      </svg>
      <Icon size={34} strokeWidth={1.5} />
      <span className="art-plus">+1</span>
    </div>
  );
}

/** A small leaderboard where "you" climb to the top. */
function ClimbArt() {
  return (
    <div className="art art-climb" aria-hidden>
      {["r1", "r2", "you", "r4"].map((row) => (
        <div key={row} className={`art-row ${row}`}>
          <i />
          <b />
          <span />
        </div>
      ))}
    </div>
  );
}

/** A trophy with the prize pool underneath. */
function WinArt({ amount }: { amount: string }) {
  return (
    <div className="art art-win" aria-hidden>
      <span className="art-trophy">
        <Trophy size={34} strokeWidth={1.5} />
      </span>
      <b>{amount}</b>
    </div>
  );
}
