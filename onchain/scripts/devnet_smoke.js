// Devnet smoke test: runs the whole flow against the deployed program with real devnet USDC.
//   create challenge (rules locked) -> player 1 joins -> player 2 joins -> oracle ends early
//   -> oracle settles with the verifier's Ed25519-signed result in the same transaction
// Run from onchain/:  node scripts/devnet_smoke.js
//
// Uses test money only. Reads keypair files from ~/.config/solana/loser-buys/ (never from the repo).
// The treasury tops up the oracle and two reusable test players, so it needs a little SOL and USDC.

const fs = require("fs");
const os = require("os");
const path = require("path");
const anchor = require("@anchor-lang/core");
const {
  getAccount,
  getOrCreateAssociatedTokenAccount,
  transfer,
  TOKEN_PROGRAM_ID,
} = require("@solana/spl-token");
const idl = require("../idl/loser_buys.json");

const { Connection, Keypair, PublicKey, SystemProgram, Transaction, LAMPORTS_PER_SOL, Ed25519Program } = anchor.web3;
const sha256 = (text) => require("crypto").createHash("sha256").update(text).digest();

/** The Proof of Sweat v2 message (layout in onchain/shared/proofMessage.ts and docs/ARCHITECTURE.md). */
function proofMessageV2(program, challenge, rulesHash, scoreHash, winners, sharesBps) {
  const shares = Buffer.alloc(2 * sharesBps.length);
  sharesBps.forEach((s, i) => shares.writeUInt16LE(s, 2 * i));
  return Buffer.concat([
    Buffer.from("rival.proof-of-effort.v2"), program.toBuffer(), challenge.toBuffer(), Buffer.from(rulesHash),
    Buffer.from(scoreHash), Buffer.from([winners.length]), ...winners.map((w) => w.toBuffer()), shares,
  ]);
}
const BN = anchor.BN;

const RPC_URL = process.env.SOLANA_RPC_URL || "https://api.devnet.solana.com";
const USDC_MINT = new PublicKey(process.env.USDC_MINT || "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU");
const KEY_DIR = process.env.KEY_DIR || path.join(os.homedir(), ".config", "solana", "loser-buys");
const BUY_IN = 500_000; // 0.50 USDC (USDC has 6 decimals)
const MIN_SOL = 0.02 * LAMPORTS_PER_SOL;

if (!RPC_URL.includes("devnet")) throw new Error("Devnet only. Refusing to run against " + RPC_URL);

function loadKeypair(name, createIfMissing = false) {
  const file = path.join(KEY_DIR, name + ".json");
  if (!fs.existsSync(file)) {
    if (!createIfMissing) throw new Error("Missing keypair file: " + file);
    fs.writeFileSync(file, JSON.stringify(Array.from(Keypair.generate().secretKey)), { mode: 0o600 });
  }
  return Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(file, "utf8"))));
}

const link = (sig) => `https://explorer.solana.com/tx/${sig}?cluster=devnet`;
const usdc = (n) => (Number(n) / 1e6).toFixed(2) + " USDC";

