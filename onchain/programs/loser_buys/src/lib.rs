//! Loser Buys: a prize pool for friend-group fitness challenges.
//!
//! Players deposit a buy-in into a vault owned by this program. When the week ends,
//! the oracle (our server) reports the winners and the program pays them from the vault.
//! No fitness data is stored here: only player addresses and a hash of the score sheet.

pub mod constants;
pub mod error;
pub mod events;
pub mod instructions;
pub mod state;

use anchor_lang::prelude::*;

pub use constants::*;
pub use events::*;
pub use instructions::*;
pub use state::*;

declare_id!("FeCj36zk7YNkdfKZXjfjSmftqpJv9C68uBNSvtRt3ssC");

#[program]
pub mod loser_buys {
    use super::*;

    /// Creates a challenge and its empty prize vault.
    pub fn create_challenge(
        ctx: Context<CreateChallenge>,
        challenge_id: u64,
        buy_in: u64,
        start_time: i64,
        end_time: i64,
        max_players: u8,
        oracle: Pubkey,
    ) -> Result<()> {
        crate::instructions::create_challenge::handle_create_challenge(
            ctx,
            challenge_id,
            buy_in,
            start_time,
            end_time,
            max_players,
            oracle,
        )
    }

    /// Deposits the buy-in and adds the caller to the player list. Before the start time only.
    pub fn join_challenge(ctx: Context<JoinChallenge>) -> Result<()> {
        crate::instructions::join_challenge::handle_join_challenge(ctx)
    }

    /// Oracle only: ends the challenge now (demo and testing).
    pub fn end_early(ctx: Context<EndEarly>) -> Result<()> {
        crate::instructions::end_early::handle_end_early(ctx)
    }

    /// Oracle only, after the end time: pays the pool to the winners.
    pub fn settle<'info>(
        ctx: Context<'info, Settle<'info>>,
        winners: Vec<Pubkey>,
        score_hash: [u8; 32],
    ) -> Result<()> {
        crate::instructions::settle::handle_settle(ctx, winners, score_hash)
    }

    /// Oracle only, after the end time: pays the pool to the winners in fixed shares
    /// (basis points, adding up to 100%). Used by formats such as a podium split.
    pub fn settle_split<'info>(
        ctx: Context<'info, Settle<'info>>,
        winners: Vec<Pubkey>,
        shares_bps: Vec<u16>,
        score_hash: [u8; 32],
    ) -> Result<()> {
        crate::instructions::settle::handle_settle_split(ctx, winners, shares_bps, score_hash)
    }

    /// Anyone: returns every buy-in when too few players joined or the oracle timed out.
    pub fn refund<'info>(ctx: Context<'info, Refund<'info>>) -> Result<()> {
        crate::instructions::refund::handle_refund(ctx)
    }
}
