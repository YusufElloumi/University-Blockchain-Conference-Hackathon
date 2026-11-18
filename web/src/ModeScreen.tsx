import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import type { MyEvent, PublicEvent } from "./api";
import type { Session } from "./App";
import { EventRow, InviteCodeBox, PublicCard } from "./events";
import { MODE_INFO, type Mode } from "./modes";
import { EmptyState, Eyebrow, Skeleton } from "./ui";

/** One mode's screen: joining takes the top, your own events follow, creating is one button away. */
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
  const createButton = (
    <button className="btn btn-primary" onClick={() => go({ view: "create", mode })}>
      <Plus size={16} aria-hidden /> {info.create}
    </button>
  );

  return (
    <div className="mode-screen">
      <header className="page-head">
        <div className="page-head-main">
          <span className="icon-tile icon-tile-lg">
            <info.Icon size={22} strokeWidth={1.75} aria-hidden />
          </span>
          <div>
            <Eyebrow>Compete</Eyebrow>
            <h1 className="headline">{info.title}</h1>
            <p className="lede">{info.line}</p>
          </div>
        </div>
        <div className="page-head-action">{createButton}</div>
      </header>

      {mode === "public" ? (
        <>
          <div className="section-head">
            <h2>Open to join</h2>
            {!!joinable?.length && <span className="count">{joinable.length}</span>}
          </div>
          {joinable === null ? (
            <Skeleton rows={2} height={170} />
          ) : joinable.length === 0 ? (
            <EmptyState
              icon={<info.Icon size={20} strokeWidth={1.75} />}
              title="No public events are open right now"
              text="Check back soon, or start one and let the community come to you."
            >
              {createButton}
            </EmptyState>
          ) : (
            <div className="public-grid">
              {joinable.map((e) => (
                <PublicCard key={e.address} event={e} now={now} onOpen={openEvent} />
              ))}
            </div>
          )}
          {!!mine?.length && (
            <>
              <div className="section-head">
                <h2>Your public events</h2>
                <span className="count">{mine.length}</span>
              </div>
              <div className="stack">
                {mine.map((e) => (
                  <EventRow key={e.address} event={e} now={now} onOpen={openEvent} />
                ))}
              </div>
            </>
          )}
        </>
      ) : (
        <div className="mode-split">
          <div>
            <div className="section-head">
              <h2>{mode === "league" ? "Your leagues" : "Your games"}</h2>
              {!!mine?.length && <span className="count">{mine.length}</span>}
            </div>
            {mine === null ? (
              <Skeleton rows={2} height={76} />
            ) : mine.length === 0 ? (
              <EmptyState
                icon={<info.Icon size={20} strokeWidth={1.75} />}
                title={mode === "league" ? "No leagues yet" : "No games yet"}
                text={
                  mode === "league"
                    ? "Ask your gym or club for their invite code, or host a league of your own."
                    : "Enter a friend's code, open their invite link, or start a game yourself."
                }
              />
            ) : (
              <div className="stack">
                {mine.map((e) => (
                  <EventRow key={e.address} event={e} now={now} onOpen={openEvent} />
                ))}
              </div>
            )}
          </div>
          <aside>
            <InviteCodeBox
              session={session}
              title="Enter invite code"
              hint={mode === "league" ? "Your organizer has it." : "Ask the friend who started the game."}
              onJoined={(c) => openEvent(c.address)}
            />
          </aside>
        </div>
      )}

      <div className="mobile-create">{createButton}</div>
    </div>
  );
}
