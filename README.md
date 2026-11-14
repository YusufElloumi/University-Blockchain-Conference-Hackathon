# Loser Buys

University Blockchain Conference Hackathon 2026.
Team: Yusuf Elloumi, Shaan Bhasin, Rohan Bhasin, Mahdi Khani.

Social fitness challenges with a prize pool. A friend group joins a weekly challenge, each person
deposits a buy-in (devnet USDC) into a pool held by our Solana program, everyone earns points from
fitness activity, and the program pays the top scorer.

**Demo only: Solana devnet and test tokens. No real money.**

This README is a work in progress. Full setup instructions and architecture notes are added as the
app is built; see `docs/ARCHITECTURE.md` for the design.

## Solana program

| Item | Value |
|---|---|
| Program ID (devnet) | [`FeCj36zk7YNkdfKZXjfjSmftqpJv9C68uBNSvtRt3ssC`](https://explorer.solana.com/address/FeCj36zk7YNkdfKZXjfjSmftqpJv9C68uBNSvtRt3ssC?cluster=devnet) |
| Framework | Anchor 1.2.2 (Rust) |
| Token | Circle devnet USDC, an SPL token: `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU` |
| Source | `onchain/programs/loser_buys/` |
| Interface (IDL) | `onchain/idl/loser_buys.json` |

The program holds each challenge's prize pool in a token vault that only the program can spend from.

| Instruction | Who can call | What it does |
|---|---|---|
| `create_challenge` | Anyone | Creates a challenge and its empty vault |
| `join_challenge` | Any player, before the start time | Moves the buy-in into the vault and adds the player |
| `end_early` | Oracle only | Ends the challenge now (demo and testing) |
| `settle` | Oracle only, after the end time | Pays the pool to the winners, who must be players, and records a hash of the score sheet |
| `refund` | Anyone | Returns every buy-in if fewer than 2 players joined, or if the oracle has not settled within 72 hours |

The oracle is a key held by our server. It reports who won, because fitness data lives off the
blockchain. It cannot send funds to anyone outside the player list, and funds cannot get stuck.

## Run the program tests

Needs WSL2 (Ubuntu) on Windows, or Linux/macOS, with Rust, the Solana CLI, Anchor 1.2.2, Node 22 and Yarn.

```
cd onchain
yarn install
anchor test --validator legacy
```

On Windows with the repo outside WSL, from the repo root:

```
wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh test --validator legacy
```
