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
import { buildJoinTransaction, explorerTx, fetchChallenge, friendlyError, sha256Hex, type ChallengeInfo } from "./chain";
import { ago, countdown, money, usdc, when } from "./format";
import JoinIntro from "./JoinIntro";
import { InviteCodeBox } from "./events";
import Leaderboard from "./Leaderboard";
import { FORMAT_INFO, type Format } from "./formats";
import { MODE_INFO, ModeBadge } from "./modes";
import { ConnectFitness, ProofCard } from "./Proof";
import { LockedRulesCard, payoutLockedLine } from "./LockedRules";
import { sportLabel } from "./activities";
import SweatWorkouts from "./Sweat";
import { EmptyState, Eyebrow, Skeleton } from "./ui";
import {
  Activity,
  ArrowUpRight,
  Bike,
  Check,
  ChevronLeft,
  CircleCheck,
  Crown,
  Dumbbell,
  Flag,
  Footprints,
  Lock,
  Mountain,
  PersonStanding,
  Share2,
  Target,
  Timer,
  Trophy,
  Undo2,
  UserPlus,
  Waves,
  X,
  type LucideIcon,
} from "lucide-react";

type Tab = "table" | "feed" | "me";

// A workout's state in this challenge (api/scoring.py). "Passed checks", not "verified": demo data is not proof.
const STATE_LABEL = { verified: "Passed checks", flagged: "Counts · unverified", rejected: "Not counted" } as const;
type Phase = "joining" | "live" | "ended" | "settled" | "refunded";

