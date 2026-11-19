// Everything that talks to Solana from the browser. Devnet only.

import { BN, Program } from "@anchor-lang/core";
import { Buffer } from "buffer";
import {
  getAccount,
  getAssociatedTokenAddressSync,
  TOKEN_PROGRAM_ID,
  TokenAccountNotFoundError,
} from "@solana/spl-token";
import { Connection, PublicKey, SystemProgram } from "@solana/web3.js";
import idl from "../../onchain/idl/loser_buys.json";
import type { LoserBuys } from "../../onchain/idl/loser_buys.ts";

export const RPC_URL: string = import.meta.env.VITE_SOLANA_RPC_URL || "https://api.devnet.solana.com";
if (!RPC_URL.includes("devnet")) throw new Error("Devnet only. Refusing to use " + RPC_URL);

export const connection = new Connection(RPC_URL, "confirmed");
// Read-only program client: it builds transactions, the user's embedded wallet signs them.
const program = new Program<LoserBuys>(idl as LoserBuys, { connection });
export const PROGRAM_ID = program.programId;

const USDC_DECIMALS = 6;
const toDollars = (units: bigint | number | string) => Number(units) / 10 ** USDC_DECIMALS;

export const explorerTx = (signature: string) => `https://explorer.solana.com/tx/${signature}?cluster=devnet`;

export type ChallengeInfo = {
  address: string;
  buyIn: number; // dollars
  pool: number; // dollars
  players: string[];
  maxPlayers: number;
  startTime: Date;
  endTime: Date;
  status: "open" | "settled" | "refunded";
  mint: PublicKey;
  vault: PublicKey;
  scoreHash: number[]; // SHA-256 of the final score sheet, set by `settle`; all zeros before
  rules: LockedRules | null; // null: created before rules were locked onchain
};

/** The challenge's Rules account: written once at creation, never changed. */
export type LockedRules = {
  rulesHash: string; // hex SHA-256 of the canonical ruleset text
  verifier: string;
  payout: "winner_takes_all" | "podium" | "goal" | "teams";
  splitBps: number[]; // podium places in basis points
};

const PAYOUT_KINDS = ["winner_takes_all", "podium", "goal", "teams"] as const;
const camel = { winner_takes_all: "winnerTakesAll", podium: "podium", goal: "goal", teams: "teams" } as const;

export const toHex = (bytes: ArrayLike<number>) =>
  Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");

/** SHA-256 of a text, as hex. Used to hash the ruleset the player is shown before they pay. */
export async function sha256Hex(text: string): Promise<string> {
  return toHex(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))));
}

export const rulesAddress = (challenge: PublicKey) =>
  PublicKey.findProgramAddressSync([Buffer.from("rules"), challenge.toBuffer()], program.programId)[0];

export async function fetchRules(challenge: PublicKey): Promise<LockedRules | null> {
  const r = await program.account.rules.fetchNullable(rulesAddress(challenge));
  if (!r) return null;
  const kind = Object.keys(r.payout)[0];
  return {
    rulesHash: toHex(r.rulesHash),
    verifier: r.verifier.toBase58(),
    payout: PAYOUT_KINDS.find((k) => camel[k] === kind) ?? "winner_takes_all",
    splitBps: Array.from(r.splitBps).filter((s) => s > 0),
  };
}

/** A wallet's balance of the given token in dollars; 0 when it has never held any. */
export async function tokenBalance(owner: string, mint: PublicKey): Promise<number> {
  try {
    const account = await getAccount(connection, getAssociatedTokenAddressSync(mint, new PublicKey(owner)));
    return toDollars(account.amount);
  } catch (e) {
    if (e instanceof TokenAccountNotFoundError) return 0;
    throw e;
  }
}

export async function fetchChallenge(address: string): Promise<ChallengeInfo> {
  const key = new PublicKey(address);
  const [c, rules] = await Promise.all([program.account.challenge.fetch(key), fetchRules(key)]);
  const vault = await getAccount(connection, c.vault);
  return {
    address,
    buyIn: toDollars(c.buyIn.toString()),
    pool: toDollars(vault.amount),
    players: c.players.map((p) => p.toBase58()),
    maxPlayers: c.maxPlayers,
    startTime: new Date(c.startTime.toNumber() * 1000),
    endTime: new Date(c.endTime.toNumber() * 1000),
    status: Object.keys(c.status)[0] as ChallengeInfo["status"],
    mint: c.mint,
    vault: c.vault,
    scoreHash: Array.from(c.scoreHash),
    rules,
  };
}

/**
 * Builds the unsigned "join this challenge" transaction, as bytes ready for the wallet to sign.
 * `shownRulesHash` is the hash of the ruleset text this browser showed the player (hashed here, not
 * taken from the server). The program refuses the deposit unless it equals the hash locked at creation.
 */
