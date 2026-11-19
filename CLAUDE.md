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

- **Devnet only.** No mainnet, no real money. The UI says "Demo · Devnet USDC only, no real money" (renamed from "test tokens" Nov 17).
- **Never commit secrets.** Private keys, keypair files, API keys, and tokens live in `.env` or host secrets. `.env` and keypair files are in `.gitignore`. Only `.env.example` (names, no values) is committed.
- **Respect Strava's API terms** (details in `docs/ARCHITECTURE.md` section 5):
  - Show a user's Strava data only to that user. Others see app-computed points only, and only after explicit opt-in consent.
  - Never send Strava data (raw, derived, or anonymized) to any AI or LLM, including Grok.
  - Do not keep raw Strava data longer than 7 days; delete a user's data when they disconnect.
  - Never put fitness data onchain. Only winner addresses and a salted score-sheet hash.
  - Use the official "Connect with Strava" button and "Powered by Strava" mark.
- Fitness data goes through the `FitnessProvider` interface only. Nothing outside `api/fitness/` may import Strava code.
- Flag anything that costs money before using it. Free tiers only.
- **NEVER touch `https://yusufelloumi.github.io`.** It is the owner's portfolio site. Do not publish to it, do not use GitHub Pages for this project (a project page would appear under that address), do not use it as an allowed origin or web address anywhere (Render, Privy, QuickNode), and do not change the portfolio's repository or GitHub Pages settings.

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
| Database | SQLAlchemy; SQLite locally, Neon free Postgres when deployed | Simplest option; free hosts wipe local files, so deployed needs Postgres. Nine tables only |
| Onchain events | QuickNode Stream (Solana Devnet) -> webhook | Bounty; replaces RPC polling |
| Fitness data | `FitnessProvider` interface with Mock, Manual, Strava | Strava may be blocked (subscription, limits, terms); must be swappable |
| Hosting | Render for both: a web service (API) and a static site (web app) | Free tiers, one account, one `render.yaml` |

Decided Nov 14 (Stage 1): the Python server sends `end_early` and `settle` itself with `solders` + `solana-py` (`api/chain.py`), building instructions by hand from the IDL. No Node helper, no `anchorpy`.

## Commands

Rows marked "verified" have been run successfully; the rest are planned.

`scripts/wsl_anchor.sh` copies `onchain/` into the WSL build folder, runs the command there, and copies the IDL, types, and lock files back. Always go through it; do not run `anchor` on the OneDrive path.

