import { useEffect, useState } from "react";
import { ArrowUpRight, CircleAlert, CircleCheck, Lock } from "lucide-react";
import { rulesAddress, sha256Hex, type ChallengeInfo } from "./chain";
import { termLabel } from "./JoinIntro";
import { PublicKey } from "@solana/web3.js";
import { Eyebrow } from "./ui";

const explorerAddress = (address: string) => `https://explorer.solana.com/address/${address}?cluster=devnet`;

/** The ruleset fields we show (api/rules.py builds them). */
type Ruleset = {
  mode: string;
  length_seconds: number;
  max_players: number;
  scoring: { source: string; version: string; sha256: string | null; stat_weights: Record<string, number> | null };
  workouts: { count: string[]; never_count: string[] };
  consent_required: boolean;
  format: { name: string } & Record<string, unknown>;
  payout: { kind: string; split_bps: number[] };
  prediction_rounds: { themes: string[]; round_hours: number } | null;
  verifier: string;
};

const PAYOUT_WORDS: Record<string, string> = {
  winner_takes_all: "winner takes all",
  goal: "an equal split among everyone who reaches the goal",
  teams: "an equal split across the winning team",
};

/** "Payout locked onchain: 60 / 30 / 10." Read from the Rules account on Solana, not from our server. */
export function payoutLockedLine(info: ChallengeInfo): string | null {
  const rules = info.rules;
  if (!rules) return null;
  const terms = rules.payout === "podium" ? rules.splitBps.map((b) => b / 100).join(" / ") : PAYOUT_WORDS[rules.payout];
  return `Payout locked onchain: ${terms}. Not even Rival can change it.`;
}

/**
 * The rules this challenge was created with, in plain words, and whether they match the hash stored
 * on Solana. The browser hashes the rules text itself, so the server can't show one thing and lock another.
 */
export function LockedRulesCard({ info, ruleset }: { info: ChallengeInfo; ruleset: string | null }) {
  const [hash, setHash] = useState<string | null>(null);
  useEffect(() => {
    if (ruleset) sha256Hex(ruleset).then(setHash);
  }, [ruleset]);

  if (!info.rules || !ruleset) {
    return (
      <section className="card rules-card">
        <Eyebrow>Rules</Eyebrow>
        <p className="fine">
          This challenge was created before rules were locked onchain. It can't be paid out by the current program; every
          entry fee is refunded 72 hours after it ends.
        </p>
      </section>
    );
  }

  const r = JSON.parse(ruleset) as Ruleset;
  const matches = hash === null ? null : hash === info.rules.rulesHash;
  const lockedLine = payoutLockedLine(info);
  const rows: [string, string][] = [
    [
      "Scoring",
      r.scoring.source === "league_stats"
        ? `League stats (${Object.entries(r.scoring.stat_weights ?? {})
            .filter(([, v]) => v > 0)
            .map(([k, v]) => `${v} per ${k.replace(/s$/, "")}`)
            .join(", ")})`
        : `Daily Mover rules, version ${r.scoring.version}`,
    ],
    ["Workouts that count", "Passed checks and hand-typed (marked unverified). Rejected ones never count."],
    ["Runs for", termLabel(r.length_seconds * 1000)],
    ["Players", `Up to ${r.max_players}. Only players who agree to share their points can score.`],
    [
      "Prediction picks",
      r.prediction_rounds
        ? `${r.prediction_rounds.round_hours === 24 ? "Daily" : "Weekly"}: ${r.prediction_rounds.themes.join(", ")}`
        : "Off",
    ],
    ["Result signed by", `${r.verifier.slice(0, 4)}...${r.verifier.slice(-4)} (Rival's verifier key)`],
  ];

  return (
    <section className="card rules-card">
      <div className="card-title-row">
        <div>
          <Eyebrow>Rules locked onchain</Eyebrow>
          <h2 className="card-title">Set before anyone paid</h2>
        </div>
        <span className="icon-tile">
          <Lock size={17} strokeWidth={1.75} aria-hidden />
        </span>
      </div>
      {lockedLine && <p className="rules-locked-line">{lockedLine}</p>}
      <dl className="rules-list">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <p className={`rules-match ${matches === false ? "bad" : matches ? "ok" : ""}`}>
        {matches === false ? <CircleAlert size={15} aria-hidden /> : <CircleCheck size={15} aria-hidden />}
        {matches === null
          ? "Checking these rules against Solana..."
          : matches
            ? "These rules match the fingerprint stored on Solana. Your entry is tied to them."
            : "These rules don't match the fingerprint on Solana. Don't join."}
      </p>
      <details className="proof-details">
        <summary>Technical details</summary>
        <dl>
          <dt>Rules hash (SHA-256)</dt>
          <dd className="mono">{info.rules.rulesHash}</dd>
          <dt>Rules account</dt>
          <dd className="mono">
            <a href={explorerAddress(rulesAddress(new PublicKey(info.address)).toBase58())} target="_blank" rel="noreferrer">
              View on Solana <ArrowUpRight size={12} aria-hidden />
            </a>
          </dd>
        </dl>
        <p className="fine">
          The program checks the payout against these rules and requires the verifier's signature on the result. It can't
          check that a workout really happened.
        </p>
      </details>
    </section>
  );
}
