import { useState } from "react";
import type { ChallengeView, StatWeights } from "./api";
import type { Session } from "./App";
import { buildCreateTransaction, friendlyError } from "./chain";
import { usdc } from "./format";
import { Check, ChevronLeft, Minus, Plus } from "lucide-react";
import { FORMATS, FORMAT_INFO, PODIUM_PRESETS, goalUnit, type Format, type FormatConfig } from "./formats";
import { MODE_INFO, ModeBadge, type Mode } from "./modes";
import { Eyebrow } from "./ui";


const BUY_INS = [1, 2, 5];
const JOIN_WINDOWS = [
  { label: "5 min", seconds: 300 },
  { label: "15 min", seconds: 900 },
  { label: "1 hour", seconds: 3600 },
  { label: "1 day", seconds: 86400 },
];
const LENGTHS = [
  { label: "15 min", seconds: 900 },
  { label: "1 day", seconds: 86400 },
  { label: "3 days", seconds: 3 * 86400 },
  { label: "1 week", seconds: 7 * 86400 },
];

function Chips<T>(props: { options: T[]; value: T; label: (o: T) => string; onPick: (o: T) => void }) {
  return (
    <div className="chips">
      {props.options.map((o) => (
        <button
          key={props.label(o)}
          type="button"
          className={o === props.value ? "chip on" : "chip"}
          onClick={() => props.onPick(o)}
        >
          {props.label(o)}
        </button>
      ))}
    </div>
  );
}

const ROUND_EVERY = [
  { label: "Daily", hours: 24 },
  { label: "Weekly", hours: 168 },
];
const STAT_LABELS: { key: keyof StatWeights; label: string }[] = [
  { key: "goals", label: "Goals" },
  { key: "assists", label: "Assists" },
  { key: "points", label: "Points" },
];
type Source = "fitness" | "league_stats";
const PLACES = ["1st", "2nd", "3rd"];

