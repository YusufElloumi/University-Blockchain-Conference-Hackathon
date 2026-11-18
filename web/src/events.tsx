// Cards and small forms for events, shared by the dashboard, the mode screens and the event page.

import { useState } from "react";
import { ArrowRight, ChevronRight, Users } from "lucide-react";
import type { ChallengeView, MyEvent, PublicEvent } from "./api";
import type { Session } from "./App";
import { countdown, money } from "./format";
import { MODE_INFO, ModeBadge } from "./modes";

/** "Starts in 2h 05m", "3d 4h left", "Final"... plus whether the event is running right now. */
export function eventStatus(e: ChallengeView, now: number): { text: string; live: boolean; done: boolean } {
  if (e.status === "settled") return { text: "Final", live: false, done: true };
  if (e.status === "refunded") return { text: "Refunded", live: false, done: true };
  const start = new Date(e.start);
  const end = new Date(e.end);
  if (now < start.getTime()) return { text: `Starts in ${countdown(start, now)}`, live: false, done: false };
  if (now < end.getTime()) return { text: `${countdown(end, now)} left`, live: true, done: false };
  return { text: "Wrapping up", live: false, done: false };
}

const roleOf = (e: MyEvent) =>
  e.joined ? "Joined" : e.is_creator ? (e.mode === "league" ? "Organizer" : "Created") : "Invited";

/** One of your events, as a tappable row. `extra` is an optional line such as your rank. */
export function EventRow(props: {
  event: MyEvent;
  now: number;
  onOpen: (address: string) => void;
  showMode?: boolean;
  extra?: string;
}) {
  const { event: e } = props;
  const status = eventStatus(e, props.now);
  const { Icon } = MODE_INFO[e.mode];
  return (
    <button className={`event-row${status.done ? " done" : ""}`} onClick={() => props.onOpen(e.address)}>
      <span className="event-row-icon">
        <Icon size={18} strokeWidth={1.75} aria-hidden />
      </span>
      <span className="event-row-main">
        <span className="event-row-name">{e.name}</span>
        <span className="event-row-meta">
          {status.live && <span className="live-dot" aria-hidden />}
          <span className={status.live ? "is-live" : ""}>{status.text}</span>
          {e.organizer_name && <span>Hosted by {e.organizer_name}</span>}
          {props.extra && <span className="event-row-extra">{props.extra}</span>}
        </span>
      </span>
      <span className="event-row-side">
        <span className="event-row-tags">
          {props.showMode && <ModeBadge mode={e.mode} />}
          <span className="tag">{roleOf(e)}</span>
        </span>
        <span className="event-row-stake">
          {money(e.buy_in)} <small>entry</small>
        </span>
      </span>
      <ChevronRight className="event-row-go" size={18} aria-hidden />
    </button>
  );
}

/** An open public event anyone can join. */
export function PublicCard(props: { event: PublicEvent; now: number; onOpen: (address: string) => void }) {
  const { event: e, now } = props;
  const filled = Math.min(100, Math.round((e.player_count / Math.max(1, e.max_players)) * 100));
  return (
    <button className="public-card" onClick={() => props.onOpen(e.address)}>
      <span className="public-card-top">
        <span className="badge">Starts in {countdown(new Date(e.start), now)}</span>
        <ArrowRight className="public-card-go" size={18} aria-hidden />
      </span>
      <span className="public-card-name">{e.name}</span>
      <span className="public-card-pool">
        <small>Prize pool</small>
        {money(e.pot)}
      </span>
      <span className="meter" aria-hidden>
        <i style={{ width: `${filled}%` }} />
      </span>
      <span className="public-card-foot">
        <span>
          <Users size={13} aria-hidden /> {e.player_count} of {e.max_players} players
        </span>
        <span>{money(e.buy_in)} entry</span>
      </span>
    </button>
  );
}

/** The "Enter invite code" field. The server checks the code; a wrong one is refused there. */
export function InviteCodeBox(props: {
  session: Session;
  onJoined: (challenge: ChallengeView) => void;
  title?: string;
  hint?: string;
}) {
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
      <div className="eyebrow">{props.title ?? "Have an invite code?"}</div>
      {props.hint && <p className="fine">{props.hint}</p>}
      <div className="invite-box-row">
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
        <button className="btn btn-primary" type="submit" disabled={busy || !code.trim()}>
          {busy ? "Checking..." : "Join"}
        </button>
      </div>
      {error && (
        <p className="fine error-text" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
