import { useState } from "react";
import type { ChallengeView, StatWeights } from "./api";
import type { Session } from "./App";
import { buildCreateTransaction, friendlyError } from "./chain";
import { usdc } from "./format";
import { MODE_INFO, ModeBadge, type Mode } from "./modes";


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
            {on ? "✓ " : ""}
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
  const usesStats = mode === "league" && source === "league_stats";
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
      });
      go({ view: "challenge", address });
    } catch (e) {
      console.error(e);
      setError(friendlyError(e));
      setBusy(false);
    }
  }

  return (
    <>
      <div className={`create-head mode-${mode}`}>
        <h2 className="section-title">New {info.noun}</h2>
        <ModeBadge mode={mode} />
      </div>

      <section className="card">
        <div className="label">Event name</div>
        <input
          value={name}
          maxLength={60}
          placeholder={mode === "league" ? "Winter Pickleball League" : ""}
          onChange={(e) => setName(e.target.value)}
          aria-label="Event name"
        />
        {mode === "league" && (
          <>
            <div className="label gap">Hosted by</div>
            <input
              value={organizer}
              maxLength={60}
              placeholder="Your gym, club or tournament"
              onChange={(e) => setOrganizer(e.target.value)}
              aria-label="Organizer name"
            />
          </>
        )}
      </section>

      <section className="card">
        <div className="label">Buy-in each</div>
        <Chips options={BUY_INS} value={buyIn} label={usdc} onPick={setBuyIn} />
        <div className="label gap">{mode === "private" ? "Friends can join for" : "Joining stays open for"}</div>
        <Chips options={JOIN_WINDOWS} value={joinWindow} label={(o) => o.label} onPick={setJoinWindow} />
        <div className="label gap">Then it runs for</div>
        <Chips options={LENGTHS} value={length} label={(o) => o.label} onPick={setLength} />
      </section>

      <section className="card">
        <div className="label">Scoring</div>
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
        <div className="row tight">
          <div className="label">Prediction picks</div>
          <button
            type="button"
            role="switch"
            aria-checked={picksOn}
            className={picksOn ? "toggle on" : "toggle"}
            onClick={() => setPicksOn(!picksOn)}
          >
            {picksOn ? "On" : "Off"}
          </button>
        </div>
        {picksOn && (
          <>
            <MultiChips options={config.pick_themes} value={themes} onChange={setThemes} />
            <div className="label gap">New pick</div>
            <Chips options={ROUND_EVERY} value={roundEvery} label={(o) => o.label} onPick={setRoundEvery} />
          </>
        )}
      </section>

      <button
        className="primary"
        onClick={onCreate}
        disabled={
          busy || !name.trim() || (mode === "league" && !organizer.trim()) || (picksOn && themes.length === 0)
        }
      >
        {busy ? "Creating..." : info.create}
      </button>
      <p className="fine center">Free to create. Top scorer takes the pool.</p>
      {error && (
        <div className="message error" role="alert">
          {error}
        </div>
      )}
      <button className="link center-link" onClick={() => go({ view: "mode", mode })} disabled={busy}>
        Cancel
      </button>
    </>
  );
}
