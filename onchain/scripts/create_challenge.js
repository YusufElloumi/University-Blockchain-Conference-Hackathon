// Creates one open challenge on devnet for trying the web app, and prints its address.
// Run from the repo root (PowerShell):
//   wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh create-challenge
//
// Optional settings: BUY_IN_USDC (default 1), START_IN_HOURS (default 48), LENGTH_HOURS (default 168).
// The treasury wallet is the creator and pays the small account fee. Nobody has joined yet.
//
// Rules are locked onchain at creation. The ruleset comes from the API, so its hash is exactly what
// the API will check on the first join (the default public, winner-takes-all rules):
//   RULES_JSON  the output of `python rules.py default <length hours>` (wsl_anchor.sh fills this in
//               by running the API's Windows venv), or
//   RULES_API   an API address, e.g. https://loser-buys-api.onrender.com (calls POST /rules).

const fs = require("fs");
const os = require("os");
const path = require("path");
const anchor = require("@anchor-lang/core");
const { TOKEN_PROGRAM_ID } = require("@solana/spl-token");
const idl = require("../idl/loser_buys.json");

const { Connection, Keypair, PublicKey, SystemProgram } = anchor.web3;
const BN = anchor.BN;

const RPC_URL = process.env.SOLANA_RPC_URL || "https://api.devnet.solana.com";
const USDC_MINT = new PublicKey(process.env.USDC_MINT || "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU");
const KEY_DIR = process.env.KEY_DIR || path.join(os.homedir(), ".config", "solana", "loser-buys");
const BUY_IN = Math.round(Number(process.env.BUY_IN_USDC || 1) * 1e6);
const START_IN = Math.round(Number(process.env.START_IN_HOURS || 48) * 3600);
const LENGTH = Math.round(Number(process.env.LENGTH_HOURS || 168) * 3600);

async function lockedRules() {
  if (process.env.RULES_JSON) return JSON.parse(process.env.RULES_JSON);
  if (!process.env.RULES_API) throw new Error("Set RULES_JSON or RULES_API (see the top of this file)");
  const reply = await fetch(process.env.RULES_API.replace(/\/$/, "") + "/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "public", format: "winner_takes_all", length_seconds: LENGTH, max_players: 8 }),
  });
  if (!reply.ok) throw new Error("POST /rules failed: " + (await reply.text()));
  return reply.json();
}

if (!RPC_URL.includes("devnet")) throw new Error("Devnet only. Refusing to run against " + RPC_URL);

const loadKeypair = (name) =>
  Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(path.join(KEY_DIR, name + ".json"), "utf8"))));

async function main() {
  const connection = new Connection(RPC_URL, "confirmed");
  const treasury = loadKeypair("treasury");
  const oracle = loadKeypair("oracle");
  const provider = new anchor.AnchorProvider(connection, new anchor.Wallet(treasury), { commitment: "confirmed" });
  const program = new anchor.Program(idl, provider);

  const id = new BN(Date.now());
  const [challenge] = PublicKey.findProgramAddressSync(
    [Buffer.from("challenge"), treasury.publicKey.toBuffer(), id.toArrayLike(Buffer, "le", 8)],
    program.programId
  );
  const [vault] = PublicKey.findProgramAddressSync([Buffer.from("vault"), challenge.toBuffer()], program.programId);
  const [rules] = PublicKey.findProgramAddressSync([Buffer.from("rules"), challenge.toBuffer()], program.programId);
  const locked = await lockedRules();
  if (JSON.parse(locked.ruleset).length_seconds !== LENGTH) throw new Error("The ruleset is for a different length");
  const now = await connection.getBlockTime(await connection.getSlot());
  const signature = await program.methods
    .createChallenge(id, new BN(BUY_IN), new BN(now + START_IN), new BN(now + START_IN + LENGTH), 8, oracle.publicKey,
      Array.from(Buffer.from(locked.rules_hash, "hex")), new PublicKey(locked.verifier), { winnerTakesAll: {} }, [])
    .accountsPartial({
      creator: treasury.publicKey,
      challenge,
      mint: USDC_MINT,
      vault,
      rules,
      tokenProgram: TOKEN_PROGRAM_ID,
      systemProgram: SystemProgram.programId,
    })
    .rpc();
  console.log("create_challenge:", `https://explorer.solana.com/tx/${signature}?cluster=devnet`);
  console.log("Buy-in:", BUY_IN / 1e6, "USDC. Joining closes in", START_IN / 3600, "hours.");
  console.log("Rules locked:", locked.rules_hash, "(public, winner takes all)");
  console.log("CHALLENGE=" + challenge.toBase58());
}

main().catch((e) => {
  console.error("FAILED:", e);
  process.exit(1);
});
