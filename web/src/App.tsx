import { useCallback, useEffect, useState } from "react";
import { usePrivy } from "@privy-io/react-auth";
import { useSignTransaction, useWallets } from "@privy-io/react-auth/solana";
import { addTestFunds, setupAccount, type Me } from "./api";
import {
  buildJoinTransaction,
  explorerTx,
  fetchChallenge,
  friendlyError,
  sendAndConfirm,
  tokenBalance,
  type ChallengeInfo,
} from "./chain";

// Stage 2 shows one challenge: the address in the link (?challenge=...) or the demo one from .env.
const CHALLENGE_ADDRESS =
  new URLSearchParams(window.location.search).get("challenge") || import.meta.env.VITE_DEMO_CHALLENGE || "";

const money = (n: number) => `$${n.toFixed(2)}`;
const usdc = (n: number) => `${Number.isInteger(n) ? n : n.toFixed(2)} USDC`;

export default function App() {
  const { ready, authenticated, login, logout, getAccessToken } = usePrivy();
  const { wallets } = useWallets();
  const { signTransaction } = useSignTransaction();

  const [me, setMe] = useState<Me | null>(null);
  const [balance, setBalance] = useState<number | null>(null);
  const [challenge, setChallenge] = useState<ChallengeInfo | null>(null);
  const [busy, setBusy] = useState<"" | "funds" | "join">("");
  const [message, setMessage] = useState<{ kind: "error" | "ok"; text: string; link?: string } | null>(null);

  // After login: tell our server (it tops up fee money behind the scenes) and learn the wallet address.
  useEffect(() => {
    if (!ready || !authenticated) {
      setMe(null);
      setBalance(null);
      return;
    }
    let cancelled = false;
    setupAccount(getAccessToken)
      .then((result) => {
        if (cancelled) return;
        setMe(result);
        setBalance(result.usdc);
      })
      .catch((e) => !cancelled && setMessage({ kind: "error", text: e.message }));
    return () => {
      cancelled = true;
    };
  }, [ready, authenticated, getAccessToken]);

  const refresh = useCallback(async () => {
    if (!CHALLENGE_ADDRESS) return;
    try {
      const info = await fetchChallenge(CHALLENGE_ADDRESS);
      setChallenge(info);
      if (me) setBalance(await tokenBalance(me.wallet, info.mint));
    } catch (e) {
      console.error(e);
      setMessage({ kind: "error", text: "Couldn't load this challenge. Check the link and try again." });
    }
  }, [me]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onAddFunds() {
    setBusy("funds");
    setMessage(null);
    try {
      const token = await getAccessToken();
      if (!token) throw new Error("Please sign in again.");
      const result = await addTestFunds(token);
      setMe(result);
      setBalance(result.usdc);
      setMessage({ kind: "ok", text: `Added ${usdc(result.test_funds_amount)} of test money.` });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy("");
    }
  }

  async function onJoin() {
    if (!me || !challenge) return;
    const wallet = wallets.find((w) => w.address === me.wallet);
    if (!wallet) {
      setMessage({ kind: "error", text: "Your account is still loading. Try again in a few seconds." });
      return;
    }
    setBusy("join");
    setMessage(null);
    try {
      const transaction = await buildJoinTransaction(me.wallet, challenge);
      const { signedTransaction } = await signTransaction({
        transaction,
        wallet,
        chain: "solana:devnet",
        options: { uiOptions: { showWalletUIs: false } },
      });
      const signature = await sendAndConfirm(signedTransaction);
      setMessage({ kind: "ok", text: `You're in! ${usdc(challenge.buyIn)} went into the pool.`, link: explorerTx(signature) });
      await refresh();
    } catch (e) {
      console.error(e);
      setMessage({ kind: "error", text: friendlyError(e) });
    } finally {
      setBusy("");
    }
  }

  const joined = !!me && !!challenge && challenge.players.includes(me.wallet);
  const joinOpen = !!challenge && challenge.status === "open" && challenge.startTime.getTime() > Date.now();
  const canAfford = balance !== null && !!challenge && balance >= challenge.buyIn;

  return (
    <div className="page">
      <div className="demo-banner">Demo - test tokens only</div>
      <header>
        <h1>Loser Buys</h1>
        {authenticated && (
          <button className="link" onClick={logout}>
            Sign out
          </button>
        )}
      </header>

      {!ready ? (
        <p className="muted center">Loading...</p>
      ) : !authenticated ? (
        <section className="card center">
          <h2>Out-move your friends. Winner takes the pool.</h2>
          <p className="muted">Everyone chips in, everyone gets moving, and the week's top scorer is paid automatically.</p>
          <button className="primary" onClick={() => login()}>
            Sign in with email
          </button>
          <p className="fine">No app to install, no passwords. We email you a code.</p>
        </section>
      ) : !me ? (
        <p className="muted center">{message?.kind === "error" ? "" : "Setting up your account..."}</p>
      ) : (
        <>
          <section className="card">
            <div className="label">Your balance</div>
            <div className="balance">{balance === null ? "..." : money(balance)}</div>
            <div className="fine">{balance === null ? "" : `${usdc(balance)} (test money)`}</div>
            {!me.test_funds_used && (
              <button className="secondary" onClick={onAddFunds} disabled={busy !== ""}>
                {busy === "funds" ? "Adding..." : `Add test funds (${usdc(me.test_funds_amount)})`}
              </button>
            )}
          </section>

          {!CHALLENGE_ADDRESS ? (
            <section className="card">
              <p className="muted">Open an invite link to join a challenge.</p>
            </section>
          ) : !challenge ? (
            <p className="muted center">Loading challenge...</p>
          ) : (
            <section className="card">
              <div className="label">This week's challenge</div>
              <div className="pool">{money(challenge.pool)} pool</div>
              <p className="muted">
                {challenge.players.length} of {challenge.maxPlayers} spots taken. Starts{" "}
                {challenge.startTime.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}.
              </p>
              {joined ? (
                <div className="joined">You're in. Good luck!</div>
              ) : !joinOpen ? (
                <p className="muted">Joining is closed for this challenge.</p>
              ) : (
                <>
                  <button className="primary" onClick={onJoin} disabled={busy !== "" || !canAfford}>
                    {busy === "join" ? "Joining..." : `Join for ${usdc(challenge.buyIn)}`}
                  </button>
                  <p className="fine">
                    {canAfford
                      ? `${usdc(challenge.buyIn)} moves from your balance into the pool. The winner takes the pool.`
                      : "Add test funds first, then you can join."}
                  </p>
                </>
              )}
            </section>
          )}
        </>
      )}

      {message && (
        <div className={`message ${message.kind}`} role="status">
          {message.text}{" "}
          {message.link && (
            <a href={message.link} target="_blank" rel="noreferrer">
              Details
            </a>
          )}
        </div>
      )}
    </div>
  );
}
