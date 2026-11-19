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
import { Check, X } from "lucide-react";
import ChallengePage from "./ChallengePage";
import CreateChallenge from "./CreateChallenge";
import Dashboard from "./Dashboard";
import HowItWorks from "./HowItWorks";
import Site from "./Site";
import ModeScreen from "./ModeScreen";
import Treasury from "./Treasury";
import WithdrawNote from "./WithdrawNote";
import { isMode, type Mode } from "./modes";
import Shell, { type Section } from "./Shell";
import { IntroLogo, prefersReducedMotion, Wordmark } from "./ui";

export type Route =
  | { view: "home" }
  | { view: "mode"; mode: Mode }
  | { view: "create"; mode: Mode }
  | { view: "challenge"; address: string }
  | { view: "invite"; code: string }
  | { view: "help" }
  | { view: "treasury" }; // admin demo: SIMULATED treasury yield

function readRoute(): Route {
  const params = new URLSearchParams(window.location.search);
  const address = params.get("challenge");
  if (address) return { view: "challenge", address };
  const code = params.get("invite");
  if (code) return { view: "invite", code };
  if (params.has("help")) return { view: "help" };
  if (params.has("treasury")) return { view: "treasury" };
  const mode = params.get("mode");
  if (params.has("new")) return { view: "create", mode: isMode(params.get("new")) ? (params.get("new") as Mode) : "private" };
  return isMode(mode) ? { view: "mode", mode } : { view: "home" };
}

function routeQuery(route: Route): string {
  switch (route.view) {
    case "challenge":
      return `?challenge=${route.address}`;
    case "invite":
      return `?invite=${encodeURIComponent(route.code)}`;
    case "mode":
      return `?mode=${route.mode}`;
    case "create":
      return `?new=${route.mode}`;
    case "help":
      return "?help";
    case "treasury":
      return "?treasury";
    default:
      return "";
  }
}

/** What every signed-in screen gets: who you are, how to call the server, and how to send a transaction. */
export type Session = {
  me: Me;
  config: AppConfig;
  call: Call;
  send: (transaction: Uint8Array) => Promise<string>;
  refreshBalance: () => Promise<void>;
  go: (route: Route, replace?: boolean) => void;
  /** An event page reports which mode it belongs to, so the navigation can highlight it. */
  markMode: (mode: Mode | null) => void;
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
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [challengeMode, setChallengeMode] = useState<Mode | null>(null);

  const tokenGetter = useRef(getAccessToken);
  tokenGetter.current = getAccessToken;

  const call = useCallback<Call>(async (method, path, body) => {
    const token = await tokenGetter.current();
    if (!token) throw new Error("Please sign in again.");
    return request(method, path, token, body);
  }, []);

  const go = useCallback((next: Route, replace = false) => {
    const url = window.location.pathname + routeQuery(next);
    if (replace) window.history.replaceState(null, "", url);
    else window.history.pushState(null, "", url);
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
      setNotice(`Added ${result.test_funds_amount} devnet USDC.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const session: Session | null =
    me && config ? { me, config, call, send, refreshBalance, go, markMode: setChallengeMode } : null;

  // A notice ("Added 10 devnet USDC") clears itself; an error stays until dismissed.
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4500);
    return () => clearTimeout(timer);
  }, [notice]);

  // The opening animation: a short wordmark reveal, once per browser session.
  const [introPlayed] = useState(shouldPlayIntro);
  const [introHeld, setIntroHeld] = useState(introPlayed);
  useEffect(() => {
    if (!introPlayed) return;
    const timer = setTimeout(() => setIntroHeld(false), 2450);
    return () => clearTimeout(timer);
  }, [introPlayed]);
  const entered = !introHeld && ready;

  // Which sidebar item is lit. An event page lights the mode it belongs to, once that is known.
  const section: Section =
    route.view === "home" || route.view === "invite"
      ? "home"
      : route.view === "help"
        ? "help"
        : route.view === "treasury"
          ? null
          : route.view === "challenge"
          ? challengeMode
          : route.mode;
  const routeKey = route.view === "challenge" ? route.address : route.view + ("mode" in route ? route.mode : "");

  return (
    <div className={`root${entered ? " entered" : ""}`}>
      {introPlayed && (
        <div className={`intro-screen${entered ? " out" : ""}`} aria-hidden>
          <IntroLogo />
        </div>
      )}

      {!ready ? (
        <div className="splash">{!introPlayed && <Wordmark />}</div>
      ) : !authenticated ? (
        <Site onLogin={login} />
      ) : !session ? (
        <div className="splash">
          <Wordmark />
          {error ? (
            <button className="btn btn-quiet btn-sm" onClick={logout}>
              Sign out
            </button>
          ) : (
            <p>Setting up your account...</p>
          )}
        </div>
      ) : (
        <Shell
          session={session}
          balance={balance}
          section={section}
          routeKey={routeKey}
          onWithdraw={() => setWithdrawOpen(true)}
          onSignOut={logout}
        >
          {route.view === "challenge" ? (
            <ChallengePage key={route.address} address={route.address} session={session} balance={balance} />
          ) : route.view === "create" ? (
            <CreateChallenge key={route.mode} mode={route.mode} session={session} balance={balance} />
          ) : route.view === "mode" ? (
            <ModeScreen key={route.mode} mode={route.mode} session={session} />
          ) : route.view === "invite" ? (
            <RedeemInvite code={route.code} session={session} />
          ) : route.view === "help" ? (
            <HowItWorks session={session} />
          ) : route.view === "treasury" ? (
            <Treasury session={session} />
          ) : (
            <Dashboard
              session={session}
              balance={balance}
              busy={busy}
              onAddFunds={onAddFunds}
              onWithdraw={() => setWithdrawOpen(true)}
              onRenamed={setMe}
              onSignOut={logout}
            />
          )}
        </Shell>
      )}

      {withdrawOpen && <WithdrawNote onClose={() => setWithdrawOpen(false)} />}

      {(notice || error) && (
        <div className="toasts">
          {notice && (
            <div className="toast ok" role="status">
              <Check size={16} aria-hidden /> {notice}
            </div>
          )}
          {error && (
            <div className="toast error" role="alert">
              <span>{error}</span>
              <button className="icon-btn" onClick={() => setError("")} aria-label="Dismiss">
                <X size={15} aria-hidden />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** True the first time the app opens in this browser tab (and motion is welcome). */
function shouldPlayIntro(): boolean {
  if (prefersReducedMotion()) return false;
  try {
    if (sessionStorage.getItem("rival-intro")) return false;
    sessionStorage.setItem("rival-intro", "1");
    return true;
  } catch {
    return false;
  }
}

/** Opening an invite link: the server checks the code, then the event opens. */
function RedeemInvite({ code, session }: { code: string; session: Session }) {
  const { call, go } = session;
  const [error, setError] = useState("");
  useEffect(() => {
    call<ChallengeView>("POST", "/invites/redeem", { code })
      .then((c) => go({ view: "challenge", address: c.address }, true))
      .catch((e) => setError(e.message));
  }, [call, go, code]);
  return (
    <div className="center-state">
      <p>{error || "Opening your invite..."}</p>
      {error && (
        <button className="btn btn-quiet" onClick={() => go({ view: "home" }, true)}>
          Back to home
        </button>
      )}
    </div>
  );
}

