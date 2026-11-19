use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token, TokenAccount};

use crate::{
    constants::*,
    error::ErrorCode,
    events::{ChallengeCreated, RulesLocked},
    instructions::settle::FULL_SHARE_BPS,
    state::*,
};

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
    /// The challenge's rules and payout terms. Created here, never changed afterwards.
    #[account(
        init,
        payer = creator,
        space = 8 + Rules::INIT_SPACE,
        seeds = [RULES_SEED, challenge.key().as_ref()],
        bump
    )]
    pub rules: Box<Account<'info, Rules>>,
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
    rules_hash: [u8; 32],
    verifier: Pubkey,
    payout: PayoutKind,
    split_bps: Vec<u16>,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    require!(buy_in > 0, ErrorCode::InvalidBuyIn);
    require!(start_time > now && end_time > start_time, ErrorCode::InvalidTimes);
    require!(
        (MIN_PLAYERS..=MAX_PLAYERS).contains(&max_players),
        ErrorCode::InvalidMaxPlayers
    );

    require!(rules_hash != [0u8; 32], ErrorCode::InvalidRulesHash);
    let split = check_split(payout, &split_bps)?;

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

    let rules = &mut ctx.accounts.rules;
    rules.challenge = challenge.key();
    rules.rules_hash = rules_hash;
    rules.verifier = verifier;
    rules.payout = payout;
    rules.split_bps = split;
    rules.bump = ctx.bumps.rules;

    emit!(RulesLocked {
        challenge: challenge.key(),
        rules_hash,
        verifier,
        payout,
        split_bps: split,
    });
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

/// A podium needs 2 or 3 places, each above zero, highest first, adding up to 100%.
/// Every other format pays equal shares and takes no split.
fn check_split(payout: PayoutKind, split_bps: &[u16]) -> Result<[u16; 3]> {
    let mut split = [0u16; 3];
    if payout != PayoutKind::Podium {
        require!(split_bps.is_empty(), ErrorCode::InvalidSplit);
        return Ok(split);
    }
    require!((2..=3).contains(&split_bps.len()), ErrorCode::InvalidSplit);
    require!(split_bps.iter().all(|s| *s > 0), ErrorCode::InvalidSplit);
    require!(split_bps.windows(2).all(|w| w[0] >= w[1]), ErrorCode::InvalidSplit);
    let total: u32 = split_bps.iter().map(|s| *s as u32).sum();
    require!(total == FULL_SHARE_BPS, ErrorCode::InvalidSplit);
    split[..split_bps.len()].copy_from_slice(split_bps);
    Ok(split)
}