/** Chips where several can be on at once. */
function MultiChips(props: { options: { id: string; label: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="chips">
      {props.options.map((o) => {
        const on = props.value.includes(o.id);
        return (
          <button
            key={o.id}
            type="button"
            aria-pressed={on}
            className={on ? "chip on" : "chip"}
            onClick={() => props.onChange(on ? props.value.filter((v) => v !== o.id) : [...props.value, o.id])}
          >
            {on && <Check size={14} strokeWidth={2.5} aria-hidden />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

const DEFAULT_NAME: Record<Mode, (player: string) => string> = {
  league: () => "",
  public: () => "Community step-up",
  private: (player) => `${player}'s game`,
};

/** Creating an event. The mode comes from the screen it was opened from, so it is never picked twice. */
export default function CreateChallenge({ mode, session }: { mode: Mode; session: Session; balance: number | null }) {
  const { me, config, call, send, go } = session;
  const info = MODE_INFO[mode];
  const [name, setName] = useState(DEFAULT_NAME[mode](me.name));
  const [organizer, setOrganizer] = useState("");
  const [buyIn, setBuyIn] = useState(1);
  const [joinWindow, setJoinWindow] = useState(JOIN_WINDOWS[1]);
  const [length, setLength] = useState(LENGTHS[3]);
  const [source, setSource] = useState<Source>("fitness");
  const [weights, setWeights] = useState<StatWeights>({ goals: 2, assists: 1, points: 0 });
  const [picksOn, setPicksOn] = useState(true);
  const [themes, setThemes] = useState<string[]>(["basketball", "general"]);
  const [roundEvery, setRoundEvery] = useState(ROUND_EVERY[0]);
  const [format, setFormat] = useState<Format>("winner_takes_all");
  const [shares, setShares] = useState<number[]>(PODIUM_PRESETS[0]);
  const [goalMetric, setGoalMetric] = useState<"active_days" | "points">("active_days");
  const [goalTarget, setGoalTarget] = useState(5);
  const [teamNames, setTeamNames] = useState(["Team A", "Team B"]);
  const usesStats = mode === "league" && source === "league_stats";
  const metric = usesStats ? "points" : goalMetric; // stat sheets have no active days
  const lengthDays = Math.max(1, Math.round(length.seconds / 86400));
  const sharesOk =
    shares.reduce((a, b) => a + b, 0) === 100 && shares.every((v, i) => v > 0 && (i === 0 || v <= shares[i - 1]));
  const teamsOk =
    teamNames.every((t) => t.trim()) && teamNames[0].trim().toLowerCase() !== teamNames[1].trim().toLowerCase();
  const formatOk = format === "podium" ? sharesOk : format === "teams" ? teamsOk : true;
  const formatConfig: FormatConfig | null =
    format === "podium"
      ? { shares }
      : format === "goal"
        ? { metric, target: goalTarget }
        : format === "teams"
          ? { teams: teamNames.map((t) => t.trim()) }
          : null;
  const rounds = picksOn && themes.length > 0;

  function chooseSource(next: Source) {
    setSource(next);
    // A league usually plays once a week, so one pick a week keeps picks a side game next to the stats.
    setRoundEvery(next === "league_stats" ? ROUND_EVERY[1] : ROUND_EVERY[0]);
  }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function onCreate() {
    setBusy(true);
    setError("");
    try {
      const { transaction, address } = await buildCreateTransaction(me.wallet, {
        buyIn,
        joinWindowSeconds: joinWindow.seconds,
        lengthSeconds: length.seconds,
        oracle: config.oracle,
        mint: config.usdc_mint,
      });
      await send(transaction);
      await call<ChallengeView>("POST", "/challenges", {
        address,
        name: name.trim(),
        mode,
        organizer_name: mode === "league" ? organizer.trim() : null,
        scoring_source: usesStats ? "league_stats" : "fitness",
        stat_weights: usesStats ? weights : null,
        pick_themes: rounds ? themes : [],
        round_hours: rounds ? roundEvery.hours : null,
        format,
        format_config: formatConfig,
      });
      go({ view: "challenge", address });
    } catch (e) {
      console.error(e);
      setError(friendlyError(e));
      setBusy(false);
    }
  }

  const ready =
    !busy &&
    !!name.trim() &&
    (mode !== "league" || !!organizer.trim()) &&
    !(picksOn && themes.length === 0) &&
    formatOk;

  return (
    <div className="create">
      <button className="back" onClick={() => go({ view: "mode", mode })} disabled={busy}>
        <ChevronLeft size={16} aria-hidden /> {info.title}
      </button>
      <header className="page-head">
        <div>
          <ModeBadge mode={mode} />
          <h1 className="headline">
            New <em className="serif">{info.noun}.</em>
          </h1>
        </div>
      </header>

      <div className="create-grid">
        <div className="create-form">
          <section className="card">
            <h2 className="card-title">The basics</h2>
            <label className="field">
              <span className="field-label">Event name</span>
              <input
                value={name}
                maxLength={60}
                placeholder={mode === "league" ? "Winter Pickleball League" : ""}
                onChange={(e) => setName(e.target.value)}
                aria-label="Event name"
              />
            </label>
            {mode === "league" && (
              <label className="field">
                <span className="field-label">Hosted by</span>
                <input
                  value={organizer}
                  maxLength={60}
                  placeholder="Your gym, club or tournament"
                  onChange={(e) => setOrganizer(e.target.value)}
                  aria-label="Organizer name"
                />
              </label>
            )}
          </section>

          <section className="card">
            <h2 className="card-title">Entry and timing</h2>
            <div className="field">
              <span className="field-label">Entry fee, each</span>
              <Chips options={BUY_INS} value={buyIn} label={usdc} onPick={setBuyIn} />
            </div>
            <div className="field">
              <span className="field-label">{mode === "private" ? "Friends can join for" : "Joining stays open for"}</span>
              <Chips options={JOIN_WINDOWS} value={joinWindow} label={(o) => o.label} onPick={setJoinWindow} />
            </div>
            <div className="field">
              <span className="field-label">Then it runs for</span>
              <Chips options={LENGTHS} value={length} label={(o) => o.label} onPick={setLength} />
            </div>
          </section>

          <section className="card">
            <h2 className="card-title">Format</h2>
            <p className="fine">How the prize pool is paid. Locked once the event is created.</p>
            <div className="format-grid" role="radiogroup" aria-label="Competition format">
              {FORMATS.map((f) => {
                const { title, Icon, line, example } = FORMAT_INFO[f];
                return (
                  <button
                    key={f}
                    type="button"
                    role="radio"
                    aria-checked={format === f}
                    className={format === f ? "format-tile on" : "format-tile"}
                    onClick={() => setFormat(f)}
                  >
                    <span className="icon-tile icon-tile-sm">
                      <Icon size={16} strokeWidth={1.75} aria-hidden />
                    </span>
                    <b>{title}</b>
                    <span>{line}</span>
                    <small>{example}</small>
                  </button>
                );
              })}
            </div>

            {format === "podium" && (
              <>
                <div className="field">
                  <span className="field-label">Split</span>
                  <Chips
                    options={PODIUM_PRESETS}
                    value={PODIUM_PRESETS.find((p) => p.join() === shares.join()) ?? []}
                    label={(o) => o.join(" / ")}
                    onPick={(o) => setShares(o)}
                  />
                </div>
                <div className="weights">
                  {shares.map((v, i) => (
                    <label key={i}>
                      <span>{PLACES[i]} place %</span>
                      <input
                        inputMode="numeric"
                        value={v}
                        aria-label={`${PLACES[i]} place percent`}
                        onChange={(e) =>
                          setShares(
                            shares.map((old, j) =>
                              j === i ? Math.min(100, Number(e.target.value.replace(/[^0-9]/g, "")) || 0) : old,
                            ),
                          )
                        }
                      />
                    </label>
                  ))}
                </div>
                {!sharesOk && <p className="fine warn">Percentages must add up to 100, highest place first.</p>}
              </>
            )}

            {format === "goal" && (
              <>
                {!usesStats && (
                  <div className="segmented" role="radiogroup" aria-label="Goal type">
                    {(["active_days", "points"] as const).map((m) => (
                      <button
                        key={m}
                        type="button"
                        role="radio"
                        aria-checked={goalMetric === m}
                        className={goalMetric === m ? "on" : ""}
                        onClick={() => setGoalMetric(m)}
                      >
                        {m === "active_days" ? "Active days" : "Points"}
                      </button>
                    ))}
                  </div>
                )}
                <div className="field">
                  <span className="field-label">Goal</span>
                  <div className="stepper">
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label="Lower the goal"
                      onClick={() => setGoalTarget(Math.max(1, goalTarget - 1))}
                    >
                      <Minus size={16} aria-hidden />
                    </button>
                    <b>
                      {goalTarget} {goalUnit(metric, goalTarget)}
                    </b>
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label="Raise the goal"
                      onClick={() => setGoalTarget(Math.min(100, goalTarget + 1))}
                    >
                      <Plus size={16} aria-hidden />
                    </button>
                  </div>
                </div>
                {metric === "active_days" && goalTarget > lengthDays && (
                  <p className="fine warn">
                    This event runs {length.label}, so nobody can reach {goalTarget} active days.
                  </p>
                )}
                <p className="fine">Nobody reaches it? Everyone gets their entry fee back.</p>
              </>
            )}

            {format === "teams" && (
              <>
                <div className="team-names">
                  {teamNames.map((t, i) => (
                    <label key={i} className="field">
                      <span className="field-label">Team {i + 1}</span>
                      <input
                        value={t}
                        maxLength={30}
                        aria-label={`Team ${i + 1} name`}
                        onChange={(e) => setTeamNames(teamNames.map((old, j) => (j === i ? e.target.value : old)))}
                      />
                    </label>
                  ))}
                </div>
                {!teamsOk && <p className="fine warn">Give the two teams different names.</p>}
                <p className="fine">Players pick a team when they join. Team score is the average, so sizes can differ.</p>
              </>
            )}
          </section>

          <section className="card">
            <h2 className="card-title">Scoring</h2>
            {mode === "league" && (
              <div className="segmented" role="radiogroup" aria-label="Scoring source">
                {(["fitness", "league_stats"] as Source[]).map((s) => (
                  <button
                    key={s}
                    type="button"
                    role="radio"
                    aria-checked={source === s}
                    className={source === s ? "on" : ""}
                    onClick={() => chooseSource(s)}
                  >
                    {s === "fitness" ? "Fitness" : "League stats"}
                  </button>
                ))}
              </div>
            )}
            {usesStats ? (
              <div className="weights">
                {STAT_LABELS.map(({ key, label }) => (
                  <label key={key}>
                    <span>{key === "points" ? "Per sheet pt" : `Per ${label.toLowerCase().replace(/s$/, "")}`}</span>
                    <input
                      inputMode="decimal"
                      value={weights[key]}
                      aria-label={`Points per ${label.toLowerCase()}`}
                      onChange={(e) =>
                        setWeights({ ...weights, [key]: Math.min(10, Number(e.target.value.replace(/[^0-9.]/g, "")) || 0) })
                      }
                    />
                  </label>
                ))}
              </div>
            ) : (
              <ul className="rule-list">
                <li>
                  <b>+1</b> 20 active minutes in a day
                </li>
                <li>
                  <b>+1</b> every 5 km
                </li>
                <li>
                  <b>3</b> max a day
                </li>
              </ul>
            )}
          </section>

          <section className="card">
            <div className="card-title-row">
              <div>
                <h2 className="card-title">Prediction picks</h2>
                <p className="fine">A side game: call real sports results for bonus points.</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={picksOn}
                aria-label="Prediction picks"
                className={picksOn ? "toggle on" : "toggle"}
                onClick={() => setPicksOn(!picksOn)}
              >
                <i />
              </button>
            </div>
            {picksOn && (
              <>
                <div className="field">
                  <span className="field-label">Themes</span>
                  <MultiChips options={config.pick_themes} value={themes} onChange={setThemes} />
                </div>
                <div className="field">
                  <span className="field-label">New pick</span>
                  <Chips options={ROUND_EVERY} value={roundEvery} label={(o) => o.label} onPick={setRoundEvery} />
                </div>
              </>
            )}
          </section>
        </div>

        <aside className="create-summary">
          <section className="card">
            <Eyebrow>Summary</Eyebrow>
            <div className="summary-name">{name.trim() || "Untitled event"}</div>
            <dl className="summary-list">
              <div>
                <dt>Entry fee</dt>
                <dd>{usdc(buyIn)} each</dd>
              </div>
              <div>
                <dt>Joining open</dt>
                <dd>{joinWindow.label}</dd>
              </div>
              <div>
                <dt>Runs for</dt>
                <dd>{length.label}</dd>
              </div>
              <div>
                <dt>Format</dt>
                <dd>{format === "podium" && sharesOk ? `Podium ${shares.join("/")}` : FORMAT_INFO[format].title}</dd>
              </div>
              <div>
                <dt>Scoring</dt>
                <dd>{usesStats ? "League stats" : "Fitness"}</dd>
              </div>
              <div>
                <dt>Picks</dt>
                <dd>{rounds ? roundEvery.label : "Off"}</dd>
              </div>
            </dl>
            <button className="btn btn-primary btn-block btn-lg" onClick={onCreate} disabled={!ready}>
              {busy ? "Creating..." : info.create}
            </button>
            <p className="fine center">Free to create. {FORMAT_INFO[format].line}</p>
            {error && (
              <div className="message error" role="alert">
                {error}
              </div>
            )}
            <button className="btn btn-text btn-block" onClick={() => go({ view: "mode", mode })} disabled={busy}>
              Cancel
            </button>
          </section>
        </aside>
      </div>
    </div>
  );
}
