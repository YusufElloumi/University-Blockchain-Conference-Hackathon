import type { ReactNode } from "react";
import { CircleHelp, House, LogOut, type LucideIcon } from "lucide-react";
import type { Session } from "./App";
import { money } from "./format";
import { MODE_INFO, MODES, type Mode } from "./modes";
import { Avatar, DemoBanner, Wordmark } from "./ui";

export type Section = Mode | "home" | "help" | null;

/** The signed-in frame: a sidebar on wide screens, a top bar and bottom navigation on phones. */
export default function Shell(props: {
  session: Session;
  balance: number | null;
  section: Section; // which navigation item is lit
  routeKey: string; // changes when the screen changes, to replay the page transition
  onWithdraw: () => void;
  onSignOut: () => void;
  children: ReactNode;
}) {
  const { session, balance, section, routeKey } = props;
  const { go } = session;
  return (
    <div className="app">
      <DemoBanner />

      <aside className="sidebar">
        <button className="brand-btn" onClick={() => go({ view: "home" })} aria-label="Rival home">
          <Wordmark />
        </button>
        <nav className="side-nav" aria-label="Main">
          <NavItem on={section === "home"} onClick={() => go({ view: "home" })} Icon={House} label="Home" />
          <div className="side-nav-label">Compete</div>
          {MODES.map((mode) => (
            <NavItem
              key={mode}
              on={section === mode}
              onClick={() => go({ view: "mode", mode })}
              Icon={MODE_INFO[mode].Icon}
              label={MODE_INFO[mode].nav}
            />
          ))}
          <div className="side-nav-label">Learn</div>
          <NavItem on={section === "help"} onClick={() => go({ view: "help" })} Icon={CircleHelp} label="How it works" />
        </nav>
        <div className="side-foot">
          <div className="side-balance" title="Your balance (devnet USDC)">
            <div>
              <div className="eyebrow">Balance</div>
              <strong>{balance === null ? "..." : money(balance)}</strong>
            </div>
            <button className="btn btn-quiet btn-sm" onClick={() => props.onWithdraw()}>
              Withdraw
            </button>
          </div>
          <div className="side-user">
            <Avatar name={session.me.name} />
            <div className="side-user-text">
              <b>{session.me.name}</b>
              {session.me.email && <span>{session.me.email}</span>}
            </div>
            <button className="icon-btn" onClick={props.onSignOut} aria-label="Sign out" title="Sign out">
              <LogOut size={16} aria-hidden />
            </button>
          </div>
        </div>
      </aside>

      <header className="topbar">
        <button className="brand-btn" onClick={() => go({ view: "home" })} aria-label="Rival home">
          <Wordmark />
        </button>
        <div className="topbar-right">
          <button className="btn btn-quiet btn-sm" onClick={() => props.onWithdraw()}>
            Withdraw
          </button>
          <div className="balance-chip" title="Your balance (devnet USDC)">
            {balance === null ? "..." : money(balance)}
          </div>
        </div>
      </header>

      <main className="main">
        <div className="main-inner" key={routeKey}>
          {props.children}
        </div>
      </main>

      <nav className="tabbar" aria-label="Main">
        <NavItem on={section === "home"} onClick={() => go({ view: "home" })} Icon={House} label="Home" />
        {MODES.map((mode) => (
          <NavItem
            key={mode}
            on={section === mode}
            onClick={() => go({ view: "mode", mode })}
            Icon={MODE_INFO[mode].Icon}
            label={MODE_INFO[mode].nav}
          />
        ))}
      </nav>
    </div>
  );
}

function NavItem(props: { on: boolean; onClick: () => void; Icon: LucideIcon; label: string }) {
  return (
    <button className={`nav-item${props.on ? " on" : ""}`} onClick={props.onClick} aria-current={props.on ? "page" : undefined}>
      <props.Icon size={18} strokeWidth={props.on ? 2 : 1.75} aria-hidden />
      <span>{props.label}</span>
    </button>
  );
}
