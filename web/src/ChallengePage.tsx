import { useCallback, useEffect, useRef, useState } from "react";
import { retryWhileNotReady, type ActivityResult, type ActivityView, type ChallengeState } from "./api";
import type { Session } from "./App";
import { buildJoinTransaction, explorerTx, fetchChallenge, friendlyError, type ChallengeInfo } from "./chain";
import { ago, countdown, money, usdc, when } from "./format";

type Tab = "table" | "feed" | "me";
type Phase = "joining" | "live" | "ended" | "settled" | "refunded";

const PHASE_LABEL: Record<Phase, string> = {
  joining: "Joining open",
  live: "Live",
  ended: "Full time",
  settled: "Final",
  refunded: "Refunded",
};
const TYPE_ICON: Record<string, string> = { run: "🏃", walk: "🚶", hike: "🥾", ride: "🚴", swim: "🏊", workout: "🏋️" };
const MINUTE_CHOICES = [20, 30, 45, 60, 90];
const FEED_ICON: Record<string, string> = {
  ChallengeCreated: "📣",
  PlayerJoined: "💵",
  ChallengeEnded: "⏱️",
  ChallengeSettled: "🏆",
  ChallengeRefunded: "↩️",
};

export default function ChallengePage(props: { address: string; session: Session; balance: number | null }) {
  const { address, session, balance } = props;
  const { me, config, call, send, refreshBalance, go } = session;

  const [info, setInfo] = useState<ChallengeInfo | null>(null); // read straight from Solana
  const [state, setState] = useState<ChallengeState | null>(null); // from our server (Stream events + scores)
  const [now, setNow] = useState(Date.now());
  const [tab, setTab] = useState<Tab>("table");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [lastTx, setLastTx] = useState("");
  const [confirmEnd, setConfirmEnd] = useState(false);
  const seenEvents = useRef(-1);

  const loadChain = useCallback(async () => {
    try {
      setInfo(await fetchChallenge(address));
    } catch (e) {
      console.error(e);
      setError((old) => old || "Couldn't load this challenge. Check the link and try again.");
    }
  }, [address]);

  const loadState = useCallback(async () => {
    try {
      const next = await call<ChallengeState>("GET", `/challenges/${address}/state`);
      setState(next);
      // A new event arrived from the Stream: something changed onchain, so re-read the pool and balance.
      if (next.feed.length !== seenEvents.current) {
        const first = seenEvents.current === -1;
        seenEvents.current = next.feed.length;
        if (!first) {
          loadChain();
          refreshBalance();
        }
      }
    } catch (e) {
      console.error(e);
    }
  }, [address, call, loadChain, refreshBalance]);

  useEffect(() => {
    loadChain();
    loadState();
    const poll = setInterval(loadState, 4000);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(clock);
    };
  }, [loadChain, loadState]);

  async function recordJoin(signature?: string) {
    await retryWhileNotReady(() =>
      call("POST", `/challenges/${address}/join`, { consent: true, deposit_tx: signature ?? null }),
    );
    await loadState();
  }

  async function onJoin() {
    if (!info) return;
    setBusy(true);
    setError("");
    try {
      const signature = await send(await buildJoinTransaction(me.wallet, info));
      setLastTx(signature);
      await Promise.all([loadChain(), refreshBalance()]);
      await recordJoin(signature);
    } catch (e) {
      console.error(e);
      setError(friendlyError(e));
    } finally {
      setBusy(false);
    }
  }

  async function onConsentOnly() {
    setBusy(true);
    setError("");
    try {
      await recordJoin();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  /** Asks the server to do whatever is due: pay the winner, or refund. `endNow` is the admin's early end. */
  const finish = useCallback(
    async (endNow: boolean) => {
      const path = endNow ? `/admin/challenges/${address}/end-now` : `/challenges/${address}/finish`;
      await call("POST", path);
      await Promise.all([loadChain(), loadState(), refreshBalance()]);
    },
    [address, call, loadChain, loadState, refreshBalance],
  );

  async function onFinish(endNow: boolean) {
    setBusy(true);
    setError("");
    setConfirmEnd(false);
    try {
      await finish(endNow);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // When the clock runs out, the first player's screen to notice asks the server to pay out.
  // The server works out the result itself; asking twice is harmless.
  const isOver = !!info && info.status === "open" && now >= info.endTime.getTime() && info.players.length >= 2;
  const mayAsk = !!state?.you.joined;
  useEffect(() => {
    if (!isOver || !mayAsk) return;
    let stopped = false;
    const attempt = () => finish(false).catch(() => !stopped && setTimeout(attempt, 15000));
    attempt();
    return () => {
      stopped = true;
    };
  }, [isOver, mayAsk, finish]);

  async function onInvite() {
    const link = `${window.location.origin}${window.location.pathname}?challenge=${address}`;
    try {
      if (navigator.share) await navigator.share({ title: "Loser Buys", text: "Join my fitness challenge", url: link });
      else {
        await navigator.clipboard.writeText(link);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch {
      /* the person closed the share sheet */
    }
  }

  if (!info) {
    return (
      <>
        <p className="muted center">{error || "Loading challenge..."}</p>
        <button className="link center-link" onClick={() => go({ view: "home" })}>
          Back to home
        </button>
      </>
    );
  }

  const phase: Phase =
    info.status !== "open"
      ? info.status
      : now < info.startTime.getTime()
        ? "joining"
        : now < info.endTime.getTime()
          ? "live"
          : "ended";
  const inOnchain = info.players.includes(me.wallet);
  const onTable = !!state?.you.joined;
  const canAfford = balance !== null && balance >= info.buyIn;
  const full = info.players.length >= info.maxPlayers;
  const pool = state?.pool ?? info.pool;
  const name = state?.challenge?.name ?? "Weekly challenge";
  const result = state?.feed.filter((f) => f.kind === "ChallengeSettled" || f.kind === "ChallengeRefunded").pop();

  return (
    <>
      <button className="link back" onClick={() => go({ view: "home" })}>
        ‹ All challenges
      </button>

      <section className={`scoreboard ${phase}`}>
        <div className="scoreboard-top">
          <div className="league">{name}</div>
          <div className={`pill ${phase}`}>
            {phase === "live" && <span className="dot" />}
            {PHASE_LABEL[phase]}
          </div>
        </div>
        <div className="pool-label">{phase === "settled" ? "Paid out" : phase === "refunded" ? "Returned" : "Prize pool"}</div>
        <div className="pool-amount">{money(phase === "settled" || phase === "refunded" ? info.buyIn * info.players.length : pool)}</div>
        <div className="scoreboard-stats">
          <div>
            <b>{info.players.length}</b>
            <span>of {info.maxPlayers} players</span>
          </div>
          <div>
            <b>{money(info.buyIn)}</b>
            <span>buy-in</span>
          </div>
          <div>
            <b>
              {phase === "joining"
                ? countdown(info.startTime, now)
                : phase === "live"
                  ? countdown(info.endTime, now)
                  : "0:00"}
            </b>
            <span>{phase === "joining" ? "to kick-off" : phase === "live" ? "remaining" : "time left"}</span>
          </div>
        </div>
      </section>

      {result && (
        <div className={`result ${result.kind === "ChallengeSettled" ? "win" : ""}`}>
          <span>{FEED_ICON[result.kind]}</span> {result.text}{" "}
          <a href={explorerTx(result.signature)} target="_blank" rel="noreferrer">
            details
          </a>
        </div>
      )}
      {phase === "ended" && info.players.length >= 2 && (
        <div className="result">Final whistle. Scores are being checked, then the pool is paid out.</div>
      )}
      {(phase === "live" || phase === "ended") && info.players.length < 2 && (
        <section className="card">
          <b>Not enough players joined.</b>
          <p className="muted">A challenge needs at least 2. Every buy-in goes back.</p>
          <button className="primary" onClick={() => onFinish(false)} disabled={busy || !state?.challenge}>
            {busy ? "Refunding..." : "Refund the buy-in"}
          </button>
        </section>
      )}

      {/* Joining */}
      {phase === "joining" && !inOnchain && (
        <section className="card">
          {full ? (
            <p className="muted">This challenge is full.</p>
          ) : (
            <>
              <label className="consent">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>Share my challenge points with this group. They see points only, never my activities.</span>
              </label>
              <button className="primary" onClick={onJoin} disabled={busy || !consent || !canAfford}>
                {busy ? "Joining..." : `Join for ${usdc(info.buyIn)}`}
              </button>
              <p className="fine">
                {canAfford
                  ? `${usdc(info.buyIn)} moves from your balance into the pool. Top scorer takes the pool.`
                  : "You need more in your balance. Add test funds from the home screen first."}
              </p>
            </>
          )}
        </section>
      )}
      {inOnchain && info.status === "open" && (
        <div className={`deposit ${state?.you.deposit_confirmed ? "confirmed" : ""}`}>
          {state?.you.deposit_confirmed ? "✓ Deposit confirmed. You're in." : "Deposit sent. Waiting for confirmation..."}
          {lastTx && (
            <>
              {" "}
              <a href={explorerTx(lastTx)} target="_blank" rel="noreferrer">
                details
              </a>
            </>
          )}
        </div>
      )}
      {inOnchain && state && !onTable && (
        <section className="card">
          <label className="consent">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>Share my challenge points with this group. They see points only, never my activities.</span>
          </label>
          <button className="primary" onClick={onConsentOnly} disabled={busy || !consent}>
            Put me on the table
          </button>
        </section>
      )}
      {phase === "joining" && !full && (
        <button className="secondary" onClick={onInvite}>
          {copied ? "Link copied!" : "Invite friends"}
        </button>
      )}
      {error && (
        <div className="message error" role="alert">
          {error}
        </div>
      )}

      <nav className="tabs" role="tablist">
        {(["table", "feed", "me"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
            {t === "table" ? "Table" : t === "feed" ? `Feed${state?.feed.length ? ` (${state.feed.length})` : ""}` : "My workouts"}
          </button>
        ))}
      </nav>

      {state?.you.is_admin && state.challenge && info.status === "open" && info.players.length >= 2 && phase !== "ended" && (
        <section className="admin">
          <div className="label">Admin</div>
          {confirmEnd ? (
            <>
              <p className="muted">This ends the challenge for everyone and pays the pool to the current leader.</p>
              <div className="row">
                <button className="small danger" onClick={() => onFinish(true)} disabled={busy}>
                  Yes, end and pay out
                </button>
                <button className="link" onClick={() => setConfirmEnd(false)}>
                  Keep playing
                </button>
              </div>
            </>
          ) : (
            <button className="secondary" onClick={() => setConfirmEnd(true)} disabled={busy}>
              {busy ? "Ending and paying out..." : "End week now"}
            </button>
          )}
        </section>
      )}

      {tab === "table" && <Table state={state} phase={phase} />}
      {tab === "feed" && <Feed state={state} now={now} />}
      {tab === "me" && (
        <MyWorkouts session={session} canAdd={onTable && config.fitness.can_add && phase !== "settled" && phase !== "refunded"} address={address} onScored={loadState} />
      )}
    </>
  );
}

function Table({ state, phase }: { state: ChallengeState | null; phase: Phase }) {
  if (!state) return <p className="muted center">Loading...</p>;
  if (!state.players) return <p className="muted center">Join this challenge to see the table.</p>;
  const days = Math.max(0, ...state.players.map((p) => p.ticks.length));
  return (
    <section className="standings">
      <div className="standings-head">
        <span>#</span>
        <span>Player</span>
        <span>Form</span>
        <span>Pts</span>
      </div>
      {state.players.map((p, i) => (
        <div key={i} className={`standing${p.is_you ? " you" : ""}${p.rank === 1 && p.points > 0 ? " leader" : ""}`}>
          <span className="rank">{p.rank}</span>
          <span className="who">
            <span className="avatar">{p.name.slice(0, 1).toUpperCase()}</span>
            <span className="who-name">{p.name}</span>
            {p.is_you && <span className="tag">You</span>}
          </span>
          <span className="form" aria-label={`${p.ticks.filter(Boolean).length} active days of ${p.ticks.length}`}>
            {p.ticks.slice(-7).map((hit, d) => (
              <i key={d} className={hit ? "hit" : "miss"} />
            ))}
          </span>
          <span className="pts">{p.points}</span>
        </div>
      ))}
      <p className="fine">
        {phase === "joining"
          ? "Scoring starts at kick-off."
          : `Form shows active days (20+ minutes)${days > 7 ? ", last 7" : ""}. Points only: nobody sees your activities.`}
      </p>
    </section>
  );
}

function Feed({ state, now }: { state: ChallengeState | null; now: number }) {
  if (!state) return <p className="muted center">Loading...</p>;
  if (state.feed.length === 0) return <p className="muted center">Nothing yet. Joins and payouts show up here live.</p>;
  return (
    <section className="feed">
      {[...state.feed].reverse().map((item) => (
        <div key={item.signature + item.kind} className="feed-item">
          <span className="feed-icon">{FEED_ICON[item.kind] ?? "•"}</span>
          <div>
            <div>{item.text}</div>
            <div className="fine">
              {ago(item.time, now)} ·{" "}
              <a href={explorerTx(item.signature)} target="_blank" rel="noreferrer">
                details
              </a>
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}

function MyWorkouts(props: { session: Session; canAdd: boolean; address: string; onScored: () => void }) {
  const { call, config } = props.session;
  const [list, setList] = useState<ActivityView[] | null>(null);
  const [type, setType] = useState("run");
  const [minutes, setMinutes] = useState(30);
  const [km, setKm] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<{ good: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    call<ActivityView[]>("GET", "/me/activities")
      .then(setList)
      .catch(() => setList([]));
  }, [call]);
  useEffect(load, [load]);

  async function onAdd() {
    setBusy(true);
    setOutcome(null);
    try {
      const result = await call<ActivityResult>("POST", "/me/activities", {
        type,
        minutes,
        distance_km: Number(km) || 0,
      });
      const here = result.challenges.find((c) => c.address === props.address);
      setOutcome(
        here?.counted
          ? { good: true, text: `Logged! You're on ${here.points} point${here.points === 1 ? "" : "s"}.` }
          : { good: false, text: `Saved, but it didn't count here: ${here?.reason ?? "not in this challenge"}.` },
      );
      setKm("");
      load();
      props.onScored();
    } catch (e) {
      setOutcome({ good: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {props.canAdd && (
        <section className="card">
          <div className="label">Log a workout</div>
          <div className="chips">
            {config.fitness.types.map((t) => (
              <button key={t} type="button" className={t === type ? "chip on" : "chip"} onClick={() => setType(t)}>
                {TYPE_ICON[t] ?? ""} {t}
              </button>
            ))}
          </div>
          <div className="label gap">Minutes</div>
          <div className="chips">
            {MINUTE_CHOICES.map((m) => (
              <button key={m} type="button" className={m === minutes ? "chip on" : "chip"} onClick={() => setMinutes(m)}>
                {m}
              </button>
            ))}
          </div>
          <div className="label gap">Distance (km, optional)</div>
          <input inputMode="decimal" placeholder="0" value={km} onChange={(e) => setKm(e.target.value.replace(/[^0-9.]/g, ""))} aria-label="Distance in kilometres" />
          <button className="primary" onClick={onAdd} disabled={busy}>
            {busy ? "Saving..." : "Add workout"}
          </button>
          <p className="fine">Source: {config.fitness.label}. Counts from now.</p>
          {outcome && <div className={`message ${outcome.good ? "ok" : "error"}`}>{outcome.text}</div>}
        </section>
      )}
      <h2 className="section-title">Only you can see these</h2>
      {list === null ? (
        <p className="muted">Loading...</p>
      ) : list.length === 0 ? (
        <p className="muted">No workouts yet.</p>
      ) : (
        <section className="feed">
          {list.map((a) => (
            <div key={a.id} className="feed-item">
              <span className="feed-icon">{TYPE_ICON[a.type] ?? "•"}</span>
              <div>
                <div>
                  <b>{a.type}</b> · {a.minutes} min{a.distance_km ? ` · ${a.distance_km} km` : ""}
                </div>
                <div className="fine">
                  {when(new Date(a.start))} · {a.verified ? a.device : "unverified"}
                </div>
              </div>
            </div>
          ))}
        </section>
      )}
    </>
  );
}
