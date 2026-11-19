import { useEffect, useState } from "react";
import { ApiError } from "./api";
import type { Session } from "./App";
import { Eyebrow } from "./ui";

/** What the server says about the caller's Oura link. Tokens never come to the browser. */
type OuraStatus = {
  available: boolean;
  connected: boolean;
  connected_at: string | null;
  missing_permissions: string[];
};

const REASONS: Record<string, string> = {
  expired: "That Oura sign-in expired or was already used. Try connecting again.",
  unknown: "We couldn't match that Oura sign-in to your account. Try connecting again.",
  unavailable: "Connecting Oura isn't available right now.",
};

// Oura sends people back to "?oura=...". React's development mode runs effects twice; finish each attempt once.
let finishing: string | null = null;

function readReturn(): { kind: string; state: string | null; reason: string | null } | null {
  const params = new URLSearchParams(window.location.search);
  const kind = params.get("oura");
  return kind ? { kind, state: params.get("oura_state"), reason: params.get("reason") } : null;
}

function clearReturn() {
  const params = new URLSearchParams(window.location.search);
  ["oura", "oura_state", "reason"].forEach((name) => params.delete(name));
  const query = params.toString();
  window.history.replaceState(null, "", window.location.pathname + (query ? `?${query}` : ""));
}

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

/** Connect an Oura Ring. Connection only for now: Rival does not read any Oura data yet. */
export default function OuraCard({ session }: { session: Session }) {
  const { call } = session;
  const [status, setStatus] = useState<OuraStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const back = readReturn();
    if (back) clearReturn();

    async function load() {
      if (back?.kind === "finish" && back.state && finishing !== back.state) {
        finishing = back.state;
        setBusy(true);
        try {
          const next = await call<OuraStatus>("POST", "/integrations/oura/complete", { state: back.state });
          if (!cancelled) {
            setStatus(next);
            setNote("Oura connected.");
          }
          return;
        } catch (e) {
          if (!cancelled) setError(message(e));
        } finally {
          if (!cancelled) setBusy(false);
        }
      } else if (back?.kind === "cancelled") {
        setNote("Oura connection cancelled. Nothing was shared.");
      } else if (back?.kind === "error") {
        setError(REASONS[back.reason ?? ""] ?? "Oura couldn't be connected. Try again.");
      }
      try {
        const next = await call<OuraStatus>("GET", "/integrations/oura");
        if (!cancelled) setStatus(next);
      } catch (e) {
        if (!cancelled) setError(message(e));
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [call]);

  async function connect() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const { url } = await call<{ url: string }>("POST", "/integrations/oura/start", {
        return_to: window.location.origin + window.location.pathname,
      });
      window.location.assign(url); // Oura's own sign-in and permission screen
    } catch (e) {
      setError(message(e));
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const next = await call<OuraStatus & { revoked: boolean }>("DELETE", "/integrations/oura");
      setStatus(next);
      setNote(next.revoked ? "Oura disconnected and access revoked." : "Oura disconnected. Rival's stored access was deleted.");
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  const connected = status?.connected ?? false;
  const since = status?.connected_at
    ? new Date(status.connected_at).toLocaleDateString([], { month: "short", day: "numeric" })
    : null;

  return (
    <section className="card oura-card" aria-busy={busy}>
      <div className="oura-head">
        <Eyebrow>Oura Ring</Eyebrow>
        {connected ? (
          <span className="status-pill live">
            <span className="live-dot" /> Connected
          </span>
        ) : status && !status.available ? (
          <span className="status-pill">Coming soon</span>
        ) : null}
      </div>

      <p className="oura-line">
        {connected
          ? `Linked${since ? ` since ${since}` : ""}. Rival doesn't read any Oura data yet; workout checks come later.`
          : "Link your ring for Proof of Sweat. Rival will only ask to see workouts and heart rate."}
      </p>

      {connected && status!.missing_permissions.length > 0 && (
        <p className="fine warn">Some permissions were not granted ({status!.missing_permissions.join(", ")}). Reconnect to allow them.</p>
      )}

      {status === null ? (
        !error && <span className="skeleton inline" />
      ) : connected ? (
        confirming ? (
          <div className="oura-actions">
            <button className="btn btn-quiet btn-sm" onClick={disconnect} disabled={busy}>
              {busy ? "Disconnecting..." : "Yes, disconnect"}
            </button>
            <button className="btn btn-quiet btn-sm" onClick={() => setConfirming(false)} disabled={busy}>
              Keep it
            </button>
          </div>
        ) : (
          <div className="oura-actions">
            {status.missing_permissions.length > 0 && (
              <button className="btn btn-primary btn-sm" onClick={connect} disabled={busy}>
                Reconnect
              </button>
            )}
            <button className="btn btn-quiet btn-sm" onClick={() => setConfirming(true)} disabled={busy}>
              Disconnect
            </button>
          </div>
        )
      ) : (
        <button className="btn btn-primary btn-sm" onClick={connect} disabled={busy || !status.available}>
          {busy ? "Opening Oura..." : "Connect Oura"}
        </button>
      )}

      {note && !error && <p className="fine oura-note" role="status">{note}</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
    </section>
  );
}