const PHASE_LABEL: Record<Phase, string> = {
  joining: "Joining open",
  live: "Live",
  ended: "Finished",
  settled: "Final",
  refunded: "Refunded",
};
const TYPE_ICON: Record<string, LucideIcon> = {
  run: Footprints,
  walk: PersonStanding,
  hike: Mountain,
  ride: Bike,
  swim: Waves,
  workout: Dumbbell,
};
/** Feed events that end a challenge. true = someone was paid (shown as a win). */
const RESULT_KINDS: Record<string, boolean> = {
  ChallengeSettled: true,
  ChallengeSettledSplit: true,
  ChallengeRefunded: false,
};
const MINUTE_CHOICES = [20, 30, 45, 60, 90];
const FEED_ICON: Record<string, LucideIcon> = {
  ChallengeCreated: Flag,
  PlayerJoined: UserPlus,
  ChallengeEnded: Timer,
  ChallengeSettled: Trophy,
  ChallengeSettledSplit: Trophy,
  ChallengeRefunded: Undo2,
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

  async function recordJoin(signature?: string, team: number | null = null) {
    await retryWhileNotReady(() =>
      call("POST", `/challenges/${address}/join`, { consent: true, deposit_tx: signature ?? null, team }),
    );
    await loadState();
  }

  async function onJoin(team: number | null) {
    if (!info) return;
    setBusy(true);
    setError("");
    try {
      // Hash the rules this page shows, here in the browser. The program only takes the deposit if this
      // equals the hash locked at creation, so nobody can pay into rules they did not see.
      const shown = state?.challenge?.ruleset;
      if (!shown || !info.rules) throw new Error("This challenge was created before rules were locked, so it can't take new players.");
      const shownHash = await sha256Hex(shown);
      if (shownHash !== info.rules.rulesHash) throw new Error("The rules shown here don't match the rules locked onchain. Nothing was paid.");
      const signature = await send(await buildJoinTransaction(me.wallet, info, shownHash));
      setLastTx(signature);
      await Promise.all([loadChain(), refreshBalance()]);
      await recordJoin(signature, team);
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

  const { markMode } = session;
  useEffect(() => {
    markMode(mode ?? null);
  }, [markMode, mode]);

  async function onInvite() {
    // Invite-only events share the code, so the link works for people who have not been let in yet.
    const query = inviteCode ? `invite=${inviteCode}` : `challenge=${address}`;
    const link = `${window.location.origin}${window.location.pathname}?${query}`;
    try {
      if (navigator.share) await navigator.share({ title: "Rival", text: "Join my fitness challenge", url: link });
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
      <div className="narrow">
        <button className="back" onClick={() => go({ view: "home" })}>
          <ChevronLeft size={16} aria-hidden /> Home
        </button>
        <EmptyState
          icon={<Lock size={20} strokeWidth={1.75} />}
          title="This event is invite only"
          text="Ask the organizer or a friend in it for the invite code."
        />
        <InviteCodeBox session={session} title="Enter invite code" onJoined={() => loadState()} />
      </div>
    );
  }

  if (!info) {
    return error ? (
      <div className="center-state">
        <p>{error}</p>
        <button className="btn btn-quiet" onClick={() => go({ view: "home" })}>
          Back to home
        </button>
      </div>
    ) : (
      <div aria-label="Loading challenge">
        <Skeleton rows={1} height={220} />
        <Skeleton rows={3} height={64} />
      </div>
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
  const result = state?.feed.filter((f) => f.kind in RESULT_KINDS).pop();
  const ResultIcon = result ? FEED_ICON[result.kind] : null;
  // How far through the event we are, for the thin progress line under the header.
  const span = info.endTime.getTime() - info.startTime.getTime();
  const progress =
    phase === "joining" ? 0 : phase === "live" ? Math.min(1, Math.max(0, (now - info.startTime.getTime()) / span)) : 1;
  const showAdmin =
    state?.you.is_admin && state.challenge && info.status === "open" && info.players.length >= 2 && phase !== "ended";
  const showJoin = phase === "joining" && !inOnchain && !!state;
  const showConsent = inOnchain && !!state && !onTable;
  const showInvite = phase === "joining" && !full;
  const showStats = statsScored && state?.you.is_creator && info.status === "open";

  return (
    <div className="challenge">
      <button className="back" onClick={() => go(mode ? { view: "mode", mode } : { view: "home" })}>
        <ChevronLeft size={16} aria-hidden /> {mode ? MODE_INFO[mode].title : "Home"}
      </button>

      <section className={`ch-hero ${phase}`}>
        <div className="ch-hero-top">
          <div className="ch-hero-meta">
            {mode && <ModeBadge mode={mode} />}
            {state?.challenge?.organizer_name && <span>Hosted by {state.challenge.organizer_name}</span>}
            {sportLabel(state?.challenge?.activities) && <span>{sportLabel(state?.challenge?.activities)} only</span>}
          </div>
          <div className={`status-pill ${phase}`}>
            {phase === "live" && <span className="live-dot" />}
            {phase === "ended" && state?.sweat?.awaiting_final_sync ? "Awaiting final sync" : PHASE_LABEL[phase]}
          </div>
        </div>
        <h1 className="ch-title">{name}</h1>
        <div className="ch-stats">
          <div className="ch-stat ch-stat-pool">
            <small>{phase === "settled" ? "Paid out" : phase === "refunded" ? "Returned" : "Prize pool"}</small>
            <b>{money(phase === "settled" || phase === "refunded" ? info.buyIn * info.players.length : pool)}</b>
          </div>
          <div className="ch-stat">
            <small>Players</small>
            <b>
              {info.players.length}
              <span> / {info.maxPlayers}</span>
            </b>
          </div>
          <div className="ch-stat">
            <small>Entry fee</small>
            <b>{money(info.buyIn)}</b>
          </div>
          <div className="ch-stat">
            <small>{phase === "joining" ? "Starts in" : phase === "live" ? "Time left" : "Ended"}</small>
            <b>
              {phase === "joining"
                ? countdown(info.startTime, now)
                : phase === "live"
                  ? countdown(info.endTime, now)
                  : when(info.endTime)}
            </b>
          </div>
        </div>
        <div className="ch-progress" role="progressbar" aria-label="Event progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
          <i style={{ width: `${progress * 100}%` }} />
        </div>
      </section>

      <div className="ch-grid">
        {/* ----- What needs your attention: results, joining, confirmation ----- */}
        <div className="ch-top">
          {result && ResultIcon && (
            <div className={`notice-card${RESULT_KINDS[result.kind] ? " win" : ""}`}>
              <span className="icon-tile">
                <ResultIcon size={18} strokeWidth={1.75} aria-hidden />
              </span>
              <div>
                <b>{result.text}</b>
                <a href={explorerTx(result.signature)} target="_blank" rel="noreferrer">
                  View receipt <ArrowUpRight size={13} aria-hidden />
                </a>
              </div>
            </div>
          )}
          {phase === "ended" && info.players.length >= 2 && (
            <div className="notice-card">
              <span className="icon-tile">
                <Timer size={18} strokeWidth={1.75} aria-hidden />
              </span>
              <div>
                <b>Time's up.</b>
                <span>Scores are being checked, then the prize pool is paid out.</span>
              </div>
            </div>
          )}
          {(phase === "live" || phase === "ended") && info.players.length < 2 && (
            <section className="card">
              <h2 className="card-title">Not enough players joined</h2>
              <p className="muted">A challenge needs at least 2. Every entry fee goes back.</p>
              <button className="btn btn-primary btn-block" onClick={() => onFinish(false)} disabled={busy || !state?.challenge}>
                {busy ? "Refunding..." : "Refund the entry fee"}
              </button>
            </section>
          )}

          {showJoin && (
            <section className="card join-card">
              {full ? (
                <p className="muted">This challenge is full.</p>
              ) : (
                <>
                  <div>
                    <h2 className="card-title">Join this challenge</h2>
                    <p className="fine">
                      {canAfford
                        ? `${usdc(info.buyIn)} moves from your balance into the prize pool. ${state?.challenge?.format_summary ?? ""} ${payoutLockedLine(info) ?? ""}`
                        : "You need more in your balance. Add devnet USDC from the home screen first."}
                    </p>
                  </div>
                  <button className="btn btn-primary btn-lg" onClick={() => setIntro(true)} disabled={busy || !canAfford}>
                    {busy ? "Joining..." : `Join for ${usdc(info.buyIn)}`}
                  </button>
                </>
              )}
            </section>
          )}
          {inOnchain && info.status === "open" && (
            <div className={`deposit${state?.you.deposit_confirmed ? " confirmed" : ""}`}>
              {state?.you.deposit_confirmed ? <CircleCheck size={16} aria-hidden /> : <span className="spinner" aria-hidden />}
              <span>{state?.you.deposit_confirmed ? "Entry confirmed. You're in." : "Entry sent. Waiting for confirmation..."}</span>
              {lastTx && (
                <a href={explorerTx(lastTx)} target="_blank" rel="noreferrer">
                  Receipt <ArrowUpRight size={13} aria-hidden />
                </a>
              )}
            </div>
          )}
          {showConsent && (
            <section className="card">
              <label className="consent">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>
                  Share my challenge points with this group. They see points only, never my activities.
                  {state?.challenge?.rules?.proof_of_sweat && " Points come from workouts Rival reads from my connected Oura account."}
                  {sportLabel(state?.challenge?.activities) &&
                    ` Only ${sportLabel(state?.challenge?.activities)!.toLowerCase()} workouts count in this event.`}
                </span>
              </label>
              <button className="btn btn-primary btn-block" onClick={onConsentOnly} disabled={busy || !consent}>
                Add me to the leaderboard
              </button>
            </section>
          )}
          {error && (
            <div className="message error" role="alert">
              {error}
            </div>
          )}
        </div>

        {/* ----- Side column: picks, invites, organizer tools ----- */}
        <div className="ch-rail">
          {phase === "settled" && inOnchain && <ProofCard call={call} info={info} />}
          {info && state?.challenge && <LockedRulesCard info={info} ruleset={state.challenge.ruleset} />}
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
          {showInvite && (
            <section className="card invite-card">
              <Eyebrow>{mode === "league" ? "Invite members" : "Invite friends"}</Eyebrow>
              {inviteCode && (
                <div className="invite-code" aria-label={`Invite code ${inviteCode}`}>
                  {inviteCode}
                </div>
              )}
              <button className="btn btn-quiet btn-block" onClick={onInvite}>
                {copied ? (
                  <>
                    <Check size={16} aria-hidden /> Link copied
                  </>
                ) : (
                  <>
                    <Share2 size={16} aria-hidden /> Share invite link
                  </>
                )}
              </button>
            </section>
          )}
          {showStats && <LeagueStats session={session} address={address} onChanged={loadState} />}
          {showAdmin && (
            <section className="card admin">
              <Eyebrow>Admin</Eyebrow>
              {confirmEnd ? (
                <>
                  <p className="muted">This ends the challenge for everyone and pays the pool by the current standings.</p>
                  <div className="btn-row">
                    <button className="btn btn-danger" onClick={() => onFinish(true)} disabled={busy}>
                      Yes, end and pay out
                    </button>
                    <button className="btn btn-text" onClick={() => setConfirmEnd(false)}>
                      Keep playing
                    </button>
                  </div>
                </>
              ) : (
                <button className="btn btn-quiet btn-block" onClick={() => setConfirmEnd(true)} disabled={busy}>
                  {busy ? "Ending and paying out..." : "End challenge now"}
                </button>
              )}
            </section>
          )}
        </div>

        {/* ----- The competition itself ----- */}
        <div className="ch-body">
          <nav className="tabs" role="tablist">
            {tabs.map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                {t === "table" ? "Leaderboard" : t === "feed" ? "Feed" : "My workouts"}
                {t === "feed" && !!state?.feed.length && <span className="count">{state.feed.length}</span>}
              </button>
            ))}
          </nav>
          <div className="tab-panel" key={tab}>
            {tab === "table" && <Table state={state} phase={phase} />}
            {tab === "feed" && <Feed state={state} now={now} />}
            {tab === "me" && !statsScored && state?.challenge?.rules?.proof_of_sweat && (
              <SweatWorkouts
                session={session}
                address={address}
                live={phase === "live" || phase === "ended"}
                sport={sportLabel(state.challenge.activities)}
                onScored={loadState}
              />
            )}
            {tab === "me" && !statsScored && !state?.challenge?.rules?.proof_of_sweat && (
              <MyWorkouts
                session={session}
                canAdd={onTable && config.fitness.can_add && phase !== "settled" && phase !== "refunded"}
                address={address}
                onScored={loadState}
              />
            )}
          </div>
        </div>
      </div>

      {intro && (
        <JoinIntro
          sweat={!!state?.challenge?.rules?.proof_of_sweat}
          sweatGeneration={state?.challenge?.rules?.generation}
          sport={sportLabel(state?.challenge?.activities)}
          scoring={state?.challenge?.scoring_source ?? "fitness"}
          weights={state?.challenge?.stat_weights ?? null}
          hasPicks={!!state?.challenge?.round_hours}
          format={state?.challenge?.format ?? "winner_takes_all"}
          formatConfig={state?.challenge?.format_config ?? {}}
          lengthMs={info.endTime.getTime() - info.startTime.getTime()}
          buyIn={info.buyIn}
          playersAfterJoin={info.players.length + 1}
          busy={busy}
          onReady={onJoin}
          onClose={() => setIntro(false)}
        />
      )}
    </div>
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
      <div className="card-title-row">
        <Eyebrow>Prediction pick{current ? ` · Round ${current.number} of ${total}` : ""}</Eyebrow>
        <a
          className="powered"
          href={current?.market_url ?? "https://www.gemini.com/predictions"}
          target="_blank"
          rel="noreferrer"
        >
          Gemini <ArrowUpRight size={12} aria-hidden />
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
                  {mark === "hit" ? <Check size={12} strokeWidth={3} aria-hidden /> : mark === "miss" ? <X size={12} strokeWidth={3} aria-hidden /> : null}
                </button>
              );
            })}
          </div>
          <span className="round-total">
            <Target size={13} aria-hidden /> {myPoints} pts
          </span>
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
      <div className="round-meta">
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
        <p className="fine with-icon">
          <Lock size={12} aria-hidden /> {round.picks_made} picked · hidden until kick-off
        </p>
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
          <Eyebrow>Stat sheet</Eyebrow>
          <div className="stats-status">{status}</div>
        </div>
        <button type="button" className="btn btn-quiet btn-sm" onClick={() => setOpen(!open)} aria-expanded={open}>
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
              <button className="btn btn-primary btn-block" onClick={() => upload(text)} disabled={busy || !text.trim()}>
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
  if (!state) return <Skeleton rows={4} height={60} />;
  if (!state.players)
    return (
      <EmptyState
        icon={<Trophy size={20} strokeWidth={1.75} />}
        title="The leaderboard is for players"
        text="Join this challenge to see how everyone is doing."
      />
    );
  const days = Math.max(0, ...state.players.map((p) => p.ticks.length));
  const sweat = !!state.challenge?.rules?.proof_of_sweat;
  const form = state.challenge?.scoring_source !== "league_stats"; // stat sheets have no daily form
  const challenge = state.challenge;
  const final = phase === "settled" || phase === "refunded";
  return (
    <section className="card board-card">
      {challenge && (
        <FormatBar
          format={challenge.format}
          summary={challenge.format_summary}
          goalMissed={!!state.format?.goal_missed && state.players.length > 0 && phase !== "joining"}
        />
      )}
      {challenge?.format === "teams" && state.format?.teams && (
        <TeamTable teams={state.format.teams} mine={state.players.find((p) => p.is_you)?.team ?? null} />
      )}
      <Leaderboard
        players={state.players}
        form={form}
        picks={!!state.rounds}
        format={challenge?.format}
        formatConfig={challenge?.format_config}
        showShares={phase !== "joining" && !final}
        sweat={sweat && !final}
      />
      {(phase === "joining" || form) && (
        <p className="fine board-note">
          {phase === "joining" ? "Scoring starts when the challenge does." : `Form shows active days${days > 7 ? " (last 7)" : ""}.`}
          {sweat &&
            ((state.challenge?.rules?.generation ?? 0) >= 2
              ? " Sweat Points come only from Oura-verified workouts: about 1 per minute, weighted by effort."
              : " Fitness points come only from Oura-verified workouts: 1 per 10 minutes, up to 6 a day.")}
          {sweat && state.sweat?.awaiting_final_sync && " Final scores are pending while workouts finish syncing."}
        </p>
      )}
    </section>
  );
}

