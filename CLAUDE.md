# Loser Buys - project memory

Social fitness challenges with a prize pool. Friend groups join a weekly challenge, each deposits a buy-in (devnet USDC) into a pool held by our Solana program, earn points from fitness activity, and the top scorer is paid by the program.

- **Hackathon:** University Blockchain Conference (UBC) 2026.
- **Deadline:** Friday, Nov 20, 2026, 12:00 PM CST (internal target 10:00 AM). In-person judging Sat Nov 21.
- **Progress source of truth:** `DEVELOPMENT_PLAN.md`. Design and research: `docs/ARCHITECTURE.md`.
- **Team:** small, one main developer, still learning blockchain. Keep explanations plain and define crypto terms.

## Working rules for every session

1. Read this file and `DEVELOPMENT_PLAN.md`, then continue from the first unchecked task.
2. Tick a box only when the task is verified (code runs, tests pass, or the program is deployed and called successfully). Partly done = leave unticked and add a note.
3. After each task: update the checkbox, add a progress log entry, and record new IDs, commands, or decisions here.
4. If the plan changes (feature cut, integration not working), update `DEVELOPMENT_PLAN.md` and explain why in the log.
5. After changing `DEVELOPMENT_PLAN.md` substantially, regenerate the PDF: `python scripts/build_plan_pdf.py`.

## Hard rules

- **Devnet only.** No mainnet, no real money. The UI says "Demo - test tokens only".
- **Never commit secrets.** Private keys, keypair files, API keys, and tokens live in `.env` or host secrets. `.env` and keypair files are in `.gitignore`. Only `.env.example` (names, no values) is committed.
- **Respect Strava's API terms** (details in `docs/ARCHITECTURE.md` section 5):
  - Show a user's Strava data only to that user. Others see app-computed points only, and only after explicit opt-in consent.
  - Never send Strava data (raw, derived, or anonymized) to any AI or LLM, including Grok.
  - Do not keep raw Strava data longer than 7 days; delete a user's data when they disconnect.
  - Never put fitness data onchain. Only winner addresses and a salted score-sheet hash.
  - Use the official "Connect with Strava" button and "Powered by Strava" mark.
- Fitness data goes through the `FitnessProvider` interface only. Nothing outside `api/fitness/` may import Strava code.
- Flag anything that costs money before using it. Free tiers only.

## Prize targets and exact requirements

