// Makes a test player join an existing devnet challenge, so one person can try the app without a second login.
// Run through the helper from the repo root:
//   wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh join <challenge address> [player number, default 2]
//
// Uses test money only. The treasury tops the test player up with fee money and the buy-in if needed.
// Keypair files are read from ~/.config/solana/loser-buys/ (never from the repo).

const fs = require("fs");
const os = require("os");
const path = require("path");
const anchor = require("@anchor-lang/core");
const { getOrCreateAssociatedTokenAccount, transfer, TOKEN_PROGRAM_ID } = require("@solana/spl-token");
const idl = require("../idl/loser_buys.json");

const { Connection, Keypair, PublicKey, SystemProgram, Transaction, LAMPORTS_PER_SOL } = anchor.web3;
const RPC_URL = process.env.SOLANA_RPC_URL || "https://api.devnet.solana.com";
const KEY_DIR = process.env.KEY_DIR || path.join(os.homedir(), ".config", "solana", "loser-buys");

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

async function main() {
  const [address, number = "2"] = process.argv.slice(2);
  if (!address) throw new Error("Usage: join <challenge address> [player number]");
  const connection = new Connection(RPC_URL, "confirmed");
  const treasury = loadKeypair("treasury");
  const player = loadKeypair("smoke-player-" + number, true);
  const provider = new anchor.AnchorProvider(connection, new anchor.Wallet(treasury), { commitment: "confirmed" });
  const program = new anchor.Program(idl, provider);

  const challenge = new PublicKey(address);
  const state = await program.account.challenge.fetch(challenge);
  // The test player quotes whatever rules are locked onchain (a real player's browser hashes the rules it showed).
  const [rules] = PublicKey.findProgramAddressSync([Buffer.from("rules"), challenge.toBuffer()], program.programId);
  const locked = await program.account.rules.fetch(rules);
  const buyIn = Number(state.buyIn.toString());

  if ((await connection.getBalance(player.publicKey)) < 0.02 * LAMPORTS_PER_SOL) {
    const topUp = new Transaction().add(
      SystemProgram.transfer({ fromPubkey: treasury.publicKey, toPubkey: player.publicKey, lamports: 0.05 * LAMPORTS_PER_SOL })
    );
    console.log("SOL top-up: ", link(await provider.sendAndConfirm(topUp)));
  }
  const playerToken = await getOrCreateAssociatedTokenAccount(connection, treasury, state.mint, player.publicKey);
  if (Number(playerToken.amount) < buyIn) {
    const treasuryToken = await getOrCreateAssociatedTokenAccount(connection, treasury, state.mint, treasury.publicKey);
    const sig = await transfer(connection, treasury, treasuryToken.address, playerToken.address, treasury, buyIn);
    console.log("USDC top-up:", link(sig));
  }

  const signature = await program.methods
    .joinChallenge(locked.rulesHash)
    .accountsPartial({
      player: player.publicKey,
      challenge,
      vault: state.vault,
      rules,
      playerToken: playerToken.address,
      tokenProgram: TOKEN_PROGRAM_ID,
    })
    .signers([player])
    .rpc();
  console.log("join_challenge:", link(signature));
  console.log("PLAYER=" + player.publicKey.toBase58());
}

main().catch((e) => {
  console.error("FAILED:", e);
  process.exit(1);
});