/** How this event pays, above the leaderboard. */
function FormatBar(props: { format: Format; summary: string; goalMissed: boolean }) {
  const { Icon, title } = FORMAT_INFO[props.format];
  return (
    <div className="format-bar">
      <span className="icon-tile icon-tile-sm">
        <Icon size={15} strokeWidth={1.75} aria-hidden />
      </span>
      <div>
        <b>{title}</b>
        <span>{props.summary}</span>
        {props.goalMissed && <span className="format-bar-note">Nobody has reached the goal yet.</span>}
      </div>
    </div>
  );
}

/** Teams format: the two teams, best average first. */
function TeamTable(props: {
  teams: { team: number; name: string; average: number | null; members: number; rank: number | null }[];
  mine: number | null;
}) {
  return (
    <div className="team-table" role="table" aria-label="Team standings">
      {props.teams.map((t) => (
        <div key={t.team} role="row" className={`team-row${t.rank === 1 ? " leader" : ""}`}>
          <span role="cell" className="team-name">
            {t.rank === 1 && t.average ? <Crown size={14} strokeWidth={2} aria-label="Leading" /> : null}
            {t.name}
            {props.mine === t.team && <span className="tag tag-accent">Your team</span>}
          </span>
          <span role="cell" className="team-members">
            {t.members} {t.members === 1 ? "player" : "players"}
          </span>
          <span role="cell" className="team-avg">
            {t.average ?? "-"}
            <small>avg</small>
          </span>
        </div>
      ))}
    </div>
  );
}

