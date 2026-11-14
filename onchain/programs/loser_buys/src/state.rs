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
