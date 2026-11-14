use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};

use crate::{
    constants::*, error::ErrorCode, events::ChallengeSettled, instructions::check_recipient,
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

/// Pays the whole pool to the winners, split equally. Any leftover fraction goes to the
/// first winner. Records a hash of the final score sheet so scores cannot be changed later.
pub fn handle_settle<'info>(
    ctx: Context<'info, Settle<'info>>,
    winners: Vec<Pubkey>,
    score_hash: [u8; 32],
) -> Result<()> {
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

    let pool_total = ctx.accounts.vault.amount;
    let payout_each = pool_total / winners.len() as u64;
    let leftover = pool_total % winners.len() as u64;

    let creator = challenge.creator;
    let id_bytes = challenge.challenge_id.to_le_bytes();
    let bump = [challenge.bump];
    let seeds: &[&[u8]] = &[CHALLENGE_SEED, creator.as_ref(), &id_bytes, &bump];
    let signer = &[seeds];

    for (i, winner) in winners.iter().enumerate() {
        let recipient = &ctx.remaining_accounts[i];
        check_recipient(recipient, winner, &challenge.mint)?;
        let amount = if i == 0 {
            payout_each + leftover
        } else {
            payout_each
        };
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
            amount,
        )?;
    }

    let challenge = &mut ctx.accounts.challenge;
    challenge.status = ChallengeStatus::Settled;
    challenge.score_hash = score_hash;

    emit!(ChallengeSettled {
        challenge: challenge.key(),
        winners,
        pool_total,
        payout_each,
        score_hash,
    });
    Ok(())
}
