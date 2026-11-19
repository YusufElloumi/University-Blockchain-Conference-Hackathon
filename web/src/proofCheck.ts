// Proof of Sweat ("Proof of Effort" in the code and API), checked in the browser. Nothing here trusts our server's word for the result.
//
// v2 (challenges with locked rules): the signed bytes are rebuilt here from the readable fields
// (onchain/shared/proofMessage.ts, the same builder the program tests use), the Ed25519 signature is
// checked against the published verifier key, the rules and score hashes are compared with the ones
// stored on Solana, and the settlement transaction is read to confirm Solana's Ed25519 program checked
// this exact message right before our program paid out.
//
// v1 (older challenges): signed JSON, checked here only. Labelled "Signed, not checked onchain".
//
// What a proof does not show: that a workout really happened. It shows our verifier approved the result.

import { PublicKey } from "@solana/web3.js";
import { proofMessageV2 } from "../../onchain/shared/proofMessage";
import { connection, PROGRAM_ID, sha256Hex, type ChallengeInfo } from "./chain";

export const VERIFIER_PUBLIC_KEY = "5hapcEHu65LyQhqD3Tqtrwm1ftzBnAm93c6jnc8gcway";
const DOMAIN = "rival.proof-of-effort";

export type Proof = { message: string; signature: string; verifier: string };

/** A v2 proof: readable fields, plus the exact signed bytes (base64) the program read at payout. */
export type ProofV2 = {
  schema: 2;
  domain: string;
  cluster: string;
  program: string;
  challenge: string;
  rules_hash: string;
  score_sheet_sha256: string;
  payout: { wallet: string; bps: number }[];
  message: string; // base64
  signature: string; // hex
  verifier: string;
  issued_at: number;
  settle_tx: string | null;
  checked_onchain: true;
};

export type AnyProof = Proof | ProofV2;
export const isV2 = (proof: AnyProof): proof is ProofV2 => (proof as ProofV2).schema === 2;

export type ScoreSheetReply = {
  sheet: Record<string, unknown>;
  canonical: string; // the exact text that was hashed
  payout: { note: string; shares_bps: Record<string, number> };
  sha256: string;
  transaction: string | null;
  proof: AnyProof | null;
  proof_problems: string[] | null;
  ruleset: string | null; // the locked ruleset text (v2 proofs name its hash)
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


/** Ed25519 signature check with the browser's own crypto. null when the browser cannot do Ed25519. */
async function ed25519Valid(verifier: string, signatureHex: string, message: Uint8Array<ArrayBuffer>): Promise<boolean | null> {
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      new Uint8Array(new PublicKey(verifier).toBytes()),
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    return await crypto.subtle.verify({ name: "Ed25519" }, key, fromHex(signatureHex), message);
  } catch {
    return null;
  }
}

const signatureValid = (proof: Proof) => ed25519Valid(proof.verifier, proof.signature, new TextEncoder().encode(proof.message));

