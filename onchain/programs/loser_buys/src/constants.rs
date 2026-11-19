use anchor_lang::prelude::*;

/// Seed for the challenge account address.
#[constant]
pub const CHALLENGE_SEED: &[u8] = b"challenge";

/// Seed for the rules account that sits next to each challenge.
#[constant]
pub const RULES_SEED: &[u8] = b"rules";

/// First bytes of every signed result (the Proof of Sweat message). See docs/ARCHITECTURE.md.
#[constant]
pub const PROOF_DOMAIN: &[u8] = b"rival.proof-of-effort.v2";

/// Seed for the token vault that holds the prize pool.
#[constant]
pub const VAULT_SEED: &[u8] = b"vault";

/// Most players one challenge can hold.
#[constant]
pub const MAX_PLAYERS: u8 = 8;

/// A challenge needs at least this many players, otherwise it is refunded.
#[constant]
pub const MIN_PLAYERS: u8 = 2;

/// If the oracle has not settled this long after the end time, anyone can refund.
#[constant]
pub const REFUND_TIMEOUT_SECONDS: i64 = 72 * 60 * 60;
