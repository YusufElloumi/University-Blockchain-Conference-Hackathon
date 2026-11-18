import { ShieldCheck, Target, Wallet } from "lucide-react";
import type { Session } from "./App";
import { Steps } from "./Landing";
import { MODE_INFO, MODES } from "./modes";
import { Eyebrow } from "./ui";

/** A short guide for signed-in players. It explains what already exists; it adds no features. */
export default function HowItWorks({ session }: { session: Session }) {
  const { config, go } = session;
  return (
    <div className="help">
      <header className="page-head">
        <div>
          <Eyebrow>How Rival works</Eyebrow>
          <h1 className="headline">
            Win the <em className="serif">week.</em>
          </h1>
          <p className="lede">Everything you need to know, in about a minute.</p>
        </div>
      </header>

      <Steps />

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
              <span className="mode-card-title">{title}</span>
              <span className="mode-card-line">{line}</span>
            </button>
          );
        })}
      </div>

      <div className="section-head">
        <h2>Good to know</h2>
      </div>
      <div className="facts">
        <div className="fact">
          <span className="icon-tile">
            <Target size={18} strokeWidth={1.75} aria-hidden />
          </span>
          <div>
            <h3>Prediction rounds</h3>
            <p>
              Some events add a side game: each round you call the result of a real sports game. A right call earns
              bonus points, up to {config.max_pick_points} a round, and the bolder the call the more it earns.
            </p>
          </div>
        </div>
        <div className="fact">
          <span className="icon-tile">
            <ShieldCheck size={18} strokeWidth={1.75} aria-hidden />
          </span>
          <div>
            <h3>Your workouts stay yours</h3>
            <p>Other players see your points and nothing else. Your activities are only ever visible to you.</p>
          </div>
        </div>
        <div className="fact">
          <span className="icon-tile">
            <Wallet size={18} strokeWidth={1.75} aria-hidden />
          </span>
          <div>
            <h3>The prize pool</h3>
            <p>
              Entry fees are held in the pool until the event ends, then paid to first place automatically. If fewer
              than two people join, everyone gets their entry back. This is a demo: devnet USDC only, no real money.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
