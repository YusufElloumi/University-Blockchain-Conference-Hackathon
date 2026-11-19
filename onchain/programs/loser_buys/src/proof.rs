//! Reads the verifier's signed result (Proof of Sweat v2) from the Ed25519 signature check that
//! must come right before `settle` / `settle_split` in the same transaction.
//!
//! Solana's Ed25519 program runs before any program instruction: if the signature in it is wrong,
//! the whole transaction fails. So if that instruction is present, names our verifier key and
//! carries the message, the message really was signed by the verifier. This module only has to
//! find it (through the instructions sysvar, the transaction's own instruction list) and read it.
//!
//! Signed message layout (all fixed sizes, integers little-endian), documented in docs/ARCHITECTURE.md:
//!   domain      24 bytes  "rival.proof-of-effort.v2"
//!   program     32 bytes  this program's ID
//!   challenge   32 bytes  the challenge account
//!   rules_hash  32 bytes  must equal Rules.rules_hash
//!   score_hash  32 bytes  SHA-256 of the final score sheet (stored by settle)
//!   count        1 byte   number of winners, 1 to 8
//!   winners     32 bytes each, in payout order
//!   shares       2 bytes each (u16, basis points), same order

use anchor_lang::prelude::*;
use solana_instructions_sysvar::{load_current_index_checked, load_instruction_at_checked};

use crate::{constants::*, error::ErrorCode};

/// Solana's native Ed25519 signature-check program.
pub const ED25519_PROGRAM_ID: Pubkey = pubkey!("Ed25519SigVerify111111111111111111111111111");

/// "This instruction" in the Ed25519 offsets: the key, signature and message are inside the check itself.
const THIS_INSTRUCTION: u16 = u16::MAX;
const HEADER: usize = 2; // number of signatures, padding
const OFFSETS: usize = 14; // seven u16 values

pub struct SignedResult {
    pub score_hash: [u8; 32],
    pub winners: Vec<Pubkey>,
    pub shares_bps: Vec<u16>,
}

fn u16_at(data: &[u8], at: usize) -> Result<u16> {
    let bytes = data
        .get(at..at + 2)
        .ok_or(error!(ErrorCode::MissingSignatureCheck))?;
    Ok(u16::from_le_bytes([bytes[0], bytes[1]]))
}

/// Finds the Ed25519 check right before the current instruction, makes sure it is by `verifier`,
/// and returns the result it signed after checking it is for this program, challenge and rules.
pub fn signed_result(
    instructions_sysvar: &AccountInfo,
    verifier: &Pubkey,
    challenge: &Pubkey,
    rules_hash: &[u8; 32],
) -> Result<SignedResult> {
    let current = load_current_index_checked(instructions_sysvar)? as usize;
    require!(current > 0, ErrorCode::MissingSignatureCheck);
    let check = load_instruction_at_checked(current - 1, instructions_sysvar)?;
    require_keys_eq!(
        check.program_id,
        ED25519_PROGRAM_ID,
        ErrorCode::MissingSignatureCheck
    );
    let data = &check.data;
    // Exactly one signature, whose key, signature and message all live inside this instruction
    // (offsets could otherwise point at bytes in some other instruction).
    require!(
        data.len() >= HEADER + OFFSETS && data[0] == 1,
        ErrorCode::MissingSignatureCheck
    );
    let field = |n: usize| u16_at(data, HEADER + 2 * n);
    let (signature_ix, key_offset, key_ix) = (field(1)?, field(2)? as usize, field(3)?);
    let (message_offset, message_size, message_ix) =
        (field(4)? as usize, field(5)? as usize, field(6)?);
    require!(
        signature_ix == THIS_INSTRUCTION
            && key_ix == THIS_INSTRUCTION
            && message_ix == THIS_INSTRUCTION,
        ErrorCode::MissingSignatureCheck
    );
    let key = data
        .get(key_offset..key_offset + 32)
        .ok_or(error!(ErrorCode::MissingSignatureCheck))?;
    require!(key == verifier.as_ref(), ErrorCode::WrongVerifier);
    let message = data
        .get(message_offset..message_offset + message_size)
        .ok_or(error!(ErrorCode::MissingSignatureCheck))?;
    parse(message, challenge, rules_hash)
}

/// Reads a signed message and checks the parts that bind it to this program, challenge and rules.
pub fn parse(message: &[u8], challenge: &Pubkey, rules_hash: &[u8; 32]) -> Result<SignedResult> {
    let fixed = PROOF_DOMAIN.len() + 32 * 4 + 1;
    require!(message.len() > fixed, ErrorCode::InvalidSignedResult);
    let mut at = 0;
    let mut take = |n: usize| {
        let part = &message[at..at + n];
        at += n;
        part
    };
    require!(take(PROOF_DOMAIN.len()) == PROOF_DOMAIN, ErrorCode::InvalidSignedResult);
    require!(take(32) == crate::ID.as_ref(), ErrorCode::InvalidSignedResult);
    require!(take(32) == challenge.as_ref(), ErrorCode::InvalidSignedResult);
    require!(take(32) == rules_hash.as_ref(), ErrorCode::InvalidSignedResult);
    let score_hash: [u8; 32] = take(32).try_into().unwrap();
    let count = take(1)[0] as usize;
    require!(
        (1..=MAX_PLAYERS as usize).contains(&count) && message.len() == fixed + count * 34,
        ErrorCode::InvalidSignedResult
    );
    let winners = (0..count)
        .map(|_| Pubkey::try_from(take(32)).unwrap())
        .collect();
    let shares_bps = (0..count)
        .map(|_| {
            let b = take(2);
            u16::from_le_bytes([b[0], b[1]])
        })
        .collect();
    Ok(SignedResult {
        score_hash,
        winners,
        shares_bps,
    })
}
