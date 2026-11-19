# Proof of Sweat

How Rival turns a workout recorded by an Oura Ring into a checked score, and how that score reaches a
Solana-settled prize pool. Written for someone who knows some computer science and physiology but is
not a blockchain engineer.

Status: built and covered by automated tests with synthetic data. The Oura connection and data
reads have worked with one real account. The full path (real workout, scored in a challenge, settled
on devnet) has **not** been run live yet; see "Live testing" at the end.

## A. The problem

Rival is a fitness competition with a prize pool. Before Proof of Sweat, a player typed a workout
into the app and the server believed it. The demo data source even labelled those entries as
recorded by a watch. Anyone could win by inventing workouts.

Proof of Sweat removes that path. In a Proof of Sweat challenge the only thing that can earn fitness
points is a workout Rival itself fetched from the player's own authorized Oura account.

## B. How it works

```
Oura API -> import -> normalize -> rules engine -> stored checked workout
        -> daily points -> leaderboard -> score sheet -> signed attestation
        -> Solana: score-sheet hash stored + escrow paid out
```

1. **Connect.** The player links Oura with OAuth 2.0 (PKCE). Rival asks for two permissions only:
   workouts and heart rate. Tokens are encrypted on the server and never reach the browser.
2. **Sync.** "Sync workouts" (and one automatic sync when a challenge ends) reads the player's recent
   workouts from Oura's API v2. Each becomes one row in `imported_activities`. A database unique
   constraint on a one-way reference to Oura's workout ID means the same workout can never be imported
   twice, by the same account or a different one.
3. **Check.** A deterministic rules engine (`api/sweat.py`, version `proof-of-sweat-v1`) runs the
   mandatory checks below. Heart-rate samples for the workout's time window are read once, reduced to
   "how many minutes had a usable reading", and discarded.
4. **Score.** Eligible minutes inside the challenge become points. Stored per day in the existing
   `score_entries` table, so the existing leaderboard and payout formats work unchanged.
5. **Settle.** After the challenge ends plus a sync grace period, the server fixes the scores,
   builds the score sheet, signs it, and calls the existing Solana program, which stores the sheet's
   SHA-256 and pays the pool from escrow.
6. **Inspect.** Each player can open a receipt per workout, and after settlement the browser checks
   the signature, the onchain hash, the payout transaction, and that the player's own receipts are
   committed in the result.

### The checks

| # | Check | Fails when |
|---|---|---|
| 1 | Authorized provider | the record did not come through the player's Oura connection |
| 2 | Eligible provenance | Oura's `source` is `manual`, missing or unknown. Accepted: `confirmed`, `autodetected`, `workout_heart_rate`, `live_oura_heart_rate`; `live_third_party_heart_rate` is accepted but never rated above limited evidence |
| 3 | Recognized activity | Oura's activity name is not in the explicit mapping (`ACTIVITY_MAP` in `api/fitness/oura_sync.py`) to run, walk, hike, ride, swim or workout |
| 4 | Valid timestamps | a time is missing or has no UTC offset, the end is not after the start, it is longer than 24 hours, or it ends in the future |
| 5 | Minimum duration | under 10 minutes |
| 6 | Challenge window | fewer than 10 of its minutes fall inside the challenge (only those minutes count) |
| 7, 8 | Duplicate and overlap | all of its time is already covered by another of the player's workouts. Partly overlapping workouts count as the union of their time: no minute twice |
| 9 | Plausibility | distance and time give a speed over the cap (run 25, walk 10, hike 10, ride 80, swim 8 km/h). A missing distance is never a reason to reject |
| 10 | Physiological evidence | never fails a workout; see D |

A workout ends in one of four states: **verified, strong evidence**; **verified, limited
evidence**; **rejected** (with the reason); or **pending** (not fully checked yet; earns nothing
until it is).

## C. Why Oura

- The record is made by a device on the body and delivered by Oura's servers to ours over an
  authorized connection. The player never handles it, so it cannot be typed in or edited on the way.
- Oura labels how each workout came to exist. Rival rejects the hand-entered ones.
- Limits: a consumer ring is not a lab instrument. Oura's "confirmed" means the wearer confirmed a
  detected activity, which is not biological proof. A ring can be worn by someone else. Rival depends
  on Oura being available and on the ring having synced.

## D. How physiology is used

Heart rate is supporting evidence only.

- For each workout, the samples inside its time window are grouped into one-minute bins. Coverage is
  bins with a usable reading divided by all bins. Three hundred readings in one minute are one minute
  of evidence, not three hundred proofs.
