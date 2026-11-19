import { useEffect, useState } from "react";
import type { ChallengeView, RulesPreview, StatWeights } from "./api";
import type { Session } from "./App";
import { buildCreateTransaction, friendlyError } from "./chain";
import { dayCount, termLabel, usdc } from "./format";
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
  { label: "Pick dates", seconds: 0 }, // shows first-day and last-day calendars
];
const CUSTOM = LENGTHS[4];
// The program accepts any end after the start; this is a typo guard. The API enforces the same range.
const MIN_LENGTH = 15 * 60;
const MAX_LENGTH = 365 * 86400;

/** A local calendar day as "YYYY-MM-DD", the format <input type="date"> uses. */
function isoDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
/** Midnight at the start of a "YYYY-MM-DD" day, in this device's time zone. */
function dayStart(iso: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}
function addDays(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
}
const shortDay = (d: Date) => d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

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
  const sweatRules = !!config.new_challenge_rules?.proof_of_sweat; // new fitness challenges are Oura-verified
  const info = MODE_INFO[mode];
  const [name, setName] = useState(DEFAULT_NAME[mode](me.name));
  const [organizer, setOrganizer] = useState("");
  const [buyIn, setBuyIn] = useState(1);
  const [joinWindow, setJoinWindow] = useState(JOIN_WINDOWS[1]);
  const [lengthChoice, setLengthChoice] = useState(LENGTHS[3]);
  // Picked dates: the event starts at midnight on the first day and ends at midnight after the last day.
  const today = new Date();
  const [startDay, setStartDay] = useState(() => isoDay(addDays(today, 1)));
  const [lastDay, setLastDay] = useState(() => isoDay(addDays(today, 7)));
  const [source, setSource] = useState<Source>("fitness");
  const [weights, setWeights] = useState<StatWeights>({ goals: 2, assists: 1, points: 0 });
  const [picksOn, setPicksOn] = useState(true);
  const [themes, setThemes] = useState<string[]>(["basketball", "general"]);
  const [roundEvery, setRoundEvery] = useState(ROUND_EVERY[0]);
  const [format, setFormat] = useState<Format>("winner_takes_all");
  const [shares, setShares] = useState<number[]>(PODIUM_PRESETS[0]);
  const [goalText, setGoalText] = useState("5"); // typed freely, so it can be empty mid-edit
  const goalTarget = Number(goalText) || 0;
  const setGoalTarget = (n: number) => setGoalText(String(Math.min(100, Math.max(1, n))));
  const [teamNames, setTeamNames] = useState(["Team A", "Team B"]);
  const usesStats = mode === "league" && source === "league_stats";
  const metric = "active_days" as const; // a goal is a number of active days
  // Stat sheets have no active days, so league-stats events can't use the goal format.
  const formatChoices = usesStats ? FORMATS.filter((f) => f !== "goal") : FORMATS;
  useEffect(() => {
    if (usesStats && format === "goal") setFormat("winner_takes_all");
  }, [usesStats, format]);
  const custom = lengthChoice === CUSTOM;
  const firstDate = dayStart(startDay);
  const lastDate = dayStart(lastDay);
  const tomorrow = addDays(today, 1);
  // Whole days, first and last included. Counted as exact 24-hour blocks so a clock change can't add a stray hour.
  const pickedDays =
    firstDate && lastDate ? Math.round((addDays(lastDate, 1).getTime() - firstDate.getTime()) / 86400000) : 0;
  const startOk = !!firstDate && firstDate.getTime() >= tomorrow.getTime();
  const startAt = custom && firstDate ? Math.floor(firstDate.getTime() / 1000) : undefined;
  const lengthSeconds = custom ? pickedDays * 86400 : lengthChoice.seconds;
  const lengthOk = lengthSeconds >= MIN_LENGTH && lengthSeconds <= MAX_LENGTH && (!custom || startOk);
  const lengthLabel = lengthOk ? termLabel(lengthSeconds * 1000) : "-";
  const lengthDays = dayCount(lengthSeconds);
  const goalInRange = goalTarget >= 1 && goalTarget <= 100;
  const goalOk = format !== "goal" || (goalInRange && goalTarget <= lengthDays);
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
      const settings = {
        mode,
        scoring_source: usesStats ? "league_stats" : "fitness",
        stat_weights: usesStats ? weights : null,
        pick_themes: rounds ? themes : [],
        round_hours: rounds ? roundEvery.hours : null,
        format,
        format_config: formatConfig,
      };
      // 1. The server turns the settings into a ruleset; its hash and the payout terms are locked onchain.
      const locked = await call<RulesPreview>("POST", "/rules", {
        ...settings,
        length_seconds: lengthSeconds,
        max_players: 8,
      });
      const { transaction, address } = await buildCreateTransaction(me.wallet, {
        buyIn,
        joinWindowSeconds: joinWindow.seconds,
        startAt,
        lengthSeconds,
        oracle: config.oracle,
        mint: config.usdc_mint,
        rulesHash: locked.rules_hash,
        verifier: locked.verifier,
        payout: locked.payout.kind,
        splitBps: locked.payout.split_bps,
      });
      await send(transaction);
      // 2. The server checks the chain holds exactly those rules before recording the event.
      await call<ChallengeView>("POST", "/challenges", {
        ...settings,
        address,
        name: name.trim(),
        organizer_name: mode === "league" ? organizer.trim() : null,
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
    formatOk &&
    lengthOk &&
    goalOk;

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
              <span className="field-label">{custom ? "Length" : "Runs for"}</span>
              <Chips options={LENGTHS} value={lengthChoice} label={(o) => o.label} onPick={setLengthChoice} />
            </div>
            {!custom && (
              <div className="field">
                <span className="field-label">{mode === "private" ? "Friends can join for" : "Joining stays open for"}</span>
                <Chips options={JOIN_WINDOWS} value={joinWindow} label={(o) => o.label} onPick={setJoinWindow} />
              </div>
            )}
            {custom && (
              <div className="field">
                <div className="date-range">
                  <label>
                    <span className="field-label">First day</span>
                    <input
                      type="date"
                      value={startDay}
                      min={isoDay(tomorrow)}
                      max={isoDay(addDays(today, 365))}
                      aria-invalid={!startOk}
                      onChange={(e) => {
                        const next = e.target.value;
                        setStartDay(next);
                        // Moving the first day keeps the same length.
                        const from = dayStart(next);
                        if (from && pickedDays > 0) setLastDay(isoDay(addDays(from, pickedDays - 1)));
                      }}
                    />
                  </label>
                  <label>
                    <span className="field-label">Last day</span>
                    <input
                      type="date"
                      value={lastDay}
                      min={startDay}
                      max={firstDate ? isoDay(addDays(firstDate, 364)) : undefined}
                      aria-invalid={startOk && !lengthOk}
                      onChange={(e) => setLastDay(e.target.value)}
                    />
                  </label>
                </div>
                {lengthOk && firstDate && lastDate ? (
                  <p className="fine">
                    {shortDay(firstDate)} to {shortDay(lastDate)} · {pickedDays} scoring day{pickedDays === 1 ? "" : "s"}.
                    Starts at midnight and ends at midnight after the last day. {mode === "private" ? "Friends" : "Players"}{" "}
                    can join until it starts.
                  </p>
                ) : (
                  <p className="fine warn" role="alert">
                    {!startOk
                      ? "Pick a first day from tomorrow on."
                      : "The last day must be on or after the first, and an event runs at most 365 days."}
                  </p>
                )}
              </div>
            )}
          </section>

          <section className="card">
            <h2 className="card-title">Format</h2>
            <p className="fine">How the prize pool is paid. Locked onchain when the event is created: not even Rival can change it.</p>
            <div className="format-grid" role="radiogroup" aria-label="Competition format">
              {formatChoices.map((f) => {
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
                    <label className="stepper-value">
                      <input
                        inputMode="numeric"
                        value={goalText}
                        maxLength={3}
                        aria-label="Goal in active days"
                        aria-invalid={!goalOk}
                        onChange={(e) => setGoalText(e.target.value.replace(/[^0-9]/g, ""))}
                        onBlur={() => goalText !== "" && setGoalTarget(goalTarget)}
                      />
                      <span>{goalUnit(metric, goalTarget)}</span>
                    </label>
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
                {!goalInRange && <p className="fine warn">Pick a goal from 1 to 100 active days.</p>}
                {goalInRange && !goalOk && lengthOk && (
                  <p className="fine warn">
                    This event has {lengthDays} scoring day{lengthDays === 1 ? "" : "s"}, so nobody can reach {goalTarget}{" "}
                    active days.
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
                {sweatRules && (config.new_challenge_rules?.generation ?? 0) >= 2 ? (
                  <>
                    <li>
                      <b>+1</b> about a point per Oura-verified minute
                    </li>
                    <li>
                      <b>×</b> {config.new_challenge_rules?.generation === 2 ? "weighted by effort, 0.85 to 1.25" : "up to 1.5 for harder sessions the data backs up"}
                    </li>
                    <li>
                      <b>60</b> minutes a day count in full, then less
                    </li>
                  </>
                ) : sweatRules ? (
                  <>
                    <li>
                      <b>+1</b> every 10 Oura-verified minutes
                    </li>
                    <li>
                      <b>6</b> max a day
                    </li>
                    <li>
                      <b>Oura</b> players connect a ring to score
                    </li>
                  </>
                ) : (
                  <>
                    <li>
                      <b>+1</b> 20 active minutes in a day
                    </li>
                    <li>
                      <b>+1</b> every 5 km
                    </li>
                    <li>
                      <b>3</b> max a day
                    </li>
                  </>
                )}
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
                <dd>{custom ? "Until it starts" : joinWindow.label}</dd>
              </div>
              <div>
                <dt>{custom ? "Dates" : "Runs for"}</dt>
                <dd>
                  {custom && lengthOk && firstDate && lastDate
                    ? `${shortDay(firstDate)} to ${shortDay(lastDate)}`
                    : lengthLabel}
                </dd>
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
