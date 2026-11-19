use anchor_lang::prelude::*;

#[error_code]
pub enum ErrorCode {
    #[msg("Buy-in must be greater than zero")]
    InvalidBuyIn,
    #[msg("Start time must be in the future and before the end time")]
    InvalidTimes,
    #[msg("Max players must be between 2 and 8")]
    InvalidMaxPlayers,
    #[msg("This challenge is already settled or refunded")]
    ChallengeNotOpen,
    #[msg("Joining closed when the challenge started")]
    JoinClosed,
    #[msg("The challenge is full")]
    ChallengeFull,
    #[msg("This player has already joined")]
    AlreadyJoined,
    #[msg("Only the oracle can do this")]
    NotOracle,
    #[msg("The challenge has already ended")]
    AlreadyEnded,
    #[msg("The challenge has not ended yet")]
    NotEnded,
    #[msg("Not enough players joined; use refund instead")]
    NotEnoughPlayers,
    #[msg("Winner list is empty, too long, or has duplicates")]
    InvalidWinners,
    #[msg("A winner is not in the player list")]
    WinnerNotPlayer,
    #[msg("Refund is not allowed yet")]
    RefundNotAllowed,
    #[msg("Expected one token account per recipient, in order")]
    WrongNumberOfTokenAccounts,
    #[msg("A token account has the wrong owner or the wrong token")]
    InvalidTokenAccount,
    #[msg("Math overflow")]
    MathOverflow,
    #[msg("Need one share per winner, adding up to exactly 100%")]
    InvalidShares,
    #[msg("Rules hash must not be empty")]
    InvalidRulesHash,
    #[msg("Payout split must be 2 or 3 places, highest first, adding up to 100% (podium only)")]
    InvalidSplit,
    #[msg("These are not the rules this challenge was created with")]
    RulesMismatch,
    #[msg("This payout is not allowed by the challenge's format")]
    WrongPayoutKind,
    #[msg("The payout shares are not the ones the challenge's rules give")]
    SharesNotAsCommitted,
    #[msg("Tie groups must cover the paid places and every winner")]
    InvalidTieGroups,
    #[msg("Expected the verifier's Ed25519 signature check right before this instruction")]
    MissingSignatureCheck,
    #[msg("The signature check is not by this challenge's verifier")]
    WrongVerifier,
    #[msg("The signed result is malformed or for another program, challenge or rules")]
    InvalidSignedResult,
}
