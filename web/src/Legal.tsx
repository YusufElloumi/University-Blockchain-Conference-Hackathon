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
    "Rival is a hackathon prototype that turns workouts into friendly competitions on the Solana devnet test network. This page explains what we collect, how the optional Oura connection is used, who can see what, and what stays private.",
  sections: [
    {
      id: "summary",
      title: "The short version",
      body: (
        <ul>
          <li>Other players see your points, never your workout details.</li>
          <li>
            If you connect an Oura account, Rival reads your workouts and heart rate to check and score them. It keeps a small
            record of each workout: no heart-rate readings, only coverage counts and one summary number per workout.
          </li>
          <li>Workout and health data never goes on the blockchain and is never sent to any AI service.</li>
          <li>The blockchain holds only wallet addresses, test-money movements, winners and a scrambled fingerprint (hash) of the final scores. It is public and permanent.</li>
          <li>Disconnecting Oura revokes Rival's access and deletes your imported workouts.</li>
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
          <h3>Workouts imported from Oura</h3>
          <p>
            Only if you connect Oura. For each workout we keep: its category (run, walk and so on), Oura's own activity name and how
            Oura says it was recorded, its start and end time, its distance if there is one, Oura's intensity label (easy, moderate or
            hard), the result of each check, how many minutes of it had heart-rate measurements, and one summary number: the
            middle (median) heart-rate value recorded during it. Details are in the Oura section below.
          </p>
          <h3>Workouts you log in the app</h3>
          <p>
            Some older challenges let you add a workout by hand. For each one we store the type, start time, duration, distance and
            how it was added. These are never treated as device-verified, and they earn no points in Proof of Sweat challenges.
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
            We do not store the series of heart-rate readings, calories, or Oura's own workout IDs. We never request
            sleep, readiness, GPS routes or location. We receive nothing from Strava or any other fitness service. We use no
            analytics, advertising or tracking tools.
          </p>
        </>
      ),
    },
    {
      id: "oura",
      title: "Oura integration",
      status: "now",
      body: (
        <>
          <p>
            Connecting Oura is optional, but new fitness challenges only award points for workouts imported from a connected Oura
            account (shown in the app as Proof of Sweat). Rival is not affiliated with or endorsed by Oura.
          </p>
          <ul>
            <li>
              <b>Your choice.</b> Nothing is read until you press Connect Oura and approve access on Oura's own screen. Rival asks for
              two permissions only: workouts and heart rate.
            </li>
            <li>
              <b>What we read.</b> When you press Sync workouts, and once more when a challenge you are in ends, Rival asks Oura for
              your recent workouts (up to 30 days back the first time) and, for each eligible workout, the heart-rate measurements
              taken during it.
            </li>
            <li>
              <b>What we keep.</b> A small record per workout, listed above. Heart-rate measurements are reduced to counts and one
              median per workout, then discarded: we never keep the readings themselves. For each challenge you play we also keep
              one "personal reference": the typical value across your earlier workouts and how many were used, fixed when the
              challenge starts. It is not a resting or maximum heart rate and is never shown to anyone, including you. Oura's workout ID is replaced by a one-way
              reference used to stop the same workout being counted twice.
            </li>
            <li>
              <b>Why.</b> To check each workout against published rules and turn eligible minutes into challenge points. Heart rate
              is used in two ways: to describe how complete the recording's evidence is, and, in newer challenges, as one of three
              bounded effort signals, where your session is compared only with your own earlier workouts. There is no pulse target,
              and a missing heart rate is treated as neutral. Nothing here is medical advice or a health assessment.
            </li>
            <li>
              <b>Who sees it.</b> Only you see your workouts and their checks. Other players see your points, and whether your Oura
              is linked and synced.
            </li>
            <li>
              <b>Storage.</b> The keys Oura gives us to read your data are stored encrypted on our server, never in your browser
              and never on the blockchain.
            </li>
            <li>
              <b>How long.</b> Imported workouts are deleted automatically 7 days after the last challenge that used them has ended,
              or 7 days after the workout if no challenge used it. This clean-up runs with our scheduled job; if that job is not
              running, the records stay until you disconnect. One exception: workouts from the 30 days before a challenge you
              joined are kept until that challenge starts, because they are what your personal reference is built from.
            </li>
            <li>
              <b>Disconnecting.</b> The Disconnect button on your dashboard asks Oura to revoke Rival's access, then deletes the
              stored keys and every imported workout, along with your points in challenges that have not finished.
            </li>
            <li>
              <b>Never.</b> We do not sell Oura data, use it for advertising, send it to any AI or language-model service, or put it
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
            To check workouts. Each imported workout is marked verified (with strong or limited heart-rate evidence), pending or
            rejected, with every check and reason shown to you. The checks are fixed rules, not an AI model.
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
              A SHA-256 hash of the challenge's rules (scoring rules, length, format and so on), locked when the challenge is created.
              When you join, your deposit is only accepted if it names that same hash. The rules text itself is kept on our server.
            </li>
            <li>The payout terms (for example 60 / 30 / 10 for a podium), also locked at creation.</li>
            <li>
              The public key of our result verifier, and, in each payout transaction, the verifier's signed result: the challenge, the
              rules hash, the score-sheet hash, the winners' wallet addresses and their shares. Solana checks that signature before the
              program pays anyone.
            </li>
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
            When a challenge ends, our server signs a result receipt (shown in the app as Proof of Sweat) with a key kept separate from
            the key that sends payouts. It holds wallet addresses, payout shares, the rules hash and the score-sheet hash, but no workout
            data. The signed result goes into the payout transaction, as described above, and a copy is stored on our server for players
            of that challenge to download. Both keys are run by our server. In Proof of Sweat challenges the score sheet also lists, per
            player, verified minutes, points, and one salted fingerprint for each workout receipt. A fingerprint reveals nothing about
            the workout.
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
            Oura access keys are encrypted by our server before they are stored. Rival is a prototype: workout records themselves
            are not separately encrypted in the database, beyond whatever protection our hosting providers apply, and the app has
            not had an independent security review. Please don't enter anything you would
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
              <b>Imported Oura workouts.</b> Deleted automatically 7 days after the last challenge that used them has ended, and
              immediately when you disconnect Oura.
            </li>
            <li>
              <b>Finished challenges.</b> Final score sheets and result receipts are kept so results stay checkable. For each of your
              workouts in a finished Proof of Sweat challenge we keep a minimal receipt for you: its category, minutes, check
              results and a random value. It holds no times, no Oura IDs and no heart-rate data.
            </li>
            <li>
              <b>Deleting your workouts.</b> Use <b>Delete my workouts</b> on your home screen in the app. It deletes every workout
              you have logged, disconnects Oura (revoking Rival's access and deleting your imported workouts and saved receipts),
              and removes your points in challenges that have not finished. You stay in those challenges with zero points. It
              cannot be undone.
            </li>
            <li>
              <b>Deleting your account.</b> There is no in-app account deletion yet. Email us and we will remove your account record
              by hand, within 72 hours for anything that came from Oura.
              Privy keeps its own login records under its own privacy policy.
            </li>
            <li>
              <b>The prototype database</b> may be reset or deleted after the hackathon.
            </li>
            <li>
              <b>The blockchain.</b> Onchain records cannot be deleted by anyone. They hold no health data.
            </li>
          </ul>
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
            <b>Oura</b> supplies your workouts and heart-rate measurements, only if you choose to connect it.
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
            This is a draft written for a prototype. We will update it as features change, and change the date at the top.
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
              Points follow the rules locked into each challenge when it is created. New fitness challenges use Proof of Sweat v2:
              about one Sweat Point for each minute of exercise recorded by your connected Oura account that passes the checks.
              In each 24-hour block from the challenge start, the first hour counts in full, the second at 0.6, the third at 0.25
              and nothing after that. Each workout is multiplied by an effort factor between 0.85 and 1.25, built from Oura's
              intensity label, your heart rate relative to your own earlier workouts, and pace where the sport has one. A signal
              that is unavailable counts as neutral. A day's total is rounded to a whole number. These are game rules, not exercise
              advice. Challenges created earlier keep the rules they started with.
            </li>
            <li>
              When a challenge ends, scores are fixed after a short wait (30 minutes by default) so rings can sync, then our server
              reports the result to the program, which pays out the pool. Workouts that have not reached Oura's servers by then do
              not count. A tie at the top splits the pool. If fewer than 2 players join, entry fees are refunded.
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
            <li>record or edit workouts in Oura that did not happen, or wear someone else's ring;</li>
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
              Proof of Sweat checks the record your Oura account returns against fixed, published rules: how it was recorded, its
              type, times, length and speed, and that no minute is counted twice. Workouts entered by hand in Oura are not counted.
            </li>
            <li>
              These checks do not prove a workout really happened. A consumer wearable can be wrong, and a record can be mislabelled.
              Heart-rate coverage is reported as strong or limited evidence only; missing heart rate is common and is not treated as
              cheating.
            </li>
            <li>
              A signed result shows that our server approved it under the rules locked at creation and that the scores were not
              changed afterwards. The Solana program stores the result's fingerprint, checks the verifier's signature at payout and
              enforces the locked payout split. It does not check workouts, and you are trusting Rival's server to have read the Oura
              records honestly.
            </li>
            <li>If Oura is unavailable, syncing and final scores can be delayed. An outage never adds or removes points by itself.</li>
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
          Rival relies on outside services, including Privy, Render, Neon, QuickNode, Solana devnet, Gemini market data and Oura.
          Their own terms apply to them, and we are not responsible for their outages or changes. Rival is not affiliated with Oura.
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
