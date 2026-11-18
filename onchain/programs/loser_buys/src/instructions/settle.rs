use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};

use crate::{
    constants::*,
    error::ErrorCode,
    events::{ChallengeSettled, ChallengeSettledSplit},
    instructions::check_recipient,
    state::*,
};

#[derive(Accounts)]
pub struct Settle<'info> {
    pub oracle: Signer<'info>,
    #[account(
        mut,
        seeds = [CHALLENGE_SEED, challenge.creator.as_ref(), &challenge.challenge_id.to_le_bytes()],
        bump = challenge.bump,
        has_one = oracle @ ErrorCode::NotOracle
    )]
    pub challenge: Box<Account<'info, Challenge>>,
    #[account(mut, address = challenge.vault)]
    pub vault: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
    // Remaining accounts: one token account per winner, in the same order as `winners`.
}

/// 100% in basis points (1 basis point = 0.01%).
pub const FULL_SHARE_BPS: u32 = 10_000;

/// Checks shared by `settle` and `settle_split`: the challenge is open and over, has enough
/// players, and the winner list is non-empty, has no duplicates, and names players only.
fn check_can_settle(ctx: &Context<Settle>, winners: &[Pubkey]) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let challenge = &ctx.accounts.challenge;

    require!(
        challenge.status == ChallengeStatus::Open,
        ErrorCode::ChallengeNotOpen
    );
    require!(now >= challenge.end_time, ErrorCode::NotEnded);
    require!(
        challenge.players.len() >= MIN_PLAYERS as usize,
        ErrorCode::NotEnoughPlayers
    );
    require!(
        !winners.is_empty() && winners.len() <= challenge.players.len(),
        ErrorCode::InvalidWinners
    );
    for (i, winner) in winners.iter().enumerate() {
        require!(challenge.players.contains(winner), ErrorCode::WinnerNotPlayer);
        require!(!winners[..i].contains(winner), ErrorCode::InvalidWinners);
    }
    require!(
        ctx.remaining_accounts.len() == winners.len(),
        ErrorCode::WrongNumberOfTokenAccounts
    );
    Ok(())
}

/// Sends `amounts[i]` from the vault to winner i, then marks the challenge settled.
fn pay_out<'info>(
    ctx: &mut Context<'info, Settle<'info>>,
    winners: &[Pubkey],
    amounts: &[u64],
    score_hash: [u8; 32],
) -> Result<()> {
    let challenge = &ctx.accounts.challenge;
    let creator = challenge.creator;
    let mint = challenge.mint;
    let id_bytes = challenge.challenge_id.to_le_bytes();
    let bump = [challenge.bump];
    let seeds: &[&[u8]] = &[CHALLENGE_SEED, creator.as_ref(), &id_bytes, &bump];
    let signer = &[seeds];

    for (i, winner) in winners.iter().enumerate() {
        let recipient = &ctx.remaining_accounts[i];
        check_recipient(recipient, winner, &mint)?;
        if amounts[i] == 0 {
            continue;
        }
        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                Transfer {
                    from: ctx.accounts.vault.to_account_info(),
                    to: recipient.to_account_info(),
                    authority: ctx.accounts.challenge.to_account_info(),
                },
                signer,
            ),
            amounts[i],
        )?;
    }

    let challenge = &mut ctx.accounts.challenge;
    challenge.status = ChallengeStatus::Settled;
    challenge.score_hash = score_hash;
    Ok(())
}

/// Pays the whole pool to the winners, split equally. Any leftover fraction goes to the
/// first winner. Records a hash of the final score sheet so scores cannot be changed later.
pub fn handle_settle<'info>(
    mut ctx: Context<'info, Settle<'info>>,
    winners: Vec<Pubkey>,
    score_hash: [u8; 32],
) -> Result<()> {
    check_can_settle(&ctx, &winners)?;

    let pool_total = ctx.accounts.vault.amount;
    let payout_each = pool_total / winners.len() as u64;
    let leftover = pool_total % winners.len() as u64;
    let amounts: Vec<u64> = (0..winners.len())
        .map(|i| if i == 0 { payout_each + leftover } else { payout_each })
        .collect();

    pay_out(&mut ctx, &winners, &amounts, score_hash)?;

    emit!(ChallengeSettled {
        challenge: ctx.accounts.challenge.key(),
        winners,
        pool_total,
        payout_each,
        score_hash,
    });
    Ok(())
}

/// Pays the pool to the winners in fixed shares, for formats such as a podium (60/30/10).
/// `shares_bps[i]` is winner i's share in basis points; the shares must add up to exactly 100%.
/// Rounding dust goes to the first winner, so the vault always ends empty.
pub fn handle_settle_split<'info>(
    mut ctx: Context<'info, Settle<'info>>,
    winners: Vec<Pubkey>,
    shares_bps: Vec<u16>,
    score_hash: [u8; 32],
) -> Result<()> {
    check_can_settle(&ctx, &winners)?;
    require!(shares_bps.len() == winners.len(), ErrorCode::InvalidShares);
    let total_bps: u32 = shares_bps.iter().map(|s| *s as u32).sum();
    require!(total_bps == FULL_SHARE_BPS, ErrorCode::InvalidShares);

    let pool_total = ctx.accounts.vault.amount;
    let mut amounts = Vec::with_capacity(winners.len());
    for share in &shares_bps {
        let amount = (pool_total as u128)
            .checked_mul(*share as u128)
            .ok_or(ErrorCode::MathOverflow)?
            / FULL_SHARE_BPS as u128;
        amounts.push(amount as u64);
    }
    let paid: u64 = amounts.iter().sum();
    amounts[0] = amounts[0]
        .checked_add(pool_total - paid)
        .ok_or(ErrorCode::MathOverflow)?;

    pay_out(&mut ctx, &winners, &amounts, score_hash)?;

    emit!(ChallengeSettledSplit {
        challenge: ctx.accounts.challenge.key(),
        winners,
        amounts,
        pool_total,
        score_hash,
    });
    Ok(())
}
