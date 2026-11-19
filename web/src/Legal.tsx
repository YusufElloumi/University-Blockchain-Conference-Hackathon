// The public legal pages: /privacy and /terms. They are separate small pages (no sign-in code is
// loaded), share the public site's header and footer, and describe what the app does today.
// Anything not built yet is marked "Planned". Keep these in step with the API (api/db.py, api/main.py).

import { useEffect, useState, type ReactNode } from "react";
import { ArrowRight, Menu, X } from "lucide-react";
import { DemoBanner, Wordmark } from "./ui";

export type LegalDoc = "privacy" | "terms";

const UPDATED = "19 November 2026";
const CONTACT = "shaanbhasin64@gmail.com";

// Addresses are relative so the pages work at /privacy, /privacy/ and under any folder.
const SITE_LINKS = [
  { href: "../?page=how", label: "How it works" },
  { href: "../?page=way", label: "The Rival way" },
  { href: "../?page=play", label: "Ways to play" },
];
const LEGAL_LINKS: { id: LegalDoc; href: string; label: string }[] = [
  { id: "privacy", href: "../privacy/", label: "Privacy" },
  { id: "terms", href: "../terms/", label: "Terms" },
];

/** Marks whether a section describes something that exists today or something still planned. */
function Status({ kind }: { kind: "now" | "planned" }) {
  return <span className={`legal-status ${kind}`}>{kind === "now" ? "In place today" : "Planned · not built yet"}</span>;
}

function Section(props: { id: string; n: number; title: string; status?: "now" | "planned"; children: ReactNode }) {
  return (
    <section id={props.id} className="legal-section">
      <div className="legal-section-head">
        <b>{String(props.n).padStart(2, "0")}</b>
        <h2>{props.title}</h2>
        {props.status && <Status kind={props.status} />}
      </div>
      {props.children}
    </section>
  );
}

type Doc = { title: ReactNode; plain: string; lede: string; sections: { id: string; title: string; status?: "now" | "planned"; body: ReactNode }[] };

