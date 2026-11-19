import * as anchor from "@anchor-lang/core";
import { BN, Program } from "@anchor-lang/core";
import {
  createMint,
  getAccount,
  getOrCreateAssociatedTokenAccount,
  mintTo,
  TOKEN_PROGRAM_ID,
} from "@solana/spl-token";
import { assert } from "chai";
import { createHash } from "crypto";
import { readFileSync } from "fs";
import { join as joinPath } from "path";
import { LoserBuys } from "../target/types/loser_buys";
import { proofMessageV2, parseProofMessageV2 } from "../shared/proofMessage";

const { Keypair, PublicKey, SystemProgram, LAMPORTS_PER_SOL, Ed25519Program, Transaction } = anchor.web3;
type Keypair = anchor.web3.Keypair;
type PublicKey = anchor.web3.PublicKey;
type Payout = "winnerTakesAll" | "podium" | "goal" | "teams";
type Created = { challenge: PublicKey; vault: PublicKey; rules: PublicKey; rulesHash: number[] };

const sha256 = (text: string) => Array.from(createHash("sha256").update(text).digest());

describe("loser_buys", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  const program = anchor.workspace.loserBuys as Program<LoserBuys>;
  const connection = provider.connection;
  const payer = (provider.wallet as anchor.Wallet).payer;

  const BUY_IN = 1_000_001; // odd on purpose, so a 2-way split of 3 buy-ins leaves 1 unit over
  const START_BALANCE = 100_000_000; // test tokens; many tests join with the same wallets
  const SCORE_HASH = Array.from({ length: 32 }, (_, i) => i + 1);

  const oracle = Keypair.generate();
  const verifier = Keypair.generate();
  const stranger = Keypair.generate();
  const players: Keypair[] = Array.from({ length: 8 }, () => Keypair.generate());
  const tokenAccounts = new Map<string, PublicKey>();
  let mint: PublicKey;
  let nextId = 1;

  const tokenOf = (kp: Keypair) => tokenAccounts.get(kp.publicKey.toBase58())!;
  const balanceOf = async (kp: Keypair) => Number((await getAccount(connection, tokenOf(kp))).amount);
  const asRemaining = (kps: Keypair[]) =>
    kps.map((kp) => ({ pubkey: tokenOf(kp), isSigner: false, isWritable: true }));

  async function chainTime(): Promise<number> {
    const slot = await connection.getSlot();
    return (await connection.getBlockTime(slot)) as number;
  }

  const addresses = (creator: PublicKey, id: BN) => {
    const [challenge] = PublicKey.findProgramAddressSync(
      [Buffer.from("challenge"), creator.toBuffer(), id.toArrayLike(Buffer, "le", 8)],
      program.programId
    );
    const [vault] = PublicKey.findProgramAddressSync([Buffer.from("vault"), challenge.toBuffer()], program.programId);
    const [rules] = PublicKey.findProgramAddressSync([Buffer.from("rules"), challenge.toBuffer()], program.programId);
    return { challenge, vault, rules };
  };

  /** Creates a challenge that starts in 10 minutes and ends in 20, with locked rules. */
  async function createChallenge(
    creator: Keypair,
    opts: { maxPlayers?: number; payout?: Payout; split?: number[]; ruleset?: string } = {}
  ): Promise<Created> {
    const id = new BN(nextId++);
    const { challenge, vault, rules } = addresses(creator.publicKey, id);
    const rulesHash = sha256(opts.ruleset ?? `ruleset ${id.toString()}`);
    const now = await chainTime();
    await program.methods
      .createChallenge(
        id,
        new BN(BUY_IN),
        new BN(now + 600),
        new BN(now + 1200),
        opts.maxPlayers ?? 8,
        oracle.publicKey,
        rulesHash,
        verifier.publicKey,
        { [opts.payout ?? "winnerTakesAll"]: {} } as any,
        opts.split ?? []
      )
      .accountsPartial({
        creator: creator.publicKey,
        challenge,
        mint,
        vault,
        rules,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([creator])
      .rpc();
    return { challenge, vault, rules, rulesHash };
  }

  const join = (c: Created, player: Keypair, rulesHash: number[] = c.rulesHash) =>
    program.methods
      .joinChallenge(rulesHash)
      .accountsPartial({
        player: player.publicKey,
        challenge: c.challenge,
        vault: c.vault,
        rules: c.rules,
        playerToken: tokenOf(player),
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([player])
      .rpc();

  const endEarly = (c: { challenge: PublicKey }, signer: Keypair = oracle) =>
    program.methods
      .endEarly()
      .accountsPartial({ oracle: signer.publicKey, challenge: c.challenge })
      .signers([signer])
      .rpc();

  const equalShares = (n: number) => {
    const each = Math.floor(10_000 / n);
    return Array.from({ length: n }, (_, i) => (i === 0 ? 10_000 - each * (n - 1) : each));
  };

  type SignOpts = {
    signer?: Keypair; // the oracle sending the payout
    signedBy?: Keypair; // who signs the result (default: the verifier)
    shares?: number[]; // signed shares (default: equal)
    signedWinners?: Keypair[]; // winners named in the signed message (default: the paid winners)
    forChallenge?: PublicKey; // challenge named in the signed message
    rulesHash?: number[]; // rules hash named in the signed message
    noCheck?: boolean; // leave the Ed25519 check out
    tamper?: boolean; // change the signed message after signing
    payTo?: Keypair[];
  };

  /** The verifier's Ed25519 check of a v2 result, as the API sends it before every payout. */
  function signatureCheck(c: Created, winners: Keypair[], o: SignOpts) {
    const message = proofMessageV2({
      program: program.programId.toBytes(),
      challenge: (o.forChallenge ?? c.challenge).toBytes(),
      rulesHash: Uint8Array.from(o.rulesHash ?? c.rulesHash),
      scoreHash: Uint8Array.from(SCORE_HASH),
      winners: (o.signedWinners ?? winners).map((w) => w.publicKey.toBytes()),
      sharesBps: o.shares ?? equalShares((o.signedWinners ?? winners).length),
    });
    const ix = Ed25519Program.createInstructionWithPrivateKey({
      privateKey: (o.signedBy ?? verifier).secretKey,
      message,
    });
    if (o.tamper) ix.data[ix.data.length - 1] ^= 1; // the last share byte
    return ix;
  }

  const settleAccounts = (c: Created, o: SignOpts) => ({
    oracle: (o.signer ?? oracle).publicKey,
    challenge: c.challenge,
    vault: c.vault,
    rules: c.rules,
    instructionsSysvar: anchor.web3.SYSVAR_INSTRUCTIONS_PUBKEY,
    tokenProgram: TOKEN_PROGRAM_ID,
  });

  const settle = (c: Created, winners: Keypair[], o: SignOpts = {}) =>
    program.methods
      .settle()
      .accountsPartial(settleAccounts(c, o))
      .remainingAccounts(asRemaining(o.payTo ?? o.signedWinners ?? winners))
      .preInstructions(o.noCheck ? [] : [signatureCheck(c, winners, o)])
      .signers([o.signer ?? oracle])
      .rpc();

  const settleSplit = (c: Created, winners: Keypair[], groups: number[], shares: number[], o: SignOpts = {}) =>
    program.methods
      .settleSplit(Buffer.from(groups))
      .accountsPartial(settleAccounts(c, o))
      .remainingAccounts(asRemaining(winners))
      .preInstructions(o.noCheck ? [] : [signatureCheck(c, winners, { ...o, shares })])
      .signers([o.signer ?? oracle])
      .rpc();

  const refund = (c: { challenge: PublicKey; vault: PublicKey }, refundTo: Keypair[]) =>
    program.methods
      .refund()
      .accountsPartial({
        caller: stranger.publicKey,
        challenge: c.challenge,
        vault: c.vault,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .remainingAccounts(asRemaining(refundTo))
      .signers([stranger])
      .rpc();

  /** Passes only if the call fails with the given program error name. */
  async function expectError(call: Promise<unknown>, code: string) {
    try {
      await call;
    } catch (e: any) {
      const got = e?.error?.errorCode?.code ?? String(e);
      assert.include(got, code, `expected ${code}, got: ${got}`);
      return;
    }
    assert.fail(`expected ${code}, but the call succeeded`);
  }

  /** Passes only if the transaction fails at all (for failures before our program runs). */
  async function expectFailure(call: Promise<unknown>, pattern: RegExp) {
    try {
      await call;
    } catch (e: any) {
      assert.match(String(e?.message ?? e) + JSON.stringify(e?.logs ?? []), pattern);
      return;
    }
    assert.fail("expected the transaction to fail, but it succeeded");
  }

  const statusOf = async (c: Created) => (await program.account.challenge.fetch(c.challenge)).status;

  before(async () => {
    // Give every test wallet SOL for fees and test tokens for buy-ins.
    const everyone = [oracle, stranger, ...players];
    const tx = new Transaction();
    for (const kp of everyone) {
      tx.add(SystemProgram.transfer({ fromPubkey: payer.publicKey, toPubkey: kp.publicKey, lamports: LAMPORTS_PER_SOL }));
    }
    await provider.sendAndConfirm(tx);

    mint = await createMint(connection, payer, payer.publicKey, null, 6);
    for (const kp of [stranger, ...players]) {
      const ata = await getOrCreateAssociatedTokenAccount(connection, payer, mint, kp.publicKey);
      tokenAccounts.set(kp.publicKey.toBase58(), ata.address);
      await mintTo(connection, payer, mint, ata.address, payer, START_BALANCE);
    }
  });

  // ---------- the shared v2 message ----------

  it("builds the shared Proof of Sweat v2 fixture byte for byte (same bytes as Python)", () => {
    const fixture = JSON.parse(readFileSync(joinPath(__dirname, "..", "shared", "proof_v2_fixture.json"), "utf8"));
    const message = proofMessageV2({
      program: new PublicKey(fixture.program).toBytes(),
      challenge: new PublicKey(fixture.challenge).toBytes(),
      rulesHash: Buffer.from(fixture.rules_hash, "hex"),
      scoreHash: Buffer.from(fixture.score_hash, "hex"),
      winners: fixture.winners.map((w: string) => new PublicKey(w).toBytes()),
      sharesBps: fixture.shares_bps,
    });
    assert.equal(Buffer.from(message).toString("hex"), fixture.message_hex);
    assert.equal(fixture.program, program.programId.toBase58(), "the fixture names this program");
    const parsed = parseProofMessageV2(message);
    assert.deepEqual(parsed.sharesBps, fixture.shares_bps);
    assert.equal(new PublicKey(parsed.winners[2]).toBase58(), fixture.winners[2]);
  });

  // ---------- locked rules ----------

  it("locks the rules hash, verifier and payout terms at creation; nothing can change them", async () => {
    const [a] = players;
    const c = await createChallenge(a, { payout: "podium", split: [6000, 3000, 1000] });
    const rules = await program.account.rules.fetch(c.rules);
    assert.deepEqual(rules.rulesHash, c.rulesHash);
    assert.equal(rules.verifier.toBase58(), verifier.publicKey.toBase58());
    assert.deepEqual(rules.payout, { podium: {} });
    assert.deepEqual(rules.splitBps, [6000, 3000, 1000]);
    assert.equal(rules.challenge.toBase58(), c.challenge.toBase58());
    // No instruction other than create_challenge (which creates it) takes the rules account as writable.
    for (const ix of program.idl.instructions) {
      const acct = ix.accounts.find((x: any) => x.name === "rules") as any;
      if (acct && ix.name !== "createChallenge" && ix.name !== "create_challenge") {
        assert.notOk(acct.writable, `${ix.name} must not be able to write the rules`);
      }
    }
  });

  it("rejects bad payout terms and an empty rules hash at creation", async () => {
    const [a] = players;
    await expectError(createChallenge(a, { payout: "podium", split: [6000, 3000] }), "InvalidSplit");
    await expectError(createChallenge(a, { payout: "podium", split: [3000, 7000] }), "InvalidSplit");
    await expectError(createChallenge(a, { payout: "podium", split: [10000] }), "InvalidSplit");
    await expectError(createChallenge(a, { payout: "podium", split: [5000, 5000, 0] }), "InvalidSplit");
    await expectError(createChallenge(a, { payout: "winnerTakesAll", split: [6000, 4000] }), "InvalidSplit");
    const id = new BN(nextId++);
    const { challenge, vault, rules } = addresses(a.publicKey, id);
    const now = await chainTime();
    await expectError(
      program.methods
        .createChallenge(id, new BN(BUY_IN), new BN(now + 600), new BN(now + 1200), 8, oracle.publicKey,
          Array(32).fill(0), verifier.publicKey, { winnerTakesAll: {} } as any, [])
        .accountsPartial({ creator: a.publicKey, challenge, mint, vault, rules, tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: SystemProgram.programId })
        .signers([a])
        .rpc(),
      "InvalidRulesHash"
    );
  });

  it("join fails unless the player quotes the locked rules hash", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await expectError(join(c, a, sha256("some other rules")), "RulesMismatch");
    const vaultBefore = Number((await getAccount(connection, c.vault)).amount);
    assert.equal(vaultBefore, 0, "no deposit went through");
    await join(c, a);
    await join(c, b);
    assert.equal((await program.account.challenge.fetch(c.challenge)).players.length, 2);
  });

  // ---------- payouts ----------

  it("happy path: two players join, the signed result is checked, winner gets the pool", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    const aBefore = await balanceOf(a);
    const bBefore = await balanceOf(b);

    await join(c, a);
    await join(c, b);
    assert.equal(Number((await getAccount(connection, c.vault)).amount), 2 * BUY_IN);

    await endEarly(c);
    await settle(c, [a]);

    assert.equal(await balanceOf(a), aBefore + BUY_IN, "winner gains the other buy-in");
    assert.equal(await balanceOf(b), bBefore - BUY_IN, "loser lost the buy-in");
    assert.equal(Number((await getAccount(connection, c.vault)).amount), 0);
    const state = await program.account.challenge.fetch(c.challenge);
    assert.deepEqual(state.status, { settled: {} });
    assert.deepEqual(state.scoreHash, SCORE_HASH, "the score hash comes from the signed result");
  });

  it("tie: two winners split the pool and the first gets the leftover unit", async () => {
    const [a, b, d] = players;
    const c = await createChallenge(a);
    for (const p of [a, b, d]) await join(c, p);
    const before = await Promise.all([a, b, d].map(balanceOf));

    await endEarly(c);
    await settle(c, [b, d]);

    const each = Math.floor((3 * BUY_IN) / 2); // 1,500,001
    assert.equal(await balanceOf(a), before[0]);
    assert.equal(await balanceOf(b), before[1] + each + 1);
    assert.equal(await balanceOf(d), before[2] + each);
  });

  it("an 8-way tie fits in one transaction with the signature check", async () => {
    const c = await createChallenge(players[0]);
    for (const p of players) await join(c, p);
    await endEarly(c);
    // Sent the way the API sends it: the oracle pays its own fee, so there is one signature.
    const tx = await program.methods
      .settle()
      .accountsPartial(settleAccounts(c, {}))
      .remainingAccounts(asRemaining(players))
      .preInstructions([signatureCheck(c, players, {})])
      .transaction();
    tx.feePayer = oracle.publicKey;
    tx.recentBlockhash = (await connection.getLatestBlockhash()).blockhash;
    tx.sign(oracle);
    const size = tx.serialize().length;
    assert.isAtMost(size, 1232, `settle with 8 winners is ${size} bytes`);
    await anchor.web3.sendAndConfirmRawTransaction(connection, tx.serialize());
    assert.deepEqual(await statusOf(c), { settled: {} });
    assert.equal(Number((await getAccount(connection, c.vault)).amount), 0);
  });

  it("settle refuses unequal signed shares", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    await expectError(settle(c, [a, b], { shares: [7000, 3000] }), "SharesNotAsCommitted");
    await settle(c, [a, b]);
  });

  it("podium: the program sets the amounts from the locked 60/30/10 split", async () => {
    const [a, b, d] = players;
    const c = await createChallenge(a, { payout: "podium", split: [6000, 3000, 1000] });
    for (const p of [a, b, d]) await join(c, p);
    const before = await Promise.all([a, b, d].map(balanceOf));
    await endEarly(c);

    await expectError(settleSplit(c, [d, a, b], [1, 1, 1], [5000, 3000, 2000]), "SharesNotAsCommitted");
    await expectError(settleSplit(c, [d, a, b], [1, 1, 1], [7000, 2000, 1000]), "SharesNotAsCommitted");
    await expectError(settle(c, [d]), "WrongPayoutKind"); // no equal payout for a podium
    await settleSplit(c, [d, a, b], [1, 1, 1], [6000, 3000, 1000]);

    // Pool 3,000,003: 1,800,001 + 900,000 + 300,000 = 3,000,001, so 2 units of dust go to first.
    assert.equal(await balanceOf(d), before[2] + 1_800_003);
    assert.equal(await balanceOf(a), before[0] + 900_000);
    assert.equal(await balanceOf(b), before[1] + 300_000);
    assert.equal(Number((await getAccount(connection, c.vault)).amount), 0);
  });

  it("podium ties share the places they cover; groups must cover every paid place", async () => {
    const [a, b, d] = players;
    const c = await createChallenge(a, { payout: "podium", split: [6000, 3000, 1000] });
    for (const p of [a, b, d]) await join(c, p);
    await endEarly(c);
    await expectError(settleSplit(c, [a, b], [2], [4500, 4500]), "InvalidTieGroups"); // 3rd place left out
    await expectError(settleSplit(c, [a, b, d], [1, 1, 1], [4500, 4500, 1000]), "SharesNotAsCommitted");
    await settleSplit(c, [a, b, d], [2, 1], [4500, 4500, 1000]); // a and b tied first: (60+30)/2 each
    assert.deepEqual(await statusOf(c), { settled: {} });
  });

  it("podium with fewer players than places gives the unfilled place to first", async () => {
    const [a, b] = players;
    const c = await createChallenge(a, { payout: "podium", split: [6000, 3000, 1000] });
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    await settleSplit(c, [b, a], [1, 1], [7000, 3000]);
  });

  it("settle_split is only for a podium", async () => {
    const [a, b] = players;
    const c = await createChallenge(a, { payout: "goal" });
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    await expectError(settleSplit(c, [a, b], [1, 1], [7000, 3000]), "WrongPayoutKind");
    await settle(c, [a, b]); // goal missed: everyone gets their fee back
  });

  // ---------- the signature check ----------

  it("refuses to pay without the verifier's signature check", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    await expectError(settle(c, [a], { noCheck: true }), "MissingSignatureCheck");
    assert.deepEqual(await statusOf(c), { open: {} });
  });

  it("refuses a result signed by the wrong key", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    await expectError(settle(c, [a], { signedBy: oracle }), "WrongVerifier");
    await expectError(settle(c, [a], { signedBy: Keypair.generate() }), "WrongVerifier");
  });

  it("refuses a result signed for another challenge or other rules", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    const other = await createChallenge(b);
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    await expectError(settle(c, [a], { forChallenge: other.challenge }), "InvalidSignedResult");
    await expectError(settle(c, [a], { rulesHash: other.rulesHash }), "InvalidSignedResult");
  });

  it("pays only the signed winners: other winners' token accounts or a changed message fail", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    // Signed for a, but the oracle tries to pay b's account.
    await expectError(settle(c, [a], { payTo: [b] }), "InvalidTokenAccount");
    // Signed for a stranger who never played.
    await expectError(settle(c, [a], { signedWinners: [stranger], payTo: [stranger] }), "WinnerNotPlayer");
    // The message is edited after signing: Solana's Ed25519 program rejects the whole transaction.
    await expectFailure(settle(c, [a, b], { tamper: true }), /precompile|signature|0x2|invalid/i);
    assert.deepEqual(await statusOf(c), { open: {} });
    await settle(c, [b]);
  });

  // ---------- the rest, unchanged ----------

  it("rejects joining after the challenge started", async () => {
    const [a, b, d] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await endEarly(c); // moves the start time to now, so joining is closed
    await expectError(join(c, d), "JoinClosed");
  });

  it("rejects joining twice and joining a full challenge", async () => {
    const [a, b, d] = players;
    const c = await createChallenge(a, { maxPlayers: 2 });
    await join(c, a);
    await expectError(join(c, a), "AlreadyJoined");
    await join(c, b);
    await expectError(join(c, d), "ChallengeFull");
  });

  it("rejects settle and end_early from anyone but the oracle", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await expectError(endEarly(c, stranger), "NotOracle");
    await endEarly(c);
    await expectError(settle(c, [a], { signer: stranger }), "NotOracle");
  });

  it("rejects duplicate winners", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    await expectError(settle(c, [a, a]), "InvalidWinners");
  });

  it("rejects settle before the end time and settling twice", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await expectError(settle(c, [a]), "NotEnded");
    await endEarly(c);
    await settle(c, [a]);
    await expectError(settle(c, [b]), "ChallengeNotOpen");
  });

  it("refund: returns the buy-in when fewer than 2 players joined", async () => {
    const [a] = players;
    const c = await createChallenge(a);
    const before = await balanceOf(a);
    await join(c, a);

    await expectError(refund(c, [a]), "RefundNotAllowed"); // not started yet
    await endEarly(c);
    await expectError(settle(c, [a]), "NotEnoughPlayers");
    await expectError(refund(c, [stranger]), "InvalidTokenAccount");
    await refund(c, [a]);

    assert.equal(await balanceOf(a), before);
    assert.deepEqual(await statusOf(c), { refunded: {} });
    await expectError(refund(c, [a]), "ChallengeNotOpen");
  });

  it("refund: not allowed for a full challenge before the 72-hour timeout", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    await expectError(refund(c, [a, b]), "RefundNotAllowed");
    await settle(c, [b]); // funds still reachable the normal way
  });

  it("rejects bad challenge settings", async () => {
    const [a] = players;
    const id = new BN(9_999);
    const { challenge, vault, rules } = addresses(a.publicKey, id);
    const now = await chainTime();
    const create = (buyIn: number, start: number, end: number, max: number) =>
      program.methods
        .createChallenge(id, new BN(buyIn), new BN(start), new BN(end), max, oracle.publicKey,
          sha256("rules"), verifier.publicKey, { winnerTakesAll: {} } as any, [])
        .accountsPartial({
          creator: a.publicKey,
          challenge,
          mint,
          vault,
          rules,
          tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: SystemProgram.programId,
        })
        .signers([a])
        .rpc();

    await expectError(create(0, now + 600, now + 1200, 8), "InvalidBuyIn");
    await expectError(create(BUY_IN, now - 10, now + 1200, 8), "InvalidTimes");
    await expectError(create(BUY_IN, now + 600, now + 500, 8), "InvalidTimes");
    await expectError(create(BUY_IN, now + 600, now + 1200, 1), "InvalidMaxPlayers");
    await expectError(create(BUY_IN, now + 600, now + 1200, 9), "InvalidMaxPlayers");
  });
});