function fromBase64(text: string): Uint8Array<ArrayBuffer> {
  const raw = atob(text);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

const sameBytes = (a: Uint8Array, b: Uint8Array) => a.length === b.length && a.every((x, i) => x === b[i]);

const ED25519_PROGRAM = "Ed25519SigVerify111111111111111111111111111";

/**
 * Reads the settlement transaction from Solana and confirms the payout instruction of our program came
 * right after Solana's Ed25519 check of exactly this message (the program refuses anything else).
 * Returns null when the transaction cannot be read right now.
 */
async function checkedAtPayout(signature: string, message: Uint8Array): Promise<boolean | null> {
  try {
    const tx = await connection.getTransaction(signature, { maxSupportedTransactionVersion: 0, commitment: "confirmed" });
    if (!tx) return null;
    if (tx.meta?.err) return false;
    const keys = tx.transaction.message.staticAccountKeys.map((k) => k.toBase58());
    const ixs = tx.transaction.message.compiledInstructions;
    const pay = ixs.findIndex((ix) => keys[ix.programIdIndex] === PROGRAM_ID.toBase58());
    if (pay < 1 || keys[ixs[pay - 1].programIdIndex] !== ED25519_PROGRAM) return false;
    const data = ixs[pay - 1].data;
    const at = data[10] | (data[11] << 8); // message offset in the Ed25519 instruction
    const size = data[12] | (data[13] << 8);
    return sameBytes(data.slice(at, at + size), message);
  } catch {
    return null;
  }
}

/** Every check for a v2 proof. `info` is the challenge as read from Solana by this browser. */
export async function checkProofV2(address: string, reply: ScoreSheetReply, info: ChallengeInfo): Promise<Check[]> {
  const proof = reply.proof as ProofV2;
  const message = fromBase64(proof.message);
  let rebuilt: Uint8Array | null = null;
  try {
    rebuilt = proofMessageV2({
      program: PROGRAM_ID.toBytes(),
      challenge: new PublicKey(address).toBytes(),
      rulesHash: fromHex(proof.rules_hash),
      scoreHash: fromHex(proof.score_sheet_sha256),
      winners: proof.payout.map((p) => new PublicKey(p.wallet).toBytes()),
      sharesBps: proof.payout.map((p) => p.bps),
    });
  } catch {
    rebuilt = null;
  }
  const readableIsSigned = !!rebuilt && sameBytes(rebuilt, message);
  const signed = await ed25519Valid(proof.verifier, proof.signature, message);
  const byUs = proof.verifier === VERIFIER_PUBLIC_KEY && info.rules?.verifier === VERIFIER_PUBLIC_KEY;
  const rulesText = reply.ruleset ? await sha256Hex(reply.ruleset) : null;
  const rulesOk = rulesText === proof.rules_hash && info.rules?.rulesHash === proof.rules_hash;
  const sheetHash = await sha256Hex(reply.canonical);
  const chainHash = hex(new Uint8Array(info.scoreHash));
  const atPayout = proof.settle_tx ? await checkedAtPayout(proof.settle_tx, message) : null;
  return [
    {
      label: "Rules locked at creation",
      ok: rulesOk,
      detail: rulesOk
        ? "The published rules hash to the value locked on Solana before anyone paid, and the result names them."
        : !info.rules
          ? "This challenge has no rules account on Solana."
          : "The rules don't match the hash locked on Solana.",
    },
    {
      label: "Result signed by Rival's verifier",
      ok: signed === null ? null : signed && byUs && readableIsSigned,
      detail:
        signed === null
          ? "This browser can't check Ed25519 signatures. Download the proof and run attest.py verify."
          : !byUs
            ? `Signed by a key that isn't the published verifier (${proof.verifier}).`
            : !readableIsSigned
              ? "The readable result is not what was signed, or it names another challenge or program."
              : signed
                ? "The signature matches the published verifier key, for this challenge and program only."
                : "The signature does not match the result.",
    },
    {
      label: "Signature checked by Solana at payout",
      ok: atPayout,
      detail:
        atPayout === null
          ? "Couldn't read the payout transaction right now. Try again, or open it on the explorer."
          : atPayout
            ? "Solana's Ed25519 check ran on exactly this result right before the program paid out."
            : "The payout transaction does not carry this signed result.",
    },
    {
      label: "Scores unchanged since payout",
      ok: sheetHash === proof.score_sheet_sha256 && sheetHash === chainHash,
      detail:
        sheetHash !== chainHash
          ? "The score sheet does not match the fingerprint stored on Solana."
          : sheetHash !== proof.score_sheet_sha256
            ? "The signed fingerprint differs from the score sheet."
            : "The score sheet's fingerprint matches the one stored on Solana at payout.",
    },
  ];
}

/** Runs every check on a v1 proof. `onchainHash` is the challenge account's `score_hash`, read from Solana by the browser. */
export async function checkProof(address: string, reply: ScoreSheetReply, onchainHash: number[]): Promise<Check[]> {
  const proof = reply.proof as Proof;
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
    {
      label: "Signed, not checked onchain",
      ok: null,
      detail: "This challenge was paid out before the program checked signatures, so only this browser checked it.",
    },
  ];
}

export function payloadOf(proof: Proof): ProofPayload {
  return JSON.parse(proof.message) as ProofPayload;
}

/** The proof and score sheet as a file, for `python attest.py verify <file>`. */
export function downloadProof(address: string, reply: ScoreSheetReply) {
  const file = { proof: reply.proof, sheet: reply.sheet, ...(reply.ruleset ? { ruleset: reply.ruleset } : {}) };
  const blob = new Blob([JSON.stringify(file, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `rival-proof-${address.slice(0, 8)}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}