const PRIVACY: Doc = {
  title: (
    <>
      Privacy <em className="serif">policy.</em>
    </>
  ),
  plain: "Privacy policy",
  lede:
    "Rival is a hackathon prototype that turns workouts into friendly competitions on the Solana devnet test network. This page explains what we collect today, what a planned Oura connection would add, who can see what, and what stays private.",
  sections: [
    {
      id: "summary",
      title: "The short version",
      body: (
        <ul>
          <li>Other players see your points, never your workout details.</li>
          <li>Workout and health data never goes on the blockchain and is never sent to any AI service.</li>
          <li>The blockchain holds only wallet addresses, test-money movements, winners and a scrambled fingerprint (hash) of the final scores. It is public and permanent.</li>
          <li>Rival does not connect to Oura yet and does not collect heart rate today. Both are planned and described below.</li>
          <li>Everything uses devnet test funds with no real-world value.</li>
        </ul>
      ),
    },
    {
      id: "collect",
      title: "What we collect today",
      status: "now",
      body: (
        <>
          <h3>Your account</h3>
          <p>
            You sign in with your email through Privy, our login provider. We store your email address, Privy's ID for you, the player
            name you choose, and the address of the wallet Privy creates for you. We also record when we sent your wallet test funds
            or a small amount of devnet SOL to cover network fees.
          </p>
          <h3>Workouts you log in the app</h3>
          <p>
            In this demo version, workouts are added inside Rival, either from the demo workout generator or typed in by hand. For each
            one we store the type, start time, duration in minutes, distance in kilometres, a device label and how it was added. No
            fitness device or fitness app is connected yet.
          </p>
          <h3>Points and competition records</h3>
          <p>
            From your workouts we work out points for each day of a challenge, whether the day counted as active, and which workouts
            counted. We also keep the challenges you create or join, invite codes you redeem, the time you agreed to share your points
            with that group, the team you picked, and any prediction-round picks.
          </p>
          <h3>League stat sheets</h3>
          <p>League organizers can upload a stat sheet. It holds player names, jersey numbers, teams, goals, assists and game dates.</p>
          <h3>What we do not collect</h3>
          <p>
            Today we do not collect heart rate, sleep, GPS routes or location, and we receive no data from Oura, Strava or any other
            fitness service. We use no analytics, advertising or tracking tools.
          </p>
        </>
      ),
    },
    {
      id: "oura",
      title: "Oura integration",
      status: "planned",
      body: (
        <>
          <p>
            We plan to let you connect an Oura account so your real workouts count without typing them in. None of this is built yet.
            When it is, it will work as follows, and this page will be updated before it goes live.
          </p>
          <ul>
            <li>
              <b>Your choice.</b> Nothing is read until you press connect and approve access on Oura's own screen. You can disconnect
              at any time.
            </li>
            <li>
              <b>What we would read.</b> Your workouts (type, start and end time, duration, distance where available) and heart-rate
              readings from the time of those workouts. We would not request sleep, readiness or other data we do not use.
            </li>
            <li>
              <b>Why.</b> To turn workouts into points, and to check that a workout was recorded by a device and looks real, for
              example that heart rate rose during it. That is the only use.
            </li>
            <li>
              <b>Who sees it.</b> Only you see your Oura workouts and heart-rate data. Other players see the points they produce.
            </li>
            <li>
              <b>Storage.</b> The keys Oura gives us to read your data would be stored encrypted on our server, never in your browser
              and never on the blockchain.
            </li>
            <li>
              <b>How long.</b> Raw Oura data would be kept only as long as needed to score and check an active challenge, under a fixed
              time limit that we will publish here before launch.
            </li>
            <li>
              <b>Disconnecting.</b> Disconnecting would cancel our access and delete the Oura data we hold for you.
            </li>
            <li>
              <b>Never.</b> We would not sell Oura data, use it for advertising, send it to any AI or language-model service, or put it
              on the blockchain.
            </li>
          </ul>
        </>
      ),
    },
    {
      id: "use",
      title: "How we use your information",
      status: "now",
      body: (
        <ul>
          <li>To run your account and wallet, and send devnet test funds.</li>
          <li>To score challenges, build leaderboards and pay out devnet test-money prize pools through our Solana program.</li>
          <li>
            To check workouts. Each workout is marked as passed checks, flagged (typed in by hand, so it counts but nobody can vouch for
            it) or rejected (for example, outside the challenge dates), with the reason shown to you.
          </li>
          <li>To keep private challenges private and to prevent abuse.</li>
        </ul>
      ),
    },
    {
      id: "visible",
      title: "Who can see what",
      status: "now",
      body: (
        <>
          <ul>
            <li>
              <b>Only you:</b> your email, your workouts and their details, and your account balance.
            </li>
            <li>
              <b>Players in the same challenge:</b> your player name, your points, which days counted, and updates like "joined" or
              "won" in the challenge feed. You agree to this for each challenge when you join it.
            </li>
            <li>
              <b>League organizers:</b> the stat sheets they upload and which player is matched to which sheet name.
            </li>
            <li>
              <b>Rival admins:</b> the Rival team members on our admin list can open any challenge, including private and league
              ones, and can end it early so it pays out by the current standings. We use this to run demos and fix stuck
              challenges. An admin who is not playing sees the challenge's details and feed, not its leaderboard, and never sees your
              workouts.
            </li>
            <li>
              <b>Anyone:</b> information on the public blockchain (next section) and the details of public events listed for anyone
              to join.
            </li>
          </ul>
          <p>Private and league challenges are only shown to their creator, players and people who entered the invite code.</p>
        </>
      ),
    },
    {
      id: "onchain",
      title: "Private data and public onchain receipts",
      status: "now",
      body: (
        <>
          <p>
            Prize pools are held by a program on the Solana devnet, a public test blockchain. Anything written there can be read by
            anyone and cannot be changed or deleted, by us or anyone else.
          </p>
          <h3>Public, on the blockchain</h3>
          <ul>
            <li>Wallet addresses, entry deposits and payouts, all in devnet test money.</li>
            <li>Each challenge's settings (entry fee, start and end times) and its winners' wallet addresses and payout shares.</li>
            <li>
              A salted SHA-256 hash of the final score sheet: a fingerprint that proves the scores were not changed later but reveals
              nothing about them.
            </li>
          </ul>
          <h3>Private, never on the blockchain</h3>
          <ul>
            <li>Workouts, distances, durations, heart rate or any other health or fitness data.</li>
            <li>Your email address.</li>
          </ul>
          <p>
            When a challenge ends, our server also signs a result receipt (shown in the app as Proof of Sweat). It holds wallet
            addresses, payout shares, hashes, the scoring-rules version and times, but no workout data. It is stored on our server and
            players of that challenge can download it.
          </p>
          <p>
            Your wallet address is not shown on screen, but because it appears on the blockchain, anyone who links it to you could see
            your devnet activity.
          </p>
        </>
      ),
    },
    {
      id: "storage",
      title: "Storage and security",
      status: "now",
      body: (
        <>
          <p>
            The deployed app is served over HTTPS. Our server runs on Render and stores data in a Postgres database hosted by Neon. The
            keys our server uses on the blockchain are kept as server secrets, not in the code. The server checks your login on every
            request and only returns data you are allowed to see.
          </p>
          <p>
            Rival is a prototype. We do not yet add our own encryption to workout records in the database, beyond whatever protection
            our hosting providers apply, and the app has not had an independent security review. Please don't enter anything you would
            not want stored in a prototype.
          </p>
        </>
      ),
    },
    {
      id: "retention",
      title: "Keeping and deleting data",
      status: "now",
      body: (
        <>
          <ul>
            <li>
              <b>No automatic deletion yet.</b> We have not set a retention schedule. Data is kept while the prototype runs. The
              prototype database may be reset or deleted after the hackathon.
            </li>
            <li>
              <b>Deleting your workouts.</b> Use <b>Delete my workouts</b> on your home screen in the app. It deletes every workout
              you have logged and your points in challenges that have not finished. You stay in those challenges with zero points.
              It cannot be undone.
            </li>
            <li>
              <b>Finished challenges.</b> Final score sheets and result receipts are kept so results stay checkable.
            </li>
            <li>
              <b>Deleting your account.</b> There is no in-app account deletion yet. Ask us and we will remove your account record by
              hand. Privy keeps its own login records under its own privacy policy.
            </li>
            <li>
              <b>The blockchain.</b> Onchain records cannot be deleted by anyone.
            </li>
          </ul>
          <p>Before an Oura connection launches, we plan to add a disconnect button, automatic time limits for raw data, and account deletion in the app.</p>
        </>
      ),
    },
    {
      id: "providers",
      title: "Services we rely on",
      status: "now",
      body: (
        <ul>
          <li>
            <b>Privy</b> handles email sign-in and creates and holds your wallet.
          </li>
          <li>
            <b>Render</b> hosts the website and server; <b>Neon</b> hosts the database.
          </li>
          <li>
            <b>Solana devnet</b> runs the prize-pool program; <b>QuickNode</b> tells our server about events on that program (public
            blockchain data only).
          </li>
          <li>
            <b>Gemini</b> supplies public prediction-market prices for prediction rounds. Nothing about you is sent to Gemini.
          </li>
          <li>
            <b>Google Fonts</b> supplies the typefaces, so your browser contacts Google when a page loads.
          </li>
          <li>
            <b>Oura</b> (planned), only if you choose to connect it.
          </li>
        </ul>
      ),
    },
    {
      id: "browser",
      title: "Your browser",
      status: "now",
      body: (
        <p>
          Privy keeps you signed in using your browser's storage. Rival itself stores one note so the opening animation plays once per
          tab. We do not use advertising or tracking cookies.
        </p>
      ),
    },
    {
      id: "age",
      title: "Age",
      body: <p>Rival is meant for people aged 18 or over. Please don't use it if you are younger.</p>,
    },
    {
      id: "changes",
      title: "Changes and contact",
      body: (
        <>
          <p>
            This is a draft written for a prototype. We will update it as features change, especially before any Oura connection goes
            live, and change the date at the top.
          </p>
          <p>
            For privacy questions and data requests, email <a href={`mailto:${CONTACT}`}>{CONTACT}</a>.
          </p>
        </>
      ),
    },
  ],
};

