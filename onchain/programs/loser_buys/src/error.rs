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
}
