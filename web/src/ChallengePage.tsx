import { useCallback, useEffect, useRef, useState } from "react";
import {
  API_BASE,
  ApiError,
  retryWhileNotReady,
  type ActivityResult,
  type ActivityView,
  type ChallengeState,
  type PickRound,
  type StatsSummary,
} from "./api";
import type { Session } from "./App";
import { buildJoinTransaction, explorerTx, fetchChallenge, friendlyError, type ChallengeInfo } from "./chain";
import { ago, countdown, money, usdc, when } from "./format";
import JoinIntro from "./JoinIntro";
import { InviteCodeBox } from "./ModeScreen";
import { MODE_INFO, ModeBadge } from "./modes";

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
  const [intro, setIntro] = useState(false); // the "how it works" pop-up shown before every join
  const [locked, setLocked] = useState(false); // invite-only event and you have no invite (the server said 404)
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
      setLocked(false);
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
      if (e instanceof ApiError && e.status === 404) setLocked(true);
      else console.error(e);
    }
  }, [address, call, loadChain, refreshBalance]);

  useEffect(() => {
    loadChain();
    loadState();
    const poll = setInterval(loadState, 4000);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    // Safety net: Stream events refresh the pool at once; this slow re-read covers a missed delivery.
    const slow = setInterval(loadChain, 30000);
    return () => {
      clearInterval(poll);
      clearInterval(clock);
      clearInterval(slow);
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
      setIntro(false);
    } catch (e) {
      console.error(e);
      setError(friendlyError(e));
      setIntro(false);
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

  const mode = state?.challenge?.mode;
  const statsScored = state?.challenge?.scoring_source === "league_stats"; // no workouts tab for these
  const tabs: Tab[] = statsScored ? ["table", "feed"] : ["table", "feed", "me"];
  const inviteCode = mode && MODE_INFO[mode].inviteOnly ? state?.challenge?.invite_code : undefined;

  async function onInvite() {
    // Invite-only events share the code, so the link works for people who have not been let in yet.
    const query = inviteCode ? `invite=${inviteCode}` : `challenge=${address}`;
    const link = `${window.location.origin}${window.location.pathname}?${query}`;
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

  if (locked) {
    return (
      <>
        <button className="link back" onClick={() => go({ view: "home" })}>
          ‹ Home
        </button>
        <section className="card">
          <b>This event is invite only.</b>
          <p className="muted">Ask the organizer or a friend in it for the invite code.</p>
        </section>
        <InviteCodeBox session={session} onJoined={() => loadState()} />
      </>
    );
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
      <button className="link back" onClick={() => go(mode ? { view: "mode", mode } : { view: "home" })}>
        ‹ {mode ? MODE_INFO[mode].title : "Home"}
      </button>

      <section className={`scoreboard ${phase}`}>
        <div className="scoreboard-top">
          <div className="league">{name}</div>
          <div className={`pill ${phase}`}>
            {phase === "live" && <span className="dot" />}
            {PHASE_LABEL[phase]}
          </div>
        </div>
        {mode && (
          <div className="scoreboard-meta">
            <ModeBadge mode={mode} />
            {state?.challenge?.organizer_name && <span>Hosted by {state.challenge.organizer_name}</span>}
          </div>
        )}
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
      {phase === "joining" && !inOnchain && state && (
        <section className="card">
          {full ? (
            <p className="muted">This challenge is full.</p>
          ) : (
            <>
              <button className="primary" onClick={() => setIntro(true)} disabled={busy || !canAfford}>
                {busy ? "Joining..." : `Join for ${usdc(info.buyIn)}`}
              </button>
              <p className="fine">
                {canAfford
                  ? `${usdc(info.buyIn)} moves from your balance into the pool. Top scorer takes the pool.`
                  : "You need more in your balance. Add devnet USDC from the home screen first."}
              </p>
            </>
          )}
        </section>
      )}
      {intro && (
        <JoinIntro
          scoring={state?.challenge?.scoring_source ?? "fitness"}
          weights={state?.challenge?.stat_weights ?? null}
          hasPicks={!!state?.challenge?.round_hours}
          lengthMs={info.endTime.getTime() - info.startTime.getTime()}
          buyIn={info.buyIn}
          playersAfterJoin={info.players.length + 1}
          busy={busy}
          onReady={onJoin}
          onClose={() => setIntro(false)}
        />
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
      {state?.rounds && (
        <PickRounds
          session={session}
          address={address}
          rounds={state.rounds}
          phase={phase}
          now={now}
          onPicked={loadState}
        />
      )}
      {phase === "joining" && !full && (
        <>
          <button className="secondary" onClick={onInvite}>
            {copied ? "Link copied!" : mode === "league" ? "Invite members" : "Invite friends"}
          </button>
          {inviteCode && (
            <p className="fine center">
              Invite code <b className="code">{inviteCode}</b>
            </p>
          )}
        </>
      )}
      {error && (
        <div className="message error" role="alert">
          {error}
        </div>
      )}

      <nav className="tabs" role="tablist" style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }}>
        {tabs.map((t) => (
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
      {tab === "me" && !statsScored && (
        <MyWorkouts session={session} canAdd={onTable && config.fitness.can_add && phase !== "settled" && phase !== "refunded"} address={address} onScored={loadState} />
      )}
      {statsScored && state?.you.is_creator && info.status === "open" && (
        <LeagueStats session={session} address={address} onChanged={loadState} />
      )}
    </>
  );
}

/** Prediction rounds: one Gemini market per round. A right pick earns 1 / chance points, capped. */
function PickRounds(props: {
  session: Session;
  address: string;
  rounds: NonNullable<ChallengeState["rounds"]>;
  phase: Phase;
  now: number;
  onPicked: () => void;
}) {
  const { call } = props.session;
  const { list, total } = props.rounds;
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [peek, setPeek] = useState<number | null>(null); // a past round tapped in the strip
  const current: PickRound | undefined = list[list.length - 1];
  const myPoints = Math.round(list.reduce((sum, r) => sum + (r.yours?.points ?? 0), 0) * 10) / 10;
  const peeked = list.find((r) => r.number === peek);

  async function choose(round: PickRound, optionId: string) {
    setSaving(optionId);
    setError("");
    try {
      await call("POST", `/challenges/${props.address}/rounds/${round.number}/pick`, { option_id: optionId });
      props.onPicked();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving("");
    }
  }

  return (
    <section className="card pickem">
      <div className="row tight">
        <div className="label">Pick{current ? ` · Round ${current.number}/${total}` : ""}</div>
        <a
          className="powered"
          href={current?.market_url ?? "https://www.gemini.com/predictions"}
          target="_blank"
          rel="noreferrer"
        >
          Gemini ↗
        </a>
      </div>

      {current ? (
        <RoundCard round={current} now={props.now} saving={saving} onChoose={(id) => choose(current, id)} />
      ) : (
        <p className="muted">
          {props.phase === "joining" ? "Round 1 opens at kick-off." : props.phase === "live" ? "Finding a game..." : "No rounds played."}
        </p>
      )}
      {error && <div className="message error">{error}</div>}

      {list.length > 0 && (
        <div className="round-strip">
          <div className="round-marks" aria-label="Your rounds">
            {Array.from({ length: total }, (_, i) => {
              const r = list.find((x) => x.number === i + 1);
              const mark = !r
                ? "future"
                : r.status === "void"
                  ? "void"
                  : r.status === "open"
                    ? r === current ? "now" : "wait"
                    : r.yours?.points
                      ? "hit"
                      : "miss";
              return (
                <button
                  key={i}
                  type="button"
                  className={`mark ${mark}${peek === i + 1 ? " sel" : ""}`}
                  disabled={!r || r === current}
                  onClick={() => setPeek(peek === i + 1 ? null : i + 1)}
                  aria-label={r ? `Round ${i + 1}: ${r.title}` : `Round ${i + 1}`}
                >
                  {mark === "hit" ? "✓" : mark === "miss" ? "✗" : ""}
                </button>
              );
            })}
          </div>
          <span className="round-total">🎯 {myPoints} pts</span>
        </div>
      )}
      {peeked && (
        <div className="round-peek">
          R{peeked.number} · {peeked.title} ·{" "}
          {peeked.status === "void"
            ? "void"
            : !peeked.yours
              ? "no pick"
              : `${peeked.yours.pick}${peeked.yours.points !== null ? ` · ${peeked.yours.points ? `+${peeked.yours.points}` : "0"} pts` : ""}`}
        </div>
      )}
    </section>
  );
}

function RoundCard(props: { round: PickRound; now: number; saving: string; onChoose: (optionId: string) => void }) {
  const { round, saving } = props;
  const open = !round.locked;
  return (
    <div className="round">
      <div className="fine">
        {round.league} ·{" "}
        {open
          ? `locks in ${countdown(new Date(round.locks_at), props.now)}`
          : round.status === "open"
            ? "in play"
            : round.status === "void"
              ? "void"
              : "final"}
      </div>
      <div className="round-title">{round.title}</div>
      <div className={round.options.length === 3 ? "sides three" : "sides"}>
        {round.options.map((o) => {
          const mine = round.yours?.option_id === o.id;
          const won = round.winner === o.label;
          const result = mine && round.yours?.points !== null && round.yours?.points !== undefined;
          return (
            <button
              key={o.id}
              className={`side stacked${mine ? " on" : ""}${won ? " won" : ""}`}
              onClick={() => props.onChoose(o.id)}
              disabled={!open || saving !== ""}
            >
              {mine && (
                <em className="side-tag">{result ? (round.yours!.points ? `+${round.yours!.points}` : "0 pts") : "Your pick"}</em>
              )}
              <span>{o.label}</span>
              <small>{o.chance}%</small>
              <b>{saving === o.id ? "..." : `${mine ? round.yours!.pays : o.pays} pts`}</b>
            </button>
          );
        })}
      </div>
      {round.everyone && round.everyone.length > 0 ? (
        <div className="picks-row">
          {round.everyone.map((p, i) => (
            <span key={i} className={p.points ? "good" : ""}>
              {p.name}: {p.pick}
            </span>
          ))}
        </div>
      ) : (
        <p className="fine">🔒 {round.picks_made} picked · hidden until kick-off</p>
      )}
    </div>
  );
}

/** Organizer only: the league's stat sheet. Collapsed to one line until "Manage" is tapped. */
function LeagueStats(props: { session: Session; address: string; onChanged: () => void }) {
  const { call } = props.session;
  const [summary, setSummary] = useState<StatsSummary | null>(null);
  const [open, setOpen] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ good: boolean; text: string } | null>(null);

  useEffect(() => {
    call<StatsSummary>("GET", `/challenges/${props.address}/stats`)
      .then(setSummary)
      .catch((e) => setMessage({ good: false, text: (e as Error).message }));
  }, [call, props.address]);

  async function upload(csv: string) {
    setBusy(true);
    setMessage(null);
    try {
      const result = await call<StatsSummary>("POST", `/challenges/${props.address}/stats`, { csv });
      setSummary(result);
      setText("");
      setPasting(false);
      const skipped = result.skipped_outside_dates ? ` · ${result.skipped_outside_dates} outside the dates` : "";
      setMessage({ good: true, text: `Uploaded${skipped}` });
      props.onChanged();
    } catch (e) {
      setMessage({ good: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function onMatch(userId: number, statName: string) {
    setMessage(null);
    try {
      setSummary(
        await call<StatsSummary>("POST", `/challenges/${props.address}/stats/match`, {
          matches: { [userId]: statName || null },
        }),
      );
      props.onChanged();
    } catch (e) {
      setMessage({ good: false, text: (e as Error).message });
    }
  }

  function fromPdf() {
    if (!summary) return;
    navigator.clipboard.writeText(summary.grok_prompt).catch(() => undefined);
    window.open(summary.grok_url, "_blank", "noopener");
    setPasting(true);
    setMessage({ good: true, text: "Prompt copied. Paste Grok's CSV below." });
  }

  const games = summary?.dates.length ?? 0;
  const status = !summary
    ? ""
    : games === 0
      ? "No stats yet"
      : `${games} game${games === 1 ? "" : "s"}${summary.unmatched.length ? ` · ${summary.unmatched.length} unmatched` : ""}`;

  return (
    <section className="card stats-card">
      <div className="stats-head">
        <div>
          <div className="label">Stat sheet</div>
          <div className="stats-status">{status}</div>
        </div>
        <button type="button" className="chip" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Done" : "Manage"}
        </button>
      </div>

      {open && (
        <>
          <div className="tools">
            <a className="tool" href={`${API_BASE}/stats/template.csv`} download>
              Template
            </a>
            <label className={busy ? "tool disabled" : "tool"}>
              {busy ? "Uploading..." : "Upload CSV"}
              <input
                type="file"
                accept=".csv,text/csv"
                disabled={busy}
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) upload(await file.text());
                }}
              />
            </label>
            <button type="button" className="tool" onClick={fromPdf} disabled={!summary || busy}>
              From PDF
            </button>
          </div>

          {pasting && (
            <>
              <textarea
                rows={3}
                value={text}
                placeholder="Paste CSV"
                onChange={(e) => setText(e.target.value)}
                aria-label="CSV from Grok"
              />
              <button className="small wide" onClick={() => upload(text)} disabled={busy || !text.trim()}>
                {busy ? "Uploading..." : "Upload"}
              </button>
            </>
          )}

          {message && <div className={`stats-message ${message.good ? "ok" : "error"}`}>{message.text}</div>}

          {summary && summary.rows > 0 && summary.players.length > 0 && (
            <div className="match-list">
              {summary.players.map((p) => (
                <label key={p.user_id} className="match-row">
                  <span>{p.name}</span>
                  <select value={p.stat_name ?? ""} onChange={(e) => onMatch(p.user_id, e.target.value)}>
                    <option value="">Not on sheet</option>
                    {summary.sheet_names.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Table({ state, phase }: { state: ChallengeState | null; phase: Phase }) {
  if (!state) return <p className="muted center">Loading...</p>;
  if (!state.players) return <p className="muted center">Join this challenge to see the table.</p>;
  const days = Math.max(0, ...state.players.map((p) => p.ticks.length));
  const form = state.challenge?.scoring_source !== "league_stats"; // stat sheets have no daily form
  return (
    <section className={form ? "standings" : "standings no-form"}>
      <div className="standings-head">
        <span>#</span>
        <span>Player</span>
        {form && <span>Form</span>}
        <span>Pts</span>
      </div>
      {state.players.map((p, i) => (
        <div key={i} className={`standing${p.is_you ? " you" : ""}${p.rank === 1 && p.points > 0 ? " leader" : ""}`}>
          <span className="rank">{p.rank}</span>
          <span className="who">
            <span className="avatar">{p.name.slice(0, 1).toUpperCase()}</span>
            <span className="who-text">
              <span className="who-name">
                {p.name} {p.is_you && <span className="tag">You</span>}
              </span>
              {state.rounds && p.pick_points > 0 && <span className="who-pick">🎯 {p.pick_points}</span>}
            </span>
          </span>
          {form && (
            <span className="form" aria-label={`${p.ticks.filter(Boolean).length} active days of ${p.ticks.length}`}>
              {p.ticks.slice(-7).map((hit, d) => (
                <i key={d} className={hit ? "hit" : "miss"} />
              ))}
            </span>
          )}
          <span className="pts">{p.points}</span>
        </div>
      ))}
      {(phase === "joining" || form) && (
        <p className="fine">
          {phase === "joining" ? "Scoring starts at kick-off." : `Form: active days${days > 7 ? ", last 7" : ""}.`}
        </p>
      )}
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
