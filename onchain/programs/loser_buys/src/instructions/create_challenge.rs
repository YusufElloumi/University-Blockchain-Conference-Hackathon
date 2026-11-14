use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token, TokenAccount};

use crate::{constants::*, error::ErrorCode, events::ChallengeCreated, state::*};

#[derive(Accounts)]
#[instruction(challenge_id: u64)]
pub struct CreateChallenge<'info> {
    #[account(mut)]
    pub creator: Signer<'info>,
    #[account(
        init,
        payer = creator,
        space = 8 + Challenge::INIT_SPACE,
        seeds = [CHALLENGE_SEED, creator.key().as_ref(), &challenge_id.to_le_bytes()],
        bump
    )]
    pub challenge: Box<Account<'info, Challenge>>,
    pub mint: Box<Account<'info, Mint>>,
    /// The prize pool. Only this program can move tokens out of it.
    #[account(
        init,
        payer = creator,
        seeds = [VAULT_SEED, challenge.key().as_ref()],
        bump,
        token::mint = mint,
        token::authority = challenge
    )]
    pub vault: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

pub fn handle_create_challenge(
    ctx: Context<CreateChallenge>,
    challenge_id: u64,
    buy_in: u64,
    start_time: i64,
    end_time: i64,
    max_players: u8,
    oracle: Pubkey,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    require!(buy_in > 0, ErrorCode::InvalidBuyIn);
    require!(start_time > now && end_time > start_time, ErrorCode::InvalidTimes);
    require!(
        (MIN_PLAYERS..=MAX_PLAYERS).contains(&max_players),
        ErrorCode::InvalidMaxPlayers
    );

    let challenge = &mut ctx.accounts.challenge;
    challenge.creator = ctx.accounts.creator.key();
    challenge.challenge_id = challenge_id;
    challenge.oracle = oracle;
    challenge.mint = ctx.accounts.mint.key();
    challenge.vault = ctx.accounts.vault.key();
    challenge.buy_in = buy_in;
    challenge.start_time = start_time;
    challenge.end_time = end_time;
    challenge.max_players = max_players;
    challenge.players = Vec::new();
    challenge.status = ChallengeStatus::Open;
    challenge.score_hash = [0u8; 32];
    challenge.bump = ctx.bumps.challenge;
    challenge.vault_bump = ctx.bumps.vault;

    emit!(ChallengeCreated {
        challenge: challenge.key(),
        creator: challenge.creator,
        challenge_id,
        oracle,
        mint: challenge.mint,
        buy_in,
        start_time,
        end_time,
        max_players,
    });
    Ok(())
}
