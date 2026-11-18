# Development Plan - Loser Buys

**Source of truth for progress.** Update the checkboxes and the progress log as work happens.

- Submission deadline: **Friday, November 20, 2026, 12:00 PM CST**. Internal target: submit by **10:00 AM**.
- In-person judging: Saturday, November 21, 2026.
- Plan written: Saturday, November 14, 2026. Nothing below has been built or verified yet.
- Background and reasoning: see `docs/ARCHITECTURE.md`. Session rules: see `CLAUDE.md`.

**Checkbox rule:** only tick a box when the task is verified (code runs, tests pass, or the program is deployed and called successfully). If something is partly done, leave it unticked and add a note under it.

## The MVP in one paragraph

A friend signs up with their email and gets a Solana wallet without ever seeing one. They open an invite link, tap "Join for 1 USDC", and their devnet USDC moves into a prize pool held by our Anchor program. During the week they earn points from fitness activities (Strava, or a mock/manual source). The leaderboard and activity feed update live, driven by a QuickNode Stream that watches our program. When the week ends (or an admin taps "End week now"), our server reports the winner to the program and the program pays out the pool.

## Feature tiers

| Tier | Features |
|---|---|
| Essential (never cut) | Anchor program on devnet (create, join, settle, refund); email login with embedded wallet; deposit of devnet USDC; one challenge template; leaderboard; one QuickNode Stream feeding the activity feed and deposit/payout status; admin "End week now"; ties split the pool; README, video, written answers |
| Important (cut only if behind) | Live Strava connection (otherwise mock/manual source plus a documented Strava flow); second challenge template; automatic end-of-week timer; refund button in the UI; polished mobile layout |
| Bounty-only | QuickNode: webhook signature check, `streams/filter.js` kept in the repo, README section. Gemini: prediction rounds (Stage 7b; the Stage 7 tiebreaker was removed). Grok: challenge helper (Stage 8) |
| Later (not for the hackathon) | Leaving a challenge before it starts, friends backing a participant, dispute window, multi-signer results, mainnet, more data sources (WHOOP, Garmin, Apple Health) |

## Schedule at a glance

One main developer, roughly 40 focused hours before the cut line. Estimates assume Claude Code writes most of the code and the developer reviews and tests.

| Stage | When | Est. hours | What | Prize |
|---|---|---|---|---|
| 0 | Sat Nov 14 | 2-3 | Tooling, accounts, repo skeleton | All |
| 1 | Sat-Sun Nov 14-15 | 6-8 | RISK: Anchor program deployed and called on devnet | Solana, Consumer |
| 2 | Sun-Mon Nov 15-16 | 4-6 | RISK: email login, embedded wallet, deposit with no wallet popup | Consumer, Solana |
| 3 | Mon Nov 16 | 3-4 | RISK: QuickNode Stream to webhook | QuickNode |
| 4 | Tue Nov 17 | 6-8 | Backend, database, fitness data layer, scoring | Consumer |
| 5 | Tue-Wed Nov 17-18 | 6-8 | Product screens end to end | Consumer |
| 6 | Wed Nov 18 | 3-4 | Settlement, payout, admin early end | Solana, Consumer |
| - | Wed Nov 18, 8 PM | - | CUT LINE REVIEW | - |
| 7 | Thu Nov 19 | 3-4 | Stretch: Gemini pick'em | Gemini |
| 8 | Thu Nov 19 | 2-3 | Optional: Grok | Grok |
| 9 | Thu-Fri Nov 19-20 | 5-6 | Deploy, README, video, written answers, submit (never cut) | All |

Office hours (Nov 16-19) fall on Stages 2-7. Bring the questions listed near the end of this file.

---

## Stage 0 - Setup and accounts (Sat Nov 14, 2-3 h)

**Goal:** every tool and account we need exists, so later stages are not blocked by sign-ups or installs.

**Working result:** `anchor --version` and `solana --version` print versions inside WSL; `solana balance` shows devnet SOL; every account below exists and its keys are in a local `.env` that git ignores.

**Satisfies:** groundwork for every prize; "public GitHub repo with setup instructions" starts here.

