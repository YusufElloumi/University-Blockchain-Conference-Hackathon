# Start from here (delete this file once Stage 4 is under way)

Written Sat Nov 14, 2026, evening. Handoff note only. `DEVELOPMENT_PLAN.md` is the source of truth for progress.

## Where things stand

| Stage | State |
|---|---|
| 0 Setup | Mostly done. Still open: Devpost team list, office hours times, Vercel/Render/Neon accounts, Solana Playground fallback check, more treasury USDC |
| 1 Anchor program | Done. Deployed on devnet |
| 2 Invisible wallet flow | Done, except the phone test (needs HTTPS) and optional Privy gas sponsorship |
| 3 QuickNode Stream | **Done.** Stream `daf4568b-a005-4eea-aa1a-732df56eb9ff` delivers our program's events to the API |
| 4 Backend, database, fitness layer, scoring | **Next. Not started** |

Everything is committed and pushed to `main`.

## What works today

- Sign in with email, get a wallet invisibly, add test funds, join a challenge with one button and no wallet popup.
- The QuickNode Stream watches Solana devnet, keeps only our program's transactions (`streams/filter.js`), and posts them to `POST /webhooks/quicknode`. The API checks the signature, decodes the events, and stores them in `chain_events`.
- Proof: the smoke test's 5 events (created, 2 joined, ended, settled) for challenge `HkeqS9dqAGiEQjiNqnTNkbKN1QhwtSPAbSncWiYKe718` arrived within seconds.
- 22 API tests pass.

## Starting a work session (the Stream needs all three)

1. API, in `api/`: `.venv\Scripts\python.exe -m uvicorn main:app --reload`
2. Tunnel, in a second window: `cloudflared tunnel --url http://localhost:8000`
3. **The tunnel address is new every time.** In the QuickNode dashboard, open the Stream, set the destination URL to `https://<new-address>/webhooks/quicknode`, and resume the Stream if it is paused.
4. Web (only when needed), in `web/`: `npm run dev`, then http://localhost:5173

## Leaving the desk, sleep, and shutdown

- The Stream only calls the API when someone uses our program. If nobody does, nothing is sent and nothing can fail.
- If the computer sleeps or shuts down, the API and tunnel stop. That is harmless unless a transaction for our program happens meanwhile. If one does, QuickNode retries 3 times, then pauses the Stream, and those events are lost (Solana Streams cannot replay).
- After any restart, do the three steps above. Lost events only affect the feed and status display; the money onchain is unaffected.
- This goes away in Stage 9, when the API is deployed with a permanent address.

## Next: Stage 4

Database tables (`challenges`, `participants`, `score_entries`, `fitness_connections`), the `FitnessProvider` interface with mock and manual providers, the "Daily Mover" scoring engine, and anti-cheat rules. None of it needs the Stream or the tunnel running. See Stage 4 in `DEVELOPMENT_PLAN.md`.

## Open points

- **Treasury USDC is low** (roughly 7 USDC). Top up at https://faucet.circle.com (20 USDC per 2 hours), or set `TEST_FUNDS_USDC` lower in `.env`.
- **Demo challenge** `GNLFdSczFf1GgYXwF1nPLwzTL4Jz5QJrknAMS67vDDc` stops accepting joins Mon Nov 16 around 4:30 PM CST. Make a new one with `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh create-challenge` (from the repo root) and put the address in `VITE_DEMO_CHALLENGE` in `.env`.
- **Phone test** still needs an HTTPS address for the web app.
- **Team:** confirm who is on the Devpost submission and that everyone can attend in person on Sat Nov 21.
- **Strava:** still nobody with a subscription, so the mock/manual provider is the plan.

## What to tell Claude next session

"Read `start from here and delete later.md`, then start Stage 4."
