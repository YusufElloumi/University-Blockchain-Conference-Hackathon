import { useState } from "react";
import type { ChallengeView } from "./api";
import type { Session } from "./App";
import { buildCreateTransaction, friendlyError } from "./chain";
import { usdc } from "./format";
import { MODE_INFO, ModeBadge, type Mode } from "./modes";

const MAX_PLAYERS = 8; // the program's limit per event

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

const DEFAULT_NAME: Record<Mode, (player: string) => string> = {
  league: () => "",
  public: () => "Community step-up",
  private: (player) => `${player}'s game`,
};

const FINE_PRINT: Record<Mode, string> = {
  league:
    "As the organizer you don't have to play. Share the invite code with your members; only people with it can see and join.",
  public: `Anyone can find it in Public Events and join, up to ${MAX_PLAYERS} players.`,
  private: "Only people with your invite code can see and join. You play too: join it like everyone else.",
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
            <div className="label gap">Organizer</div>
            <input
              value={organizer}
              maxLength={60}
              placeholder="Your gym, club or tournament"
              onChange={(e) => setOrganizer(e.target.value)}
              aria-label="Organizer name"
            />
            <p className="fine">Shown on the event as "Hosted by ...".</p>
          </>
        )}

        <div className="label gap">Rules</div>
        <div className="rules">
          <div className="rules-title">Daily Mover</div>
          <ul>
            <li>
              <b>+1</b> for a day with 20 active minutes
            </li>
            <li>
              <b>+1</b> for every 5 km that day
            </li>
            <li>
              <b>3</b> points a day at most
            </li>
          </ul>
        </div>

        <div className="label gap">Buy-in each</div>
        <Chips options={BUY_INS} value={buyIn} label={usdc} onPick={setBuyIn} />

        <div className="label gap">{mode === "private" ? "Friends can join for" : "Joining stays open for"}</div>
        <Chips options={JOIN_WINDOWS} value={joinWindow} label={(o) => o.label} onPick={setJoinWindow} />

        <div className="label gap">Then it runs for</div>
        <Chips options={LENGTHS} value={length} label={(o) => o.label} onPick={setLength} />
      </section>

      <button
        className="primary"
        onClick={onCreate}
        disabled={busy || !name.trim() || (mode === "league" && !organizer.trim())}
      >
        {busy ? "Creating..." : info.create}
      </button>
      <p className="fine center">
        Creating is free. Each player pays the {usdc(buyIn)} buy-in when they join. Top scorer takes the pool; ties
        split it. {FINE_PRINT[mode]}
      </p>
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