| Task | Command | Where |
|---|---|---|
| Build program | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh build` | repo root, PowerShell (verified Nov 14) |
| Test program | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh test --validator legacy` | repo root (verified Nov 18, 13 passing) |
| Deploy to devnet | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh deploy --provider.cluster devnet` | repo root (verified Nov 14) |
| Devnet smoke test | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh smoke` | repo root (verified Nov 14) |
| Oracle from Python | `python chain.py show\|end-early\|settle <challenge> [winners]` with `ORACLE_KEYPAIR_PATH` set | `api/`, venv (verified Nov 14) |
| Oracle split payout | `python chain.py settle-split <challenge> <wallet>:<basis points> ...` (shares add up to 10000) | `api/`, venv (verified Nov 18) |
| Short test challenge | `wsl -d Ubuntu -- env START_IN_HOURS=0.06 LENGTH_HOURS=0.05 bash -l scripts/wsl_anchor.sh create-challenge`, then `join <address> 1` and `join <address> 2` | repo root (verified Nov 18) |
| Devnet SOL | https://faucet.solana.com (`solana airdrop 2` is rate-limited) | browser |
| Run API | `.venv\Scripts\python.exe -m uvicorn main:app --reload` | `api/` (verified Nov 14) |
| Test API | `.venv\Scripts\python.exe -m pytest` (macOS: `.venv/bin/python -m pytest`) | `api/` (verified Nov 18 on Windows, 191 passing) |
| Check a Proof of Effort file | `.venv\Scripts\python.exe attest.py verify <proof.json>` (file from "Download proof"; reads the hash from devnet) | `api/` (verified Nov 18) |
| Run web | `npm run dev` (http://localhost:5173) | `web/` (verified Nov 14) |
| Build web | `npm run build` | `web/` (verified Nov 14) |
| Create a demo challenge | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh create-challenge` then put the printed address in `VITE_DEMO_CHALLENGE` | repo root (verified Nov 14) |
| Add a test player to a challenge | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh join <challenge address>` (uses the `smoke-player-2` wallet; the treasury pays its buy-in) | repo root (verified Nov 14) |
| Run the scheduler step by hand | `POST http://localhost:8000/internal/tick` with header `X-Tick-Secret: <TICK_SECRET from .env>` | anywhere (verified Nov 14) |
| Rebuild plan PDF | `C:\Python313\python.exe scripts/build_plan_pdf.py` (the API venv has no `reportlab`) | repo root (verified Nov 14) |

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
- The repo lives at `D:\dev\loser-buys` (moved off OneDrive on Nov 14). Editing, commits, and pushes happen there. Anchor builds run in a WSL build folder at `~/dev/loser-buys/onchain`, filled by `scripts/wsl_anchor.sh`. Never run `anchor` directly on the Windows path.
- **The C: drive is nearly full** (about 5 GB free on Nov 14, after hitting 0). Keep large things on D:. npm's cache is set to `D:\npm-cache`. Still on C: and growing: the WSL disk (about 10 GB, could be moved with `wsl --manage Ubuntu --move`), pip's cache, and temp files. If an install fails with "no space left", check C: first.
- One `.env` at the repo root serves both the API (`api/config.py` loads it) and the web app (Vite `envDir: ".."`; only `VITE_` names reach the browser).
- Web packages are pinned to exact versions. `npm install` in `web/` takes about 20 minutes on a cold cache (Privy pulls a very large dependency tree).
- Privy React SDK v3: Solana hooks come from `@privy-io/react-auth/solana` and take a serialized transaction (`Uint8Array`). The app builds with Anchor + `@solana/web3.js` v1, signs with `useSignTransaction`, and sends through its own connection (`web/src/chain.ts`).
- Privy embedded wallets need HTTPS or `localhost`. A phone cannot test against the laptop's LAN `http://` address.
- The API finds a user's wallet by asking Privy (`GET https://auth.privy.io/api/v1/users/<id>` with the app secret), never from the browser.
- Local webhook tunnel: `cloudflared tunnel --url http://localhost:8000`. The Stream pauses after 3 failed deliveries, so pause it in the QuickNode dashboard whenever the API or tunnel is off, and resume it after.
- QuickNode's "Check Connection" sends an unsigned request. `POST /webhooks/quicknode` answers unsigned requests with OK and stores nothing; anything with signature headers must verify.
- Neon's command-line tool is installed (`neon`, signed in). The repo is linked through the `.neon` file (ignored by git). Refresh the addresses with `neon env pull --file .env.local -s postgres`. Always pass `--file .env.local`: without it the tool writes `DATABASE_URL` into `.env`, which would switch local runs from SQLite to the live database.
- `.env` is not in git. If the repo is ever cloned again, copy `.env` across by hand.
- Solana Playground (https://beta.solpg.io) is the fallback only. Using it would put the program source, IDL, and deploy wallet outside the repo.

## Deployed IDs and addresses

Fill in as they are created. Public addresses only - never keys.

| Item | Value |
|---|---|
| Program ID (`loser_buys`, devnet) | `FeCj36zk7YNkdfKZXjfjSmftqpJv9C68uBNSvtRt3ssC` (deployed Nov 14; upgraded Nov 18 with `settle_split`) |
| Deploy wallet public key (pays for deploys, upgrade authority) | `AYvBmTfVifruj1XMCGu5pJShLWqo9wYEa1gJFd6pT9re` |
| Oracle public key | `6EEkAR114PYKhJJCWBiJLb342VAMNF69H6dmAB8MtFdD` |
| Verifier public key (signs Proof of Effort results; keypair `~/.config/solana/loser-buys/verifier.json` in WSL, `VERIFIER_KEYPAIR_PATH` in `.env`, needs `VERIFIER_KEYPAIR` on Render) | `5hapcEHu65LyQhqD3Tqtrwm1ftzBnAm93c6jnc8gcway` (created Nov 18) |
| Treasury public key | `J73KdqANTzJ7P1TMTnd37xNCdXvc3LChG7J8X1XX4XY9` |
| USDC mint (devnet) | `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU` |
| QuickNode Stream ID | `daf4568b-a005-4eea-aa1a-732df56eb9ff` (created Nov 14, free plan, no card asked; also in `.env` as `QUICKNODE_STREAM_ID`) |
| Stream network / dataset / destination | Solana Devnet / Programs + Logs / webhook `POST /webhooks/quicknode` (verified Nov 14 through a cloudflared tunnel; the tunnel address changes on every restart, so update the Stream's destination URL each time until the API is deployed) |
| Privy app ID | In `.env` as `PRIVY_APP_ID` and `VITE_PRIVY_APP_ID` (set Nov 14) |
| Demo challenge (devnet, 1 USDC buy-in, joining closes Nov 16 about 4:30 PM CST) | `GNLFdSczFf1GgYXwF1nPLwzTL4Jz5QJrknAMS67vDDc` |
| Neon database | Project `loser buys`, ID `noisy-truth-03069747`, branch `production`, AWS Oregon (created Nov 15, free plan). Addresses are in `.env.local`: `DATABASE_URL` (pooled, the one for Render) and `DATABASE_URL_UNPOOLED` |
| Strava app (client ID) | TBD or not used |
| Oura app redirect URI | `https://loser-buys-api.onrender.com/integrations/oura/callback` (client ID and secret only in Render and `.env`: `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET`, `OURA_REDIRECT_URI`, plus `TOKEN_ENCRYPTION_KEY`) |
| Deployed web URL | TBD: Render static site `loser-buys-web` (not created yet) |
| Deployed API URL | `https://loser-buys-api.onrender.com` (live Nov 15) |

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
- 2026-11-14 (Stage 2): Fees stay hidden with the gas drip (0.02 SOL when a wallet is under 0.005 SOL, max 3 per user). Privy gas sponsorship not used. The `users` table was created now; the other five tables come in Stage 4.
- 2026-11-14 (Stage 4): Added a seventh table, `logged_activities`, for activities entered through our own app (mock and manual sources). Strava activities are never stored there.
- 2026-11-14 (Stage 4): Sharing consent is stored per challenge (`participants.consent_at`), because the consent is given to one group.
- 2026-11-14 (Stage 4): A scoring "day" is a 24-hour block counted from the challenge start, not a calendar day. No time zones needed.
- 2026-11-14 (Stage 4): Pure scoring rules live in `api/scoring.py`; storing points and the leaderboard live in `api/scores.py`. Both get activities only through `fitness.get_provider()`.
- 2026-11-14 (Stage 4): The API never trusts the browser about a challenge. `POST /challenges` and `/join` read buy-in, dates, creator, and players from the chain.
- 2026-11-14 (Stage 4): Activities must start inside the challenge dates and may not overlap. In a challenge created minutes before a demo, each player can add about one workout; for a fuller leaderboard, create the demo challenge a day or more ahead.
- 2026-11-14 (Stage 5): A workout logged in the app counts from the moment it is logged (not dated backwards), so it lands inside a challenge that has just kicked off. A second one within its length is rejected as overlapping.
- 2026-11-14 (Stage 5): The challenge screen polls one call, `GET /challenges/{address}/state`, every 4 seconds. A new Stream event triggers a re-read of the pool and balance; a slow 30-second re-read is the safety net.
- 2026-11-14 (Stage 5): The UI is styled like a fantasy league app (scoreboard, league table with form dots, feed, tabs), dark theme, one accent colour. Friendly, not casino-like. No wallet addresses on screen.
- 2026-11-14 (Stage 5): Challenges are only recorded if they name our oracle and the devnet USDC mint. A challenge made outside the web app is recorded on its first join.
- 2026-11-14 (Stage 6): Settlement lives in `api/settlement.py`. `finish` does whatever is due: refund (fewer than 2 players after the start) or settle (after the end plus `SETTLE_GRACE_SECONDS`). If nobody scored, everyone ties and the pool is split. A player who deposited but never agreed to share points scores zero.
- 2026-11-14 (Stage 6): Any player's screen asks the server to finish a challenge when its clock runs out; the server decides the result. `/internal/tick` does the same for every due challenge and needs the `X-Tick-Secret` header.
- 2026-11-14 (Stage 6): `events.catch_up` fetches missed events from the network after a settlement or refund, because a Solana Stream cannot replay missed blocks. The Stream is still the normal source.
- 2026-11-14 (Stage 6): New columns on an existing table are added at startup by `db._add_missing_columns` (optional columns only). `create_all` alone never alters a table.
- 2026-11-14 (Stage 7): Pick'em tiebreaker built on Gemini's public market data. **Removed Nov 17** (see below). Still true: look up one event by its `ticker` (`GET /v1/prediction-markets/events/<ticker>`; the numeric ID and the slug return 404). The winning side is the contract with `resolutionSide: "yes"`. No user or fitness data is sent to Gemini.
- 2026-11-15: The web app is hosted as a Render static site (second service in `render.yaml`), not Vercel. **Never publish anything under `yusufelloumi.github.io`**: that is the owner's portfolio. No GitHub Pages for this project; a Pages workflow was added and removed the same day, before it published anything. Vite keeps `base: "./"`, which is harmless.
- Tests read the real `.env`. A test that depends on a setting must set it itself (see `TICK_SECRET` in `test_stage6.py`).
- 2026-11-16 (Stage 5b): Three play modes, stored off-chain in `challenges.mode`: `league` (organizer hosts, does not have to play, invite only, `organizer_name` shown), `public` (listed at `GET /events/public`, anyone joins), `private` (invite only, creator plays). Rows with no mode are private. The program was not changed.
- 2026-11-16 (Stage 5b): The server is the gate. League and private events answer 404 to anyone who is not the creator, a player, or in the `invites` table (filled by `POST /invites/redeem`). Invite links are `?invite=CODE`; codes are 6 characters with no look-alikes and not case sensitive. Limit: anyone can still call `join_challenge` onchain directly; we never record them, so they score zero.
- 2026-11-17 (Stage 7b): Prediction rounds (`api/pickrounds.py`, tables `pick_rounds` and `round_picks`). Themes and frequency (24 or 168 hours) are set at creation and stored on `challenges` (`pick_themes`, `round_hours`). The round's market is chosen when the round opens, from `GET /v1/prediction-markets/events?sport=...&sports_market_type=moneyline` (sports: `basketball`, `soccer`, `hockey`, `american_football`); other filters such as `subcategory` are silently ignored by Gemini. A right pick earns 1 / probability, max 5 points; probability is the bid/ask midpoint scaled to 100%, saved at pick time. Settlement waits up to 6 hours after the end for results, then voids. Market page link: `https://www.gemini.com/predictions/<ticker>`.
- 2026-11-17: **No tiebreakers.** The pick'em tiebreaker (`api/pickem.py`, `/pickem/games`, `/challenges/{address}/pick`) was removed. Gemini is used only through prediction rounds, the same way in every mode; a tie at the top splits the pool. An older database may still hold an unused `picks` table; it is left alone.
- 2026-11-17 (Stage 7b): League stats scoring (`api/leaguestats.py`, table `league_stats`, `participants.stat_name`), League events only, chosen at creation (`challenges.scoring_source`, `stat_weights`). The organizer uploads CSV text (sent as JSON; no upload library). The app never reads PDFs or calls Grok; it only shows a link and a prompt. The score sheet records a hash of the stat rows.
- 2026-11-16 (Stage 5b): An event first recorded on join (made by our scripts) is public, so `scripts/wsl_anchor.sh join` keeps working without a code. The player cap stays 8 for every mode.
- 2026-11-17: **The product is now called Rival on screen** (wordmark "rival."). Only user-facing text changed; the program (`loser_buys`), repo, service names and URLs keep the old name. Design rules: dark only, one accent (periwinkle `#929BFF`), Geist for the interface, Instrument Serif italic for headline highlights only, `lucide-react` icons instead of emoji, no per-mode colours. All styles live in `web/src/styles.css`; shared pieces in `web/src/ui.tsx`. On screen say "entry fee", "prize pool" and "leaderboard". The devnet banner wording is unchanged.
- 2026-11-18 (Stage 7c, issue #3): **Competition formats**, stored off-chain on `challenges.format` / `format_config` (JSON), fixed at creation: `winner_takes_all` (default; also any row with no format), `podium` (2-3 places, whole percentages adding to 100, highest first), `goal` (`active_days` or `points`, target 1-100; league stats: points only), `teams` (two names; `participants.team` is 0 or 1). Rules are pure functions in `api/formats.py`; the score sheet includes `format`. Equal payouts use `settle`; unequal ones use the new program instruction `settle_split` (basis points, 10,000 = 100%). Goal missed = equal `settle` to every player, which returns each entry fee. Personal improvement not built (no baseline data in the mock source).
- 2026-11-18 (Stage 7d, issue #1): **Proof of Effort** (shown on screen as **Proof of Sweat**; code names unchanged). A separate verifier key signs each result at settlement (`api/attest.py`, Ed25519, canonical JSON, domain `rival.proof-of-effort`, bound to challenge + program + devnet). Stored offchain in `challenges.attestation`; no fitness data in it. The score sheet now names `rules_version` and `rules_sha256` (`scoring.RULES_VERSION`; bump it whenever a scoring number changes). The browser checks the proof against the published key and the onchain `score_hash` (`web/src/proofCheck.ts`, WebCrypto, no new package). Workout states per challenge: verified / flagged (hand-typed) / rejected; the UI says "Passed checks", not "verified", because demo data is not proof. No Strava button or logo until Strava sign-in works (their brand rules tie the button to the real authorize link); the app shows "Connect a fitness app · Coming soon" instead. Issue #2 (TEE, Solana Confidential Compute) deferred: beta SDK, paid confidential VMs, and our data reaches the backend in plain form anyway.
- 2026-11-18: **Brand v2 replaces the periwinkle palette.** Near-black neutrals (`#070809`), athletic blue `#78AFFF` as the brand accent, citrus green `#BCEB9C` only for progress, activity and positive signals. Typography rule unchanged (Geist plus Instrument Serif italic highlights). The public site is `web/src/Site.tsx` with pages at `?page=how|way|play` (query addresses, so the static host needs no rewrite rules). Photos and the hero film are shown black and white by CSS and live in `web/src/assets/media/`; only add media whose licence allows commercial use, and record it in `CREDITS.md` there. Mixkit "Restricted License" clips are not allowed.
- 2026-11-18: **Three type roles.** Geist for the interface; Instrument Serif italic for emotion and headline highlights (also the lowercase "rival" wordmark); Barlow Condensed capitals (`--caps`) for competition labels and scoreboard numerals only, never headlines. Green is for live state, progress and momentum; blue stays the brand and action colour. Outside the hero film, prefer the drawn graphics in `web/src/graphics.tsx` (lanes, scorelines) over photographs; label any sample data.
- 2026-11-18: **Public site layout rules.** Full browser width with the `--gutter` padding (no centred max-width column); keep paragraphs to a reading width. Stay about 90% dark: vary sections with the `.env-blue`, `.env-charcoal`, `.env-green` backgrounds, not light themes (the off-white ticker is the single light moment). Interactive demos live in `web/src/interactive.tsx`, must use the real scoring rules, run only in the browser, and be labelled as sample data. No animation library is used; scroll effects are a small scroll listener plus CSS.
- 2026-11-18: **Legal pages** at `/privacy` and `/terms` (`web/src/Legal.tsx`), separate Vite pages that load no Privy or Solana code. They must describe only what is built; anything planned (Oura, heart rate, retention limits, deletion controls) is labelled "Planned". Update them whenever data handling changes. No Oura code exists yet.
- 2026-11-19: **Oura connection (OAuth only).** `api/fitness/oura.py`. Three steps because Oura's redirect carries no Rival login: start (signed in) -> callback (parks the encrypted code on a hashed, single-use, 10-minute `oauth_states` row) -> complete (signed in; must be the same user). PKCE S256. Scopes `workout heartrate` only. Tokens encrypted with Fernet (`api/secretbox.py`, `TOKEN_ENCRYPTION_KEY`, comma-separated keys allowed for rotation); losing the key means users reconnect. Disconnect revokes at Oura (best effort) and deletes the tokens. `DELETE /me/fitness` still deletes the Oura row too, without revoking. No Oura data is read yet; the privacy page keeps Oura marked as planned until a real account has been connected end to end.
- 2026-11-19: **Oura data check** (`api/fitness/oura_data.py`, `GET /integrations/oura/workouts`): read-only, owner only, nothing stored. Heart rate is reported as coverage counts only, never bpm. Oura data endpoints: `https://api.ouraring.com/v2/usercollection/workout` (`start_date`/`end_date`, paged by `next_token`) and `/heartrate` (`start_datetime`/`end_datetime`). Workout fields per OpenAPI 1.43: required `id, activity, day, start_datetime, end_datetime, intensity, source`; optional `calories` (kcal), `distance` (metres), `label`. Never send Oura data to an AI service; tests use synthetic records.
- 2026-11-18: **Custom challenge lengths**: 15 minutes to 365 days (a typo guard, not a program limit; the program only needs end after start). Enforced by `POST /challenges` from the chain values (`scoring.MIN_LENGTH` / `MAX_LENGTH`), not on script-made challenges recorded at first join. Scoring days = `scoring.day_count` (24-hour blocks, a shorter last one counts as a day); an active-days goal may not exceed it. **Admins (ADMIN_EMAILS) can open any event**, but the leaderboard stays players-only because points are shared with the group by consent. "Delete my workouts" calls `DELETE /me/fitness`, which removes all of a user's logged workouts (mock and manual) and their points in unsettled challenges.
