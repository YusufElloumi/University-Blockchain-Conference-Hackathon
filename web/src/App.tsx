import { useCallback, useEffect, useRef, useState } from "react";
import { usePrivy } from "@privy-io/react-auth";
import { useSignTransaction, useWallets } from "@privy-io/react-auth/solana";
import { PublicKey } from "@solana/web3.js";
import {
  getAppConfig,
  request,
  retryWhileNotReady,
  type AppConfig,
  type Call,
  type ChallengeView,
  type Me,
} from "./api";
import { sendAndConfirm, tokenBalance } from "./chain";
import ChallengePage from "./ChallengePage";
import CreateChallenge from "./CreateChallenge";
import { money, usdc, when } from "./format";

type Route = { view: "home" } | { view: "create" } | { view: "challenge"; address: string };

function readRoute(): Route {
  const params = new URLSearchParams(window.location.search);
  const address = params.get("challenge");
  if (address) return { view: "challenge", address };
  return params.has("new") ? { view: "create" } : { view: "home" };
}

/** What every signed-in screen gets: who you are, how to call the server, and how to send a transaction. */
export type Session = {
  me: Me;
  config: AppConfig;
  call: Call;
  send: (transaction: Uint8Array) => Promise<string>;
  refreshBalance: () => Promise<void>;
  go: (route: Route) => void;
};

