// Everything that talks to Solana from the browser. Devnet only.

import { Program } from "@anchor-lang/core";
import {
  getAccount,
  getAssociatedTokenAddressSync,
  TOKEN_PROGRAM_ID,
  TokenAccountNotFoundError,
} from "@solana/spl-token";
import { Connection, PublicKey } from "@solana/web3.js";
import idl from "../../onchain/idl/loser_buys.json";
import type { LoserBuys } from "../../onchain/idl/loser_buys.ts";

export const RPC_URL: string = import.meta.env.VITE_SOLANA_RPC_URL || "https://api.devnet.solana.com";
if (!RPC_URL.includes("devnet")) throw new Error("Devnet only. Refusing to use " + RPC_URL);

export const connection = new Connection(RPC_URL, "confirmed");
// Read-only program client: it builds transactions, the user's embedded wallet signs them.
const program = new Program<LoserBuys>(idl as LoserBuys, { connection });

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
};

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
  const c = await program.account.challenge.fetch(new PublicKey(address));
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
  };
}

/** Builds the unsigned "join this challenge" transaction, as bytes ready for the wallet to sign. */
export async function buildJoinTransaction(player: string, challenge: ChallengeInfo): Promise<Uint8Array> {
  const playerKey = new PublicKey(player);
  const tx = await program.methods
    .joinChallenge()
    .accountsPartial({
      player: playerKey,
      challenge: new PublicKey(challenge.address),
      vault: challenge.vault,
      playerToken: getAssociatedTokenAddressSync(challenge.mint, playerKey),
      tokenProgram: TOKEN_PROGRAM_ID,
    })
    .transaction();
  tx.feePayer = playerKey;
  tx.recentBlockhash = (await connection.getLatestBlockhash("confirmed")).blockhash;
  return new Uint8Array(tx.serialize({ requireAllSignatures: false, verifySignatures: false }));
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
  const logs = (e as { logs?: string[] } | null)?.logs;
  const text = (e instanceof Error ? e.message : String(e)) + " " + JSON.stringify(logs ?? "");
  if (/AlreadyJoined/.test(text)) return "You're already in this challenge.";
  if (/JoinClosed/.test(text)) return "This challenge has already started, so joining is closed.";
  if (/ChallengeFull/.test(text)) return "This challenge is full.";
  if (/ChallengeNotOpen/.test(text)) return "This challenge is over.";
  if (/insufficient funds|AccountNotInitialized|InvalidTokenAccount/i.test(text))
    return "You don't have enough in your balance yet. Add test funds first.";
  if (/429|Too Many Requests/i.test(text)) return "The network is busy. Wait a few seconds and try again.";
  if (/longer than usual/.test(text)) return (e as Error).message;
  return "That didn't go through. Please try again.";
}