const TERMS: Doc = {
  title: (
    <>
      Terms of <em className="serif">service.</em>
    </>
  ),
  plain: "Terms of service",
  lede:
    "These terms cover your use of Rival, a hackathon prototype for friendly fitness competitions. By using Rival you agree to them. The most important points: it is a prototype, and every amount of money in it is devnet test money with no real-world value.",
  sections: [
    {
      id: "prototype",
      title: "A prototype",
      body: (
        <p>
          Rival was built for the University Blockchain Conference 2026 hackathon. It is provided as is, for demonstration and testing.
          Features may change, break or be removed, and data, challenges and balances may be reset at any time without notice.
        </p>
      ),
    },
    {
      id: "devnet",
      title: "Devnet test funds only",
      body: (
        <>
          <p>
            Rival runs only on the Solana devnet, a public test network. The USDC and SOL in Rival are devnet test tokens: they have no
            real-world monetary value and cannot be exchanged for money, goods or real tokens.
          </p>
          <ul>
            <li>Entry fees, prize pools and payouts are all in devnet test money.</li>
            <li>Never send real money or real (mainnet) tokens to any Rival wallet or address. They would be lost.</li>
            <li>Rival is not a betting, gambling, investment or payment service, and we will never ask you to pay.</li>
          </ul>
        </>
      ),
    },
    {
      id: "account",
      title: "Your account and wallet",
      body: (
        <p>
          You must be 18 or over. You sign in with your email through Privy, which creates a wallet for you. You are responsible for
          your email account and for what happens when you are signed in. Pick a player name that is not offensive and does not
          pretend to be someone else.
        </p>
      ),
    },
    {
      id: "competitions",
      title: "How competitions work",
      body: (
        <>
          <ul>
            <li>
              Challenges can be private (invite only, the creator plays), public (anyone can join before the start) or leagues (an
              organizer hosts and may score from a stat sheet). Up to 8 players can join one challenge.
            </li>
            <li>
              Each player pays the same entry fee in devnet test money into a prize pool held by our Solana program. The challenge's
              format (for example winner takes all, podium, goal or teams) is fixed when it is created.
            </li>
            <li>
              Points follow the rules shown in the app. Today: 20 or more active minutes in a day earns a point (minutes from all your
              workouts that day add up), every 5 km earns a point,
              and at most 3 points count per day. Days are 24-hour blocks from the challenge start.
            </li>
            <li>
              When a challenge ends, our server reports the result to the program, which pays out the pool. A tie at the top splits the
              pool. If fewer than 2 players join, entry fees are refunded.
            </li>
            <li>Prediction rounds, where enabled, only add points. They are not bets.</li>
          </ul>
          <p>Before a challenge settles we may correct scores that are wrong because of a bug. Once it settles, the result is final.</p>
        </>
      ),
    },
    {
      id: "fair",
      title: "Fair play",
      body: (
        <>
          <p>Rival only works if everyone plays straight. You agree not to:</p>
          <ul>
            <li>log workouts that did not happen, or log the same workout twice;</li>
            <li>use more than one account to play in the same challenge, or play on someone else's account;</li>
            <li>upload stat sheets you know are wrong;</li>
            <li>tamper with, overload or try to get around the app, its server or its program;</li>
            <li>harass other players.</li>
          </ul>
          <p>We may flag or reject workouts, remove points, remove players from leaderboards or suspend accounts that break these rules.</p>
        </>
      ),
    },
    {
      id: "verification",
      title: "Limits of workout checks",
      body: (
        <>
          <ul>
            <li>
              In this demo version, workouts are added inside the app. Workouts typed in by hand are flagged: they count, but nobody can
              vouch for them.
            </li>
            <li>
              Our checks confirm that a workout fits the rules (for example, the challenge dates). They do not prove a workout really
              happened.
            </li>
            <li>
              A result receipt (Proof of Sweat) shows that our server approved a result and that the scores were not changed
              afterwards. It does not prove the workouts behind it.
            </li>
            <li>
              A planned Oura connection would add device-recorded workouts and heart-rate checks. Device data can still be wrong or
              missing, so no check is perfect.
            </li>
          </ul>
        </>
      ),
    },
    {
      id: "health",
      title: "Your health",
      body: (
        <p>
          Rival is not medical advice and is not a medical device. Exercise within your limits, and talk to a doctor before starting a
          new routine if you have any doubts. You take part in any activity at your own risk.
        </p>
      ),
    },
    {
      id: "services",
      title: "Other services",
      body: (
        <p>
          Rival relies on outside services, including Privy, Render, Neon, QuickNode, Solana devnet, Gemini market data, and Oura once
          that connection exists. Their own terms apply to them, and we are not responsible for their outages or changes.
        </p>
      ),
    },
    {
      id: "liability",
      title: "No warranty and limited liability",
      body: (
        <p>
          Rival is provided "as is" and "as available", without warranties of any kind. To the fullest extent the law allows, the Rival
          team is not liable for any loss arising from your use of the prototype, including lost data, lost devnet test tokens or
          downtime. Because Rival handles no real money, no real-money losses should arise from using it as intended.
        </p>
      ),
    },
    {
      id: "privacy",
      title: "Privacy",
      body: (
        <p>
          How we handle your information is explained in our <a href="../privacy/">privacy policy</a>.
        </p>
      ),
    },
    {
      id: "changes",
      title: "Ending, changes and contact",
      body: (
        <>
          <p>
            You can stop using Rival at any time. We may suspend or shut down the prototype at any time. We may update these terms, and
            the date at the top will change when we do.
          </p>
          <p>
            Questions about these terms: <a href={`mailto:${CONTACT}`}>{CONTACT}</a>.
          </p>
        </>
      ),
    },
  ],
};

