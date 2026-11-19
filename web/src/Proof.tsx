import { useState } from "react";
import { ArrowUpRight, CircleAlert, CircleCheck, CircleHelp, Download, Link2, ShieldCheck, X } from "lucide-react";
import type { Call } from "./api";
import { explorerTx, type ChallengeInfo } from "./chain";
import {
  checkProof,
  checkProofV2,
  downloadProof,
  isV2,
  payloadOf,
  VERIFIER_PUBLIC_KEY,
  type Check,
  type Proof,
  type ScoreSheetReply,
} from "./proofCheck";
import { Eyebrow, useEscape } from "./ui";

const explorerAddress = (address: string) => `https://explorer.solana.com/address/${address}?cluster=devnet`;

/**
 * "Check this result": for players of a settled challenge. Fetches the signed result and checks it
 * in the browser, against the hash Solana stored at payout. Crypto stays out of sight until asked for.
 */
export function ProofCard({ call, info }: { call: Call; info: ChallengeInfo }) {
  const [open, setOpen] = useState(false);
  const [reply, setReply] = useState<ScoreSheetReply | null>(null);
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onOpen() {
    setOpen(true);
    if (checks) return;
    try {
      const found = await call<ScoreSheetReply>("GET", `/challenges/${info.address}/score-sheet`);
      setReply(found);
      if (!found.proof) {
        setError("This challenge was paid out before signed results existed, so there is nothing to check.");
        return;
      }
      setChecks(
        isV2(found.proof)
          ? await checkProofV2(info.address, found, info)
          : await checkProof(info.address, found, info.scoreHash),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const v2 = !!reply?.proof && isV2(reply.proof);
  // v1 proofs end with an informational "Signed, not checked onchain" line that is neither good nor bad.
  const scored = checks?.filter((c) => !(c.ok === null && c.label.startsWith("Signed, not"))) ?? null;
  const allGood = scored?.every((c) => c.ok === true);
  const payload = reply?.proof && !isV2(reply.proof) ? payloadOf(reply.proof as Proof) : null;
  const proofV2 = reply?.proof && isV2(reply.proof) ? reply.proof : null;
  const payoutTx = proofV2?.settle_tx ?? reply?.transaction ?? null;

  return (
    <section className="card proof-card">
      <div className="card-title-row">
        <div>
          <Eyebrow>Proof of Sweat</Eyebrow>
          <h2 className="card-title">Check this result</h2>
          <p className="fine">Rules locked at creation → result signed → signature checked by Solana at payout.</p>
        </div>
        <span className="icon-tile">
          <ShieldCheck size={18} strokeWidth={1.75} aria-hidden />
        </span>
      </div>
      {!open ? (
        <button className="btn btn-quiet btn-block" onClick={onOpen}>
          Check result
        </button>
      ) : error ? (
        <div className="message">{error}</div>
      ) : !checks ? (
        <div className="message">Checking...</div>
      ) : (
        <>
          <ul className="proof-checks">
            {checks.map((c) => (
              <li key={c.label} className={c.ok === true ? "ok" : c.ok === false ? "bad" : "unknown"}>
                {c.ok === true ? (
                  <CircleCheck size={16} aria-hidden />
                ) : c.ok === false ? (
                  <CircleAlert size={16} aria-hidden />
                ) : (
                  <CircleHelp size={16} aria-hidden />
                )}
                <div>
                  <b>{c.label}</b>
                  <span>{c.detail}</span>
                </div>
              </li>
            ))}
          </ul>
          <p className={`message ${allGood ? "ok" : checks.some((c) => c.ok === false) ? "error" : ""}`}>
            {allGood
              ? v2
                ? "Everything checks out. Solana itself checked the signed result before paying."
                : "Everything checks out. Signed, not checked onchain (paid out before the program checked signatures)."
              : checks.some((c) => c.ok === false)
                ? "Something doesn't match. Don't trust this result."
                : "Some checks couldn't run in this browser."}
          </p>
          <details className="proof-details">
            <summary>Technical details</summary>
            <dl>
              {proofV2 ? (
                <>
                  <dt>Format</dt>
                  <dd>Proof of Sweat v2, checked onchain</dd>
                  <dt>Rules hash (SHA-256)</dt>
                  <dd className="mono">{proofV2.rules_hash}</dd>
                </>
              ) : (
                <>
                  <dt>Format</dt>
                  <dd>v1, signed, not checked onchain</dd>
                  <dt>Rules</dt>
                  <dd>{payload?.rules.version ?? "unknown"}</dd>
                </>
              )}
              <dt>Score sheet SHA-256</dt>
              <dd className="mono">{proofV2?.score_sheet_sha256 ?? payload?.score_sheet_sha256}</dd>
              <dt>Verifier key</dt>
              <dd className="mono">
                <a href={explorerAddress(VERIFIER_PUBLIC_KEY)} target="_blank" rel="noreferrer">
                  {VERIFIER_PUBLIC_KEY}
                </a>
              </dd>
              <dt>Signed</dt>
              <dd>{new Date((proofV2?.issued_at ?? payload?.issued_at ?? 0) * 1000).toLocaleString()}</dd>
            </dl>
            <p className="fine">
              The program pays only the winners and shares in a result signed by this key, under the rules locked at
              creation. That shows Rival's verifier approved the result; it does not prove a workout happened. Payouts and
              signatures use separate keys, both run by Rival's server. No workout details are in the proof or on
              Solana.
            </p>
          </details>
          <div className="btn-row">
            {payoutTx && (
              <a className="btn btn-text" href={explorerTx(payoutTx)} target="_blank" rel="noreferrer">
                Payout on Solana <ArrowUpRight size={13} aria-hidden />
              </a>
            )}
            {reply && (
              <button className="btn btn-text" onClick={() => downloadProof(info.address, reply)}>
                <Download size={14} aria-hidden /> Download proof
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}

/** "Connect a fitness app": not live yet. Says so plainly. No Strava button or logo until sign-in really works. */
export function ConnectFitness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="card connect-row" onClick={() => setOpen(true)}>
        <span className="icon-tile icon-tile-sm">
          <Link2 size={15} strokeWidth={1.75} aria-hidden />
        </span>
        <span className="connect-text">
          <b>Connect a fitness app</b>
          <span className="fine">Sync workouts from your watch automatically</span>
        </span>
        <span className="tag">Coming soon</span>
      </button>
      {open && <ComingSoon onClose={() => setOpen(false)} />}
    </>
  );
}

function ComingSoon({ onClose }: { onClose: () => void }) {
  useEscape(onClose);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-plain" role="dialog" aria-modal="true" aria-labelledby="connect-title" onClick={(e) => e.stopPropagation()}>
        <button className="icon-btn modal-close" onClick={onClose} aria-label="Close">
          <X size={16} aria-hidden />
        </button>
        <h2 id="connect-title" className="modal-title">
          Fitness sync is <em className="serif">coming.</em>
        </h2>
        <div className="modal-body">
          <p>
            Live sync with apps like Strava, Garmin and Apple Health is planned. In this demo, workouts are sample data
            or entered by hand.
          </p>
          <p>
            Every workout still goes through the same checks: inside the challenge dates, no copies, no overlaps, no
            impossible speeds. Hand-entered ones are marked as unverified.
          </p>
        </div>
        <button className="btn btn-primary btn-block btn-lg" onClick={onClose} autoFocus>
          Got it
        </button>
      </div>
    </div>
  );
}
