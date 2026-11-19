//! Loser Buys: a prize pool for friend-group fitness challenges.
//!
//! Players deposit a buy-in into a vault owned by this program. When the week ends,
//! the oracle (our server) reports the winners and the program pays them from the vault.
//! No fitness data is stored here: only player addresses and a hash of the score sheet.
//!
//! Rules are locked before anyone pays: each challenge has a `Rules` account (rules hash, payout
//! terms, verifier key) written once at creation. Joining quotes the rules hash; settling needs the
//! verifier's Ed25519 signature on the result, checked through the instructions sysvar, and the
//! program sets the payout amounts from the committed terms.

pub mod constants;
pub mod error;
pub mod events;
pub mod instructions;
pub mod proof;
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
        rules_hash: [u8; 32],
        verifier: Pubkey,
        payout: PayoutKind,
        split_bps: Vec<u16>,
    ) -> Result<()> {
        crate::instructions::create_challenge::handle_create_challenge(
            ctx,
            challenge_id,
            buy_in,
            start_time,
            end_time,
            max_players,
            oracle,
            rules_hash,
            verifier,
            payout,
            split_bps,
        )
    }

    /// Deposits the buy-in and adds the caller to the player list. Before the start time only,
    /// and only if `expected_rules_hash` is the rules hash fixed at creation.
    pub fn join_challenge(ctx: Context<JoinChallenge>, expected_rules_hash: [u8; 32]) -> Result<()> {
        crate::instructions::join_challenge::handle_join_challenge(ctx, expected_rules_hash)
    }

    /// Oracle only: ends the challenge now (demo and testing).
    pub fn end_early(ctx: Context<EndEarly>) -> Result<()> {
        crate::instructions::end_early::handle_end_early(ctx)
    }

    /// Oracle only, after the end time: pays the pool in equal shares to the winners named in the
    /// verifier's signed result (an Ed25519 check must be the instruction right before this one).
    /// Winner takes all, goal and teams formats only.
    pub fn settle<'info>(ctx: Context<'info, Settle<'info>>) -> Result<()> {
        crate::instructions::settle::handle_settle(ctx)
    }

    /// Oracle only, after the end time: podium payout. The signed result names the winners in rank
    /// order; `tie_groups` says how many players share each rank. The program works out every share
    /// from the split fixed at creation and pays only if the signed shares are exactly those.
    pub fn settle_split<'info>(ctx: Context<'info, Settle<'info>>, tie_groups: Vec<u8>) -> Result<()> {
        crate::instructions::settle::handle_settle_split(ctx, tie_groups)
    }

    /// Anyone: returns every buy-in when too few players joined or the oracle timed out.
    pub fn refund<'info>(ctx: Context<'info, Refund<'info>>) -> Result<()> {
        crate::instructions::refund::handle_refund(ctx)
    }
}
