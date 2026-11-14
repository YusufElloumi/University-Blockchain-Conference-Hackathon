use anchor_lang::prelude::*;

use crate::{constants::*, error::ErrorCode, events::ChallengeEnded, state::*};

#[derive(Accounts)]
pub struct EndEarly<'info> {
    pub oracle: Signer<'info>,
    #[account(
        mut,
        seeds = [CHALLENGE_SEED, challenge.creator.as_ref(), &challenge.challenge_id.to_le_bytes()],
        bump = challenge.bump,
        has_one = oracle @ ErrorCode::NotOracle
    )]
    pub challenge: Box<Account<'info, Challenge>>,
}

/// Ends the challenge now. For demos and testing: the week does not have to run in real time.
pub fn handle_end_early(ctx: Context<EndEarly>) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let challenge = &mut ctx.accounts.challenge;

    require!(
        challenge.status == ChallengeStatus::Open,
        ErrorCode::ChallengeNotOpen
    );
    require!(now < challenge.end_time, ErrorCode::AlreadyEnded);

    challenge.end_time = now;
    // If it had not started yet, joining closes now too.
    if challenge.start_time > now {
        challenge.start_time = now;
    }

    emit!(ChallengeEnded {
        challenge: challenge.key(),
        end_time: now,
    });
    Ok(())
}
