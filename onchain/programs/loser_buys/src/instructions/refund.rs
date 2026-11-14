use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};

use crate::{constants::*, error::ErrorCode, events::ChallengeRefunded, state::*};

#[derive(Accounts)]
pub struct Refund<'info> {
    /// Anyone can trigger a refund once it is allowed. They only pay the fee.
    pub caller: Signer<'info>,
    #[account(
        mut,
        seeds = [CHALLENGE_SEED, challenge.creator.as_ref(), &challenge.challenge_id.to_le_bytes()],
        bump = challenge.bump
    )]
    pub challenge: Box<Account<'info, Challenge>>,
    #[account(mut, address = challenge.vault)]
    pub vault: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
    // Remaining accounts: one token account per player, in the same order as `challenge.players`.
}

/// Checks that `account` is a token account for `mint` that belongs to `owner`.
/// Stops funds from being sent to anyone who is not the intended recipient.
pub fn check_recipient(account: &AccountInfo, owner: &Pubkey, mint: &Pubkey) -> Result<()> {
    require_keys_eq!(*account.owner, token::ID, ErrorCode::InvalidTokenAccount);
    let data = account.try_borrow_data()?;
    let token_account = TokenAccount::try_deserialize(&mut &data[..])
        .map_err(|_| error!(ErrorCode::InvalidTokenAccount))?;
    require_keys_eq!(token_account.owner, *owner, ErrorCode::InvalidTokenAccount);
    require_keys_eq!(token_account.mint, *mint, ErrorCode::InvalidTokenAccount);
    Ok(())
}

/// Returns every buy-in. Allowed when fewer than 2 players joined by the start time,
/// or when the oracle has not settled within 72 hours of the end time.
pub fn handle_refund<'info>(ctx: Context<'info, Refund<'info>>) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let challenge = &ctx.accounts.challenge;

    require!(
        challenge.status == ChallengeStatus::Open,
        ErrorCode::ChallengeNotOpen
    );
    let too_few_players =
        now >= challenge.start_time && challenge.players.len() < MIN_PLAYERS as usize;
    let oracle_timed_out = now >= challenge.end_time.saturating_add(REFUND_TIMEOUT_SECONDS);
    require!(
        too_few_players || oracle_timed_out,
        ErrorCode::RefundNotAllowed
    );
    require!(
        ctx.remaining_accounts.len() == challenge.players.len(),
        ErrorCode::WrongNumberOfTokenAccounts
    );

    let creator = challenge.creator;
    let id_bytes = challenge.challenge_id.to_le_bytes();
    let bump = [challenge.bump];
    let seeds: &[&[u8]] = &[CHALLENGE_SEED, creator.as_ref(), &id_bytes, &bump];
    let signer = &[seeds];

    for (i, player) in challenge.players.iter().enumerate() {
        let recipient = &ctx.remaining_accounts[i];
        check_recipient(recipient, player, &challenge.mint)?;
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
            challenge.buy_in,
        )?;
    }

    let challenge = &mut ctx.accounts.challenge;
    challenge.status = ChallengeStatus::Refunded;

    emit!(ChallengeRefunded {
        challenge: challenge.key(),
        player_count: challenge.players.len() as u8,
        refund_each: challenge.buy_in,
    });
    Ok(())
}
