import { useEffect, useState } from "react";
import { ArrowRight, Flame, Footprints, ShieldCheck, Target, Timer, Trophy, Users } from "lucide-react";
import type { PlayerRow } from "./api";
import Leaderboard from "./Leaderboard";
import { MODE_INFO, type Mode } from "./modes";
import { DemoBanner, prefersReducedMotion, Reveal, Wordmark } from "./ui";

/** The public website: what Rival is, shown to anyone who is not signed in. */
export default function Landing({ onLogin }: { onLogin: () => void }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const jump = (id: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    document.getElementById(id)?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  };

  return (
    <div className="site">
      <DemoBanner />
      <header className={`site-nav${scrolled ? " scrolled" : ""}`}>
        <div className="site-nav-inner">
          <a href="#top" onClick={jump("top")} className="site-brand" aria-label="Rival, back to top">
            <Wordmark />
          </a>
          <nav className="site-links" aria-label="Sections">
            <a href="#how" onClick={jump("how")}>
              How it works
            </a>
            <a href="#why" onClick={jump("why")}>
              Why Rival
            </a>
            <a href="#play" onClick={jump("play")}>
              Ways to play
            </a>
          </nav>
          <button className="btn btn-quiet btn-sm" onClick={onLogin}>
            Sign in
          </button>
        </div>
      </header>

      <main id="top">
        {/* ---------- Hero ---------- */}
        <section className="hero">
          <div className="hero-glow" aria-hidden />
          <div className="hero-copy">
            <div className="pill rise" style={{ "--i": 0 } as React.CSSProperties}>
              <span className="pill-dot" /> Social fitness competitions
            </div>
            <h1 className="display rise" style={{ "--i": 1 } as React.CSSProperties}>
              Compete with <em className="serif">friends.</em>
            </h1>
            <p className="lede rise" style={{ "--i": 2 } as React.CSSProperties}>
              Rival turns your workouts into friendly competition. Start a challenge, put a little on the line, and
              climb the leaderboard together.
            </p>
            <div className="hero-actions rise" style={{ "--i": 3 } as React.CSSProperties}>
              <button className="btn btn-primary btn-lg" onClick={onLogin}>
                Get started <ArrowRight size={18} aria-hidden />
              </button>
              <a className="btn btn-quiet btn-lg" href="#how" onClick={jump("how")}>
                How it works
              </a>
            </div>
            <p className="hero-fine rise" style={{ "--i": 4 } as React.CSSProperties}>
              Sign in with your email. No app to install, no passwords.
            </p>
          </div>
          <div className="hero-visual rise" style={{ "--i": 3 } as React.CSSProperties}>
            <HeroPreview />
          </div>
        </section>

        {/* ---------- How it works ---------- */}
        <section className="band" id="how">
          <Reveal className="band-head">
            <div className="eyebrow">How it works</div>
            <h2 className="headline">
              Make progress. <em className="serif">Make it count.</em>
            </h2>
          </Reveal>
          <Steps />
        </section>

        {/* ---------- Why ---------- */}
        <section className="band band-split" id="why">
          <Reveal className="band-head">
            <div className="eyebrow">Why Rival</div>
            <h2 className="headline">
              Progress made <em className="serif">social.</em>
            </h2>
            <p className="lede">
              It's easier to show up when your friends are watching the same leaderboard, and a lot more fun when one
              of them is trying to pass you.
            </p>
          </Reveal>
          <div className="why-list">
            {[
              {
                Icon: Users,
                title: "Accountability, built in",
                text: "Your group sees the leaderboard move every time you do.",
              },
              {
                Icon: Flame,
                title: "Stakes that motivate",
                text: "A small entry fee makes every workout matter a little more. It's the nudge, not the point.",
              },
              {
                Icon: ShieldCheck,
                title: "Private by design",
                text: "Friends see your points. Never your routes, times or activities.",
              },
            ].map(({ Icon, title, text }, i) => (
              <Reveal key={title} className="why-item" delay={i * 90}>
                <span className="icon-tile">
                  <Icon size={18} strokeWidth={1.75} aria-hidden />
                </span>
                <div>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* ---------- Ways to play ---------- */}
        <section className="band" id="play">
          <Reveal className="band-head">
            <div className="eyebrow">Ways to play</div>
            <h2 className="headline">
              Find your <em className="serif">rival.</em>
            </h2>
          </Reveal>
          <div className="play-grid">
            {(["private", "public", "league"] as Mode[]).map((mode, i) => {
              const { Icon, title, line } = MODE_INFO[mode];
              return (
                <Reveal key={mode} className="play-card" delay={i * 90}>
                  <span className="icon-tile">
                    <Icon size={18} strokeWidth={1.75} aria-hidden />
                  </span>
                  <h3>{title}</h3>
                  <p>{line}</p>
                </Reveal>
              );
            })}
            <Reveal className="play-card play-card-wide" delay={120}>
              <div>
                <span className="icon-tile">
                  <Target size={18} strokeWidth={1.75} aria-hidden />
                </span>
                <h3>Prediction rounds</h3>
                <p>
                  An optional side game. Each round, call the result of a real sports game for bonus points. The bolder
                  the call, the more it earns.
                </p>
              </div>
              <div className="pick-demo" aria-hidden>
                <div className="pick-demo-side on">
                  <small>Your pick</small>
                  <span>Home</span>
                  <b>1.6 pts</b>
                </div>
                <div className="pick-demo-side">
                  <small>&nbsp;</small>
                  <span>Away</span>
                  <b>2.7 pts</b>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ---------- Final call ---------- */}
        <section className="band finale">
          <Reveal>
            <h2 className="display">
              Earn your <em className="serif">edge.</em>
            </h2>
            <p className="lede">Your next challenge is one invite away.</p>
            <button className="btn btn-primary btn-lg" onClick={onLogin}>
              Get started <ArrowRight size={18} aria-hidden />
            </button>
          </Reveal>
        </section>
      </main>

      <footer className="site-foot">
        <Wordmark />
        <span>Demo version. Devnet USDC only, no real money.</span>
      </footer>
    </div>
  );
}

/** The three steps, with the real scoring rules. Also shown on the signed-in "How it works" page. */
export function Steps() {
  return (
    <ol className="steps">
      <Reveal as="li" className="step">
        <div className="step-art">
          <div className="mini-chips">
            <span>$1</span>
            <span className="on">$5</span>
            <span>1 week</span>
          </div>
          <div className="mini-invite">
            <Users size={14} aria-hidden /> Invite code <b>K7M2QX</b>
          </div>
        </div>
        <span className="step-num">01</span>
        <h3>Start a challenge</h3>
        <p>Pick an entry fee and a length, then invite your people. Or join one that's already open.</p>
      </Reveal>
      <Reveal as="li" className="step" delay={90}>
        <div className="step-art">
          <ul className="mini-rules">
            <li>
              <Timer size={14} aria-hidden /> 20 active minutes <b>+1</b>
            </li>
            <li>
              <Footprints size={14} aria-hidden /> Every 5 km <b>+1</b>
            </li>
          </ul>
        </div>
        <span className="step-num">02</span>
        <h3>Move to earn points</h3>
        <p>Up to 3 points a day, so showing up all week beats one big effort.</p>
      </Reveal>
      <Reveal as="li" className="step" delay={180}>
        <div className="step-art">
          <div className="mini-podium">
            <i style={{ height: "58%" }} />
            <i className="first" style={{ height: "100%" }}>
              <Trophy size={16} aria-hidden />
            </i>
            <i style={{ height: "40%" }} />
          </div>
        </div>
        <span className="step-num">03</span>
        <h3>Win the week</h3>
        <p>A live leaderboard keeps score. When time's up, first place takes the prize pool. Ties split it.</p>
      </Reveal>
    </ol>
  );
}

/* ---------- The animated product preview in the hero (sample data) ---------- */

const SAMPLE: { name: string; you?: boolean; ticks: boolean[]; points: number[] }[] = [
  { name: "Maya", ticks: [true, true, false, true, true, true, true], points: [11, 11, 11] },
  { name: "Jordan", ticks: [true, false, true, true, true, false, true], points: [9, 9, 10] },
  { name: "You", you: true, ticks: [true, true, true, false, true, true, true], points: [8, 10, 12] },
  { name: "Sam", ticks: [false, true, true, false, true, false, true], points: [6, 6, 7] },
  { name: "Priya", ticks: [true, false, false, true, false, true, false], points: [4, 5, 5] },
];

function HeroPreview() {
  const still = prefersReducedMotion();
  const [frame, setFrame] = useState(still ? 2 : 0);
  useEffect(() => {
    if (still) return;
    // Three scores, then a pause on the last one before starting over.
    const timer = setInterval(() => setFrame((f) => (f + 1) % 4), 2600);
    return () => clearInterval(timer);
  }, [still]);
  const at = Math.min(frame, 2);

  const players: PlayerRow[] = SAMPLE.map((p) => ({ ...p, score: p.points[at] }))
    .sort((a, b) => b.score - a.score)
    .map((p, i) => ({
      rank: i + 1,
      name: p.name,
      points: p.score,
      base_points: p.score,
      pick_points: 0,
      team: null,
      projected_share: 0,
      goal_progress: null,
      ticks: p.ticks,
      is_you: !!p.you,
    }));

  return (
    <div className="preview" aria-label="A preview of a Rival challenge, with sample data">
      <div className="preview-card">
        <div className="preview-top">
          <div>
            <div className="eyebrow">Private game</div>
            <div className="preview-title">Sunday Run Club</div>
          </div>
          <span className="status-pill live">
            <span className="live-dot" /> Live
          </span>
        </div>
        <div className="preview-stats">
          <div>
            <small>Prize pool</small>
            <b className="accent">$25.00</b>
          </div>
          <div>
            <small>Players</small>
            <b>5</b>
          </div>
          <div>
            <small>Time left</small>
            <b>2d 14h</b>
          </div>
        </div>
        <Leaderboard players={players} form picks={false} compact />
      </div>
      <div className={`preview-toast${at > 0 ? " show" : ""}`} key={at}>
        <span className="icon-tile">
          <Footprints size={16} aria-hidden />
        </span>
        <span>
          <b>{at === 2 ? "Evening run · 5 km" : "Morning run · 5 km"}</b>
          <small>You earned +2 points</small>
        </span>
      </div>
      <div className="preview-caption">Preview with sample data</div>
    </div>
  );
}
