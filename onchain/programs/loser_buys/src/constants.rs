use anchor_lang::prelude::*;

/// Seed for the challenge account address.
#[constant]
pub const CHALLENGE_SEED: &[u8] = b"challenge";

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
