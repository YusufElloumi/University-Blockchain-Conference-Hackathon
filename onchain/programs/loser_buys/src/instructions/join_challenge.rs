use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};

use crate::{constants::*, error::ErrorCode, events::PlayerJoined, state::*};

#[derive(Accounts)]
pub struct JoinChallenge<'info> {
    #[account(mut)]
    pub player: Signer<'info>,
    #[account(
        mut,
        seeds = [CHALLENGE_SEED, challenge.creator.as_ref(), &challenge.challenge_id.to_le_bytes()],
        bump = challenge.bump
    )]
    pub challenge: Box<Account<'info, Challenge>>,
    #[account(mut, address = challenge.vault)]
    pub vault: Box<Account<'info, TokenAccount>>,
    /// The player's own token account that the buy-in is taken from.
    #[account(
        mut,
        token::mint = challenge.mint,
        token::authority = player
    )]
    pub player_token: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
}

pub fn handle_join_challenge(ctx: Context<JoinChallenge>) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let player = ctx.accounts.player.key();
    let challenge = &mut ctx.accounts.challenge;

    require!(
        challenge.status == ChallengeStatus::Open,
        ErrorCode::ChallengeNotOpen
    );
    require!(now < challenge.start_time, ErrorCode::JoinClosed);
    require!(
        challenge.players.len() < challenge.max_players as usize,
        ErrorCode::ChallengeFull
    );
    require!(!challenge.players.contains(&player), ErrorCode::AlreadyJoined);

    token::transfer(
        CpiContext::new(
            ctx.accounts.token_program.key(),
            Transfer {
                from: ctx.accounts.player_token.to_account_info(),
                to: ctx.accounts.vault.to_account_info(),
                authority: ctx.accounts.player.to_account_info(),
            },
        ),
        challenge.buy_in,
    )?;

    challenge.players.push(player);
    let player_count = challenge.players.len() as u8;
    let pool_total = challenge
        .buy_in
        .checked_mul(player_count as u64)
        .ok_or(ErrorCode::MathOverflow)?;

    emit!(PlayerJoined {
        challenge: challenge.key(),
        player,
        player_count,
        pool_total,
    });
    Ok(())
}
