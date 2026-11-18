import { Crown, Target } from "lucide-react";
import type { PlayerRow } from "./api";
import { goalUnit, type Format, type FormatConfig } from "./formats";
import { Avatar, useFlip } from "./ui";

/**
 * The leaderboard: rank, player, recent form (active days) and points.
 * Players see each other's points only, never the activities behind them.
 */
export default function Leaderboard(props: {
  players: PlayerRow[];
  form: boolean; // show the row of active-day dots
  picks: boolean; // show prediction points under the name
  compact?: boolean;
  format?: Format;
  formatConfig?: FormatConfig;
  showShares?: boolean; // show what each player would win if the event ended now
}) {
  const teams = props.format === "teams" ? (props.formatConfig?.teams ?? []) : [];
  const goal = props.format === "goal" ? props.formatConfig : undefined;
  const flip = useFlip();
  const used = new Map<string, number>();

  return (
    <div className={`board${props.form ? "" : " no-form"}${props.compact ? " compact" : ""}`} role="table" aria-label="Leaderboard">
      <div className="board-head" role="row">
        <span role="columnheader">Rank</span>
        <span role="columnheader">Player</span>
        {props.form && <span role="columnheader">Form</span>}
        <span role="columnheader">Pts</span>
      </div>
      <div className="board-rows">
        {props.players.map((p) => {
          // Two players can share a name, so the key also counts repeats.
          const base = `${p.name}|${p.is_you ? "you" : ""}`;
          const n = used.get(base) ?? 0;
          used.set(base, n + 1);
          const key = `${base}|${n}`;
          const leader = p.rank === 1 && p.points > 0;
          return (
            <div
              key={key}
              ref={flip(key)}
              role="row"
              className={`board-row${p.is_you ? " you" : ""}${leader ? " leader" : ""}`}
            >
              <span className="board-rank" role="cell">
                {String(p.rank).padStart(2, "0")}
              </span>
              <span className="board-who" role="cell">
                <Avatar name={p.name} size="sm" />
                <span className="board-who-text">
                  <span className="board-name">
                    <span>{p.name}</span>
                    {leader && <Crown className="board-crown" size={14} strokeWidth={2} aria-label="Leading" />}
                    {p.is_you && <span className="tag tag-accent">You</span>}
                  </span>
                  {props.picks && p.pick_points > 0 && (
                    <span className="board-sub">
                      <Target size={11} aria-hidden /> {p.pick_points} from picks
                    </span>
                  )}
                  {(p.team != null && teams[p.team]) || goal || (props.showShares && props.format === "podium" && p.projected_share > 0) ? (
                    <span className="board-sub board-extras">
                      {p.team != null && teams[p.team] && <span>{teams[p.team]}</span>}
                      {goal && p.goal_progress != null && (
                        <span className={p.goal_progress >= (goal.target ?? 0) ? "goal-met" : ""}>
                          {Math.min(p.goal_progress, goal.target ?? 0)}/{goal.target} {goalUnit(goal.metric, goal.target)}
                        </span>
                      )}
                      {props.showShares && p.projected_share > 0 && props.format === "podium" && (
                        <span className="share">Wins {Math.round(p.projected_share)}%</span>
                      )}
                    </span>
                  ) : null}
                </span>
              </span>
              {props.form && (
                <span
                  className="board-form"
                  role="cell"
                  aria-label={`${p.ticks.filter(Boolean).length} active days of ${p.ticks.length}`}
                >
                  {p.ticks.slice(-7).map((hit, d) => (
                    <i key={d} className={hit ? "hit" : ""} />
                  ))}
                </span>
              )}
              <span className="board-pts" role="cell">
                {p.points}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
