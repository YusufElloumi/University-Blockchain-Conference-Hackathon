import { useEffect, useState } from "react";
import { ArrowRight, ChevronRight, CircleHelp, LogOut, Pencil, Plus, Trophy } from "lucide-react";
import type { ChallengeState, ChallengeView, Me, MyEvent } from "./api";
import type { Session } from "./App";
import { EventRow, eventStatus, InviteCodeBox } from "./events";
import { money } from "./format";
import { MODE_INFO, MODES } from "./modes";
import { Avatar, EmptyState, Eyebrow, Skeleton } from "./ui";

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 5 ? "Still up" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

const ordinal = (n: number) => {
  const tail = n % 100;
  if (tail >= 11 && tail <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
};

/** The signed-in home: your competitions, your balance, and the ways to play. */
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
  const [standing, setStanding] = useState<Record<string, string>>({});
  const [now, setNow] = useState(Date.now());
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(me.name);

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
                const line = `${ordinal(you.rank)} of ${state.players!.length} · ${you.points} pt${you.points === 1 ? "" : "s"}`;
                setStanding((old) => ({ ...old, [e.address]: line }));
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

  const openEvent = (address: string) => go({ view: "challenge", address });
  const active = events?.filter((e) => !eventStatus(e, now).done) ?? [];
  const finished = events?.filter((e) => eventStatus(e, now).done) ?? [];

  return (
    <div className="dash">
      <header className="page-head">
        <div>
          <Eyebrow>{new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}</Eyebrow>
          <h1 className="headline">
            {greeting()}, <em className="serif">{me.name}.</em>
          </h1>
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
              <Skeleton rows={2} height={76} />
            ) : active.length === 0 ? (
              <EmptyState
                icon={<Trophy size={20} strokeWidth={1.75} />}
                title="Nothing on the line yet"
                text="Join a friend's challenge with their code, find a public event, or start your own."
              >
                <button className="btn btn-primary" onClick={() => go({ view: "create", mode: "private" })}>
                  <Plus size={16} aria-hidden /> Start a challenge
                </button>
                <button className="btn btn-quiet" onClick={() => go({ view: "mode", mode: "public" })}>
                  Browse public events
                </button>
              </EmptyState>
            ) : (
              <div className="stack">
                {active.map((e) => (
                  <EventRow key={e.address} event={e} now={now} onOpen={openEvent} showMode extra={standing[e.address]} />
                ))}
              </div>
            )}
          </section>

          <section>
            <div className="section-head">
              <h2>Ways to play</h2>
            </div>
            <div className="mode-cards">
              {MODES.map((mode) => {
                const { Icon, title, line } = MODE_INFO[mode];
                return (
                  <button key={mode} className="mode-card" onClick={() => go({ view: "mode", mode })}>
                    <span className="icon-tile">
                      <Icon size={18} strokeWidth={1.75} aria-hidden />
                    </span>
                    <span className="mode-card-title">
                      {title} <ArrowRight size={15} aria-hidden />
                    </span>
                    <span className="mode-card-line">{line}</span>
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
          <section className="card balance-card">
            <Eyebrow>Your balance</Eyebrow>
            <div className="balance-amount">{balance === null ? <span className="skeleton inline" /> : money(balance)}</div>
            <p className="fine">{balance === null ? " " : `${balance} devnet USDC`}</p>
            <div className="balance-actions">
              {!me.test_funds_used && (
                <button className="btn btn-primary" onClick={props.onAddFunds} disabled={props.busy}>
                  {props.busy ? "Adding..." : `Add ${me.test_funds_amount} devnet USDC`}
                </button>
              )}
              <button className="btn btn-quiet" onClick={props.onWithdraw}>
                Withdraw
              </button>
            </div>
          </section>

          <InviteCodeBox
            session={session}
            onJoined={(c: ChallengeView) => openEvent(c.address)}
            hint="Enter it here to open a friend's game or a league."
          />

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