/** A whole legal page: the public site's header, the document, and the footer. */
export default function Legal({ doc }: { doc: LegalDoc }) {
  const content = doc === "privacy" ? PRIVACY : TERMS;
  const [menu, setMenu] = useState(false);

  useEffect(() => {
    document.title = `${content.plain} · Rival`;
  }, [content.plain]);

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

  return (
    <div className="site">
      <DemoBanner />
      <header className="site-nav solid">
        <div className="site-nav-inner">
          <a href="../" className="site-brand" aria-label="Rival home">
            <Wordmark />
          </a>
          <nav className="site-links" aria-label="Site">
            {SITE_LINKS.map((l) => (
              <a key={l.href} href={l.href}>
                {l.label}
              </a>
            ))}
          </nav>
          <div className="site-nav-right">
            <a className="btn btn-primary btn-sm" href="../">
              Open Rival
            </a>
            <button className="icon-btn site-menu-btn" onClick={() => setMenu(!menu)} aria-label={menu ? "Close menu" : "Open menu"} aria-expanded={menu}>
              {menu ? <X size={20} aria-hidden /> : <Menu size={20} aria-hidden />}
            </button>
          </div>
        </div>
      </header>

      {menu && (
        <div className="site-menu" role="dialog" aria-label="Menu">
          <nav>
            {[{ href: "../", label: "Home" }, ...SITE_LINKS].map((l, i) => (
              <a key={l.href} href={l.href} style={{ "--i": i } as React.CSSProperties}>
                <b>0{i + 1}</b> {l.label}
              </a>
            ))}
          </nav>
          <a className="btn btn-primary btn-lg btn-block" href="../">
            Open Rival <ArrowRight size={18} aria-hidden />
          </a>
        </div>
      )}

      <main className="site-main legal">
        <header className="wrap legal-hero">
          <nav className="legal-switch" aria-label="Legal pages">
            {LEGAL_LINKS.map((l) => (
              <a key={l.id} href={l.href} className={l.id === doc ? "on" : ""} aria-current={l.id === doc ? "page" : undefined}>
                {l.label}
              </a>
            ))}
          </nav>
          <h1 className="display">{content.title}</h1>
          <p className="lede">{content.lede}</p>
          <p className="legal-meta">
            <span>Draft</span>
            <span>Last updated {UPDATED}</span>
            <span>Devnet test funds only</span>
          </p>
        </header>

        <div className="wrap legal-body">
          <nav className="legal-toc" aria-label="On this page">
            <small>On this page</small>
            {content.sections.map((s, i) => (
              <a key={s.id} href={`#${s.id}`}>
                <b>{String(i + 1).padStart(2, "0")}</b> {s.title}
              </a>
            ))}
          </nav>
          <article className="legal-doc">
            {content.sections.map((s, i) => (
              <Section key={s.id} id={s.id} n={i + 1} title={s.title} status={s.status}>
                {s.body}
              </Section>
            ))}
          </article>
        </div>
      </main>

      <footer className="site-foot">
        <div className="site-foot-top">
          <Wordmark />
          <nav aria-label="Footer">
            {SITE_LINKS.map((l) => (
              <a key={l.href} href={l.href}>
                {l.label}
              </a>
            ))}
            {LEGAL_LINKS.map((l) => (
              <a key={l.id} href={l.href}>
                {l.label}
              </a>
            ))}
          </nav>
        </div>
        <div className="site-foot-fine">
          <span>Demo version. Devnet USDC only, no real money.</span>
        </div>
      </footer>
    </div>
  );
}
