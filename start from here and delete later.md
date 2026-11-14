# Start from here (delete this file once Stage 3 is done)

Written Sat Nov 14, 2026, end of session. This is a handoff note. `DEVELOPMENT_PLAN.md` is still the source of truth for progress.

## Where things stand

| Stage | State |
|---|---|
| 0 Setup | Mostly done. QuickNode account now exists (school email). Still open: Devpost team list, office hours times, Vercel/Render/Neon accounts, Solana Playground fallback check |
| 1 Anchor program | Done. Deployed on devnet |
| 2 Invisible wallet flow | Done and tested in the browser, except the phone test (needs HTTPS) and optional Privy gas sponsorship |
| 3 QuickNode Stream | Code written and tested locally. **Manual setup not done yet.** No boxes ticked |

**Nothing from Stage 2 or Stage 3 is committed.** All of it is in the working tree. Commit before doing anything risky.

## What was built today

**Stage 2 (verified)**
- `web/`: React + Vite + Privy app. Email login, wallet created invisibly, balance in dollars, "Add test funds", "Join for 1 USDC" with no wallet popup.
- `api/`: FastAPI server.
  - `auth.py` checks the Privy login token.
  - `treasury.py` sends fee money (gas drip) and test USDC.
  - `db.py` has the `users` table.
  - `main.py` has `POST /me/setup` and `POST /me/fund`.
- `onchain/scripts/create_challenge.js` plus a `create-challenge` command in `scripts/wsl_anchor.sh`.
- Two browser accounts joined the demo challenge `GNLFdSczFf1GgYXwF1nPLwzTL4Jz5QJrknAMS67vDDc` on devnet. Joining closes Mon Nov 16 around 4:30 PM CST; make a new one after that.

**Stage 3 (code only, not yet proven with a real Stream)**
- `streams/filter.js`: the Stream filter. Check it with `node streams/test_filter.js`.
- `api/events.py`: checks QuickNode's signature, decodes the program's events from log lines, stores them without duplicates.
- `api/db.py`: new `chain_events` table.
- `api/main.py`: `POST /webhooks/quicknode` and `GET /challenges/{address}/events`.
- 21 API tests pass. The decoder was also run against today's real devnet transactions and read `ChallengeCreated` and two `PlayerJoined` events correctly.

## Your next steps (Stage 3 manual setup)

**1. Tunnel, so QuickNode can reach your laptop**
1. PowerShell: `winget install --id Cloudflare.cloudflared`
2. New PowerShell window: `cloudflared tunnel --url http://localhost:8000`
3. Copy the `https://<random-words>.trycloudflare.com` address. Leave the window open. The address changes every restart.

**2. Create the Stream** (dashboard.quicknode.com, Streams, "+ New Stream")
1. Name `loser-buys-devnet`, network **Solana Devnet**, start at the latest block.
2. Dataset **Programs + Logs**.
3. "Customize your payload": clear the editor and paste all of `streams/filter.js`.
4. **Run test**. `null` is the normal result. An error is not.
5. Destination **Webhook**, URL `https://<your-tunnel-address>/webhooks/quicknode`, compression None, other settings default.
6. Copy the **Security token**. Do not create the Stream yet.

**3. Token and API**
1. In `.env` at the repo root set `QUICKNODE_STREAM_SECURITY_TOKEN=<the token>`.
2. In `api/`: `.venv\Scripts\python.exe -m uvicorn main:app --reload`
3. In QuickNode: **Check Connection**, then **Create a Stream**.

**4. Prove it**
1. Repo root: `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh smoke`
2. The API window should log "Stored N onchain event(s) from the Stream" within seconds.
3. Tell Claude the Stream ID so it can verify the rows, record the ID in `CLAUDE.md`, and tick the Stage 3 boxes.

## Known risks and open points

- **"Check Connection" may fail with 401.** The webhook rejects unsigned requests. If QuickNode will not let you continue, that one case needs loosening.
- **Payload shape is unconfirmed.** The filter and the webhook were written from QuickNode's docs and handle a few possible shapes, but no real delivery has been seen yet.
- **Dashboard labels may differ** from the names above.
- **The Stream pauses after 3 failed deliveries.** Pause it yourself when the API or tunnel is off; resume it in the dashboard.
- **No replay of missed events** on Solana.
- **Did QuickNode ask for a card?** Record the answer in the plan (Stage 0 asks for it).
- **Treasury USDC is low** (about 7 USDC). Top up at https://faucet.circle.com before more people test, or set `TEST_FUNDS_USDC` lower in `.env`.
- **Phone test** still needs an HTTPS address. The cloudflared tunnel could also serve the web app for this.
- **Servers:** the API was stopped at the end of the session. The web dev server may still be running on port 5173.

## How to run things

| Task | Command | Where |
|---|---|---|
| API | `.venv\Scripts\python.exe -m uvicorn main:app --reload` | `api/` |
| API tests | `.venv\Scripts\python.exe -m pytest` | `api/` |
| Web | `npm run dev`, then http://localhost:5173 | `web/` |
| New demo challenge | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh create-challenge`, then put the address in `VITE_DEMO_CHALLENGE` in `.env` | repo root |
| Smoke test | `wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh smoke` | repo root |

## What to tell Claude next session

"Read `start from here and delete later.md`, then continue Stage 3." If the Stream is already created, include the Stream ID and whether the smoke test produced the "Stored N onchain event(s)" log line.

## Still to update once Stage 3 is verified

- Tick the Stage 3 boxes and add a progress log row in `DEVELOPMENT_PLAN.md`, then rebuild the PDF with `C:\Python313\python.exe scripts/build_plan_pdf.py` (plain `python` picks the API venv, which lacks `reportlab`).
- Fill in the Stream ID in `CLAUDE.md`.
- Delete this file.
