import { useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, ChevronRight, CircleHelp, LogOut, Pencil, Plus, Trash2 } from "lucide-react";
import type { ChallengeState, ChallengeView, Me, MyEvent } from "./api";
import type { Session } from "./App";
import { EventRow, eventStatus, InviteCodeBox } from "./events";
import { money } from "./format";
import { PHOTOS } from "./media";
import { MODE_INFO, ModeBadge, MODES } from "./modes";
import OuraCard from "./Oura";
import { Avatar, Eyebrow, Skeleton } from "./ui";

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 5 ? "Still up" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

const ordinal = (n: number) => {
  const tail = n % 100;
  if (tail >= 11 && tail <= 13) return "th";
  return ["th", "st", "nd", "rd"][n % 10] ?? "th";
};

type Standing = { rank: number; of: number; points: number };

/** The signed-in home: your competitions first, what to do next, and your account to the side. */
export default function Dashboard(props: {
  session: Session;
  balance: number | null;
  busy: boolean;
  onAddFunds: () => void;
  onWithdraw: () => void;
  onRenamed: (me: Me) => void;
  onSignOut: () => void;
}) {
  const { session, balance } = props;
  const { me, call, go } = session;
  const [events, setEvents] = useState<MyEvent[] | null>(null);
  const [standing, setStanding] = useState<Record<string, Standing>>({});
  const [now, setNow] = useState(Date.now());
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(me.name);
  const codeBox = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    call<MyEvent[]>("GET", "/me/challenges")
      .then((list) => {
        if (cancelled) return;
        setEvents(list);
        // For the few events you are playing right now, also show where you stand.
        list
          .filter((e) => e.joined && e.status === "open")
          .slice(0, 4)
          .forEach((e) =>
            call<ChallengeState>("GET", `/challenges/${e.address}/state`)
              .then((state) => {
                const you = state.players?.find((p) => p.is_you);
                if (!you || cancelled) return;
                setStanding((old) => ({
                  ...old,
                  [e.address]: { rank: you.rank, of: state.players!.length, points: you.points },
                }));
              })
              .catch(() => undefined),
          );
      })
      .catch(() => !cancelled && setEvents([]));
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      cancelled = true;
      clearInterval(clock);
    };
  }, [call]);

  async function saveName(e: React.FormEvent) {
    e.preventDefault();
    try {
      props.onRenamed(await call<Me>("POST", "/me/name", { name }));
      setEditing(false);
    } catch (err) {
      console.error(err);
    }
  }

  function focusCode() {
    codeBox.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    codeBox.current?.querySelector("input")?.focus({ preventScroll: true });
  }

  const openEvent = (address: string) => go({ view: "challenge", address });
  const active = events?.filter((e) => !eventStatus(e, now).done) ?? [];
  const finished = events?.filter((e) => eventStatus(e, now).done) ?? [];
  const live = active.filter((e) => eventStatus(e, now).live).length;
  const message =
    events === null
      ? " "
      : active.length === 0
        ? "Nothing on the line yet. Start something, or join a friend."
        : live > 0
          ? `${live} ${live === 1 ? "competition is" : "competitions are"} live. Every workout counts.`
          : `${active.length} ${active.length === 1 ? "competition is" : "competitions are"} about to start.`;

  return (
    <div className="dash">
      <header className="welcome">
        <div>
          <Eyebrow>{new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}</Eyebrow>
          <h1 className="display">
            {greeting()}, <em className="serif">{me.name}.</em>
          </h1>
          <p className="lede">{message}</p>
        </div>
        <div className="welcome-actions">
          <button className="btn btn-primary" onClick={() => go({ view: "create", mode: "private" })}>
            <Plus size={16} aria-hidden /> Start a challenge
          </button>
          <button className="btn btn-quiet" onClick={focusCode}>
            Join with a code
          </button>
        </div>
      </header>

      <div className="dash-grid">
        <div className="dash-main">
          <section>
            <div className="section-head">
              <h2>Your competitions</h2>
              {active.length > 0 && <span className="count">{active.length} active</span>}
            </div>
            {events === null ? (
              <Skeleton rows={1} height={210} />
            ) : active.length === 0 ? (
              <div className="starter">
                <img src={PHOTOS.tennisFeet.src} alt="" />
                <div className="starter-copy">
                  <h3 className="headline">
                    Your first rival is <em className="serif">waiting.</em>
                  </h3>
                  <p>Start a game for your friends, or jump into a public event that's about to begin.</p>
                  <div className="starter-actions">
                    <button className="btn btn-primary" onClick={() => go({ view: "create", mode: "private" })}>
                      <Plus size={16} aria-hidden /> Start a challenge
                    </button>
                    <button className="btn btn-glass" onClick={() => go({ view: "mode", mode: "public" })}>
                      Browse public events
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="comp-grid">
                {active.map((e) => (
                  <CompetitionCard key={e.address} event={e} now={now} standing={standing[e.address]} onOpen={openEvent} />
                ))}
              </div>
            )}
            {events !== null && !me.test_funds_used && (
              <div className="nudge">
                <span>
                  <b>New here?</b> Add {me.test_funds_amount} devnet USDC to cover your first entry fees. It's demo money.
                </span>
                <button className="btn btn-quiet btn-sm" onClick={props.onAddFunds} disabled={props.busy}>
                  {props.busy ? "Adding..." : `Add ${me.test_funds_amount} devnet USDC`}
                </button>
              </div>
            )}
          </section>

          <section>
            <div className="section-head">
              <h2>Ways to play</h2>
            </div>
            <div className="mode-rows">
              {MODES.map((mode, i) => {
                const { title, line } = MODE_INFO[mode];
                return (
                  <button key={mode} className="mode-row" onClick={() => go({ view: "mode", mode })}>
                    <b>0{i + 1}</b>
                    <span className="mode-row-title">{title}</span>
                    <span className="mode-row-line">{line}</span>
                    <ArrowUpRight size={18} aria-hidden />
                  </button>
                );
              })}
            </div>
          </section>

          {finished.length > 0 && (
            <section>
              <div className="section-head">
                <h2>Completed</h2>
                <span className="count">{finished.length}</span>
              </div>
              <div className="stack">
                {finished.map((e) => (
                  <EventRow key={e.address} event={e} now={now} onOpen={openEvent} showMode />
                ))}
              </div>
            </section>
          )}
        </div>

        <aside className="dash-rail">
          <div ref={codeBox}>
            <InviteCodeBox
              session={session}
              onJoined={(c: ChallengeView) => openEvent(c.address)}
              hint="Enter it to open a friend's game or a league."
            />
          </div>

          <section className="card balance-card">
            <div className="balance-row">
              <div>
                <Eyebrow>Balance</Eyebrow>
                <div className="balance-amount">{balance === null ? <span className="skeleton inline" /> : money(balance)}</div>
              </div>
              <button className="btn btn-quiet btn-sm" onClick={props.onWithdraw}>
                Withdraw
              </button>
            </div>
            <p className="fine">{balance === null ? " " : `${balance} devnet USDC · demo money, no real value`}</p>
          </section>

          <section className="card profile-card">
            <Eyebrow>Player name</Eyebrow>
            {editing ? (
              <form className="profile-edit" onSubmit={saveName}>
                <input value={name} maxLength={24} onChange={(e) => setName(e.target.value)} aria-label="Player name" autoFocus />
                <button className="btn btn-primary btn-sm" type="submit" disabled={!name.trim()}>
                  Save
                </button>
              </form>
            ) : (
              <div className="profile-row">
                <Avatar name={me.name} size="lg" />
                <div className="profile-name">
                  <b>{me.name}</b>
                  {me.email && <span>{me.email}</span>}
                </div>
                <button className="icon-btn" onClick={() => setEditing(true)} aria-label="Change player name">
                  <Pencil size={15} aria-hidden />
                </button>
              </div>
            )}
            <p className="fine">This is what other players see on the leaderboard.</p>
          </section>

          <OuraCard session={session} />

          <DeleteWorkouts call={call} />

          <div className="rail-links">
            <button className="rail-link" onClick={() => go({ view: "help" })}>
              <CircleHelp size={16} aria-hidden /> How Rival works <ChevronRight size={15} aria-hidden />
            </button>
            <button className="rail-link" onClick={props.onSignOut}>
              <LogOut size={16} aria-hidden /> Sign out
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

/** One of your active competitions: where you stand, and how far through it is. */
function CompetitionCard(props: { event: MyEvent; now: number; standing?: Standing; onOpen: (address: string) => void }) {
  const { event: e, now, standing } = props;
  const status = eventStatus(e, now);
  const start = new Date(e.start).getTime();
  const end = new Date(e.end).getTime();
  const progress = now <= start ? 0 : Math.min(1, (now - start) / Math.max(1, end - start));
  const role = e.joined ? null : e.is_creator ? (e.mode === "league" ? "You're the organizer" : "You created this") : "You're invited";

  return (
    <button className={`comp-card${status.live ? " live" : ""}`} onClick={() => props.onOpen(e.address)}>
      <span className="comp-top">
        <ModeBadge mode={e.mode} />
        <span className={`status-pill${status.live ? " live" : ""}`}>
          {status.live && <span className="live-dot" />}
          {status.live ? "Live" : status.text}
        </span>
      </span>
      <span className="comp-name">{e.name}</span>
      {e.organizer_name && <span className="comp-host">Hosted by {e.organizer_name}</span>}

      <span className="comp-body">
        {standing ? (
          <>
            <span className="comp-rank">
              {standing.rank}
              <sup>{ordinal(standing.rank)}</sup>
              <small>of {standing.of}</small>
            </span>
            <span className="comp-points">
              <b>{standing.points}</b>
              <small>point{standing.points === 1 ? "" : "s"}</small>
            </span>
          </>
        ) : (
          <span className="comp-role">
            {role ?? (status.live ? "You're in. Log a workout to get on the board." : "You're in. Scoring starts with the challenge.")}
          </span>
        )}
      </span>

      <span className="comp-progress" aria-hidden>
        <i style={{ transform: `scaleX(${progress})` }} />
      </span>
      <span className="comp-foot">
        <span>{status.live ? status.text : `${money(e.buy_in)} entry`}</span>
        <span className="comp-go">
          Open <ArrowRight size={15} aria-hidden />
        </span>
      </span>
    </button>
  );
}

/**
 * "Delete my workouts": DELETE /me/fitness removes every workout you logged, revokes and removes the Oura
 * connection with its imported workouts and saved receipts, and removes your points in
 * challenges that have not finished. You stay in those pools. Finished results are kept.
 * The confirm step is part of the card, not a browser dialog.
 */
function DeleteWorkouts({ call }: { call: Session["call"] }) {
  const [step, setStep] = useState<"idle" | "confirm" | "busy" | "done" | "error">("idle");
  async function remove() {
    setStep("busy");
    try {
      await call("DELETE", "/me/fitness");
      setStep("done");
    } catch (e) {
      console.error(e);
      setStep("error");
    }
  }
  return (
    <section className="card data-card">
      <Eyebrow>Your data</Eyebrow>
      {step === "confirm" || step === "busy" ? (
        <>
          <p className="muted">
            This deletes every workout you have logged, disconnects Oura and deletes the workouts imported from it, and removes
            your points in challenges that have not finished. You stay in those challenges with zero points. Finished results
            are kept. This cannot be undone.
          </p>
          <div className="btn-row">
            <button className="btn btn-danger btn-sm" onClick={remove} disabled={step === "busy"}>
              {step === "busy" ? "Deleting..." : "Yes, delete them"}
            </button>
            <button className="btn btn-text btn-sm" onClick={() => setStep("idle")} disabled={step === "busy"}>
              Keep them
            </button>
          </div>
        </>
      ) : (
        <>
          <button className="btn btn-quiet btn-sm btn-block" onClick={() => setStep("confirm")}>
            <Trash2 size={15} aria-hidden /> Delete my workouts
          </button>
          <p className="fine" role="status">
            {step === "done"
              ? "Done. Your workouts and unfinished-challenge points are deleted, and Oura is disconnected. Reload to refresh this page."
              : step === "error"
                ? "That didn't work. Try again in a moment."
                : "Removes your logged and Oura-imported workouts, disconnects Oura, and clears your points in unfinished challenges."}
          </p>
        </>
      )}
    </section>
  );
}