export async function buildJoinTransaction(
  player: string,
  challenge: ChallengeInfo,
  shownRulesHash: string,
): Promise<Uint8Array> {
  const playerKey = new PublicKey(player);
  const key = new PublicKey(challenge.address);
  const tx = await program.methods
    .joinChallenge(Array.from(Buffer.from(shownRulesHash, "hex")))
    .accountsPartial({
      player: playerKey,
      challenge: key,
      vault: challenge.vault,
      rules: rulesAddress(key),
      playerToken: getAssociatedTokenAddressSync(challenge.mint, playerKey),
      tokenProgram: TOKEN_PROGRAM_ID,
    })
    .transaction();
  tx.feePayer = playerKey;
  tx.recentBlockhash = (await connection.getLatestBlockhash("confirmed")).blockhash;
  return new Uint8Array(tx.serialize({ requireAllSignatures: false, verifySignatures: false }));
}

export type NewChallenge = {
  buyIn: number; // dollars
  joinWindowSeconds: number; // how long people can join before it starts
  lengthSeconds: number;
  oracle: string; // the server's address that is allowed to report results
  mint: string;
  // From POST /rules: locked onchain at creation, never changeable.
  rulesHash: string; // hex
  verifier: string; // the key whose signature the program requires at payout
  payout: LockedRules["payout"];
  splitBps: number[]; // podium only
};

/** Builds the unsigned "create a challenge" transaction. Returns it with the new challenge's address. */
export async function buildCreateTransaction(
  creator: string,
  options: NewChallenge,
): Promise<{ transaction: Uint8Array; address: string }> {
  const creatorKey = new PublicKey(creator);
  const id = new BN(Date.now());
  // The challenge and its prize vault live at addresses worked out from the creator and this ID.
  const [challenge] = PublicKey.findProgramAddressSync(
    [Buffer.from("challenge"), creatorKey.toBuffer(), id.toArrayLike(Buffer, "le", 8)],
    program.programId,
  );
  const [vault] = PublicKey.findProgramAddressSync([Buffer.from("vault"), challenge.toBuffer()], program.programId);
  const rules = rulesAddress(challenge);
  // Use the network's clock, not this device's, because the program checks times against the network.
  const chainNow = await connection.getBlockTime(await connection.getSlot()).catch(() => null);
  const start = (chainNow ?? Math.floor(Date.now() / 1000)) + options.joinWindowSeconds;
  const tx = await program.methods
    .createChallenge(
      id,
      new BN(Math.round(options.buyIn * 10 ** USDC_DECIMALS)),
      new BN(start),
      new BN(start + options.lengthSeconds),
      8,
      new PublicKey(options.oracle),
      Array.from(Buffer.from(options.rulesHash, "hex")),
      new PublicKey(options.verifier),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { [camel[options.payout]]: {} } as any,
      options.splitBps,
    )
    .accountsPartial({
      creator: creatorKey,
      challenge,
      mint: new PublicKey(options.mint),
      vault,
      rules,
      tokenProgram: TOKEN_PROGRAM_ID,
      systemProgram: SystemProgram.programId,
    })
    .transaction();
  tx.feePayer = creatorKey;
  tx.recentBlockhash = (await connection.getLatestBlockhash("confirmed")).blockhash;
  return {
    transaction: new Uint8Array(tx.serialize({ requireAllSignatures: false, verifySignatures: false })),
    address: challenge.toBase58(),
  };
}

/** Sends a signed transaction and waits until the network confirms it. Returns its signature. */
export async function sendAndConfirm(signedTransaction: Uint8Array): Promise<string> {
  const signature = await connection.sendRawTransaction(signedTransaction, { preflightCommitment: "confirmed" });
  for (let i = 0; i < 40; i++) {
    const status = (await connection.getSignatureStatuses([signature])).value[0];
    if (status?.err) throw new Error("Transaction failed: " + JSON.stringify(status.err));
    if (status?.confirmationStatus === "confirmed" || status?.confirmationStatus === "finalized") return signature;
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error("This is taking longer than usual. Refresh in a minute to see if it went through.");
}

/** Turns a program or network error into a sentence a person can act on. */
export function friendlyError(e: unknown): string {
  // Errors from our own server already carry a sentence written for people.
  if (e instanceof Error && "status" in e) return e.message;
  const logs = (e as { logs?: string[] } | null)?.logs;
  const text = (e instanceof Error ? e.message : String(e)) + " " + JSON.stringify(logs ?? "");
  if (/AlreadyJoined/.test(text)) return "You're already in this challenge.";
  if (/RulesMismatch/.test(text))
    return "The rules you were shown don't match the rules locked for this challenge, so nothing was paid.";
  if (/AccountNotInitialized.*rules|rules.*AccountNotInitialized/is.test(text))
    return "This challenge was created before rules were locked, so it can't take new players.";
  if (/JoinClosed/.test(text)) return "This challenge has already started, so joining is closed.";
  if (/ChallengeFull/.test(text)) return "This challenge is full.";
  if (/ChallengeNotOpen/.test(text)) return "This challenge is over.";
  if (/insufficient funds|AccountNotInitialized|InvalidTokenAccount/i.test(text))
    return "You don't have enough in your balance yet. Add devnet USDC first.";
  if (/429|Too Many Requests/i.test(text)) return "The network is busy. Wait a few seconds and try again.";
  if (/InvalidTimes/.test(text)) return "Those dates don't work. Pick a start time a little further away.";
  if (/longer than usual|still loading|sign in again|before rules were locked|rules shown here/.test(text))
    return (e as Error).message;
  return "That didn't go through. Please try again.";
}