- [x] Fill in `docs/HACKATHON_GUIDE.md` and re-check every checklist in this file against it. (Done Nov 14: guide added, checklists and open questions updated.)
- [ ] Decide who is listed on the Devpost submission. The guide allows teams of 1-4; README lists four names, the brief says two people. Everyone listed must attend the closing ceremony in person on Nov 21 to qualify for any prize.
- [ ] Get the office hours and workshop times from the schedule linked in the guide (or the Telegram) and put them on the calendar.
- [x] Confirm skills. (Confirmed Nov 14: Python, some JavaScript/React, no Rust or Solana experience. Stack stands.)
- [x] Install WSL2 with Ubuntu (`wsl --install -d Ubuntu`, may need a restart). Anchor does not support native Windows. (Done Nov 14: Ubuntu 26.04 on WSL2, after enabling virtualization in the BIOS.)
- [x] Clone the repo inside the WSL home folder (for example `~/dev/...`), not under OneDrive. Rust builds on a OneDrive-synced Windows path are very slow and OneDrive will try to sync build folders. (Done Nov 14: cloned to `~/dev/loser-buys` at commit `79fb620`. Git in WSL has no GitHub login yet, so pushes still go from the Windows copy.)
- [x] In WSL, run the Solana one-line installer (installs Rust, Solana CLI, Anchor, Node, Yarn). Record the real versions in `CLAUDE.md`. (Done Nov 14, installed piece by piece instead of the one-liner because it needs a sudo password: Rust 1.100.0, Solana CLI 4.3.2, Anchor 1.2.2, Node 26.13.1, Yarn 1.22.22.)
- [x] `solana config set -ud`, create a deploy keypair, and collect devnet SOL (`solana airdrop 2`, plus https://faucet.solana.com). Start early: faucets are rate-limited and deploying a program needs a few SOL. (Done Nov 14: `solana airdrop` was rate-limited; the web faucet worked. Deploy wallet 5 SOL, treasury 5 SOL, checked with `solana balance`.)
- [x] Create the server wallets (keypair files outside git): `oracle` (reports results) and `treasury` (hands out test SOL and test USDC). (Done Nov 14: in WSL at `~/.config/solana/loser-buys/`; addresses in `CLAUDE.md`.)
- [ ] Start collecting devnet USDC for the treasury at https://faucet.circle.com (20 USDC per 2 hours per address). Repeat through the week.
  - Note (Nov 14): started. Treasury 20 USDC, deploy wallet 20 USDC (checked with `spl-token accounts`). Keep repeating for the treasury.
- [ ] Create accounts: Privy (free Developer plan), QuickNode (free trial; note whether a card is required), Vercel, Render, Neon. Flag anything that asks for payment.
  - Note (Nov 14): Privy and QuickNode accounts exist (QuickNode under the school email, free plan, no card asked). Vercel, Render, and Neon still to create.
- [ ] Strava: check whether a team member already has a Strava subscription. Strava's docs say a subscription is required to create an API app. **This may cost money.** If nobody has one, skip live Strava and use the mock/manual source.
  - Note (Nov 14): nobody has a subscription yet; the team will decide as we go. Build on the mock/manual source until then.
- [x] Add `.gitignore` (`.env`, keypair files, `target/`, `node_modules/`, `.anchor/`, `*.db`) and `.env.example` with variable names only. (Done Nov 14. Keypairs are matched by `*keypair*.json`, not `*.json`, so `package.json` and the IDL can be committed. Checked with `git check-ignore`.)
- [x] Create the folder skeleton: `onchain/`, `web/`, `api/`, `streams/`, `scripts/`. (Done Nov 14, with `.gitkeep` placeholders.)
- [ ] Fallback check: open https://beta.solpg.io and confirm it can build an Anchor project in the browser, in case WSL setup fails.

## Stage 1 - RISK: Anchor program on devnet (Sat-Sun, 6-8 h)

**Goal:** the prize pool program exists on devnet and has been called successfully from a script.

**Working result:** `anchor test` passes locally. The program is deployed to devnet. A script creates a challenge, has two test wallets join with devnet USDC, settles, and the winner's USDC balance goes up. All transaction links open in Solana Explorer.

**Satisfies:** Solana award (core onchain functionality, Anchor, SPL token/devnet USDC, program ID in README); Consumer track ("interact with the blockchain").

Program design (kept small on purpose):

| Instruction | Who can call | What it does |
|---|---|---|
| `create_challenge` | Anyone (the group creator) | Creates the challenge account and a token vault owned by the program. Stores buy-in, token mint, start and end time, max players (8), and the oracle address |
| `join_challenge` | Any player, before start time | Moves the buy-in from the player's token account into the vault and adds the player to the list |
| `end_early` | Oracle only | Sets the end time to now (demo and testing) |
| `settle` | Oracle only, after end time | Takes a list of winners (must be players) and a hash of the final score sheet. Splits the vault equally among winners and pays them in the same transaction |
| `refund` | Anyone | Returns every buy-in if fewer than 2 players joined by start time, or if the oracle has not settled within 72 hours of the end time |

Each instruction emits an event (`ChallengeCreated`, `PlayerJoined`, `ChallengeEnded`, `ChallengeSettled`, `ChallengeRefunded`) so the QuickNode Stream has something to read.

- [x] `anchor init` the workspace in `onchain/`, program name `loser_buys`. (Done Nov 14, Anchor 1.2.2, TypeScript/mocha test template.)
- [x] Write the `Challenge` account, the vault, and the five instructions with events and clear error codes. (Done Nov 14. Settle pays the vault's full balance; winner and refund token accounts are passed as extra accounts and checked for owner and mint.)
- [x] Tests on a local validator: happy path, tie (2 winners), join after start rejected, settle by a non-oracle rejected, winner not in player list rejected, settle before end rejected, refund paths. (Done Nov 14: 11 tests pass with `anchor test --validator legacy`.)
  - Gap: the 72-hour refund timeout is not exercised by a test, because the local validator's clock cannot be moved forward. Only the "too early" rejection and the fewer-than-2-players refund are tested. A Rust LiteSVM test could cover it if time allows.
- [x] Deploy to devnet. Record the program ID in `CLAUDE.md` and `README.md`. (Done Nov 14: `FeCj36zk7YNkdfKZXjfjSmftqpJv9C68uBNSvtRt3ssC`, cost about 1.15 devnet SOL.)
- [x] `scripts/devnet_smoke` runs the full create, join, join, settle flow on devnet using the real devnet USDC mint (`4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`). (Done Nov 14. Lives at `onchain/scripts/devnet_smoke.js` so it can use the Anchor packages; winner's balance rose by 0.50 USDC and the vault emptied.)
- [x] Decide how the Python server calls the program: try `solders` plus `solana-py` (or `anchorpy`) to send `settle`. If that is not working within 2 hours, use a tiny Node script with the official Anchor client instead, and log the decision. (Done Nov 14: `solders` + `solana-py` work. `api/chain.py` sent `end_early` and `settle` on devnet from Windows Python. No Node helper and no `anchorpy` needed.)
- [ ] Fallback if devnet USDC is scarce: create our own test token. The mint is a parameter, so no program change is needed.

## Stage 2 - RISK: Invisible wallet flow (Sun-Mon, 4-6 h)

**Goal:** a person with only an email address can deposit into a challenge without seeing a wallet, a seed phrase, or a gas fee.

**Working result:** in the browser, log in with an email code, see a balance in dollars, press one button, and a `join_challenge` transaction lands on devnet signed by the embedded wallet with no wallet popup. Works on a phone browser too.

**Satisfies:** Consumer track (working frontend, invisible crypto, no seed phrases, no gas confusion); Solana award (onchain call from the real app).

- [x] React + Vite + TypeScript app in `web/` with `@privy-io/react-auth`. (Done Nov 14: Vite 8, React 19, Privy 3.51.4, versions pinned exactly. Type-check and production build pass.)
- [x] Email login through Privy's login modal, with `embeddedWallets.solana.createOnLogin: 'users-without-wallets'`. (Automatic wallet creation only works through Privy's modal, not a custom code form.) (Done Nov 14: two accounts signed in by email code and each got a Solana wallet.)
- [x] Turn off wallet confirmation popups (`showWalletUIs: false`) and replace them with our own plain-language confirm button ("Join for 1 USDC"). (Done Nov 14: no popup appeared in the browser test.)
- [x] FastAPI server in `api/` with one endpoint that verifies the Privy access token (ES256 JWT; check signature, expiry, issuer `privy.io`, audience = our app ID). (Done Nov 14: `api/auth.py`, keys from Privy's JWKS URL. 13 tests pass, including expired, wrong issuer, wrong app, and wrong key.)
- [x] Gas plan A ("gas drip"): on first login the server sends a small amount of devnet SOL from the treasury to the new wallet. The user never sees it. (Done Nov 14: `POST /me/setup` sends 0.02 SOL when a wallet holds under 0.005 SOL, at most 3 times per user.)
- [x] "Add test funds" button: the server sends 5 devnet USDC from the treasury (stands in for a card on-ramp in the demo). Limit to once per user. (Done Nov 14: `POST /me/fund`. The wallet address comes from Privy's server, not the browser. Amount is set by `TEST_FUNDS_USDC`.)
- [x] Build and send `join_challenge` from the browser with the Anchor TypeScript client and the Privy wallet. Pin package versions (`@anchor-lang/core` works with `@solana/web3.js` v1 only). (Done Nov 14: two browser accounts joined devnet challenge `GNLFdSczFf1GgYXwF1nPLwzTL4Jz5QJrknAMS67vDDc`; both wallets are in its onchain player list.)
- [ ] Optional upgrade if time: Privy native gas sponsorship (`sponsor: true`). Needs TEE execution and prepaid credits; check whether devnet is free before enabling.
- [ ] Test on one phone browser.
  - Note (Nov 14): not done. Embedded wallets need HTTPS, so a phone cannot use the laptop's `http://` address. Test through a tunnel or after the Stage 9 deploy.

## Stage 3 - RISK: QuickNode Stream (Mon, 3-4 h)

**Goal:** our server learns about every onchain event from a QuickNode Stream, not by polling.

**Working result:** running the Stage 1 smoke script makes rows appear in the `chain_events` table within seconds, delivered by the Stream's webhook and passing the signature check.

**Satisfies:** QuickNode Streams bounty (Stream configured with a filter and a destination; Streams is a core data source).

- [x] Create one Stream: network Solana Devnet, dataset "Programs + Logs" (fall back to "Block" if the payload lacks what we need), start at chain tip. (Done Nov 14: Stream `loser-buys-devnet`, Solana Devnet, Programs + Logs, started at the chain tip.)
- [x] Write the filter in `streams/filter.js`: keep only successful transactions that call our program ID; return signature, slot, block time, and log lines; return `null` otherwise. Test it with the dashboard's "Run Test". (Done Nov 14: pasted into the dashboard; the smoke test's five transactions all came through it. Local check: `node streams/test_filter.js`.)
- [x] Destination: webhook to `POST /webhooks/quicknode` on the API. For local work use a tunnel (for example `cloudflared`). (Done Nov 14: through a `cloudflared` quick tunnel. The dashboard's "Check Connection" sends an unsigned request, so the endpoint answers unsigned requests with OK and stores nothing.)
- [x] Verify each delivery: HMAC-SHA256 over nonce + timestamp + body using the Stream's security token (`X-QN-Nonce`, `X-QN-Timestamp`, `X-QN-Signature`). (Done Nov 14: `api/events.py`. Real deliveries passed the check; wrong token, changed body, partly signed, and old deliveries are rejected in tests.)
- [x] Decode the program's events from the log lines and store them, de-duplicated by transaction signature (the free plan has no reorg handling, so the handler must be safe to run twice). (Done Nov 14: `chain_events` table. The smoke test produced 5 rows: ChallengeCreated, 2 PlayerJoined, ChallengeEnded, ChallengeSettled. 22 API tests pass.)
- [x] Record the Stream ID, network, dataset, and destination in `CLAUDE.md`. (Done Nov 14: Stream `daf4568b-a005-4eea-aa1a-732df56eb9ff`.)
- [x] Note for later: a Stream pauses after 3 failed deliveries. If the server sleeps or restarts, re-activate the Stream. (Noted Nov 14 in `CLAUDE.md`. The filter returns nothing for blocks without our program, so failures only happen if someone uses the program while the API or tunnel is down.)

## Stage 4 - Backend, database, fitness layer (Tue, 6-8 h)

**Goal:** the server can turn fitness activities into daily points, from any data source.

**Working result:** with the mock source, adding an activity for a user changes their points; switching `FITNESS_PROVIDER` between `mock`, `manual`, and `strava` needs no change outside `api/fitness/`. If Strava is available, a real activity recorded on a watch shows up as points within a minute.

**Satisfies:** Consumer track (daily-use value); respects the Strava hard rules.

Database (SQLite locally, free Neon Postgres when deployed; same code through SQLAlchemy):

| Table | Holds |
|---|---|
| `users` | Privy ID, email, display name, wallet address |
| `fitness_connections` | Provider, athlete ID, encrypted tokens, sharing consent time |
| `challenges` | Name, rules, buy-in, start/end, status, invite code, onchain address |
| `participants` | Which user is in which challenge, deposit transaction |
| `score_entries` | Per user, per day: points, source, source activity ID |
| `chain_events` | Events received from the QuickNode Stream |

- [x] Create the six tables and the SQLAlchemy models. (Done Nov 14 in `api/db.py`, with a seventh table, `logged_activities`, for activities entered through our own app. Sharing consent is stored per challenge in `participants.consent_at`, not in `fitness_connections`. Tables confirmed in the local SQLite file.)
- [x] Define the `FitnessProvider` interface: `connect_url`, `handle_callback`, `fetch_activities(user, start, end)`, `disconnect`. Every provider returns the same simple `Activity` shape (type, start time, minutes, distance, device, is_manual). (Done Nov 14: `api/fitness/base.py`, plus `log_activity` for sources where the user enters activities. `FITNESS_PROVIDER` picks the source in `api/fitness/__init__.py`.)
- [x] `MockProvider` (scripted activities for demos and tests) and `ManualProvider` (user logs an activity; marked unverified). (Done Nov 14. Mock activities look like watch recordings; manual ones are labelled "Self-reported (unverified)" and still earn points.)
- [x] Scoring engine with one template: "Daily Mover" - 1 point for each day with at least 20 active minutes, plus 1 point per 5 km, max 3 points per day. Unit tests. (Done Nov 14: `api/scoring.py`. A "day" is a 24-hour block counted from the challenge start, so no time zones are involved.)
- [x] Anti-cheat rules in scoring: ignore manual entries when the source is Strava, ignore activities outside the challenge window, ignore duplicates, cap points per day, reject impossible speeds. (Done Nov 14, plus overlapping activities and a required device name. The owner is told why an activity did not count. 51 API tests pass.)
- [ ] `StravaProvider` (only if a subscription and app exist): OAuth with `activity:read`, token refresh, one webhook subscription, fetch activity on webhook, "Connect with Strava" button and "Powered by Strava" mark.
  - Note (Nov 14): not built; nobody has a Strava subscription. `FITNESS_PROVIDER=strava` answers with a clear "not set up" message.
- [ ] Strava data rules in code: store only points plus the activity ID, purge raw data within 7 days, delete everything for a user who disconnects, never send Strava data to any AI service.
  - Note (Nov 14): partly done, and it applies to every source. `score_entries` holds points and activity IDs only; `DELETE /me/fitness` deletes the user's activities, connection, and points in unsettled challenges; other players see points only. Not done: the 7-day purge, which only matters once Strava data exists.
- [x] Write `docs/STRAVA_FLOW.md` describing the intended Strava integration step by step, whether or not it is live. (Done Nov 14.)

New endpoints (all need the login token): `POST /challenges`, `POST /challenges/{address}/join`, `GET /challenges/{address}/leaderboard`, `POST /me/activities`, `GET /me/activities`, `DELETE /me/fitness`. Challenge details and the player list are read from the chain, not trusted from the browser.

Not yet verified: these endpoints have only been run in tests (with a fake chain and fake login), not from the browser against devnet. That happens in Stage 5, when the screens call them.

## Stage 5 - Product screens (Tue-Wed, 6-8 h)

**Goal:** a new user can go from an invite link to a live leaderboard on their phone.

**Working result:** two people on two phones: one creates a challenge and shares a link, the other signs up, adds test funds, joins, and both see the pool total, the leaderboard, and a live activity feed.

**Satisfies:** Consumer track (working frontend, thoughtful UX).

- [x] Create challenge screen: name, template, buy-in, start and end. Calls `create_challenge`. (Done Nov 14: `web/src/CreateChallenge.tsx`. Start and end are picked as "friends can join for" and "then it runs for". Two challenges created from the browser on devnet with no wallet popup.)
- [x] Invite link and join screen with a clear consent line: "Share my challenge points with this group." (Done Nov 14. The Join button stays off until the box is ticked. "Invite friends" uses the phone's share sheet, or copies the link.)
- [ ] Deposit status comes from the Stream event, not from the browser guessing ("Deposit confirmed").
  - Note (Nov 14): built, and it shows "Deposit confirmed" from a stored `PlayerJoined` event. But the Stream was paused during this session, so the events came from the catch-up (see Stage 6), not from a live Stream delivery. Tick after one join is confirmed with the Stream running.
- [x] Leaderboard: display name, points, daily ticks. Points only; no raw activity details of other people. (Done Nov 14: the "Table" tab, shown only to players who agreed to share points.)
- [x] "My activity" view (only the owner sees their own activities, with a "View on Strava" link when relevant). (Done Nov 14: the "My workouts" tab, with a "Log a workout" form for the mock and manual sources. A logged run scored 2 points in the browser. No Strava link, since Strava is not connected.)
- [ ] Live feed from `chain_events`: "Maya joined - pool is now 3 USDC", "Week settled - Sam won 4 USDC".
  - Note (Nov 14): built (the "Feed" tab) and showing real devnet events, but not yet seen updating from a live Stream delivery. Same check as the deposit status.
- [x] Plain-language money: show "USDC" and dollar amounts, hide addresses behind a "details" link to Solana Explorer. (Done Nov 14. No wallet address appears anywhere in the app.)
- [ ] Mobile layout pass at phone width.
  - Note (Nov 14): the layout is a single 460-pixel column with large tap targets, but it has only been looked at in a desktop browser. Needs the phone test (HTTPS).

Look and feel (asked for on Nov 14): styled like a fantasy league app. A scoreboard header with the pool, player count, and a countdown to kick-off; a league table with rank, form dots for active days, and points; a live feed; three tabs. Dark "pitch" theme with one bright accent colour.

Not done from the "working result": two people on two phones. One real account plus a scripted test player (`scripts/wsl_anchor.sh join <challenge>`) were used instead.

## Stage 6 - Settlement and payout (Wed, 3-4 h)

**Goal:** the week ends, the right person is paid by the program, and everyone can see it.

**Working result:** an admin taps "End week now"; within seconds the winner's balance rises, the challenge shows as settled with an Explorer link, and the feed shows the payout event that arrived through the Stream. A tie pays both winners half.

**Satisfies:** Solana award (program controls the pool and distributes winnings); Consumer track; the "admin action to end a week early" requirement.

- [x] Finalize step: pull any missing activities, compute final scores, pick winner(s), build the score-sheet hash. (Done Nov 14: `api/settlement.py`. The sheet holds wallet and points only, plus a random salt. After a real settlement, the hash stored onchain matched the sheet in our database.)
- [x] Server sends `settle` signed by the oracle key. (Done Nov 14, on devnet from the running API.)
- [x] Admin page (admin emails set in `.env`): "End week now" sends `end_early` then `settle`. (Done Nov 14. It is a section on the challenge screen, shown only to emails in `ADMIN_EMAILS`, with a second "Yes, end and pay out" tap. Used for both devnet settlements below.)
- [ ] Automatic path: a `/internal/tick` endpoint settles challenges whose end time plus a grace period has passed; call it from a free scheduler (for example GitHub Actions cron or cron-job.org).
  - Note (Nov 14): the endpoint exists, is protected by `TICK_SECRET`, and answered correctly on the running API (nothing was due). The scheduler is not set up; it needs the deployed API address (Stage 9). Also, the challenge screen asks the server to pay out as soon as the clock runs out (`POST /challenges/{address}/finish`), so a payout does not depend on the scheduler while someone has the page open. That screen-triggered path passed its tests but was not watched live.
- [x] Refund button for a challenge that never reached 2 players. (Done Nov 14: appears once the challenge has started with fewer than 2 players. The server sends `refund`; the oracle only pays the fee.)
- [x] Test on devnet: single winner, tie, refund. (Done Nov 14, all through the web app with one real account and a scripted test player.)
  - Refund: challenge `JMjBkJYw2mopKmVdKHYacpoQa52jwfaCTxmb8j9Y2WD`, 1 player, balance went from 3 back to 4 USDC.
  - Single winner: challenge `6xr7yYYLKur31ZBnf4NnD7YrDVJoxYWax9zp6TiTdsLt`, scores 1 and 0, winner's balance went from 3 to 5 USDC.
  - Tie: challenge `9fXUkUszcHksGWTmDNht32cKSNCYRKXK3kEqDvcoRGep`, ended before kick-off with nobody scoring, each player received 1 USDC.

Added beyond the plan: a catch-up (`events.catch_up`) that fetches a challenge's recent transactions from the network and stores any events we missed. It runs after every settlement or refund. Reason: a Solana Stream cannot replay blocks it failed to deliver, and the Stream was paused during this session. The Stream stays the normal source; the README must describe this honestly.

Still to verify for the "working result": the payout event arriving through the live Stream (it was paused), and the feed updating on a second person's screen.

## Stage 5b - Play modes: League, Public, Private (Mon Nov 16, 3-4 h)

Every event belongs to one mode. Mode is off-chain metadata on our server; the program is unchanged.

- [x] `challenges.mode` (`league`, `public`, `private`) and `organizer_name`; new `invites` table; events from before modes are private.
- [x] Server-side access rules: league and private events cannot be read (state, leaderboard, score sheet, finish, pick) or joined without being the creator, a player, or having redeemed the invite code. Outsiders get 404.
- [x] `GET /events/public`, `POST /invites/redeem`, `GET /me/challenges?mode=`. Six-character invite codes without look-alike characters.
- [x] Tests for the access rules (`api/tests/test_modes.py`); all 103 API tests pass.
- [x] Screens: home with three mode cards, a mode screen (public list, or invite-code box plus my events), create flow that takes the mode from its screen, mode badge and "Hosted by" on the event page, invite links by code. Type-check and build pass.
- [ ] Click through on devnet with two real accounts: create one event per mode, join a public one from the list, join a private and a league one by code, and check that a wrong code is refused.
- Known limit: the program's `join_challenge` is open to anyone who knows the address, so an uninvited wallet could still deposit directly onchain. Our server never records them, so they score zero. Closing that onchain would need a program change (server co-signs joins); not done.
- Player cap is still 8 per event (`MAX_PLAYERS`, account sized at creation), public events included.

## CUT LINE REVIEW - Wednesday, November 18, 8:00 PM

Ask one question: **is Stage 6 verified on devnet?**

- **Yes:** continue to Stage 7 (Gemini) only if at least 4 spare hours remain before Stage 9; otherwise go straight to Stage 9.
- **No:** drop everything below, in this order, and finish Stages 5-6 on Thursday morning. Stage 9 must start by Thursday 2 PM.

| Drop order | Feature dropped | What we do instead |
|---|---|---|
| 1 | Grok (Stage 8) | Nothing |
| 2 | Gemini (Stage 7) | Mention as future work |
| 3 | Live Strava | Demo with mock/manual source; show `docs/STRAVA_FLOW.md` and explain why |
| 4 | Privy native gas sponsorship | Keep the gas drip |
| 5 | Automatic end-of-week timer | Admin "End week now" only |
| 6 | Second template, refund button, extra polish | One template; refund stays in the program and is shown by script |

Never cut: program on devnet, email login with embedded wallet, deposit, one working Stream, settle with payout, and all of Stage 9.

## Stage 7 - Stretch: Gemini pick'em tiebreaker (Thu, 3-4 h) - bounty-only - REMOVED Nov 17

**Removed Nov 17:** replaced by prediction rounds (Stage 7b). Ties now always split the pool. Kept below as a record.

**Goal:** a feature that uses Gemini Prediction Markets data and fits the product.

**Working result:** when creating a challenge, the group can turn on "Pick'em tiebreaker". The app lists live sports events from Gemini with current prices; each member makes one free pick before the week starts; if the week ends in a tie, the correct pick wins instead of splitting.

**Satisfies:** Gemini Prediction Markets bounty (uses the API for market data). The guide confirms market data alone qualifies, and lists "bring prediction market data into other apps, such as ... social" as an objective. This is the largest bounty ($2,500 / $1,000 / $500), so it is the first stretch item to build. See the honest assessment in `docs/ARCHITECTURE.md` before starting.

- [ ] Ask Gemini at office hours first: is a pick'em built on live market data the kind of entry they want to see, and what would make it stronger?
  - Note (Nov 14): built ahead of office hours because the public API needed no account. Still worth asking; the answer could change what we show.
- [x] Server proxy for `GET /v1/prediction-markets/events` (public, no key) with a short cache. (Done Nov 14: `api/pickem.py`, `GET /pickem/games`, 60-second cache. Lists active Sports events with exactly two sides starting in the next 7 days. Real games and odds showed in the browser.)
- [x] Pick screen with event title and current yes/no price; store picks. (Done Nov 14: a "Tiebreaker pick" card on the challenge screen, shown to players. Each side shows the market's chance as a percentage. A real pick was saved from the browser. New table: `picks`.)
- [ ] Resolve picks from the event's settlement status; apply as tiebreaker in the finalize step.
  - Note (Nov 14): written and tested against a pretend Gemini (right pick wins a tie, points beat picks, unsettled or equal picks split, an outage splits). Not yet seen with a real settled game: that needs a tied challenge that ends after its picked game has finished. The field we rely on (`resolutionSide: "yes"`) was checked on real settled games.
- [x] README section on the Gemini integration. (Done Nov 14.)

Decision (Nov 14): the pick'em is available in every challenge rather than being a switch on the create screen. It is optional per player and only matters in a tie, so a switch added a step for no benefit.

## Stage 7b - Gemini prediction rounds and league stats scoring (Tue Nov 17, 8-10 h)

**Goal:** make Gemini central rather than a tiebreaker, and let leagues score from their own stat sheet. Research and verdicts: chat report of Nov 17 (summarised in the progress log).

**Working result:** at setup the organizer picks themes (Basketball, Soccer, Hockey, Football, General) and a round frequency (daily, or weekly). Each round the server chooses one real Gemini market; players pick a side; a right pick earns 1 / chance points, capped at 5. In League mode the organizer can switch scoring to "League stats" and upload a CSV (template, plus a Grok prompt for PDFs; the app never calls Grok).

- [x] Market chooser and result reader (`api/pickrounds.py`): sport and moneyline filters, full-game scope, ranking, Sunday rule, themes taking turns, General from 24-hour volume including price ladders as yes/no. (Done Nov 17: 24 new tests against a pretend Gemini; also run against the live API, which chose a real market for every theme, for example NBA Portland vs Minnesota and EPL Arsenal vs Newcastle.)
- [x] Tables `pick_rounds`, `round_picks`, `league_stats`; new optional columns on `challenges` and `participants`. Pick and stat points in the leaderboard; settlement waits up to 6 hours for results, then voids. (Done Nov 17: 127 API tests pass.)
- [x] League stats: CSV template, upload, automatic and manual name matching, weights, stats hash in the score sheet. (Done Nov 17, tested.)
- [x] Screens: theme picker and frequency on the create screen, scoring source switch for League events, round card with live odds and a link to the market on Gemini, organizer stat-sheet card. (Done Nov 17: `npm run build` passes.)
- [ ] Click through on devnet: create a 1-day event with picks on, make picks from two accounts, and see a real game resolve and its points land on the table.
- [ ] Click through a League stats event: upload the template, match names, see points.

Decisions (Nov 17): replaces the Stage 7 tiebreaker, which was then removed entirely (no tiebreakers; ties split). Probability = mid of bid and ask, scaled to 100%, saved at pick time (Gemini has no price history). Cap of 5 points. A round's market must finish before the challenge ends. Default one round a week for League stats, one a day otherwise. "Points only, no money is staked" shown on every pick card. The Solana program did not change.

## Stage 7c - Competition formats (Wed Nov 18, GitHub issue #3, branch `competition-formats`)

**Goal:** more ways to compete than winner takes all. Chosen at creation, locked afterwards, and written into the score sheet whose hash goes onchain.

Formats built: **Winner takes all** (unchanged default), **Podium** (default 60/30/10; 2 or 3 places, organizer sets the percentages), **Goal** (reach N active days or N points; everyone who makes it splits the pool; nobody makes it = every entry fee goes back), **Team vs team** (two named teams, picked when joining; team score = average, so uneven teams are fair; the winning team splits the pool; tied teams split among everyone on them). **Personal improvement was not built:** it needs a fitness history to compare against, and the mock/manual source has none, so a demo would be faked.

- [x] Program: new `settle_split(winners, shares_bps, score_hash)` instruction (shares in basis points, must add up to 100%; rounding dust to first place) and `ChallengeSettledSplit` event; new error `InvalidShares` added at the end, so existing error codes are unchanged. `settle`, `refund` and the account layout are unchanged, so existing challenges keep working. (Done Nov 18: 13 program tests pass, 2 new.)
- [x] Upgrade the program on devnet (same program ID) and call `settle_split` once for real. (Done Nov 18: upgrade tx `2suVQCWw...TejRgTi`, program data auto-extended by 12,000 bytes. Test challenge `FxKZaN9G1PxS4zRUT3YdCZNyDDL2HGN3gZjRmvzjCwTz`, two smoke players, ended early and settled 70/30 from `python chain.py settle-split`: tx `52siznHM...h5wsnxC` paid 1.4 and 0.6 USDC from a 2 USDC pool; `events.decode_events` reads the `ChallengeSettledSplit` event.)
- [x] API: `api/formats.py` (pure payout rules), columns `challenges.format`, `challenges.format_config`, `participants.team`; create validates settings; join takes a team (a join without one goes to the smaller team); state returns team standings, goal progress and each player's projected share; settlement uses `settle` for equal splits and `settle_split` otherwise; feed sentence for split payouts. (Done Nov 18: 142 API tests pass; 28 new in `test_formats.py` cover rules and create -> join -> score -> settle for each format.)
- [x] Screens: format picker (four tiles) with podium percentages, goal type and target, and team names; join pop-up explains the format and asks for a team; leaderboard shows a format line, team standings, goal progress, and podium shares. (Done Nov 18: `npm run build` passes.)
- [ ] Click through on devnet: one event per format, two accounts, end with "End challenge now", check the payout amounts in the explorer.
- [ ] Phone-width check of the format picker and team standings.

Rules (Nov 18): ties are handled by each format (podium: tied players share the places they cover equally; places nobody can fill go to first). Refunds are unchanged for every format: fewer than 2 players at the start, or no result 72 hours after the end. "Goal missed" is paid with a plain equal `settle` to every player, which returns each entry fee exactly; the program needed no new refund rule. A league-stats event can only use a points goal.

## Stage 7d - Proof of Effort (Wed Nov 18, GitHub issue #1, branch `proof-of-effort`)

**Goal:** results anyone in the group can check, without a real fitness connection. A separate verifier key signs each result; the browser checks it against the hash stored onchain. Workouts get a visible state. Honest "Coming soon" for fitness sync.

- [x] Rules version and fingerprint in `api/scoring.py`, written into every score sheet (so into the onchain hash).
- [x] Workout states per challenge: verified, flagged (hand-typed, still counts), rejected (with reason). `GET /me/activities?challenge=<address>`, owner only.
- [x] `api/attest.py`: Ed25519 proof bound to challenge, program, devnet and a domain label; `check()` with plain-language problems; `python attest.py verify <file>`. Signed at settlement, stored in `challenges.attestation`. `GET /verifier` publishes the key and rules.
- [x] 21 new tests (`api/tests/test_proof.py`): valid proof, edited message, changed sheet, replay on another challenge, other network/program/domain/schema, wrong signer, onchain hash mismatch, no verifier key, workout states. 163 API tests pass.
- [x] Real devnet run (Nov 18): test challenge `8wrBXzJadpevoTvwuet2KsEE5s92iA7kyBLVjRbL8S3n`, two smoke players, settled by the local API with the real verifier key (tx `K1RKwjHZ...YGA2vc`, tie, 50/50). `attest.py verify` says OK against devnet; a copy with an edited score is rejected. The browser's WebCrypto steps, run in Node, verify the signature and match the onchain hash.
- [x] Web: "Check result" card on settled challenges (players only), workout state tags, "Connect a fitness app · Coming soon" pop-up. `npm run build` passes.
- [ ] Click through in the browser with two accounts: settle a challenge, open "Check result", see three green checks.
- [x] Fixes after first look (Nov 18): the card is renamed **Proof of Sweat** and sits in the right column; the result trophy is centred again (`.notice-card span` was also styling the icon box); the feed shows player names in events with prediction rounds (the rounds code had overwritten the wallet-to-name lookup, so names fell back to "Player" plus the last 4 characters of the wallet). Regression test added; 164 API tests pass.
- [ ] Render: add the `VERIFIER_KEYPAIR` secret (contents of `verifier.json`) before merging, or deployed results will not be signed.
- [ ] Stretch (Option B): check the verifier signature inside the program (Solana's Ed25519 program plus instruction introspection), so anyone could submit a signed result. Only if deploy, README and video are on track.
- Not done from issue #1: a real fitness provider (needs a paid Strava subscription), a `revoked` state, and an onchain signature check.
- Issue #2 (TEE with Solana Confidential Compute): deferred past the hackathon. The beta SDK came out Nov 13 and is unaudited, confidential VMs cost money, and our workouts reach the backend in plain form, so a privacy claim would be false.

## Stage 8 - Optional: Grok (Thu, 2-3 h) - bounty-only

**Goal:** only if Stage 7 is done or skipped with time left. Per the guide, Grok Bot is xAI's assistant built into X that can run tasks, automate workflows, and watch onchain activity. The prize is a keyboard and swag, so this is the lowest priority.

**Possible feature:** Grok Bot watches our program's onchain events and posts a group recap on X ("Pool of 4 USDC settled, winner paid"). It would see wallet and pool events only.

**Satisfies:** Grok Bot bounty (Grok Bot is a core part, chat export, 3-4 sentence README, working and technically sound).

- [ ] Redeem X Premium (link from organizers) and test what Grok Bot can actually do with a Solana devnet program.
- [ ] Keep all fitness data away from Grok. Strava's policy forbids sending Strava data to AI, including derived data such as points.
- [ ] Chat export and README section.

## Stage 9 - Ship (Thu-Fri, 5-6 h) - never cut

**Goal:** everything the judges need exists and works from a clean start.

**Working result:** a stranger can open the deployed link, sign up, and join a challenge; the repo README lets someone run it locally; the submission form is sent by Friday 10:00 AM.

**Satisfies:** every general submission requirement and each prize's README requirements.

- [ ] Deploy `web/` (Vercel) and `api/` (Render free plan + Neon free Postgres). Point the Stream webhook at the deployed API and re-activate the Stream.
  - Note (Nov 14): prepared, nothing deployed. `render.yaml` describes the API service; server keys can come from the secrets `ORACLE_KEYPAIR` and `TREASURY_KEYPAIR` (file contents) instead of file paths; a plain Postgres address is accepted and the `psycopg` driver is in `requirements.txt`; `.github/workflows/tick.yml` calls `/internal/tick` every 10 minutes once the secrets `API_URL` and `TICK_SECRET` exist (it also keeps the server awake). **None of this has run against Postgres or Render.** Expect small fixes on the first deploy. Needs the Vercel, Render, and Neon accounts.
  - Note (Nov 15): Neon project `loser buys` created (free plan, Oregon, branch `production`). The API's database code ran against it: all 8 tables created, times and large numbers stored and read back correctly, pooled and direct addresses both work. The addresses are in `.env.local` (not in git); local runs still use SQLite. Render and Vercel still to do.
  - Note (Nov 15): the API is live on Render at `https://loser-buys-api.onrender.com` (health, settings, webhook connection test, and login refusals checked from outside; logged-in calls and writing to Neon not checked yet). Plan change: the web app will be a Render static site (`loser-buys-web` in `render.yaml`) instead of Vercel. GitHub Pages was considered and dropped, because its address sits under the owner's portfolio site. The static site has not been created or built on Render yet.
- [ ] Keep-alive ping so the free server does not sleep during judging; re-check the Stream is active before the demo.
- [ ] Clean-machine test: follow the README setup steps from scratch.
- [ ] README: what it is, architecture diagram, setup, program ID(s), how we use Solana, QuickNode section (network, dataset, filter logic, destination, why), security and trust notes, Strava note, devnet-only disclaimer.
- [ ] Record the 2-3 minute demo video (script: problem, sign-up, join, activity, live feed, end week, payout, Explorer link). Upload to YouTube or Google Drive and check the link opens in a private window.
- [ ] Write the five answers.
- [ ] Final secret scan of the repo and git history; make the repo public.
- [ ] Submit on Devpost (ubc-hackathon-2026.devpost.com): select Consumer Applications, chain award Solana, and opt in to each bounty we actually built.
- [ ] Prepare the finalist pitch: 5 minutes plus 2 minutes of Q&A, built around the judging criteria (technical execution, product and UX, innovation, impact, demo). Finalists are told by Friday 11:59 PM.
- [ ] Prepare the in-person demo: seeded challenge, two phones, backup video. The team must be at the closing ceremony to receive any prize.

---

## Submission checklist

**General (every prize)** - from "What to Submit" in `docs/HACKATHON_GUIDE.md`. Submitted on Devpost.

- [ ] Project name, short description, and all team members (Stage 9)
- [ ] Main track selected: Consumer Applications; chain award selected: Best use of Solana; every bounty we are applying for opted in (Stage 9)
- [ ] Technologies and sponsor tools used (Stage 9)
- [ ] Public GitHub repo with source code and setup instructions, built during the hackathon (Stage 0, 9)
- [ ] README with technical documentation and architecture overview (Stage 9)
- [ ] Working demo or deployed app (Stage 9)
- [ ] 2-3 minute demo video on Google Drive or YouTube, accessible to judges (Stage 9)
- [ ] Track-specific items: program ID(s) and Solana explanation in the README (Stage 1, 9)
- [ ] Team present in person at the closing ceremony on Nov 21
- [ ] Answer: What did you build? (Stage 9)
- [ ] Answer: What problem does it solve? (Stage 9)
- [ ] Answer: How does it work? (Stage 9)
- [ ] Answer: What makes it unique? (Stage 9)
- [ ] Answer: What would you build next? (Stage 9)

**Consumer Applications track**

- [ ] Interacts with the blockchain (Stage 1, 2, 6)
- [ ] Working user-facing frontend, web or mobile (Stage 2, 5)
- [ ] Crypto is invisible: no seed phrases (Stage 2), no gas confusion (Stage 2), plain-language money (Stage 5)
- [ ] Daily-use value: daily points and live feed (Stage 4, 5)

**Best use of Solana**

- [ ] Core onchain functionality on Solana devnet (Stage 1, 6)
- [ ] Program written with Anchor (Stage 1)
- [ ] SPL token (devnet USDC) used for the pool (Stage 1)
- [ ] Program ID(s) listed in the README (Stage 1, 9)
- [ ] README explains how the project uses Solana (Stage 9)

**QuickNode Streams bounty**

- [ ] At least one Stream configured with a filter and a destination (Stage 3)
- [ ] Streams is a core data source: deposit status, feed, and payout confirmation all come from it (Stage 3, 5, 6)
- [ ] README explains network, dataset, filter logic, destination, and why (Stage 9)
- [ ] Filter source committed at `streams/filter.js` (Stage 3)

**Gemini Prediction Markets bounty (stretch)**

- [ ] Project uses the Gemini Prediction Markets API (Stage 7)
- [ ] README section describing the use (Stage 7)

**Grok Bot bounty (optional)**

- [ ] Grok Bot is a core part of the project (Stage 8)
- [ ] Grok Bot chat export included (Stage 8)
- [ ] 3-4 sentence README section on Grok Bot's role (Stage 8)
- [ ] Working and technically sound (Stage 8)

## Open questions

Answered by the guide (Nov 14): prizes stack (track + one chain award + bounties + overall winner); teams of 1-4; devnet is fine; market data alone qualifies for Gemini; Grok Bot is the assistant inside X; finalists get 5 minutes plus 2 minutes of Q&A.

**Organizers**

- [ ] Are there rules against apps involving wagering between users, even with test tokens?
- [ ] "A working demo or deployed application": is a hosted link expected, or is a local demo plus video enough? (We plan to deploy either way.)
- [ ] Do non-finalist teams demo to judges in person on Nov 21, or only the 13 finalists?
- [ ] Where is the office hours schedule, and when is each sponsor's session?

**Solana office hours**

- [ ] Review our program accounts and the oracle + refund-timeout trust model. Is there a simple improvement judges would value?
- [ ] Is paying winners inside `settle` (up to 8 token transfers) fine, or should we use a claim step?
- [ ] Best way to make fees invisible for a hackathon: gas drip, our own fee payer, or Privy sponsorship?
- [ ] Is the Python client path (`solders`/`anchorpy`) reliable with the current Anchor version?
- [ ] Can we get extra devnet SOL if the faucet limits block a deploy?
- [ ] What do judges look for in "Best use of Solana" beyond a deployed program?

**Circle office hours**

- [ ] Is Circle's devnet USDC mint the right token for a demo, and can we get more than 20 USDC per 2 hours?
- [ ] We are not entering the Arc award. Does using devnet USDC on Solana qualify for anything from Circle?
- [ ] For a real launch, what would a compliant on-ramp from card to USDC look like?

**QuickNode**

- [x] Does the free trial allow a Solana **devnet** Stream with a filter and webhook? Is a card required? (Answered Nov 14 by doing it: yes on the free plan, no card.)
- [ ] Which dataset is better for program events on Solana: "Programs + Logs" or "Block"? What does the payload look like for our program?
- [ ] Our webhook server may sleep on a free host. What is the best way to avoid the Stream pausing, and can we replay missed blocks on the free plan (docs say no backfill for Solana)?
- [ ] What makes Streams count as a "core data source" in the judges' eyes?

**Gemini**

- [ ] What separates a winning entry from one that merely uses the API? Would a pick'em on live odds inside a social app place?
- [ ] Is our reading correct that third parties cannot create custom markets?
- [ ] Are prediction markets enabled in the sandbox, and which sports events will be live around Nov 19-21?
- [ ] Are the public endpoints callable from a browser (CORS) or only from a server?

**Strava (email developers@strava.com; no office hours)**

- [ ] May a small friend group see each other's app-computed points when each user gives explicit consent (API Policy sections 2.3, 5.13, 6.1)?
- [ ] Does a points-based friend challenge count as "competitive to Strava" (section 5.2)?
- [ ] Is an app where users put money into a shared pool allowed (section 5.8)?
- [ ] Do computed scores count as Strava Data for the 7-day cache rule?

**Privy**

- [ ] Is native gas sponsorship free on Solana devnet, and does the free plan allow it?
- [ ] Recommended way to verify access tokens from a Python server?

## Progress log

| Date | What was done | What is next |
|---|---|---|
| 2026-11-14 | Planning only: researched platforms, wrote `CLAUDE.md`, `DEVELOPMENT_PLAN.md`, `docs/ARCHITECTURE.md`, and the PDF. No application code. Found: `docs/HACKATHON_GUIDE.md` is empty; no WSL distribution, Rust, Solana CLI, or Anchor installed on this machine. | Team reviews the plan. Then Stage 0. |
| 2026-11-14 | `docs/HACKATHON_GUIDE.md` filled in. Reconciled the plan: added Devpost submission items, in-person attendance rule, finalist pitch prep; rewrote the Grok stage now that Grok Bot is defined; removed open questions the guide answers; noted Gemini is the largest bounty and market data alone qualifies. No change to stages 1-6 or the cut line. | Team reviews the plan. Then the rest of Stage 0. |
| 2026-11-14 | Team named the app **Loser Buys** (program name `loser_buys`). Skills confirmed. No Strava subscription yet, so the mock/manual source is the default. | Team approves the plan. Then the rest of Stage 0. |
| 2026-11-14 | Name is **Loser Buys** for now (was briefly Easy Money; may change again). WSL install failed: CPU virtualization is disabled in the BIOS (HP, i7-8700). Fix steps are in `COME_BACK_AND_DELETE.md`. | Enable virtualization in BIOS, install Ubuntu, then the toolchain. |
| 2026-11-14 | WSL2 works (Ubuntu 26.04). Toolchain installed and version-checked in WSL: Rust 1.100.0, Solana CLI 4.3.2, Anchor 1.2.2, Node 26.13.1, Yarn 1.22.22. Created deploy, oracle, and treasury wallets (devnet, keypairs outside the repo). Added `.gitignore`, `.env.example`, folder skeleton. Decided to stay on WSL; Solana Playground is the fallback only. `solana airdrop` is rate-limited, wallets hold 0 SOL. Deleted `COME_BACK_AND_DELETE.md`. | Team funds the deploy and treasury wallets from the web faucets. Commit and push, clone the repo into the WSL home folder, then Stage 1. |
| 2026-11-14 | Wallets funded from the web faucets and confirmed onchain: deploy 5 SOL + 20 USDC, treasury 5 SOL + 20 USDC, oracle 0 (to be topped up from the treasury). First commit of the plan, docs, and skeleton pushed to GitHub. | Clone the repo into the WSL home folder, then Stage 1. Keep collecting treasury USDC. |
| 2026-11-14 | **Stage 1 done.** Program `loser_buys` written (5 instructions, 5 events), 11 local tests pass, deployed to devnet as `FeCj36zk7YNkdfKZXjfjSmftqpJv9C68uBNSvtRt3ssC`. Devnet smoke test passed with real devnet USDC. Python (`solders` + `solana-py`) sent `end_early` and `settle` on devnet, so the server needs no Node helper. Found along the way: Anchor 1.x defaults to the `surfpool` validator (not installed; use `--validator legacy`); its mocha test setup breaks on Node 26, so WSL now uses Node 22; the public devnet RPC rate-limits (HTTP 429), so `api/chain.py` retries. Builds run through `scripts/wsl_anchor.sh`. Untested: the 72-hour refund timeout. | Stage 2 (Privy login and invisible wallet flow). Needs the Privy account. |
| 2026-11-14 | **Stage 2 done except the phone test.** `web/` (React + Vite + Privy) and `api/` (FastAPI) exist. In the browser: email login, wallet created invisibly, gas drip, "Add test funds", and "Join for 1 USDC" with no wallet popup; two accounts joined a devnet challenge and are in its onchain player list. API has 13 passing tests. Added `create-challenge` to `scripts/wsl_anchor.sh` to make a demo challenge. Found: Privy's React SDK v3 takes transactions as serialized bytes, so the app builds with Anchor + web3.js v1, has Privy sign, and sends through our own RPC connection. Treasury is down to about 7 USDC. | Stage 3 (QuickNode Stream). Needs the QuickNode account. Keep collecting treasury USDC. Phone test once there is an HTTPS address. |
| 2026-11-14 | Stage 3 code written, no boxes ticked: `streams/filter.js`, signed webhook `POST /webhooks/quicknode`, event decoding, `chain_events` table, `GET /challenges/{address}/events`. 21 API tests pass. QuickNode account created. The Stream itself is not created yet, so nothing has been delivered for real. Stage 2 and this code committed and pushed (`d887135`). | Manual Stream setup (steps in `start from here and delete later.md`): cloudflared tunnel, create the Stream, token into `.env`, run the smoke test. Then verify, record the Stream ID, tick Stage 3. |
| 2026-11-14 | **Stage 3 working.** QuickNode Stream (Solana Devnet, Programs + Logs, filter from `streams/filter.js`) delivers to `POST /webhooks/quicknode` through a cloudflared tunnel. Running the smoke test put 5 events for challenge `HkeqS9dqAGiEQjiNqnTNkbKN1QhwtSPAbSncWiYKe718` into `chain_events` within seconds, each passing the signature check. Found: the dashboard's "Check Connection" is unsigned, so unsigned requests get an OK but store nothing. | Stream ID recorded (`daf4568b-a005-4eea-aa1a-732df56eb9ff`), so **Stage 3 is done**. Next: Stage 4. Update the Stream's destination URL whenever the tunnel restarts. |
| 2026-11-14 | **Stage 4 done except live Strava.** Added the `challenges`, `participants`, `score_entries`, and `fitness_connections` tables; the `FitnessProvider` interface with mock and manual sources; the Daily Mover scoring engine with anti-cheat rules; six endpoints for recording challenges and joins, adding activities, the leaderboard, and disconnecting; `docs/STRAVA_FLOW.md`. 51 API tests pass. Plan changes: a seventh table (`logged_activities`) because mock and manual activities need somewhere to live; consent is stored per challenge; a scoring day is a 24-hour block from the challenge start. Limit to know for the demo: activities must start inside the challenge dates and may not overlap, so in a challenge created minutes before a demo each player can add about one workout. Deleted `start from here and delete later.md`. | Stage 5 (product screens), which is also the first real run of the new endpoints against devnet. Still open from Stage 0: Devpost team list, Vercel/Render/Neon accounts, treasury USDC (about 7 left). The demo challenge stops taking joins Mon Nov 16 around 4:30 PM CST. |
| 2026-11-14 | **Stage 5 mostly done, Stage 6 verified on devnet.** Screens: home, create challenge, challenge scoreboard with table, feed, and workouts, styled like a fantasy league app. Server: one "challenge screen" call, feed sentences from stored events, names, settlement, refunds, admin "End week now", `/internal/tick`, score-sheet hash. From the browser on devnet: created 3 challenges, joined, logged a workout (2 points), refunded one, settled one to a single winner, settled one as a tie. 73 API tests pass. Fixes found by testing: a logged workout now counts from the moment it is logged (it used to be dated before kick-off and never counted); server error messages now reach the screen. New helper: `scripts/wsl_anchor.sh join <challenge>` makes a test player join. | Needs a person: resume the QuickNode Stream and confirm one join shows "Deposit confirmed" and a feed line from a live delivery; test on a phone and with a second real account; create Vercel, Render, and Neon accounts for Stage 9. Then README, deploy, scheduler for `/internal/tick`, video. Stage 7 (Gemini) and Stage 8 (Grok) are still to be decided at the cut line. |
| 2026-11-14 | **README written. Stage 7 (Gemini pick'em) built except a real-game resolution.** `api/pickem.py` reads live games and odds from Gemini's public Prediction Markets API; players make one free pick before kick-off; a correct pick breaks a tie at settlement and is recorded in the score sheet. Real games showed in the browser and a real pick was saved. 87 API tests pass. Built before the cut line because Stages 1-6 were already verified and the API needed no account. | Same list that needs a person as above. For Gemini: run one tied challenge whose picked game finishes before it ends, to see a real resolution. Stage 8 (Grok) needs X Premium, so it waits for a person. |
| 2026-11-15 | Neon database created and linked with Neon's command-line tool (`neon`, installed globally). The API's database code works against it unchanged: 8 tables created, a row written to five of them and read back, times in UTC. Connection strings are in `.env.local` (ignored by git); the repo's `.env` was left alone so local runs stay on SQLite. Neon's agent plugin and `neon.ts` file were not installed, since the app only needs the address. | Render: New > Blueprint, with `DATABASE_URL` set to the pooled address from `.env.local`. Then Vercel, the Stream's destination URL, and the two GitHub secrets. |
| 2026-11-15 | Added `docs/SETUP.md`: step-by-step teammate setup for macOS and Windows (tools, the shared team `.env` with keys inline, running the API and web app, troubleshooting, optional program toolchain). README "Run it locally" now shows macOS and Windows commands and links to it. Not ticked: the macOS steps and a fresh-WSL install have not been tried on a clean computer. | A teammate follows `docs/SETUP.md` on a Mac and reports what breaks (counts toward the Stage 9 clean-machine test). Yusuf prepares the team `.env`. |
| 2026-11-16 | **Play modes built (Stage 5b), not yet clicked through on devnet.** League, Public and Private modes as off-chain metadata: new `mode` and `organizer_name` columns, a ninth table `invites`, access rules enforced by the server, public event list, invite-code redeem, mode screens and badges. Program, deposit, scoring and settlement unchanged. 103 API tests pass (16 new); two existing test fixtures now create a public event, because an event with no mode is private and their second player has no invite. Events first recorded on join (made by the scripts) are public. The home screen no longer shows the demo-challenge shortcut or the flat "Your challenges" list; events live in their mode screens. | Click through all three modes on devnet with two accounts. Decide whether the existing demo challenge should be set to public in the deployed database. |
| 2026-11-17 | **Stage 7b built: Gemini prediction rounds and League stats scoring.** Research first (live API, Nov 17): `sport=` and `sports_market_type=moneyline` filters work; `subcategory`, `sort` and `template` are silently ignored; the unfiltered list caps at 1,000 events; NBA and NHL games are listed only 0-2 days ahead, so a round's market is chosen when the round opens; soccer is mostly weekends plus Champions League midweek; games settle 2-3 hours after kick-off; `expiryDate` is 24-48 hours after kick-off and is not the game's end. Built `api/pickrounds.py`, `api/leaguestats.py`, three new tables (12 in all), 8 endpoint changes, new create-screen options and challenge-screen cards, with a link from each round to its Gemini market page. 127 API tests pass (24 new); `npm run build` passes. Program unchanged. Found and not fixed: the older tiebreaker's `list_games` reads only the first 100 of about 950 Sports events. | Click through both features on devnet (two accounts). Ask Gemini at office hours whether rounds are the entry they want. |
| 2026-11-17 | **Join pop-up and stat-sheet tidy-up.** Tapping Join now opens a three-screen "how it works" pop-up (Next, Next, "I'm ready · Join") on every event: how points are earned (the organizer's goal/assist values for League stats, Daily Mover rules otherwise, plus a picks line when rounds are on), climbing the table, and first place taking the pool after the event's length. Pictures are drawn in code (SVG) and animated; motion stops for people who ask their device for less. "I'm ready" replaces the consent checkbox; the agreement is stated above the button. The Workouts tab is hidden on League stats events, and the organizer's stat-sheet card is collapsed behind "Manage" with three buttons (Template, Upload CSV, From PDF). Checked in Chrome on a temporary preview page (since removed); type check passes. | See the pop-up in the real join flow on devnet with a second account. |
| 2026-11-17 | **Tiebreaker removed.** Decision: Gemini is used only through prediction rounds, the same way in League, Public and Private events, and a tie at the top always splits the pool. Deleted `api/pickem.py`, its two endpoints, the tiebreak step in settlement, its card on the challenge screen, and its 14 tests; the Gemini fetch moved into `api/pickrounds.py`. 113 API tests pass; type check passes. An older database keeps an unused `picks` table. | Same as above. |
| 2026-11-17 | **UI tidy-up.** Pick card: one footer line, a "Your pick" tag on the chosen side, a countdown to lock, the Gemini link in the header, and past rounds as a row of marks (tap one for its game and result). Table: no empty Form column on League stats events; tabs fill the bar. The organizer's stat-sheet card moved below the table. Create screen: four short cards (name, buy-in and timing, scoring, picks), a Fitness / League stats switch, and one line of small print. Picks stay available on 15-minute events because demos use them. Checked in Chrome on a temporary preview page (removed); type check passes. | Click through on devnet. |
| 2026-11-17 | **Wording and Withdraw note.** All on-screen mentions of "test money / test funds / test tokens" now say "devnet USDC" (banner: "Demo · Devnet USDC only, no real money"). New **Withdraw** button in the header opens a small pop-up (`web/src/WithdrawNote.tsx`, picture in `web/src/assets/withdraw.png`): it is a demo, devnet USDC has no real value and stays in the app. Closes with Got it, the ✕, Esc, or a tap outside. Checked in Chrome; type check and 113 API tests pass. | - |
| 2026-11-17 | **Rebrand to Rival and full UI redesign (branch `rival-redesign`, not merged).** Visual and layout only: `web/src/chain.ts`, `web/src/api.ts`, the API and the program are untouched, and technical names (`loser_buys`, repo, URLs) stay. New design system in `web/src/styles.css` (dark only, periwinkle `#929BFF` as the single accent, Geist for the interface and Instrument Serif italic for headlines). New public homepage (`Landing.tsx`) with an animated sample leaderboard, a one-time opening animation, and scroll reveals. Signed-in app now has a sidebar on desktop and a top bar plus bottom navigation on phones (`Shell.tsx`), a dashboard listing your competitions with your rank (`Dashboard.tsx`), a "How it works" page (`?help`), and a create form with a live summary. Emoji icons replaced by `lucide-react` (new pinned dependency: rerun `npm install` in `web/`). Football wording dropped ("Table" is now "Leaderboard", "buy-in" is "entry fee" on screen). Verified: `tsc` and `npm run build` pass; every screen checked by screenshot at 1440px and 390px, with sample server data for the signed-in screens and the real demo challenge read from devnet. **Not verified:** a real sign-in, create, join, pick, workout and payout through the new screens. |
| 2026-11-18 | **Competition formats (issue #3, branch `competition-formats`, not merged).** Podium, Goal and Team vs team added next to Winner takes all. New program instruction `settle_split` for unequal payouts (13 program tests pass, not yet deployed to devnet). API format rules, team join, standings, projected shares; 142 API tests pass (one older test, `test_same_day_beats_later_and_big_leagues_rank_higher`, fails depending on the time of day, also on `main`). Web format picker, team pick on join, format-aware leaderboard; build passes. Personal improvement left out (no fitness history in the mock source). | Upgrade the program on devnet, then click through each format with two accounts. |
| 2026-11-18 | **Program upgraded on devnet with `settle_split`** (same program ID). Real 70/30 payout on a test challenge paid exactly 1.4 / 0.6 USDC; the API decodes the new event. Added `python chain.py settle-split`. | Click through each format in the app with two accounts. |
| 2026-11-18 | Join pop-up, first screen (fitness events): the progress ring is replaced by an animated runner drawn in SVG (swinging limbs, bounce, speed lines, moving track, "+1" pop). Still pose when the device asks for reduced motion. League-stats events keep the ring. Checked with frozen frames in headless Edge; type-check passes. | Click through each format in the app. |
| 2026-11-18 | **Proof of Effort (issue #1, branch `proof-of-effort`, not merged).** New verifier key `5hapcEHu...cway` signs every result (`api/attest.py`); the score sheet names its rules version and fingerprint; workouts show Passed checks / Counts · unverified / Not counted. Players check a result in the browser against the onchain hash. 163 API tests pass (21 new); web build passes; a real devnet settlement verified with `attest.py verify`, and an edited copy was rejected. No Strava button (brand rules); "Coming soon" pop-up instead. Issue #2 (TEE) deferred with reasons. | Add `VERIFIER_KEYPAIR` on Render, then merge. Click through "Check result" in the browser. Then deploy, README, video. |
| 2026-11-18 | **Brand v2: blue and citrus palette, cinematic public site, new dashboard (branch `rival-brand-v2`, not merged).** Visual and layout only: `chain.ts`, `api.ts`, the API and the program are untouched. Palette moved from periwinkle to near-black with athletic blue `#78AFFF` and a restrained citrus green `#BCEB9C` (progress and activity only). The public site is now four real pages with their own addresses and working back button (`Site.tsx`: home, `?page=how`, `?page=way`, `?page=play`), a desktop nav and a full-screen mobile menu. The home hero is a 13-second black-and-white running film (three Mixkit clips cut together, a 6 MB desktop file and a 1 MB phone file, poster image, still image for reduced motion). Photography replaces icon grids; all media is in `web/src/assets/media/` with sources and licence in `CREDITS.md` (Mixkit Stock Video Free License only; restricted-licence clips were rejected). Signed-in dashboard rebuilt: welcome with actions, competition cards showing rank, points and a progress line, a photo first-run panel, balance moved to the side. Leaderboard uses race-style rank numbers. Verified: `tsc` and `npm run build` pass; every public page and the dashboard, challenge page and empty state checked by screenshot at 1440px and 390px with no sideways scroll; the film plays on both sizes and the phone gets the small file; page links, deep links and the back button work. **Not verified:** real sign-in, create, join, pick, workout and payout through the new screens; Safari and Firefox; reduced-motion mode. |
| 2026-11-18 | **Logo mark and sharper, wider-ranging media (branch `rival-brand-v2`).** The team's two-peak logo (black background removed, `web/src/assets/logo-mark.png`) now sits beside the "rival." wordmark everywhere, and is the browser-tab icon. The hero film was re-cut from 4K masters as six shots across several sports (hand wraps, shoes on pavement, runner silhouette, barbell, basketball dribble, two runners) and is served in four sizes chosen by screen width: 480p 1.6 MB, 720p 4 MB, 1080p 8.8 MB, 4K 18 MB (only for screens wider than 2400px). Photos replaced with non-face, more cinematic frames and exported at 1920px plus 3840px where the source was 4K (`srcset`); list in `web/src/media.ts`, sources in `CREDITS.md`. The media folder is now about 42 MB. Restricted-licence clips again rejected. Verified: `tsc` and build pass; phone, laptop and 2560px screens each loaded the intended film file; home and Rival-way pages checked by screenshot. **Not verified:** the logo inside the signed-in app (same component, not viewed), the How and Ways pages after the photo swap, real sign-in flows. |
| 2026-11-18 | **Logo-led opening animation.** The intro (once per browser tab, skipped for reduced motion, about 2.4 seconds) now opens close in on a trace of light running up the path between the logo's two peaks, eases back as the peaks resolve around it, then opens the wordmark (`IntroLogo` in `web/src/ui.tsx`; the path was traced from the artwork, and the mark is split into `logo-peak-blue.png` and `logo-peak-green.png`). Mark and wordmark sit closer together. Verified by frame captures in Chrome; build passes. |
| 2026-11-18 | **Competition layer (branch `rival-brand-v2`).** A third typeface, Barlow Condensed in capitals, now sets labels, status pills, ranks, points and countdowns (rule: small labels and numerals only, never headlines; the italic serif stays the expressive face). More citrus green: live indicators, progress, lane numbers. Most photographs outside the hero were replaced with drawn graphics (`web/src/graphics.tsx`): a rules strip under the hero, a weekly "lane board", a head-to-head scoreline, a daily-cap illustration, and a ticket, open-events list and stat sheet for the three ways to play. All use the real scoring rules and are labelled as sample data. Leaderboard rows now show the gap to first place. Seven unused stills removed. Wordmark is lowercase italic serif. Verified: `tsc` and build pass; home and Ways-to-play pages checked by screenshot at 1440px, home at 390px with no sideways scroll. **Not verified:** signed-in screens with the new typeface (not viewed), the How and Rival-way pages, real sign-in flows. |
| 2026-11-18 | **Immersive public site (branch `rival-brand-v2`).** No new libraries. The public site now spans the full browser width (fluid gutter, type and grids; checked to 3440px). The home page is a sequence of distinct dark environments: film hero; a blue-tinted section with a **playable scoring demo** (log a sample workout, the sample leaderboard reorders by the real rules: 20 min or 5 km a point, 3 a day); one thin off-white ticker band; a **scroll-driven week** (a pinned section where scrolling advances the lane board day by day and the lead changes hands); the four steps on charcoal; the head-to-head scoreline; a green-tinted **ways-to-play selector**; the photo finale. Header tucks away on scroll down and returns on scroll up, with a scroll-progress line; page changes cross-fade where the browser supports view transitions. Signed-in app content area widened (to 1560px) with fluid side columns. All interactive pieces are in `web/src/interactive.tsx`, run on sample data in the browser, and are labelled as such. Verified in Chrome: `tsc` and build pass; demo clicked through (points, cap message, reorder); no sideways scroll at 390, 1920 and 3440px; inner pages at 1920px. **Not verified:** signed-in screens after the widening and type change, Safari and Firefox, reduced-motion mode, real sign-in flows. |
| 2026-11-18 | **Selective colour in the film and photos (branch `rival-brand-v2`).** The footage stays black and white, but one object per shot keeps a brand colour: blue hand wraps, green running shoes, a blue basketball in the hero film; blue wraps and green tennis shoes in the two photos. Baked into the files with small Swift tools now kept in `scripts/media/` (Core Image colour keys plus Apple Vision's per-frame subject mask for the shoes); the page's CSS no longer applies grayscale. Also: large type capped so it stops growing past about 1740px, and the footer logo reduced. All remaining photos come from 4K masters. Verified: twelve frames across the film and both photos viewed; hero and two pages viewed on the site; build passes. **Not verified:** the film watched at full speed (edges of the colour may flicker on fast motion), signed-in screens, other browsers. |