- **Strong** needs at least 50% coverage, at least 5 covered minutes, and at least one sample Oura
  tagged as recorded during exercise (not background "awake" or "rest" readings).
- Everything else that passes the mandatory checks is **limited**: no samples, low coverage,
  background-only samples, or heart rate that could not be read.
- There is **no minimum heart rate**. A workout averaging 105 bpm does not fail and one at 175 bpm
  does not pass because of it. Heart rate depends on fitness, the type of exercise, medication, how
  the ring fits and signal quality, so a threshold would punish some bodies and sports. Readings
  outside 25 to 250 bpm are treated as sensor errors and ignored, with a quality warning.
- Missing heart rate is common. In a real account's recent history, coverage ranged from none to
  complete even among workouts Oura marked as confirmed. So limited evidence still earns full points.

These thresholds are engineering classifications, not validated fraud detectors.

## E. How points are earned

**One point for every complete 10 minutes of verified exercise, up to 6 points per challenge day.**

`points(day) = min(6, floor(eligible minutes that day / 10))`

- A challenge day is a 24-hour block counted from the challenge start. A workout across a boundary
  feeds both days.
- Minutes from separate workouts in a day are added before dividing: 15 + 25 minutes is 4 points.
- Distance, calories, heart rate and Oura's intensity score never add points. This keeps cycling
  from beating walking on distance, and avoids favouring larger bodies or higher heart rates.
- The cap means nobody wins a week in one afternoon.

Every challenge records its rule set when it is created and keeps it. Challenges made before Proof
of Sweat keep the old rules; settled results are never recalculated.

## F. What the blockchain contributes

Enforced by the Solana program (`loser_buys`, unchanged, devnet):

- Entry fees sit in an escrow vault only the program can move.
- Only listed players can be paid, only after the end time, only once, and only on the oracle's
  instruction; or everyone is refunded if too few joined or the oracle goes quiet for 72 hours.
- The 32-byte SHA-256 of the final score sheet is stored in the challenge account at payout.

Added offchain by Rival and checkable by anyone with the sheet:

- The score sheet names the rule set by version and hash, and lists per player the verified minutes,
  the points and one **commitment** per workout receipt.
- A commitment is `SHA-256(canonical JSON of the receipt)`. The receipt carries a random 128-bit
  salt, so the commitment reveals nothing and cannot be guessed. It is bound to the challenge, the
  player's wallet, the program and the rule set by fields inside it, under the domain
  `rival.proof-of-sweat.receipt`.
- Rival's verifier key signs (Ed25519) a message naming the sheet hash, the payout, and a hash over
  all receipt commitments.
- The browser recomputes the sheet hash, checks the signature against the published verifier key,
  compares the hash with the one read from Solana, asks Solana whether the payout transaction is
  confirmed, and re-hashes the player's own receipts to confirm they are in the sheet.

### What is and is not proven

| Claim | True? |
|---|---|
| The result was not changed after payout | Yes: onchain hash |
| The payout followed the program's conditions | Yes: enforced onchain |
| Rival's verifier approved exactly this result | Yes: signature |
| My workout's checks are part of the result | Yes: my receipt hashes to a committed value |
| Solana verified the workouts or heart rate | **No.** Workouts are checked offchain by Rival's server |
| The signature is checked onchain | **No.** It is checked in the browser and offline |
| A person really exercised | **No.** Recorded evidence was checked against rules |

The oracle key (which instructs the payout) and the verifier key (which signs) are both held by
Rival's server. The blockchain protects the integrity and settlement of the committed result; it
does not remove the need to trust that server's reading of the Oura records.

## G. Limitations

- Wearable measurements are imperfect and a record can be mislabelled or confirmed wrongly in Oura.
- Heart-rate records are often incomplete, so most assurance comes from provenance, not physiology.
- A workout that has not reached Oura's cloud by the end of the grace period (30 minutes by default)
  does not count. That is a compromise, not a guarantee that rings sync in time.
- If Oura is down at settlement, Rival retries a bounded number of times, then settles on what was
  already verified and marks that player's sync as unavailable in the score sheet. It never invents
  or removes points because of an outage.
- Oura does not tell us which Oura account a workout belongs to (we do not ask for that permission),
  so "one workout, one Rival account" is enforced by the workout's ID, first importer wins.
- Disconnecting Oura deletes the imported workouts, so points in unfinished challenges go with them.
- Privacy limits what can be shown: other players see points only, so they cannot audit each
  other's workouts, only that the result is intact.
