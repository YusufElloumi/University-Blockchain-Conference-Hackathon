import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { ApiError } from "./api";
import type { Session } from "./App";
import { syncOura } from "./Sweat";
import { Eyebrow } from "./ui";

/** What the server says about the caller's Oura link. Tokens never come to the browser. */
type OuraStatus = {
  available: boolean;
  connected: boolean;
  connected_at: string | null;
  missing_permissions: string[];
  last_sync_at?: string | null;
  last_sync_error?: string | null;
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

const SYNC_ERROR: Record<string, string> = {
  reconnect: "Oura stopped accepting Rival's access. Disconnect, then connect again.",
  permission: "Oura refused access to workouts. Reconnect and allow workouts and heart rate.",
  rate_limited: "Oura was busy on the last sync. Try again in a few minutes.",
  unreachable: "Oura couldn't be reached on the last sync. Your points are unchanged.",
  error: "The last sync didn't finish. Your points are unchanged.",
};

const ago = (iso: string) => {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
};

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

/** Connect an Oura Ring. Connection only for now: Rival does not read any Oura data yet. */
export default function OuraCard({ session }: { session: Session }) {
  const { call } = session;
  const [syncing, setSyncing] = useState(false);
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

  async function sync() {
    setSyncing(true);
    setError(null);
    setNote(null);
    try {
      const done = await syncOura(call);
      setStatus(await call<OuraStatus>("GET", "/integrations/oura"));
      setNote(done);
    } catch (e) {
      setError(message(e));
      call<OuraStatus>("GET", "/integrations/oura").then(setStatus).catch(() => undefined);
    } finally {
      setSyncing(false);
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
          ? `Linked${since ? ` since ${since}` : ""}. Workouts your ring records earn your challenge points, checked by Proof of Sweat.`
          : "Link your ring to earn challenge points. Rival reads workouts and heart rate only, and other players see just your points."}
      </p>

      {connected && (
        <p className="fine oura-synced">
          {status!.last_sync_at ? `Last synced ${ago(status!.last_sync_at)}.` : "Not synced yet."}
        </p>
      )}
      {connected && status!.last_sync_error && !error && !note && (
        <p className="fine warn">{SYNC_ERROR[status!.last_sync_error] ?? SYNC_ERROR.error}</p>
      )}

      {connected && status!.missing_permissions.length > 0 && (
        <p className="fine warn">Some permissions were not granted ({status!.missing_permissions.join(", ")}). Reconnect to allow them.</p>
      )}

      {status === null ? (
        !error && <span className="skeleton inline" />
      ) : connected ? (
        confirming ? (
          <div className="oura-actions">
            <p className="fine">
              This revokes Rival's access and deletes your imported workouts, including your points in challenges that haven't
              finished. Finished results stay.
            </p>
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
            <button className="btn btn-primary btn-sm" onClick={sync} disabled={busy || syncing}>
              <RefreshCw size={14} className={syncing ? "spin" : ""} aria-hidden /> {syncing ? "Checking Oura..." : "Sync workouts"}
            </button>
            <button className="btn btn-quiet btn-sm" onClick={() => setConfirming(true)} disabled={busy || syncing}>
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

      {/* Developer diagnostic: admins only (the server refuses everyone else). */}
      {connected && !confirming && session.me?.is_admin && <OuraDiagnostic call={call} />}
    </section>
  );
}

/* ---------- Developer diagnostic (admins only) ----------
   Shows what Oura's API returns for the signed-in owner's own account, via GET /integrations/oura/workouts.
   Deliberately leaves out workout IDs, times, calories, distances and every heart-rate value: only field
   names, classifications and sample counts. Nothing is saved; the summary lives in this card until reload. */

type HeartRateCheck = {
  status: string;
  reason?: string;
  sample_count?: number;
  workout_minutes?: number;
  minutes_with_samples?: number;
  coverage_pct?: number;
  sources?: Record<string, number>;
};

type WorkoutCheck = {
  source: string | null;
  intensity: string | null;
  missing_fields: string[];
  undocumented_fields: string[];
  heart_rate?: HeartRateCheck;
};

type OuraReport = {
  window: { days: number };
  workouts_found: number;
  workouts_shown: number;
  documented_fields: { required: string[]; optional: string[] };
  field_presence: Record<string, number>;
  workouts: WorkoutCheck[];
};

const tally = (values: (string | null)[]) =>
  Object.entries(
    values.reduce<Record<string, number>>((all, v) => ({ ...all, [v ?? "none"]: (all[v ?? "none"] ?? 0) + 1 }), {}),
  )
    .map(([name, n]) => `${name} ×${n}`)
    .join(", ") || "—";

function OuraDiagnostic({ call }: { call: Session["call"] }) {
  const [report, setReport] = useState<OuraReport | null>(null);
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function check() {
    setChecking(true);
    setProblem(null);
    try {
      setReport(await call<OuraReport>("GET", "/integrations/oura/workouts?days=30&limit=10"));
    } catch (e) {
      setProblem(message(e));
    } finally {
      setChecking(false);
    }
  }

  const shown = report?.workouts_shown ?? 0;
  const fields = report ? [...report.documented_fields.required, ...report.documented_fields.optional] : [];
  const undocumented = report ? [...new Set(report.workouts.flatMap((w) => w.undocumented_fields))] : [];

  return (
    <div className="oura-diag">
      <div className="oura-diag-head">
        <span className="oura-diag-tag">Diagnostic · admins only</span>
        <button className="btn btn-quiet btn-sm" onClick={check} disabled={checking}>
          {checking ? "Checking..." : report ? "Check again" : "Check Oura data"}
        </button>
      </div>
      <p className="fine">Only you see this. It reads your last 30 days from Oura and shows what kinds of data came back. Nothing is saved.</p>

      {problem && <p className="error-text" role="alert">{problem}</p>}

      {report && (
        <div className="oura-diag-body" role="status">
          <p className="oura-diag-total">
            <b>{report.workouts_found}</b> workout{report.workouts_found === 1 ? "" : "s"} found in {report.window.days} days
            {report.workouts_found > shown && ` · newest ${shown} checked`}
          </p>

          {shown > 0 && (
            <>
              <h4>Fields returned</h4>
              <ul className="oura-diag-fields">
                {fields.map((f) => {
                  const n = report.field_presence[f] ?? 0;
                  return (
                    <li key={f} className={n === shown ? "all" : n === 0 ? "none" : "some"}>
                      <code>{f}</code> {n}/{shown}
                    </li>
                  );
                })}
              </ul>
              <p className="fine">
                Undocumented fields: {undocumented.length ? undocumented.map((f) => <code key={f}>{f} </code>) : "none"}
              </p>

              <h4>Classifications</h4>
              <p className="fine">Source: {tally(report.workouts.map((w) => w.source))}</p>
              <p className="fine">Intensity: {tally(report.workouts.map((w) => w.intensity))}</p>

              <h4>Per workout</h4>
              <ol className="oura-diag-list">
                {report.workouts.map((w, i) => {
                  const hr = w.heart_rate;
                  return (
                    <li key={i}>
                      <span className="oura-diag-row">
                        <b>{w.source ?? "—"}</b> · {w.intensity ?? "—"}
                      </span>
                      <span className="fine">
                        {hr?.status === "ok"
                          ? `Heart rate: ${hr.sample_count} samples · ${hr.minutes_with_samples}/${hr.workout_minutes} min covered (${hr.coverage_pct}%)` +
                            (hr.sources && Object.keys(hr.sources).length ? ` · ${Object.keys(hr.sources).join(", ")}` : "")
                          : `Heart rate: ${hr?.status ?? "not checked"}${hr?.reason ? ` (${hr.reason})` : ""}`}
                      </span>
                      {w.missing_fields.length > 0 && <span className="fine">Missing: {w.missing_fields.join(", ")}</span>}
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </div>
      )}
    </div>
  );
}
