use anchor_lang::prelude::*;

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum ChallengeStatus {
    /// Accepting players, running, or waiting to be settled.
    Open,
    /// Winners were paid.
    Settled,
    /// Every buy-in was returned.
    Refunded,
}

/// How the pool is paid, fixed at creation (`Rules.payout`).
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace, Debug)]
pub enum PayoutKind {
    /// Top scorer takes the pool; a tie at the top splits it equally. Paid with `settle`.
    WinnerTakesAll,
    /// Top places share the pool by `Rules.split_bps`. Paid with `settle_split`; the program sets the amounts.
    Podium,
    /// Everyone who reaches the goal splits equally (nobody: everyone gets their fee back). Paid with `settle`.
    Goal,
    /// The winning team's players split equally. Paid with `settle`.
    Teams,
}

/// The rules a challenge was created with. A separate account next to the challenge (seeds
/// `["rules", challenge]`), so challenges created before it existed keep their layout and can still
/// be refunded. Written once by `create_challenge`; no instruction can change it afterwards.
#[account]
#[derive(InitSpace)]
pub struct Rules {
    pub challenge: Pubkey,
    /// SHA-256 of the canonical JSON ruleset (scoring rules, format, length, verifier...). The ruleset
    /// itself is published offchain so anyone can re-hash it. `join_challenge` must quote this hash.
    pub rules_hash: [u8; 32],
    /// The key whose Ed25519 signature on the result `settle` and `settle_split` require.
    pub verifier: Pubkey,
    pub payout: PayoutKind,
    /// Podium only: basis points per place (2 or 3 places, highest first, adding up to 10,000).
    /// Unused places, and every place for other formats, are 0.
    pub split_bps: [u16; 3],
    pub bump: u8,
}

/// One weekly challenge and its prize pool.
#[account]
#[derive(InitSpace)]
pub struct Challenge {
    /// Who created the challenge (and paid for the accounts).
    pub creator: Pubkey,
    /// Number chosen by the creator so one creator can have many challenges.
    pub challenge_id: u64,
    /// The only key allowed to end early and to report winners.
    pub oracle: Pubkey,
    /// Token used for the pool (devnet USDC).
    pub mint: Pubkey,
    /// Token account that holds the pool. Owned by this challenge account.
    pub vault: Pubkey,
    /// Amount each player deposits, in the token's smallest unit.
    pub buy_in: u64,
    /// Joining closes at this time (unix seconds).
    pub start_time: i64,
    /// Settlement is allowed from this time (unix seconds).
    pub end_time: i64,
    pub max_players: u8,
    #[max_len(8)]
    pub players: Vec<Pubkey>,
    pub status: ChallengeStatus,
    /// Hash of the final score sheet, set by `settle`. All zeros until then.
    pub score_hash: [u8; 32],
    pub bump: u8,
    pub vault_bump: u8,
}
