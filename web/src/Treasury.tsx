import { useCallback, useEffect, useState } from "react";
import { FlaskConical, RefreshCw, RotateCcw } from "lucide-react";
import type { Session } from "./App";
import { when } from "./format";
import { Eyebrow, Skeleton } from "./ui";

/** What GET /admin/treasury returns (api/yieldsim.py). Every amount is in USDC and every number is SIMULATED. */
type TreasuryView = {
  simulated: true;
  sim_time: string;
  real_time: string;
  clock_offset_hours: number;
  last_run: string | null;
  total_escrowed: number;
  lent: number;
  liquid_buffer: number;
  interest: number;
  target_now: { amount: number; uncapped: number; cap: number | null; capped: boolean; note: string };
  apy: number;
  apy_source: string;
  apy_live: boolean;
  protocol_liquidity: number | null;
  settings: { grace_hours: number; withdraw_hours: number; safety_hours: number; buffer_pct: number; liquidity_cap_pct: number; apy: number };
  events: {
    address: string;
    name: string;
    pool: number;
    start: string;
    end: string;
    unstake_deadline: string;
    status: string;
    allocated: number;
    projected_yield: number;
  }[];
  log: { sim_time: string; action: string; amount: number; principal: number; interest_added: number; reason: string; warning: string | null }[];
};

const usd = (n: number, digits = 2) => `$${n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
const pct = (n: number) => `${(n * 100).toFixed(2)}%`;
const at = (iso: string) => when(new Date(iso));

/**
 * Admin-only demo page: a SIMULATION of lending escrowed USDC while events run. No real funds are lent,
 * and nothing here changes a challenge, its pool or its payout. The time control moves only the simulation's clock.
 */
export default function Treasury({ session }: { session: Session }) {
  const { call } = session;
  const [view, setView] = useState<TreasuryView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = useCallback(
    async (method: "GET" | "POST", path: string, body?: unknown) => {
      setBusy(true);
      setError("");
      try {
        setView(await call<TreasuryView>(method, path, body));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [call],
  );

  useEffect(() => {
    void run("GET", "/admin/treasury");
  }, [run]);

  return (
    <div className="treasury">
      <header className="page-head">
        <div>
          <Eyebrow>Admin · demo only</Eyebrow>
          <h1 className="headline">
            Treasury <em className="serif">(simulated)</em>
          </h1>
          <p className="lede">How escrowed entry fees could earn yield while events run, and come back before payouts.</p>
        </div>
      </header>

      <div className="sim-banner" role="note">
        <FlaskConical size={18} aria-hidden />
        <div>
          <strong>Simulated: no real funds are lent.</strong> Entry fees stay in the Solana program's vault. Deposits,
          scoring and payouts are not affected, and simulated interest is never added to any prize pool.
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}
      {!view ? (
        <Skeleton rows={3} />
      ) : (
        <>
          <div className="sim-controls card">
            <div className="sim-clock">
              <span className="eyebrow">Simulated clock</span>
              <strong>{at(view.sim_time)}</strong>
              <span className="muted">
                {view.clock_offset_hours > 0 ? `+${formatHours(view.clock_offset_hours)} ahead of real time` : "Real time"}
                {view.last_run ? ` · last run ${at(view.last_run)}` : " · not run yet"}
              </span>
            </div>
            <div className="btn-row">
              <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => run("POST", "/admin/treasury/rebalance")}>
                <RefreshCw size={14} aria-hidden /> Run rebalance now
              </button>
              {[6, 24, 72].map((h) => (
                <button key={h} className="btn btn-quiet btn-sm" disabled={busy}
                  onClick={() => run("POST", "/admin/treasury/clock", { advance_hours: h })}>
                  +{formatHours(h)}
                </button>
              ))}
              <button className="btn btn-text btn-sm" disabled={busy} onClick={() => run("POST", "/admin/treasury/clock", { reset: true })}>
                <RotateCcw size={14} aria-hidden /> Reset
              </button>
            </div>
            <p className="fine">The time control moves only this simulation. Real events, scoring and settlement use real time.</p>
          </div>

          <div className="sim-stats">
            <Stat label="Total escrowed" value={usd(view.total_escrowed)} />
            <Stat label="Lent (simulated)" value={usd(view.lent)} />
            <Stat label="Liquid buffer" value={usd(view.liquid_buffer)} />
            <Stat label="Interest earned (simulated)" value={usd(view.interest, 6)} />
            <Stat label="APY" value={pct(view.apy)} sub={view.apy_source} warn={!view.apy_live} />
          </div>
          <p className="fine">
            Target now {usd(view.target_now.amount)}. {view.target_now.note}
            {view.protocol_liquidity !== null && ` Protocol USDC available: ${usd(view.protocol_liquidity, 0)}.`} Buffer{" "}
            {pct(view.settings.buffer_pct)}, cap {pct(view.settings.liquidity_cap_pct)} of protocol liquidity, grace{" "}
            {view.settings.grace_hours} h, withdraw {view.settings.withdraw_hours} h, safety {view.settings.safety_hours} h.
          </p>

          <div className="section-head">
            <h2>Events</h2>
          </div>
          <div className="sim-table-wrap">
            <table className="sim-table">
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Pool</th>
                  <th>Start</th>
                  <th>End</th>
                  <th>Money back by (U)</th>
                  <th>Status</th>
                  <th>Projected yield</th>
                </tr>
              </thead>
              <tbody>
                {view.events.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted">No active events.</td>
                  </tr>
                )}
                {view.events.map((e) => (
                  <tr key={e.address}>
                    <td title={e.address}>{e.name || e.address.slice(0, 6) + "..."}</td>
                    <td>{usd(e.pool)}</td>
                    <td>{at(e.start)}</td>
                    <td>{at(e.end)}</td>
                    <td>{at(e.unstake_deadline)}</td>
                    <td>
                      <span className={`sim-status sim-${e.status.replace(/\s+/g, "-")}`}>{e.status}</span>
                    </td>
                    <td>{usd(e.projected_yield, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="section-head">
            <h2>Job log</h2>
          </div>
          <div className="sim-table-wrap">
            <table className="sim-table">
              <thead>
                <tr>
                  <th>Simulated time</th>
                  <th>Action</th>
                  <th>Amount</th>
                  <th>Principal after</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {view.log.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">No runs yet. Press "Run rebalance now".</td>
                  </tr>
                )}
                {view.log.map((r, i) => (
                  <tr key={i}>
                    <td>{at(r.sim_time)}</td>
                    <td>{r.action}</td>
                    <td>{usd(r.amount)}</td>
                    <td>{usd(r.principal)}</td>
                    <td>
                      {r.reason}
                      {r.warning && <div className="sim-warning">Warning: {r.warning}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function Stat(props: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className="card sim-stat">
      <span className="eyebrow">{props.label}</span>
      <strong>{props.value}</strong>
      {props.sub && <span className={props.warn ? "sim-warning" : "muted"}>{props.sub}</span>}
    </div>
  );
}

function formatHours(h: number): string {
  return h >= 24 && h % 24 === 0 ? `${h / 24}d` : `${Math.round(h * 10) / 10}h`;
}
