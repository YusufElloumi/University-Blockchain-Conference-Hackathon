use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};

use crate::{
    constants::*,
    error::ErrorCode,
    events::{ChallengeSettled, ChallengeSettledSplit},
    instructions::check_recipient,
    proof::{signed_result, SignedResult},
    state::*,
};

/// The instructions sysvar: the list of instructions in the current transaction.
pub const INSTRUCTIONS_SYSVAR_ID: Pubkey = pubkey!("Sysvar1nstructions1111111111111111111111111");

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
    #[account(seeds = [RULES_SEED, challenge.key().as_ref()], bump = rules.bump)]
    pub rules: Box<Account<'info, Rules>>,
    /// CHECK: the address is checked; it is read only through `solana_instructions_sysvar`.
    #[account(address = INSTRUCTIONS_SYSVAR_ID)]
    pub instructions_sysvar: UncheckedAccount<'info>,
    pub token_program: Program<'info, Token>,
    // Remaining accounts: one token account per winner, in the same order as the signed winners.
}

/// 100% in basis points (1 basis point = 0.01%).
pub const FULL_SHARE_BPS: u32 = 10_000;

/// The verifier's signed result for this challenge and its rules (see `proof.rs`).
fn read_result(ctx: &Context<Settle>) -> Result<SignedResult> {
    let rules = &ctx.accounts.rules;
    signed_result(
        &ctx.accounts.instructions_sysvar.to_account_info(),
        &rules.verifier,
        &ctx.accounts.challenge.key(),
        &rules.rules_hash,
    )
}

/// Equal shares in basis points; the rounding goes to the first winner (as `formats._equal` in the API).
pub fn equal_shares(count: usize) -> Vec<u16> {
    let each = FULL_SHARE_BPS / count as u32;
    let mut shares = vec![each as u16; count];
    shares[0] = (FULL_SHARE_BPS - each * (count as u32 - 1)) as u16;
    shares
}

/// Podium shares in basis points, in rank order, from the committed split.
///
/// Places nobody can fill (fewer players than places) go to first place. Players tied at a rank
/// share the places they cover equally; the rounding goes to the first of them. `tie_groups[i]` is
/// how many players share the i-th rank; together they must cover every paid place and nobody else.
/// Mirrors `formats.podium` in the API.
pub fn podium_shares(split_bps: &[u16; 3], player_count: usize, tie_groups: &[u8]) -> Result<Vec<u16>> {
    let set = split_bps.iter().filter(|s| **s > 0).count();
    let mut places: Vec<u32> = split_bps[..set.min(player_count)]
        .iter()
        .map(|s| *s as u32)
        .collect();
    require!(!places.is_empty(), ErrorCode::InvalidTieGroups);
    let filled: u32 = places.iter().sum();
    places[0] += FULL_SHARE_BPS - filled;

    let mut shares = Vec::new();
    let mut rank = 0usize;
    for size in tie_groups {
        let size = *size as usize;
        // Every group starts on a paid place; nobody past the paid places is listed.
        require!(size > 0 && rank < places.len(), ErrorCode::InvalidTieGroups);
        let covered = &places[rank..(rank + size).min(places.len())];
        let pot: u32 = covered.iter().sum();
        let each = pot / size as u32;
        shares.push((pot - each * (size as u32 - 1)) as u16);
        shares.extend(std::iter::repeat(each as u16).take(size - 1));
        rank += size;
    }
    require!(rank >= places.len(), ErrorCode::InvalidTieGroups);
    Ok(shares)
}

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

/// Pays the whole pool equally to the winners in the verifier's signed result. Only for formats
/// that pay equal shares; the signed shares must be the equal split. Records the score sheet hash.
pub fn handle_settle<'info>(mut ctx: Context<'info, Settle<'info>>) -> Result<()> {
    require!(
        ctx.accounts.rules.payout != PayoutKind::Podium,
        ErrorCode::WrongPayoutKind
    );
    let result = read_result(&ctx)?;
    let winners = result.winners;
    check_can_settle(&ctx, &winners)?;
    require!(
        result.shares_bps == equal_shares(winners.len()),
        ErrorCode::SharesNotAsCommitted
    );

    let pool_total = ctx.accounts.vault.amount;
    let payout_each = pool_total / winners.len() as u64;
    let leftover = pool_total % winners.len() as u64;
    let amounts: Vec<u64> = (0..winners.len())
        .map(|i| if i == 0 { payout_each + leftover } else { payout_each })
        .collect();

    pay_out(&mut ctx, &winners, &amounts, result.score_hash)?;

    emit!(ChallengeSettled {
        challenge: ctx.accounts.challenge.key(),
        winners,
        pool_total,
        payout_each,
        score_hash: result.score_hash,
    });
    Ok(())
}

/// Podium payout. The oracle chooses the order (through the signed result and `tie_groups`); the
/// program sets the amounts from the split fixed at creation. The signed shares must be exactly
/// those, so the signature covers what is paid. Rounding dust goes to the first winner.
pub fn handle_settle_split<'info>(
    mut ctx: Context<'info, Settle<'info>>,
    tie_groups: Vec<u8>,
) -> Result<()> {
    require!(
        ctx.accounts.rules.payout == PayoutKind::Podium,
        ErrorCode::WrongPayoutKind
    );
    let split = ctx.accounts.rules.split_bps;
    let result = read_result(&ctx)?;
    let winners = result.winners;
    check_can_settle(&ctx, &winners)?;
    let expected = podium_shares(&split, ctx.accounts.challenge.players.len(), &tie_groups)?;
    require!(expected.len() == winners.len(), ErrorCode::InvalidTieGroups);
    require!(result.shares_bps == expected, ErrorCode::SharesNotAsCommitted);

    let pool_total = ctx.accounts.vault.amount;
    let mut amounts = Vec::with_capacity(winners.len());
    for share in &expected {
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

    pay_out(&mut ctx, &winners, &amounts, result.score_hash)?;

    emit!(ChallengeSettledSplit {
        challenge: ctx.accounts.challenge.key(),
        winners,
        amounts,
        pool_total,
        score_hash: result.score_hash,
    });
    Ok(())
}