async function main() {
  const connection = new Connection(RPC_URL, "confirmed");
  const treasury = loadKeypair("treasury");
  const oracle = loadKeypair("oracle");
  const verifier = loadKeypair("verifier");
  const player1 = loadKeypair("smoke-player-1", true);
  const player2 = loadKeypair("smoke-player-2", true);

  const provider = new anchor.AnchorProvider(connection, new anchor.Wallet(treasury), { commitment: "confirmed" });
  const program = new anchor.Program(idl, provider);
  console.log("Program:  ", program.programId.toBase58());
  console.log("Oracle:   ", oracle.publicKey.toBase58());
  console.log("Player 1: ", player1.publicKey.toBase58());
  console.log("Player 2: ", player2.publicKey.toBase58());

  // 1. Top up fees (SOL) and buy-in money (USDC) from the treasury where needed.
  const topUp = new Transaction();
  for (const kp of [oracle, player1, player2]) {
    if ((await connection.getBalance(kp.publicKey)) < MIN_SOL) {
      topUp.add(SystemProgram.transfer({ fromPubkey: treasury.publicKey, toPubkey: kp.publicKey, lamports: 0.05 * LAMPORTS_PER_SOL }));
    }
  }
  if (topUp.instructions.length > 0) console.log("SOL top-up:", link(await provider.sendAndConfirm(topUp)));

  const treasuryToken = await getOrCreateAssociatedTokenAccount(connection, treasury, USDC_MINT, treasury.publicKey);
  const tokens = {};
  for (const kp of [player1, player2]) {
    const ata = await getOrCreateAssociatedTokenAccount(connection, treasury, USDC_MINT, kp.publicKey);
    tokens[kp.publicKey.toBase58()] = ata.address;
    if (Number(ata.amount) < BUY_IN) {
      const sig = await transfer(connection, treasury, treasuryToken.address, ata.address, treasury, 2 * BUY_IN);
      console.log("USDC top-up:", link(sig));
    }
  }
  const tokenOf = (kp) => tokens[kp.publicKey.toBase58()];
  const balance = async (kp) => (await getAccount(connection, tokenOf(kp))).amount;
  const before1 = await balance(player1);
  const before2 = await balance(player2);
  console.log(`Before:    player 1 has ${usdc(before1)}, player 2 has ${usdc(before2)}`);

  // 2. Create the challenge (player 1 is the group creator).
  const id = new BN(Date.now());
  const [challenge] = PublicKey.findProgramAddressSync(
    [Buffer.from("challenge"), player1.publicKey.toBuffer(), id.toArrayLike(Buffer, "le", 8)],
    program.programId
  );
  const [vault] = PublicKey.findProgramAddressSync([Buffer.from("vault"), challenge.toBuffer()], program.programId);
  const [rules] = PublicKey.findProgramAddressSync([Buffer.from("rules"), challenge.toBuffer()], program.programId);
  const rulesHash = Array.from(sha256("smoke-test-ruleset " + id.toString()));
  const now = await connection.getBlockTime(await connection.getSlot());
  const createSig = await program.methods
    .createChallenge(id, new BN(BUY_IN), new BN(now + 300), new BN(now + 600), 8, oracle.publicKey,
      rulesHash, verifier.publicKey, { winnerTakesAll: {} }, [])
    .accountsPartial({
      creator: player1.publicKey,
      challenge,
      mint: USDC_MINT,
      vault,
      rules,
      tokenProgram: TOKEN_PROGRAM_ID,
      systemProgram: SystemProgram.programId,
    })
    .signers([player1])
    .rpc();
  console.log("Challenge:", challenge.toBase58());
  console.log("create_challenge:", link(createSig));

  const locked = await program.account.rules.fetch(rules);
  if (Buffer.compare(Buffer.from(locked.rulesHash), Buffer.from(rulesHash)) !== 0) throw new Error("Rules not locked");
  console.log("Rules locked:", Buffer.from(rulesHash).toString("hex").slice(0, 16) + "...");

  // A join quoting other rules must fail before any money moves.
  try {
    await program.methods
      .joinChallenge(Array.from(sha256("other rules")))
      .accountsPartial({ player: player2.publicKey, challenge, vault, rules, playerToken: tokenOf(player2),
        tokenProgram: TOKEN_PROGRAM_ID })
      .signers([player2])
      .rpc();
    throw new Error("A join with the wrong rules hash went through");
  } catch (e) {
    if (!String(e).includes("RulesMismatch")) throw e;
    console.log("join with the wrong rules hash: refused (RulesMismatch)");
  }

  // 3. Both players join and deposit the buy-in, quoting the locked rules.
  for (const kp of [player1, player2]) {
    const sig = await program.methods
      .joinChallenge(rulesHash)
      .accountsPartial({ player: kp.publicKey, challenge, vault, rules, playerToken: tokenOf(kp), tokenProgram: TOKEN_PROGRAM_ID })
      .signers([kp])
      .rpc();
    console.log("join_challenge:  ", link(sig));
  }
  console.log("Pool:     ", usdc((await getAccount(connection, vault)).amount));

  // Optional: stop here so another client (the Python server) can end and settle this challenge.
  if (process.env.SMOKE_STOP_BEFORE_END === "1") {
    console.log("STOPPED before end_early. Winner to report:", player1.publicKey.toBase58());
    return;
  }

  // 4. The oracle ends the week now and reports player 1 as the winner.
  const endSig = await program.methods
    .endEarly()
    .accountsPartial({ oracle: oracle.publicKey, challenge })
    .signers([oracle])
    .rpc();
  console.log("end_early:       ", link(endSig));

  const scoreHash = sha256("smoke-test-score-sheet");
  const settleAccounts = {
    oracle: oracle.publicKey, challenge, vault, rules,
    instructionsSysvar: anchor.web3.SYSVAR_INSTRUCTIONS_PUBKEY, tokenProgram: TOKEN_PROGRAM_ID,
  };
  const pay = () => program.methods
    .settle()
    .accountsPartial(settleAccounts)
    .remainingAccounts([{ pubkey: tokenOf(player1), isSigner: false, isWritable: true }])
    .signers([oracle]);

  // Without the verifier's signature check the program must refuse to pay.
  try {
    await pay().rpc();
    throw new Error("settle without a signature check went through");
  } catch (e) {
    if (!String(e).includes("MissingSignatureCheck")) throw e;
    console.log("settle without the verifier's signature: refused (MissingSignatureCheck)");
  }

  const message = proofMessageV2(program.programId, challenge, rulesHash, scoreHash, [player1.publicKey], [10000]);
  const check = Ed25519Program.createInstructionWithPrivateKey({ privateKey: verifier.secretKey, message });
  const settleSig = await pay().preInstructions([check]).rpc();
  console.log("settle (signed):  ", link(settleSig));

  // 5. Check the money moved the way it should.
  const after1 = await balance(player1);
  const after2 = await balance(player2);
  const vaultAfter = (await getAccount(connection, vault)).amount;
  console.log(`After:     player 1 has ${usdc(after1)}, player 2 has ${usdc(after2)}, pool has ${usdc(vaultAfter)}`);

  const state = await program.account.challenge.fetch(challenge);
  const ok =
    after1 - before1 === BigInt(BUY_IN) && before2 - after2 === BigInt(BUY_IN) && vaultAfter === 0n &&
    Buffer.compare(Buffer.from(state.scoreHash), scoreHash) === 0;
  if (!ok) throw new Error("Balances or the stored score hash are not what was expected");
  console.log("SMOKE TEST PASSED: rules locked, wrong-rules join refused, unsigned payout refused,");
  console.log("the signed payout paid the winner 0.50 USDC, and the pool is empty.");
}

main().catch((e) => {
  console.error("SMOKE TEST FAILED:", e);
  process.exit(1);
});
