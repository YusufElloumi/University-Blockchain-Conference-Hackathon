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
import { LoserBuys } from "../target/types/loser_buys";

const { Keypair, PublicKey, SystemProgram, LAMPORTS_PER_SOL } = anchor.web3;
type Keypair = anchor.web3.Keypair;
type PublicKey = anchor.web3.PublicKey;

describe("loser_buys", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  const program = anchor.workspace.loserBuys as Program<LoserBuys>;
  const connection = provider.connection;
  const payer = (provider.wallet as anchor.Wallet).payer;

  const BUY_IN = 1_000_001; // odd on purpose, so a 2-way split of 3 buy-ins leaves 1 unit over
  const START_BALANCE = 10_000_000;
  const SCORE_HASH = Array.from({ length: 32 }, (_, i) => i + 1);

  const oracle = Keypair.generate();
  const stranger = Keypair.generate();
  const players: Keypair[] = [Keypair.generate(), Keypair.generate(), Keypair.generate()];
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

  /** Creates a challenge that starts in 10 minutes and ends in 20. */
  async function createChallenge(creator: Keypair, maxPlayers = 8) {
    const id = new BN(nextId++);
    const [challenge] = PublicKey.findProgramAddressSync(
      [Buffer.from("challenge"), creator.publicKey.toBuffer(), id.toArrayLike(Buffer, "le", 8)],
      program.programId
    );
    const [vault] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault"), challenge.toBuffer()],
      program.programId
    );
    const now = await chainTime();
    await program.methods
      .createChallenge(id, new BN(BUY_IN), new BN(now + 600), new BN(now + 1200), maxPlayers, oracle.publicKey)
      .accountsPartial({
        creator: creator.publicKey,
        challenge,
        mint,
        vault,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([creator])
      .rpc();
    return { challenge, vault };
  }

  const join = (c: { challenge: PublicKey; vault: PublicKey }, player: Keypair) =>
    program.methods
      .joinChallenge()
      .accountsPartial({
        player: player.publicKey,
        challenge: c.challenge,
        vault: c.vault,
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

  const settle = (
    c: { challenge: PublicKey; vault: PublicKey },
    winners: Keypair[],
    opts: { signer?: Keypair; payTo?: Keypair[] } = {}
  ) =>
    program.methods
      .settle(
        winners.map((w) => w.publicKey),
        SCORE_HASH
      )
      .accountsPartial({
        oracle: (opts.signer ?? oracle).publicKey,
        challenge: c.challenge,
        vault: c.vault,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .remainingAccounts(asRemaining(opts.payTo ?? winners))
      .signers([opts.signer ?? oracle])
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

  before(async () => {
    // Give every test wallet SOL for fees and test tokens for buy-ins.
    const everyone = [oracle, stranger, ...players];
    const tx = new anchor.web3.Transaction();
    for (const kp of everyone) {
      tx.add(
        SystemProgram.transfer({
          fromPubkey: payer.publicKey,
          toPubkey: kp.publicKey,
          lamports: LAMPORTS_PER_SOL,
        })
      );
    }
    await provider.sendAndConfirm(tx);

    mint = await createMint(connection, payer, payer.publicKey, null, 6);
    for (const kp of [stranger, ...players]) {
      const ata = await getOrCreateAssociatedTokenAccount(connection, payer, mint, kp.publicKey);
      tokenAccounts.set(kp.publicKey.toBase58(), ata.address);
      await mintTo(connection, payer, mint, ata.address, payer, START_BALANCE);
    }
  });

  it("happy path: two players join, oracle settles, winner gets the pool", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    const aBefore = await balanceOf(a);
    const bBefore = await balanceOf(b);

    await join(c, a);
    await join(c, b);
    assert.equal(Number((await getAccount(connection, c.vault)).amount), 2 * BUY_IN);
    assert.equal(await balanceOf(a), aBefore - BUY_IN);

    await endEarly(c);
    await settle(c, [a]);

    assert.equal(await balanceOf(a), aBefore + BUY_IN, "winner gains the other buy-in");
    assert.equal(await balanceOf(b), bBefore - BUY_IN, "loser lost the buy-in");
    assert.equal(Number((await getAccount(connection, c.vault)).amount), 0);

    const state = await program.account.challenge.fetch(c.challenge);
    assert.deepEqual(state.status, { settled: {} });
    assert.deepEqual(state.scoreHash, SCORE_HASH);
    assert.equal(state.players.length, 2);
  });

  it("tie: two winners split the pool and the first gets the leftover unit", async () => {
    const [a, b, d] = players;
    const c = await createChallenge(a);
    for (const p of players) await join(c, p);
    const before = await Promise.all(players.map(balanceOf));

    await endEarly(c);
    await settle(c, [b, d]);

    const pool = 3 * BUY_IN; // 3,000,003
    const each = Math.floor(pool / 2); // 1,500,001
    assert.equal(await balanceOf(a), before[0]);
    assert.equal(await balanceOf(b), before[1] + each + 1);
    assert.equal(await balanceOf(d), before[2] + each);
    assert.equal(Number((await getAccount(connection, c.vault)).amount), 0);
  });

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
    const c = await createChallenge(a, 2);
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
    await expectError(settle(c, [b], { signer: a }), "NotOracle");
  });

  it("rejects a winner who is not a player, duplicates, and an empty list", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    await expectError(settle(c, [stranger]), "WinnerNotPlayer");
    await expectError(settle(c, [a, a]), "InvalidWinners");
    await expectError(settle(c, []), "InvalidWinners");
  });

  it("rejects paying a winner's share into someone else's token account", async () => {
    const [a, b] = players;
    const c = await createChallenge(a);
    await join(c, a);
    await join(c, b);
    await endEarly(c);
    await expectError(settle(c, [a], { payTo: [stranger] }), "InvalidTokenAccount");
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
    const state = await program.account.challenge.fetch(c.challenge);
    assert.deepEqual(state.status, { refunded: {} });
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
    const [challenge] = PublicKey.findProgramAddressSync(
      [Buffer.from("challenge"), a.publicKey.toBuffer(), id.toArrayLike(Buffer, "le", 8)],
      program.programId
    );
    const [vault] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault"), challenge.toBuffer()],
      program.programId
    );
    const now = await chainTime();
    const create = (buyIn: number, start: number, end: number, max: number) =>
      program.methods
        .createChallenge(id, new BN(buyIn), new BN(start), new BN(end), max, oracle.publicKey)
        .accountsPartial({
          creator: a.publicKey,
          challenge,
          mint,
          vault,
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
