use anchor_lang::prelude::*;

// Events are written to the transaction logs. The QuickNode Stream reads them.

#[event]
pub struct ChallengeCreated {
    pub challenge: Pubkey,
    pub creator: Pubkey,
    pub challenge_id: u64,
    pub oracle: Pubkey,
    pub mint: Pubkey,
    pub buy_in: u64,
    pub start_time: i64,
    pub end_time: i64,
    pub max_players: u8,
}

#[event]
pub struct PlayerJoined {
    pub challenge: Pubkey,
    pub player: Pubkey,
    pub player_count: u8,
    pub pool_total: u64,
}

#[event]
pub struct ChallengeEnded {
    pub challenge: Pubkey,
    pub end_time: i64,
}

#[event]
pub struct ChallengeSettled {
    pub challenge: Pubkey,
    pub winners: Vec<Pubkey>,
    pub pool_total: u64,
    pub payout_each: u64,
    pub score_hash: [u8; 32],
}

#[event]
pub struct ChallengeRefunded {
    pub challenge: Pubkey,
    pub player_count: u8,
    pub refund_each: u64,
}
