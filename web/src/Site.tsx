import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ArrowRight, Menu, X } from "lucide-react";
import { FORMAT_INFO, FORMATS } from "./formats";
import { CapGraphic, HeroRules, Matchup, ModeGraphic, RuleStrip } from "./graphics";
import { RaceStory, Ticker, WaysSelector, WorkoutDemo } from "./interactive";
import { PHOTOS, type Picture } from "./media";
import { HeroVideo, Lane, Photo, ProductPreview, StepList } from "./sitekit";
import { flushSync } from "react-dom";
import { DemoBanner, prefersReducedMotion, Reveal, Wordmark } from "./ui";

/** The public website's pages. Each has its own address (?page=...), so links and the back button work. */
export type SitePage = "home" | "how" | "way" | "play";

const PAGES: { id: SitePage; label: string }[] = [
  { id: "how", label: "How it works" },
  { id: "way", label: "The Rival way" },
  { id: "play", label: "Ways to play" },
];

const TITLES: Record<SitePage, string> = {
  home: "Rival · Compete with friends",
  how: "How it works · Rival",
  way: "The Rival way · Rival",
  play: "Ways to play · Rival",
};

function readPage(): SitePage {
  const page = new URLSearchParams(window.location.search).get("page");
  return PAGES.some((p) => p.id === page) ? (page as SitePage) : "home";
}

type Nav = { go: (page: SitePage) => void; onLogin: () => void };

