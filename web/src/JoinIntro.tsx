import { useEffect, useState } from "react";
import type { StatWeights } from "./api";
import { usdc } from "./format";
import { FORMAT_INFO, goalUnit, payoutTitle, type Format, type FormatConfig } from "./formats";
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
  format: Format;
  formatConfig: FormatConfig;
  lengthMs: number;
  buyIn: number;
  playersAfterJoin: number;
  busy: boolean;
  onReady: (team: number | null) => void; // team: the team picked, for team events
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

/** One sentence on how this event pays, finishing "After 1 week, ...". */
function payoutLine(format: Format, config: FormatConfig): string {
  if (format === "podium") {
    const places = (config.shares ?? []).map((p, i) => `${["1st", "2nd", "3rd"][i]} ${p}%`).join(", ");
    return `the top places share the pool: ${places}. Ties share their places.`;
  }
  if (format === "goal") {
    const n = config.target ?? 0;
    return `everyone with ${n} ${goalUnit(config.metric, n)} splits the pool. If nobody makes it, everyone gets their fee back.`;
  }
  if (format === "teams") return "the team with the best average score splits the pool. Pick your side:";
  return "first place wins the whole pool. Ties split it.";
}

const pts = (n: number) => `${n} pt${n === 1 ? "" : "s"}`;

export default function JoinIntro(props: JoinIntroProps) {
  const [step, setStep] = useState(0);
  const [team, setTeam] = useState<number | null>(null);
  const teams = props.format === "teams" ? (props.formatConfig.teams ?? []) : [];
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
      art: stats ? <RingArt Icon={Goal} /> : <RunArt />,
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
      art: teams.length ? null : <WinArt amount={usdc(pool)} />,
      title: (
        <>
          {payoutTitle(props.format)} <em className="serif">pool.</em>
        </>
      ),
      body: (
        <>
          <p>
            After {termLabel(props.lengthMs)}, {payoutLine(props.format, props.formatConfig)} Prize pool: <b>{usdc(pool)}</b>.
          </p>
          {teams.length > 0 && (
            <div className="team-pick" role="radiogroup" aria-label="Pick your team">
              {teams.map((name, i) => (
                <button
                  key={name}
                  type="button"
                  role="radio"
                  aria-checked={team === i}
                  className={team === i ? "chip on" : "chip"}
                  onClick={() => setTeam(i)}
                >
                  {team === i && <FORMAT_INFO.teams.Icon size={14} aria-hidden />}
                  {name}
                </button>
              ))}
            </div>
          )}
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
          {screen.art && <div className="modal-art">{screen.art}</div>}
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
          onClick={() => (last ? props.onReady(teams.length ? team : null) : setStep(step + 1))}
          disabled={props.busy || (last && teams.length > 0 && team === null)}
          autoFocus
        >
          {last
            ? props.busy
              ? "Joining..."
              : teams.length && team === null
                ? "Pick a team"
                : `I'm ready · Join for ${usdc(props.buyIn)}`
            : "Next"}
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

/** A runner in mid-stride on a moving track, with a "+1" popping up now and then. */
function RunArt() {
  // One limb: an upper part that swings from the hip or shoulder, and a lower part that bends at the joint.
  const leg = (side: "near" | "far") => (
    <g className={`run-thigh ${side}`}>
      <line x1="58" y1="62" x2="58" y2="80" />
      <g className="run-shin">
        <line x1="58" y1="80" x2="58" y2="97" />
        <line x1="58" y1="97" x2="64" y2="97" />
      </g>
    </g>
  );
  const arm = (side: "near" | "far") => (
    <g className={`run-arm ${side}`}>
      <line x1="62" y1="41" x2="62" y2="53" />
      <g className="run-forearm">
        <line x1="62" y1="53" x2="62" y2="64" />
      </g>
    </g>
  );
  return (
    <div className="art art-run" aria-hidden>
      <svg viewBox="0 0 120 120">
        <g className="run-lines">
          <line x1="14" y1="44" x2="30" y2="44" />
          <line x1="8" y1="60" x2="28" y2="60" />
          <line x1="16" y1="76" x2="30" y2="76" />
        </g>
        <line className="run-ground" x1="0" y1="104" x2="120" y2="104" />
        <g className="run-body">
          {arm("far")}
          {leg("far")}
          <line x1="58" y1="62" x2="63" y2="38" />
          <circle cx="66" cy="27" r="7" />
          {leg("near")}
          {arm("near")}
        </g>
      </svg>
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