- Legal: Oura's API agreement forbids keeping data longer than strictly necessary and requires
  deletion within 72 hours of a request. Retention here is 7 days after the last challenge that used
  a workout. Whether entry fees, even in test money, sit comfortably with the agreement's clause on
  charging users should be reviewed before any commercial use. Nothing here is legal advice.

## H. What could come next (not built)

- Commit the rule-set hash onchain when a challenge is created (needs a new program account).
- Verify the verifier's Ed25519 signature inside the settlement transaction.
- Hold the verifier key somewhere separate from the oracle, or run verification in a TEE.
- Device or provider attestations stronger than an API label.
- More fitness providers behind the same rules engine.

Any of the first two needs a program upgrade signed by the deploy wallet
(`AYvBmTfVifruj1XMCGu5pJShLWqo9wYEa1gJFd6pT9re`) from the main developer's Anchor toolchain, with new
accounts rather than a resized `Challenge` account. Not attempted.

---

## Where things live

| Piece | File |
|---|---|
| Rules engine (checks, evidence, scoring) | `api/sweat.py` |
| Import, sync, final sync, clean-up | `api/fitness/oura_sync.py` |
| Oura OAuth and tokens | `api/fitness/oura.py` |
| Per-challenge rule selection, recompute lock | `api/scores.py` |
| Grace period, receipts, score sheet | `api/settlement.py` |
| Signed attestation (schema 2 for Proof of Sweat) | `api/attest.py` |
| Routes: `POST /integrations/oura/sync`, `GET /me/sweat` | `api/main.py` |
| Workouts tab and receipts | `web/src/Sweat.tsx` |
| Oura card | `web/src/Oura.tsx` |
| Browser proof check | `web/src/proofCheck.ts`, `web/src/Proof.tsx` |
| Tests (synthetic data only) | `api/tests/test_sweat.py`, `api/tests/test_sweat_flow.py`, `api/tests/test_oura.py` |

Settings (all optional; defaults in `api/config.py`): `SYNC_GRACE_SECONDS` (1800),
`SYNC_GIVE_UP_SECONDS` (21600), `EVIDENCE_RETENTION_DAYS` (7). `NEW_CHALLENGE_RULES` must stay unset
in production; the tests set it to `daily_mover` to exercise the old rules.

Stored per imported workout: category, Oura's activity name and provenance label, UTC start and end,
distance, check results, heart-rate minute-bin counts. Not stored: Oura's workout ID (a one-way
reference instead), calories, intensity, labels, raw replies, heart-rate readings.

## Live testing

Needs: the branch merged and both Render services redeployed; the scheduler (GitHub Actions `tick`)
running, or a player keeping the challenge page open at the end.

Workouts only count inside a challenge's dates, and a challenge always starts after it is created.
So a past workout cannot be used for B, F or G: someone has to record a workout during the test
challenge. Do not backdate anything to make a demo pass.

- **A. Import.** Dashboard, Oura card, "Sync workouts". Then open any Proof of Sweat challenge you
  are in, "My workouts". Past workouts outside the challenge are imported but not listed there.
  Confirm the message reports workouts found and "Last synced" updates.
- **B. Scoring.** Create a short challenge (two accounts must join before it starts). During it,
  record a workout of 10+ minutes with the ring, let the ring sync to the Oura app, press "Sync
  workouts". Expect `floor(minutes / 10)` points, capped at 6, and a receipt with eight lines.
- **C. Duplicates.** Press "Sync workouts" again (after 30 seconds). Points must not change.
- **D. Manual rejection.** In that challenge there is no "Log a workout" form. For the server-side
  check, the automated test `test_hand_entered_workouts_never_score_and_cannot_be_backdated` covers
  a direct API request.
- **E. Limited evidence.** Open receipts until one shows "Limited evidence" on the physiological
  line. It must still show its normal points.
- **F. Leaderboard.** The Leaderboard tab shows your points and "Oura verified"; the second account
  shows "Oura not connected" and 0 unless it has its own ring.
- **G. Settlement.** Let the challenge end. The header reads "Awaiting final sync" for the grace
  period, then the challenge settles. Open "Check result" on the proof card: every line should pass,
  including "Your workout receipts are in this result" and "Payout confirmed on Solana", and the
  payout link opens Solana Explorer.

Dependency: G needs two joined players (the program refuses to settle with one), so a second
account with devnet USDC is required. It does not need an Oura ring; it scores 0.