/** Everything a signed-out visitor sees. */
export default function Site({ onLogin }: { onLogin: () => void }) {
  const [page, setPage] = useState<SitePage>(readPage);
  const [menu, setMenu] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  const go = useCallback((next: SitePage) => {
    const url = window.location.pathname + (next === "home" ? "" : `?page=${next}`);
    window.history.pushState(null, "", url);
    const apply = () => {
      setPage(next);
      setMenu(false);
      window.scrollTo(0, 0);
    };
    // Where the browser supports it, cross-fade between pages instead of cutting.
    const doc = document as Document & { startViewTransition?: (run: () => void) => unknown };
    if (doc.startViewTransition && !prefersReducedMotion()) doc.startViewTransition(() => flushSync(apply));
    else apply();
  }, []);

  useEffect(() => {
    const onBack = () => setPage(readPage());
    // The header stays put at all times; it only gains a solid backing once the page has scrolled.
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("popstate", onBack);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("popstate", onBack);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  useEffect(() => {
    document.title = TITLES[page];
    return () => {
      document.title = TITLES.home;
    };
  }, [page]);

  // The mobile menu covers the page: lock scrolling behind it and close it on Escape.
  useEffect(() => {
    if (!menu) return;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  const nav: Nav = { go, onLogin };
  const link = (target: SitePage) => ({
    href: target === "home" ? "./" : `?page=${target}`,
    onClick: (e: React.MouseEvent) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey) return; // let people open a new tab
      e.preventDefault();
      go(target);
    },
  });

  return (
    <div className={`site${page === "home" ? " site-home" : ""}`}>
      <DemoBanner />
      <header className={`site-nav${scrolled || menu ? " solid" : ""}`}>
        <i className="scroll-progress" aria-hidden />
        <div className="site-nav-inner">
          <a {...link("home")} className="site-brand" aria-label="Rival home">
            <Wordmark />
          </a>
          <nav className="site-links" aria-label="Site">
            {PAGES.map((p) => (
              <a key={p.id} {...link(p.id)} className={page === p.id ? "on" : ""} aria-current={page === p.id ? "page" : undefined}>
                {p.label}
              </a>
            ))}
          </nav>
          <div className="site-nav-right">
            <button className="btn btn-primary btn-sm" onClick={onLogin}>
              Launch app
            </button>
            <button className="icon-btn site-menu-btn" onClick={() => setMenu(!menu)} aria-label={menu ? "Close menu" : "Open menu"} aria-expanded={menu}>
              {menu ? <X size={20} aria-hidden /> : <Menu size={20} aria-hidden />}
            </button>
          </div>
        </div>
      </header>

      {menu && (
        <div className="site-menu" role="dialog" aria-label="Menu">
          <nav>
            {[{ id: "home" as SitePage, label: "Home" }, ...PAGES].map((p, i) => (
              <a key={p.id} {...link(p.id)} className={page === p.id ? "on" : ""} style={{ "--i": i } as React.CSSProperties}>
                <b>0{i + 1}</b> {p.label}
              </a>
            ))}
          </nav>
          <button className="btn btn-primary btn-lg btn-block" onClick={onLogin}>
            Launch app <ArrowRight size={18} aria-hidden />
          </button>
        </div>
      )}

      <main key={page} className="site-main">
        {page === "how" ? <HowPage {...nav} /> : page === "way" ? <WayPage {...nav} /> : page === "play" ? <PlayPage {...nav} /> : <HomePage {...nav} />}
      </main>

      <footer className="site-foot">
        <div className="site-foot-top">
          <Wordmark />
          <nav aria-label="Footer">
            {PAGES.map((p) => (
              <a key={p.id} {...link(p.id)}>
                {p.label}
              </a>
            ))}
            <button onClick={onLogin}>Launch app</button>
            <a href="privacy/">Privacy</a>
            <a href="terms/">Terms</a>
          </nav>
        </div>
        <div className="site-foot-fine">
          <span>Demo version. Devnet USDC only, no real money.</span>
          <span>Footage: Mixkit</span>
        </div>
      </footer>
    </div>
  );
}

/* ---------- Home ---------- */

function HomePage({ go, onLogin }: Nav) {
  return (
    <>
      <section className="hero">
        <HeroVideo />
        <div className="hero-inner">
          <p className="kicker rise" style={{ "--i": 0 } as React.CSSProperties}>
            Fitness challenges with your friends
          </p>
          <h1 className="mega rise" style={{ "--i": 1 } as React.CSSProperties}>
            A little competition. <em className="serif">A lot of progress.</em>
          </h1>
          <div className="hero-foot rise" style={{ "--i": 2 } as React.CSSProperties}>
            <div className="hero-pitch">
              <p className="lede">
                Rival turns your workouts into a friendly contest. Start a challenge, bring your people, and climb the
                leaderboard together.
              </p>
              <div className="hero-actions">
                <button className="btn btn-primary btn-lg" onClick={onLogin}>
                  Start competing <ArrowRight size={18} aria-hidden />
                </button>
                <button className="btn btn-glass btn-lg" onClick={() => go("how")}>
                  How it works
                </button>
              </div>
            </div>
            <HeroRules />
          </div>
        </div>
      </section>

      <RuleStrip />

      {/* Blue-tinted dark: the product, playable */}
      <section className="env env-blue">
        <div className="wrap play-demo">
          <Reveal className="play-demo-copy">
            <Lane n="01" label="The competition" />
            <h2 className="display">
              Better because we're <em className="serif">competing.</em>
            </h2>
            <p className="lede">
              Every workout moves a leaderboard your friends are watching. Log one below and see what a couple of
              points does to the order.
            </p>
          </Reveal>
          <Reveal delay={100}>
            <WorkoutDemo />
          </Reveal>
        </div>
      </section>

      <Ticker />

      {/* Near-black: a week of racing, driven by the scroll */}
      <RaceStory>
        <Lane n="02" label="A week on Rival" />
      </RaceStory>

      {/* Charcoal: the four steps across the full width */}
      <section className="env env-charcoal">
        <div className="wrap steps-wide">
          <Reveal className="steps-wide-head">
            <Lane n="03" label="How it works" />
            <h2 className="display">
              Make progress. <em className="serif">Make it count.</em>
            </h2>
            <button className="text-link" onClick={() => go("how")}>
              The full rundown <ArrowRight size={16} aria-hidden />
            </button>
          </Reveal>
          <StepList />
        </div>
      </section>

      <section className="versus">
        <div className="wrap versus-inner">
          <Reveal className="versus-copy">
            <Lane n="04" label="The Rival way" />
            <blockquote className="display">
              Nobody trains harder than someone <em className="serif">one point behind.</em>
            </blockquote>
            <button className="text-link" onClick={() => go("way")}>
              Read why it works <ArrowRight size={16} aria-hidden />
            </button>
          </Reveal>
          <Matchup />
        </div>
      </section>

      {/* Green-tinted dark: choose a way to play */}
      <section className="env env-green">
        <div className="wrap ways">
          <Reveal>
            <Lane n="05" label="Ways to play" />
            <h2 className="display">
              Find your <em className="serif">rival.</em>
            </h2>
          </Reveal>
          <Reveal delay={100}>
            <WaysSelector onMore={() => go("play")} />
          </Reveal>
        </div>
      </section>

      <Finale onLogin={onLogin} />
    </>
  );
}

function Finale({ onLogin, children }: { onLogin: () => void; children?: ReactNode }) {
  return (
    <section className="bleed finale">
      <Photo photo={PHOTOS.summit} />
      <Reveal className="bleed-copy">
        <h2 className="mega">
          {children ?? (
            <>
              Earn your <em className="serif">edge.</em>
            </>
          )}
        </h2>
        <p className="lede">Your next challenge is one invite away.</p>
        <button className="btn btn-primary btn-lg" onClick={onLogin}>
          Start competing <ArrowRight size={18} aria-hidden />
        </button>
      </Reveal>
    </section>
  );
}

/** The top of an inner page: a large headline beside a photograph. */
function PageHero(props: { lane: string; label: string; title: ReactNode; lede: string; photo: Picture }) {
  return (
    <section className="wrap page-hero">
      <div className="page-hero-copy">
        <div className="rise" style={{ "--i": 0 } as React.CSSProperties}>
          <Lane n={props.lane} label={props.label} />
        </div>
        <h1 className="display rise" style={{ "--i": 1 } as React.CSSProperties}>
          {props.title}
        </h1>
        <p className="lede rise" style={{ "--i": 2 } as React.CSSProperties}>
          {props.lede}
        </p>
      </div>
      <div className="rise" style={{ "--i": 2 } as React.CSSProperties}>
        <Photo photo={props.photo} eager sizes="(min-width: 960px) 50vw, 100vw" />
      </div>
    </section>
  );
}

/* ---------- How it works ---------- */

function HowPage({ go, onLogin }: Nav) {
  return (
    <>
      <PageHero
        lane="01"
        label="How it works"
        title={
          <>
            Show up. <em className="serif">Keep score.</em>
          </>
        }
        lede="A Rival challenge takes a minute to set up and runs itself from there. Here is the whole thing, start to finish."
        photo={PHOTOS.tennisFeet}
      />

      <section className="wrap chapters-long">
        <Reveal className="chapter">
          <div className="chapter-copy">
            <span className="chapter-n">01</span>
            <h2 className="headline">Start a challenge</h2>
            <p className="lede">
              Give it a name, choose what each player puts in, and decide how long it runs. Then choose how the prize
              pool is shared: winner takes all, a podium, a shared goal, or team against team.
            </p>
          </div>
          <div className="chapter-visual" aria-hidden>
            <div className="demo-panel">
              <small>Entry fee, each</small>
              <div className="mini-chips">
                <span>$1</span>
                <span>$2</span>
                <span className="on">$5</span>
              </div>
              <small>Runs for</small>
              <div className="mini-chips">
                <span>1 day</span>
                <span>3 days</span>
                <span className="on">1 week</span>
              </div>
            </div>
          </div>
        </Reveal>

        <Reveal className="chapter flip">
          <div className="chapter-copy">
            <span className="chapter-n">02</span>
            <h2 className="headline">Bring your people</h2>
            <p className="lede">
              Private games and leagues are invite only: share a six-letter code or a link. Public events are listed
              for anyone to join. Every event holds up to eight players.
            </p>
          </div>
          <div className="chapter-visual" aria-hidden>
            <div className="demo-panel center">
              <small>Invite code</small>
              <div className="demo-code">K7M2QX</div>
            </div>
          </div>
        </Reveal>

        <Reveal className="chapter">
          <div className="chapter-copy">
            <span className="chapter-n">03</span>
            <h2 className="headline">Move, and earn points</h2>
            <p className="lede">
              Scoring rewards consistency. The daily cap means nobody can win the week in a single afternoon, so the
              person who keeps showing up is the one to beat.
            </p>
          </div>
          <div className="chapter-visual" aria-hidden>
            <ul className="demo-rules">
              <li>
                <b>+1</b> 20 active minutes in a day
              </li>
              <li>
                <b>+1</b> every 5 km
              </li>
              <li>
                <b>3</b> points a day, at most
              </li>
            </ul>
          </div>
        </Reveal>

        <Reveal className="chapter flip">
          <div className="chapter-copy">
            <span className="chapter-n">04</span>
            <h2 className="headline">Climb, then collect</h2>
            <p className="lede">
              The leaderboard updates as workouts come in. When time runs out, the prize pool is paid out automatically
              by the rules you chose. If fewer than two people joined, everyone gets their entry back.
            </p>
          </div>
          <div className="chapter-visual">
            <ProductPreview />
          </div>
        </Reveal>
      </section>

      <section className="wrap principles">
        <Reveal>
          <Lane n="02" label="Fair by design" />
          <h2 className="headline">
            The fine print, <em className="serif">in plain words.</em>
          </h2>
        </Reveal>
        <div className="principles-grid">
          <Reveal>
            <h3>Your workouts stay yours</h3>
            <p>Other players see your points and nothing else. Your activities are only ever visible to you.</p>
          </Reveal>
          <Reveal delay={80}>
            <h3>Nobody holds the pool</h3>
            <p>Entry fees are locked until the event ends, then paid out by the rules. No person can move them early.</p>
          </Reveal>
          <Reveal delay={160}>
            <h3>It's a demo</h3>
            <p>Rival currently runs on test money: devnet USDC, with no real value. Nothing here costs you anything.</p>
          </Reveal>
        </div>
        <Reveal>
          <button className="text-link" onClick={() => go("play")}>
            See the ways to play <ArrowRight size={16} aria-hidden />
          </button>
        </Reveal>
      </section>

      <Finale onLogin={onLogin}>
        Ready when <em className="serif">you are.</em>
      </Finale>
    </>
  );
}

/* ---------- The Rival way ---------- */

function WayPage({ go, onLogin }: Nav) {
  return (
    <>
      <section className="wrap essay-head">
        <div className="rise" style={{ "--i": 0 } as React.CSSProperties}>
          <Lane n="01" label="The Rival way" />
        </div>
        <h1 className="mega rise" style={{ "--i": 1 } as React.CSSProperties}>
          Built to compete. <em className="serif">Made to grow.</em>
        </h1>
      </section>

      <section className="bleed bleed-short rise" style={{ "--i": 2 } as React.CSSProperties}>
        <Photo photo={PHOTOS.wraps} eager />
      </section>

      <section className="wrap essay">
        <Reveal className="essay-lead">
          <p>
            Most fitness plans fail for a simple reason: nobody notices when you skip a day. Rival fixes that with the
            oldest motivator there is. <em className="serif">Someone to beat.</em>
          </p>
        </Reveal>

        <div className="tenets">
          <Reveal className="tenet">
            <span className="chapter-n">01</span>
            <h2>Accountability you can see</h2>
            <p>
              A leaderboard is a promise made in public. When your friends can watch it move, a rest day becomes a
              choice instead of a default.
            </p>
          </Reveal>
          <Reveal className="tenet" delay={80}>
            <span className="chapter-n">02</span>
            <h2>Consistency over heroics</h2>
            <p>
              Points are capped each day. You can't buy the week with one enormous Sunday, so the habit wins, not the
              highlight.
            </p>
          </Reveal>
          <Reveal className="tenet" delay={160}>
            <span className="chapter-n">03</span>
            <h2>Stakes as a nudge</h2>
            <p>
              A few dollars in a shared pool is enough to make a Tuesday run matter. The money is the spark. The
              progress is the point.
            </p>
          </Reveal>
        </div>
      </section>

      <section className="wrap cap-section">
        <CapGraphic />
      </section>

      <section className="wrap essay">
        <Reveal className="pull">
          <blockquote className="display">
            Not a bet on exercise. <em className="serif">A reason to show up.</em>
          </blockquote>
          <p className="lede">
            Rival is friendly by design. Small entry fees, groups of people who know each other, and a score that only
            ever measures effort. Everybody who plays ends the week fitter than they started it.
          </p>
          <button className="text-link" onClick={() => go("how")}>
            See how a challenge works <ArrowRight size={16} aria-hidden />
          </button>
        </Reveal>
      </section>

      <Finale onLogin={onLogin}>
        Progress is better <em className="serif">together.</em>
      </Finale>
    </>
  );
}

/* ---------- Ways to play ---------- */

function PlayPage({ onLogin }: Nav) {
  const modes = [
    {
      name: "Private play",
      accent: "play.",
      title: "Private",
      text: "The classic. Start a game, send the code to the group chat, and settle who's actually been training. Invite only and never listed anywhere.",
      points: ["Invite by code or link", "Up to eight players", "You set the fee and the length"],
      mode: "private" as const,
    },
    {
      name: "Public events",
      accent: "events.",
      title: "Public",
      text: "Open to anyone on Rival. Join a community challenge that's about to start, or create one and let the field come to you.",
      points: ["Listed for everyone", "Join in one tap", "Bigger fields, bigger prize pools"],
      mode: "public" as const,
    },
    {
      name: "Leagues",
      accent: "play.",
      title: "League",
      text: "For gyms, clubs and tournaments. An organizer hosts and invites members, and can score by fitness or by the league's own stat sheet.",
      points: ["Hosted by an organizer", "Members join with a code", "Fitness or league-stat scoring"],
      mode: "league" as const,
    },
  ];
  return (
    <>
      <section className="wrap essay-head">
        <div className="rise" style={{ "--i": 0 } as React.CSSProperties}>
          <Lane n="01" label="Ways to play" />
        </div>
        <h1 className="mega rise" style={{ "--i": 1 } as React.CSSProperties}>
          Pick your <em className="serif">arena.</em>
        </h1>
        <p className="lede rise" style={{ "--i": 2 } as React.CSSProperties}>
          Three kinds of competition, four ways to share the prize pool, and one optional side game.
        </p>
      </section>

      <section className="wrap chapters-long">
        {modes.map((mode, i) => (
          <Reveal key={mode.name} className={`chapter${i % 2 ? " flip" : ""}`}>
            <div className="chapter-copy">
              <span className="chapter-n">0{i + 1}</span>
              <h2 className="headline">
                {mode.title} <em className="serif">{mode.accent}</em>
              </h2>
              <p className="lede">{mode.text}</p>
              <ul className="tick-list">
                {mode.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </div>
            <div className="chapter-visual">
              <ModeGraphic mode={mode.mode} />
            </div>
          </Reveal>
        ))}
      </section>

      <section className="wrap principles">
        <Reveal>
          <Lane n="02" label="Sharing the pool" />
          <h2 className="headline">
            Four ways to <em className="serif">win.</em>
          </h2>
        </Reveal>
        <div className="principles-grid four">
          {FORMATS.map((format, i) => (
            <Reveal key={format} delay={i * 70}>
              <h3>{FORMAT_INFO[format].title}</h3>
              <p>
                {FORMAT_INFO[format].line} <span>{FORMAT_INFO[format].example}</span>
              </p>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="wrap split">
        <Reveal className="split-copy">
          <Lane n="03" label="The side game" />
          <h2 className="headline">
            Prediction <em className="serif">rounds.</em>
          </h2>
          <p className="lede">
            Switch them on when you create an event. Each round, everyone calls the result of a real sports game. A
            right call earns bonus points, and the bolder the call, the more it's worth.
          </p>
        </Reveal>
        <Reveal className="split-visual" delay={120}>
          <div className="demo-panel pick" aria-hidden>
            <small>NBA · sample round</small>
            <div className="demo-pick-title">Home vs Away</div>
            <div className="demo-pick">
              <div className="on">
                <em>Your pick</em>
                <span>Home</span>
                <b>1.6 pts</b>
              </div>
              <div>
                <em>&nbsp;</em>
                <span>Away</span>
                <b>2.7 pts</b>
              </div>
            </div>
          </div>
        </Reveal>
      </section>

      <Finale onLogin={onLogin}>
        Find your <em className="serif">rival.</em>
      </Finale>
    </>
  );
}