| Target | Requirements |
|---|---|
| **Main track: Consumer Applications** | Interact with the blockchain; working user-facing frontend (web or mobile). Judging favors invisible crypto (no seed phrases, no gas confusion), daily-use value, thoughtful UX |
| **Chain award: Best use of Solana** | Core onchain functionality on Solana (devnet fine); program ID(s) in the README; explanation of how the project uses Solana. Use Anchor and Solana-native primitives (SPL tokens, devnet USDC) |
| **Bounty: QuickNode Streams** | Streams is a core data source; at least one Stream with a filter and a destination (e.g. webhook); README explains network, dataset, filter logic, destination, and why |
| **Bounty (stretch): Gemini Prediction Markets** | Must use the Gemini Prediction Markets API (market data and/or trading). Only if the feature genuinely adds value |
| **Optional: Grok Bot** (keyboard + swag) | Grok Bot (xAI's assistant inside X) is a core part; chat export; 3-4 sentence README; working and technically sound. Must never receive fitness data |
| **Not targeting** | ElevenLabs; Arc (only one chain award allowed) |
| **Every prize** | Devpost submission with project name, description, team members, track, chain award, bounties, technologies used; public GitHub repo with setup instructions; README with technical docs and architecture; working demo or deployed app; 2-3 minute demo video (YouTube or Google Drive); written answers: What did you build? What problem does it solve? How does it work? What makes it unique? What would you build next? |

Prize values: Track Winner $2,000; Best use of Solana $1,500; QuickNode $500; Gemini $2,500 / $1,000 / $500; overall winner $2,500 / $1,000 / $500 (automatic). All stack except Solana and Arc.

Other rules from `docs/HACKATHON_GUIDE.md` (the source of truth; this table was checked against it on Nov 14):
- Submit at ubc-hackathon-2026.devpost.com. Opt in to track, chain award, and each bounty there.
- The team must be present in person at the closing ceremony (Nov 21) to receive any prize.
- Up to 13 finalists, told by Fri Nov 20 11:59 PM; pitch is 5 minutes plus 2 minutes of Q&A.
- Judging criteria: technical execution, product and UX, innovation, impact and potential, demo.
- The project must be substantially built during the hackathon (started Nov 12). AI tools are allowed.

## Tech stack and why

| Layer | Choice | Why |
|---|---|---|
| Onchain program | Rust + Anchor on Solana devnet | Required by the Solana award; the only new language, kept to one small program |
| Token | Circle devnet USDC, mint `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU` | Real SPL token on devnet; free from faucet. Mint is a parameter so a test token can replace it |
| Frontend | React + Vite + TypeScript | Team knows some React; Privy and Anchor have first-class browser SDKs |
| Auth + wallet | Privy: email login, embedded Solana wallet, wallet popups off | Invisible crypto for the Consumer track; free at our size |
| Fees | "Gas drip": server sends new wallets a little devnet SOL | Simplest way to hide gas; Privy sponsorship is an optional upgrade |
| Backend | Python + FastAPI | Team's strongest language; holds scoring, Strava, webhooks, oracle key |
| Database | SQLAlchemy; SQLite locally, Neon free Postgres when deployed | Simplest option; free hosts wipe local files, so deployed needs Postgres. Six tables only |
| Onchain events | QuickNode Stream (Solana Devnet) -> webhook | Bounty; replaces RPC polling |
| Fitness data | `FitnessProvider` interface with Mock, Manual, Strava | Strava may be blocked (subscription, limits, terms); must be swappable |
| Hosting | Vercel (web), Render (API) | Free tiers |

Decided Nov 14 (Stage 1): the Python server sends `end_early` and `settle` itself with `solders` + `solana-py` (`api/chain.py`), building instructions by hand from the IDL. No Node helper, no `anchorpy`.

## Repo structure (planned; created in Stage 0)

```
onchain/            Anchor workspace: programs/loser_buys (Rust), tests (TypeScript)
web/                React + Vite frontend
api/                FastAPI backend
  fitness/          FitnessProvider interface + mock, manual, strava providers
streams/filter.js   QuickNode Stream filter source
scripts/            devnet smoke test, build_plan_pdf.py
docs/               ARCHITECTURE.md, HACKATHON_GUIDE.md, development_plan.pdf, STRAVA_FLOW.md
```

## Commands

Rows marked "verified" have been run successfully; the rest are planned.

`scripts/wsl_anchor.sh` copies `onchain/` into the WSL build folder, runs the command there, and copies the IDL, types, and lock files back. Always go through it; do not run `anchor` on the OneDrive path.

| Task | Command | Where |
|---|---|---|
| Build program | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh build` | repo root, PowerShell (verified Nov 14) |
| Test program | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh test --validator legacy` | repo root (verified Nov 14, 11 passing) |
| Deploy to devnet | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh deploy --provider.cluster devnet` | repo root (verified Nov 14) |
| Devnet smoke test | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh smoke` | repo root (verified Nov 14) |
| Oracle from Python | `python chain.py show\|end-early\|settle <challenge> [winners]` with `ORACLE_KEYPAIR_PATH` set | `api/`, venv (verified Nov 14) |
| Devnet SOL | https://faucet.solana.com (`solana airdrop 2` is rate-limited) | browser |
| Run API | `uvicorn main:app --reload` | `api/` |
| Test API | `pytest` | `api/` |
| Run web | `npm run dev` | `web/` |
| Build web | `npm run build` | `web/` |
| Rebuild plan PDF | `python scripts/build_plan_pdf.py` | repo root (verified Nov 14) |

Environment notes:
- Windows 11. Node 22.14 and Python 3.13 are installed on the Windows side.
- WSL2 with Ubuntu 26.04 (user `yelloumi`), installed Nov 14. Inside WSL: Rust 1.100.0 (the program itself builds with 1.89.0, pinned in `onchain/rust-toolchain.toml`), Solana CLI 4.3.2 (Agave), Anchor CLI 1.2.2 (via `avm`), Node 22.23.5 as the `nvm` default, Yarn 1.22.22. Solana CLI is set to devnet.
- Node 26 is also installed in WSL but breaks Anchor's mocha test runner. Stay on Node 22.
- Anchor 1.x differences from older tutorials: the TypeScript package is `@anchor-lang/core`; `CpiContext::new` takes the program ID, not an account; `anchor test` defaults to the `surfpool` validator, which is not installed, so pass `--validator legacy`.
- The program keypair (decides the program ID) is backed up at `~/.config/solana/loser-buys/program-keypair.json` in WSL. Smoke-test player wallets live in the same folder.
- The public devnet RPC rate-limits (HTTP 429). Code that talks to it must retry; QuickNode's RPC replaces it in Stage 3.
- Python venv for the API: `api/.venv` (Windows Python 3.13). From Windows, the oracle key path is `\\wsl.localhost\Ubuntu\home\yelloumi\.config\solana\loser-buys\oracle.json`.
- The built IDL and TypeScript types are committed in `onchain/idl/` for the web app and API. Rebuild and recommit them whenever the program changes.
- From Windows, run WSL commands as `wsl -d Ubuntu -- bash -lc "<command>"`. For anything with `$` or quotes, write a script file and run that; inline quoting through PowerShell gets mangled. Node needs `source ~/.nvm/nvm.sh` first in non-interactive shells.
- Keypair files live in WSL only, outside the repo: deploy wallet `~/.config/solana/id.json`; `oracle.json` and `treasury.json` in `~/.config/solana/loser-buys/`. Devnet only. No seed phrases were saved, so the files are the only copy.
- `solana airdrop` is usually rate-limited; use https://faucet.solana.com instead.
- Two copies of the repo: the Windows one under OneDrive (where editing, commits, and pushes happen) and a WSL clone at `~/dev/loser-buys` (where Anchor builds run). Git in WSL has no GitHub login, so it can pull (public repo) but not push. Never build Anchor on the OneDrive path.
- Solana Playground (https://beta.solpg.io) is the fallback only. Using it would put the program source, IDL, and deploy wallet outside the repo.

## Deployed IDs and addresses

Fill in as they are created. Public addresses only - never keys.

| Item | Value |
|---|---|
| Program ID (`loser_buys`, devnet) | `FeCj36zk7YNkdfKZXjfjSmftqpJv9C68uBNSvtRt3ssC` (deployed Nov 14) |
| Deploy wallet public key (pays for deploys, upgrade authority) | `AYvBmTfVifruj1XMCGu5pJShLWqo9wYEa1gJFd6pT9re` |
| Oracle public key | `6EEkAR114PYKhJJCWBiJLb342VAMNF69H6dmAB8MtFdD` |
| Treasury public key | `J73KdqANTzJ7P1TMTnd37xNCdXvc3LChG7J8X1XX4XY9` |
| USDC mint (devnet) | `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU` |
| QuickNode Stream ID | TBD (Stage 3) |
| Stream network / dataset / destination | Solana Devnet / Programs + Logs / webhook `POST /webhooks/quicknode` (planned) |
| Privy app ID | TBD (Stage 0) |
| Strava app (client ID) | TBD or not used |
| Deployed web URL | TBD (Stage 9) |
| Deployed API URL | TBD (Stage 9) |

## Decisions log

- 2026-11-14: Embedded wallets (Privy) over connect-wallet, for the Consumer track.
- 2026-11-14: Results are reported by a server-held oracle key; limits on that trust are winners-must-be-players, a score-sheet hash, and a 72-hour refund timeout.
- 2026-11-14: Leaderboard shows points only, with opt-in consent, to fit Strava's policy. Demo defaults to the mock provider.
- 2026-11-14: Gemini pick'em and Grok are stretch items, decided at the Wed Nov 18 cut line.
- 2026-11-14: App name is **Loser Buys** for now (may change; Loser Buys was the other candidate). Program name `loser_buys`. Keep the UI tone friendly, not casino-like.
- 2026-11-14: Program tests are TypeScript (mocha) rather than Anchor 1.x's default Rust LiteSVM tests, because the same client code is reused by the smoke script and the web app.
- 2026-11-14: Winners are paid into their standard ("associated") USDC token account. `settle` and `refund` take those accounts as extra accounts, in list order, and the program checks owner and mint.
- 2026-11-14: `end_early` before the start time also closes joining (start time becomes now).
- 2026-11-14: Nobody has a Strava subscription yet. Build on the mock/manual provider; revisit Strava as we go.