function Feed({ state, now }: { state: ChallengeState | null; now: number }) {
  if (!state) return <Skeleton rows={3} height={56} />;
  if (state.feed.length === 0)
    return (
      <EmptyState
        icon={<Activity size={20} strokeWidth={1.75} />}
        title="Nothing yet"
        text="Joins and payouts show up here as they happen."
      />
    );
  return (
    <section className="card feed">
      {[...state.feed].reverse().map((item) => {
        const Icon = FEED_ICON[item.kind] ?? Activity;
        return (
          <div key={item.signature + item.kind} className="feed-item">
            <span className="icon-tile icon-tile-sm">
              <Icon size={15} strokeWidth={1.75} aria-hidden />
            </span>
            <div>
              <div>{item.text}</div>
              <div className="fine">
                {ago(item.time, now)} ·{" "}
                <a href={explorerTx(item.signature)} target="_blank" rel="noreferrer">
                  receipt
                </a>
              </div>
            </div>
          </div>
        );
      })}
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
    call<ActivityView[]>("GET", `/me/activities?challenge=${props.address}`)
      .then(setList)
      .catch(() => setList([]));
  }, [call, props.address]);
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
    <div className="workouts">
      {props.canAdd && (
        <section className="card">
          <h2 className="card-title">Log a workout</h2>
          <div className="field">
            <span className="field-label">Activity</span>
            <div className="chips">
              {config.fitness.types.map((t) => {
                const Icon = TYPE_ICON[t] ?? Activity;
                return (
                  <button key={t} type="button" className={t === type ? "chip cap on" : "chip cap"} onClick={() => setType(t)}>
                    <Icon size={15} strokeWidth={1.75} aria-hidden /> {t}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="field">
            <span className="field-label">Minutes</span>
            <div className="chips">
              {MINUTE_CHOICES.map((m) => (
                <button key={m} type="button" className={m === minutes ? "chip on" : "chip"} onClick={() => setMinutes(m)}>
                  {m}
                </button>
              ))}
            </div>
          </div>
          <label className="field">
            <span className="field-label">Distance (km, optional)</span>
            <input inputMode="decimal" placeholder="0" value={km} onChange={(e) => setKm(e.target.value.replace(/[^0-9.]/g, ""))} aria-label="Distance in kilometres" />
          </label>
          <button className="btn btn-primary btn-block" onClick={onAdd} disabled={busy}>
            {busy ? "Saving..." : "Add workout"}
          </button>
          <p className="fine">Source: {config.fitness.label}. Counts from now.</p>
          {outcome && <div className={`message ${outcome.good ? "ok" : "error"}`}>{outcome.text}</div>}
        </section>
      )}
      <ConnectFitness />
      <div className="section-head">
        <h2>Your workouts</h2>
        <span className="count with-icon">
          <Lock size={11} aria-hidden /> Only you can see these
        </span>
      </div>
      {list === null ? (
        <Skeleton rows={2} height={56} />
      ) : list.length === 0 ? (
        <EmptyState icon={<Footprints size={20} strokeWidth={1.75} />} title="No workouts yet" />
      ) : (
        <section className="card feed">
          {list.map((a) => {
            const Icon = TYPE_ICON[a.type] ?? Activity;
            return (
              <div key={a.id} className="feed-item">
                <span className="icon-tile icon-tile-sm">
                  <Icon size={15} strokeWidth={1.75} aria-hidden />
                </span>
                <div className="workout-main">
                  <div>
                    <b className="cap">{a.type}</b> · {a.minutes} min{a.distance_km ? ` · ${a.distance_km} km` : ""}
                  </div>
                  <div className="fine">
                    {when(new Date(a.start))} · {a.verified ? a.device : "unverified"}
                    {a.status === "rejected" && a.reason ? ` · ${a.reason}` : ""}
                  </div>
                </div>
                {a.status && <span className={`tag workout-state ${a.status}`}>{STATE_LABEL[a.status]}</span>}
              </div>
            );
          })}
        </section>
      )}
    </div>
  );
}