export default function App() {
  const { ready, authenticated, login, logout, getAccessToken } = usePrivy();
  const { wallets } = useWallets();
  const { signTransaction } = useSignTransaction();

  const [me, setMe] = useState<Me | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [balance, setBalance] = useState<number | null>(null);
  const [route, setRoute] = useState<Route>(readRoute);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const tokenGetter = useRef(getAccessToken);
  tokenGetter.current = getAccessToken;

  const call = useCallback<Call>(async (method, path, body) => {
    const token = await tokenGetter.current();
    if (!token) throw new Error("Please sign in again.");
    return request(method, path, token, body);
  }, []);

  const go = useCallback((next: Route) => {
    const query = next.view === "challenge" ? `?challenge=${next.address}` : next.view === "create" ? "?new" : "";
    window.history.pushState(null, "", window.location.pathname + query);
    setRoute(next);
    window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    const onBack = () => setRoute(readRoute());
    window.addEventListener("popstate", onBack);
    return () => window.removeEventListener("popstate", onBack);
  }, []);

  // After login: tell our server (it tops up fee money behind the scenes) and learn the wallet address.
  useEffect(() => {
    if (!ready || !authenticated) {
      setMe(null);
      setBalance(null);
      return;
    }
    let cancelled = false;
    Promise.all([retryWhileNotReady(() => call<Me>("POST", "/me/setup")), getAppConfig()])
      .then(([account, settings]) => {
        if (cancelled) return;
        setMe(account);
        setBalance(account.usdc);
        setConfig(settings);
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [ready, authenticated, call]);

  const refreshBalance = useCallback(async () => {
    if (!me || !config) return;
    try {
      setBalance(await tokenBalance(me.wallet, new PublicKey(config.usdc_mint)));
    } catch (e) {
      console.error(e); // the balance simply stays as it was
    }
  }, [me, config]);

  const send = useCallback(
    async (transaction: Uint8Array) => {
      const wallet = wallets.find((w) => w.address === me?.wallet);
      if (!wallet) throw new Error("Your account is still loading. Try again in a few seconds.");
      const { signedTransaction } = await signTransaction({
        transaction,
        wallet,
        chain: "solana:devnet",
        options: { uiOptions: { showWalletUIs: false } }, // no wallet popup; our own buttons say what happens
      });
      return sendAndConfirm(signedTransaction);
    },
    [wallets, me, signTransaction],
  );

  async function onAddFunds() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await call<Me>("POST", "/me/fund");
      setMe(result);
      setBalance(result.usdc);
      setNotice(`Added ${usdc(result.test_funds_amount)} of test money.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const session: Session | null = me && config ? { me, config, call, send, refreshBalance, go } : null;

  return (
    <div className="page">
      <div className="demo-banner">Demo - test tokens only</div>
      <header>
        <button className="brand" onClick={() => go({ view: "home" })} aria-label="Home">
          LOSER<span>BUYS</span>
        </button>
        {session && (
          <div className="wallet-chip" title="Your balance (test money)">
            {balance === null ? "..." : money(balance)}
          </div>
        )}
      </header>

      {!ready ? (
        <p className="muted center">Loading...</p>
      ) : !authenticated ? (
        <section className="hero">
          <div className="kicker">The weekly fitness league</div>
          <h1>
            Out-move your friends.
            <br />
            <em>Winner takes the pool.</em>
          </h1>
          <ol className="steps">
            <li>
              <b>1</b> Everyone chips in
            </li>
            <li>
              <b>2</b> Workouts score points
            </li>
            <li>
              <b>3</b> Top of the table gets paid
            </li>
          </ol>
          <button className="primary" onClick={() => login()}>
            Sign in with email
          </button>
          <p className="fine center">No app to install, no passwords. We email you a code.</p>
        </section>
      ) : !session ? (
        <p className="muted center">{error ? "" : "Setting up your account..."}</p>
      ) : route.view === "challenge" ? (
        <ChallengePage key={route.address} address={route.address} session={session} balance={balance} />
      ) : route.view === "create" ? (
        <CreateChallenge session={session} balance={balance} />
      ) : (
        <Home
          session={session}
          balance={balance}
          busy={busy}
          onAddFunds={onAddFunds}
          onRenamed={setMe}
          onSignOut={logout}
        />
      )}

      {notice && <div className="message ok">{notice}</div>}
      {error && (
        <div className="message error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

function Home(props: {
  session: Session;
  balance: number | null;
  busy: boolean;
  onAddFunds: () => void;
  onRenamed: (me: Me) => void;
  onSignOut: () => void;
}) {
  const { session, balance } = props;
  const { me, call, go } = session;
  const [challenges, setChallenges] = useState<ChallengeView[] | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(me.name);
  const demo: string = import.meta.env.VITE_DEMO_CHALLENGE || "";

  useEffect(() => {
    call<ChallengeView[]>("GET", "/me/challenges")
      .then(setChallenges)
      .catch(() => setChallenges([]));
  }, [call]);

  async function saveName() {
    try {
      props.onRenamed(await call<Me>("POST", "/me/name", { name }));
      setEditing(false);
    } catch (e) {
      console.error(e);
    }
  }

  return (
    <>
      <section className="card wallet-card">
        <div className="label">Your balance</div>
        <div className="big-number">{balance === null ? "..." : money(balance)}</div>
        <div className="fine">{balance === null ? "" : `${usdc(balance)} (test money)`}</div>
        {!me.test_funds_used && (
          <button className="secondary" onClick={props.onAddFunds} disabled={props.busy}>
            {props.busy ? "Adding..." : `Add test funds (${usdc(me.test_funds_amount)})`}
          </button>
        )}
      </section>

      <section className="card">
        <div className="label">Player name</div>
        {editing ? (
          <div className="row">
            <input value={name} maxLength={24} onChange={(e) => setName(e.target.value)} aria-label="Player name" />
            <button className="small" onClick={saveName} disabled={!name.trim()}>
              Save
            </button>
          </div>
        ) : (
          <div className="row">
            <div className="player-name">
              <span className="avatar">{me.name.slice(0, 1).toUpperCase()}</span>
              {me.name}
            </div>
            <button className="link" onClick={() => setEditing(true)}>
              Change
            </button>
          </div>
        )}
        <p className="fine">This is what friends see on the table.</p>
      </section>

      <button className="primary" onClick={() => go({ view: "create" })}>
        + Start a challenge
      </button>

      <h2 className="section-title">Your challenges</h2>
      {challenges === null ? (
        <p className="muted">Loading...</p>
      ) : challenges.length === 0 ? (
        <p className="muted">None yet. Start one, or open a friend's invite link.</p>
      ) : (
        challenges.map((c) => (
          <button key={c.address} className="fixture" onClick={() => go({ view: "challenge", address: c.address })}>
            <div>
              <div className="fixture-name">{c.name}</div>
              <div className="fine">
                {c.status === "open" ? `Ends ${when(new Date(c.end))}` : c.status === "settled" ? "Final" : "Refunded"}
              </div>
            </div>
            <div className="fixture-stake">{money(c.buy_in)}</div>
          </button>
        ))
      )}
      {demo && !challenges?.some((c) => c.address === demo) && (
        <button className="fixture" onClick={() => go({ view: "challenge", address: demo })}>
          <div>
            <div className="fixture-name">Demo challenge</div>
            <div className="fine">Open to everyone</div>
          </div>
          <div className="fixture-stake">View</div>
        </button>
      )}

      <button className="link center-link" onClick={props.onSignOut}>
        Sign out
      </button>
    </>
  );
}
