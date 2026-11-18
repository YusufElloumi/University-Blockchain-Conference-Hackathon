// Proof of Sweat ("Proof of Effort" in the code and API), checked in the browser. Nothing here trusts our server's word for the result:
//   1. the signature is checked against the verifier key published below (and in the README);
//   2. the proof must name this challenge, our program and devnet;
//   3. the score sheet is hashed here and compared with the hash stored onchain by `settle`.
// What a proof does not show: that a workout really happened. It shows our verifier approved the result.

import { PublicKey } from "@solana/web3.js";
import { PROGRAM_ID } from "./chain";

export const VERIFIER_PUBLIC_KEY = "5hapcEHu65LyQhqD3Tqtrwm1ftzBnAm93c6jnc8gcway";
const DOMAIN = "rival.proof-of-effort";

export type Proof = { message: string; signature: string; verifier: string };

export type ScoreSheetReply = {
  sheet: Record<string, unknown>;
  canonical: string; // the exact text that was hashed
  payout: { note: string; shares_bps: Record<string, number> };
  sha256: string;
  transaction: string | null;
  proof: Proof | null;
  proof_problems: string[] | null;
};

export type ProofPayload = {
  schema: number;
  domain: string;
  cluster: string;
  program: string;
  challenge: string;
  rules: { name: string | null; version: string | null; sha256: string | null };
  score_sheet_sha256: string;
  payout: { wallet: string; bps: number }[];
  issued_at: number;
  nonce: string;
  verifier: string;
};

export type Check = { label: string; ok: boolean | null; detail: string };

const hex = (bytes: Uint8Array) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");

function fromHex(text: string): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(text.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(text.slice(i * 2, i * 2 + 2), 16);
  return out;
}

async function sha256Hex(text: string): Promise<string> {
  return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))));
}

/** Ed25519 signature check with the browser's own crypto. null when the browser cannot do Ed25519. */
async function signatureValid(proof: Proof): Promise<boolean | null> {
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      new Uint8Array(new PublicKey(proof.verifier).toBytes()),
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    return await crypto.subtle.verify({ name: "Ed25519" }, key, fromHex(proof.signature), new TextEncoder().encode(proof.message));
  } catch {
    return null;
  }
}

/** Runs every check. `onchainHash` is the challenge account's `score_hash`, read from Solana by the browser. */
export async function checkProof(address: string, reply: ScoreSheetReply, onchainHash: number[]): Promise<Check[]> {
  const proof = reply.proof!;
  const payload = JSON.parse(proof.message) as ProofPayload;
  const signed = await signatureValid(proof);
  const byUs = proof.verifier === VERIFIER_PUBLIC_KEY && payload.verifier === VERIFIER_PUBLIC_KEY;
  const sheetHash = await sha256Hex(reply.canonical);
  const chainHash = hex(new Uint8Array(onchainHash));
  const bound =
    payload.domain === DOMAIN &&
    payload.cluster === "devnet" &&
    payload.program === PROGRAM_ID.toBase58() &&
    payload.challenge === address;
  return [
    {
      label: "Signed by Rival's verifier",
      ok: signed === null ? null : signed && byUs,
      detail:
        signed === null
          ? "This browser can't check Ed25519 signatures. Download the proof and run attest.py verify."
          : !byUs
            ? `Signed by an unknown key (${proof.verifier}).`
            : signed
              ? "The signature matches the published verifier key."
              : "The signature does not match the message.",
    },
    {
      label: "Made for this challenge only",
      ok: bound,
      detail: bound
        ? "It names this challenge, the Rival program and devnet, so it can't be reused anywhere else."
        : "It names a different challenge, program or network.",
    },
    {
      label: "Scores unchanged since payout",
      ok: sheetHash === payload.score_sheet_sha256 && sheetHash === chainHash,
      detail:
        sheetHash !== chainHash
          ? "The score sheet does not match the fingerprint stored on Solana."
          : sheetHash !== payload.score_sheet_sha256
            ? "The signed fingerprint differs from the score sheet."
            : "The score sheet's fingerprint matches the one stored on Solana at payout.",
    },
  ];
}

export function payloadOf(proof: Proof): ProofPayload {
  return JSON.parse(proof.message) as ProofPayload;
}

/** The proof and score sheet as a file, for `python attest.py verify <file>`. */
export function downloadProof(address: string, reply: ScoreSheetReply) {
  const blob = new Blob([JSON.stringify({ proof: reply.proof, sheet: reply.sheet }, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `rival-proof-${address.slice(0, 8)}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}
