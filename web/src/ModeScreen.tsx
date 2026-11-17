import { useEffect, useState } from "react";
import type { ChallengeView, MyEvent, PublicEvent } from "./api";
import type { Session } from "./App";
import { countdown, money, when } from "./format";
import { MODE_INFO, type Mode } from "./modes";

/** One mode's screen: joining takes the top, creating is a quiet button further down. */
export default function ModeScreen({ mode, session }: { mode: Mode; session: Session }) {
  const { call, go } = session;
  const info = MODE_INFO[mode];
  const [mine, setMine] = useState<MyEvent[] | null>(null);
  const [open, setOpen] = useState<PublicEvent[] | null>(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    call<MyEvent[]>("GET", `/me/challenges?mode=${mode}`)
      .then(setMine)
      .catch(() => setMine([]));
    if (mode === "public")
      call<PublicEvent[]>("GET", "/events/public")
        .then(setOpen)
        .catch(() => setOpen([]));
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(clock);
  }, [call, mode]);

  const openEvent = (address: string) => go({ view: "challenge", address });
  // In the public list, events you are already in show under "Your public events" instead.
  const joinable = open?.filter((e) => !mine?.some((m) => m.address === e.address)) ?? null;

  return (
    <div className={`mode-${mode}`}>
      <button className="link back" onClick={() => go({ view: "home" })}>
        ‹ Home
      </button>
      <div className="mode-head">
        <span className="mode-icon">{info.icon}</span>
        <div>
          <h1 className="mode-title">{info.title}</h1>
          <p className="fine">{info.line}</p>
        </div>
      </div>

      {mode === "public" ? (
        <>
          <h2 className="section-title">Open to join</h2>
          {joinable === null ? (
            <p className="muted">Loading...</p>
          ) : joinable.length === 0 ? (
            <Empty text="No public events are open right now. Check back soon, or start one below." />
          ) : (
            joinable.map((e) => <PublicCard key={e.address} event={e} now={now} onOpen={openEvent} />)
          )}
          {!!mine?.length && (
            <>
              <h2 className="section-title">Your public events</h2>
              {mine.map((e) => (
                <EventRow key={e.address} event={e} onOpen={openEvent} />
              ))}
            </>
          )}
        </>
      ) : (
        <>
          <InviteCodeBox session={session} onJoined={(c) => openEvent(c.address)} />
          <h2 className="section-title">{mode === "league" ? "Your leagues" : "Your games"}</h2>
          {mine === null ? (
            <p className="muted">Loading...</p>
          ) : mine.length === 0 ? (
            <Empty
              text={
                mode === "league"
                  ? "No leagues yet. Ask your gym or club for their invite code."
                  : "No games yet. Enter a friend's code, or open their invite link."
              }
            />
          ) : (
            mine.map((e) => <EventRow key={e.address} event={e} onOpen={openEvent} />)
          )}
        </>
      )}

      <button className="create-link" onClick={() => go({ view: "create", mode })}>
        + {info.create}
      </button>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="empty">{text}</div>;
}

/** The big "Enter invite code" field. The server checks the code; a wrong one is refused there. */
export function InviteCodeBox(props: { session: Session; onJoined: (challenge: ChallengeView) => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      props.onJoined(await props.session.call<ChallengeView>("POST", "/invites/redeem", { code: code.trim() }));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <form className="card invite-box" onSubmit={onSubmit}>
      <div className="label">Enter invite code</div>
      <input
        className="code-input"
        value={code}
        maxLength={20}
        placeholder="ABC123"
        autoCapitalize="characters"
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => setCode(e.target.value.toUpperCase())}
        aria-label="Invite code"
      />
      <button className="primary" type="submit" disabled={busy || !code.trim()}>
        {busy ? "Checking..." : "Join"}
      </button>
      {error && (
        <p className="fine error-text" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function PublicCard(props: { event: PublicEvent; now: number; onOpen: (address: string) => void }) {
  const { event: e, now } = props;
  return (
    <button className="event-card" onClick={() => props.onOpen(e.address)}>
      <div className="event-card-top">
        <div className="fixture-name">{e.name}</div>
        <div className="fixture-stake">{money(e.pot)}</div>
      </div>
      <div className="event-stats">
        <span>
          <b>
            {e.player_count}/{e.max_players}
          </b>{" "}
          players
        </span>
        <span>
          <b>{money(e.buy_in)}</b> buy-in
        </span>
        <span>
          <b>{countdown(new Date(e.start), now)}</b> to start
        </span>
      </div>
    </button>
  );
}

function EventRow(props: { event: MyEvent; onOpen: (address: string) => void }) {
  const { event: e } = props;
  const status =
    e.status === "settled" ? "Final" : e.status === "refunded" ? "Refunded" : `Ends ${when(new Date(e.end))}`;
  const role = e.joined ? "Joined" : e.is_creator ? (e.mode === "league" ? "Organizer" : "Created") : "Invited";
  return (
    <button className="fixture" onClick={() => props.onOpen(e.address)}>
      <div>
        <div className="fixture-name">{e.name}</div>
        <div className="fine">
          {e.organizer_name ? `Hosted by ${e.organizer_name} · ` : ""}
          {status}
        </div>
      </div>
      <div className="fixture-side">
        <span className="tag">{role}</span>
        <div className="fixture-stake">{money(e.buy_in)}</div>
      </div>
    </button>
  );
}
