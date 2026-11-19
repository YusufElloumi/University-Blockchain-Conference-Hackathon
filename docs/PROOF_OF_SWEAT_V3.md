# Proof of Sweat v3

v3 is the rule set new challenges use (`proof_of_sweat_v3` / `proof-of-sweat-v3`, `api/sweat3.py`).
It is v2 with effort made consequential. Read `docs/PROOF_OF_SWEAT_V2.md` first: everything about
verification there still applies, unchanged.

## What stayed the same (imported from `api/sweat2.py`, object for object)

- The mandatory checks (v1's gates): authorized Oura source, recorded not hand-entered, supported
  activity, valid times, 10-minute minimum, inside the challenge, no duplicate time, believable speed.
  A failed check is always zero.
- The Evidence Index (source 35, timing and duplicates 25, movement 15, physiological 25). A
  rule-based score of how complete the recording is. Not a probability that a workout happened.
- Base points: about one per verified minute, the day's first hour in full, then x0.6, then x0.25,
  nothing past three hours.
- `final = base + base x (effort multiplier - 1) x reliability`, reliability 100% / 85% / 65% / 40%
  for an Evidence Index of 90+ / 75+ / 50+ / below.
- A missing signal is exactly x1.00 and nothing is renormalized. Exact decimals, one rounding per day.
- The personal heart-rate reference (median of 4-10 earlier workouts, frozen at the challenge start).
  No absolute bpm rule anywhere.

## What changed

| | v2 | v3 |
|---|---|---|
| Weights | 40% Oura intensity, 40% heart rate, 20% movement | **45% heart rate, 30% movement, 25% Oura intensity** |
| Effort multiplier | x0.85 to x1.25 (the signals could only reach about x1.13) | **x0.85 to x1.50** (the signals can reach the cap) |
| Oura intensity | easy 0.90, moderate 1.00, hard 1.12 | easy 0.85, moderate 1.00, hard 1.30 |
| Heart rate vs own reference | `1 + 1.25 x (ratio - 1)`, 0.90 to 1.15 | `1 + 3 x (ratio - 1)`, 0.80 to 1.65 |
| Movement (pace bands) | 0.95 to 1.10 | 0.90 to 1.45 (walk tops out at 1.30, hike at 1.20) |

Why this order of weights: heart rate against the player's own history is measured and personal, so
it leads; movement is measured but depends on terrain; Oura's intensity label is an estimate and
can be Oura's default, so it weighs least.

Worked example, 40-minute run (base 40.00), full evidence:

| | Oura | Heart | Pace | Multiplier | Points |
|---|---|---|---|---|---|
| Hard, 10% above usual, 11 km/h | 1.30 | 1.30 | 1.20 | 1.270 | **50.80** (v2: 44.32) |
| Easy, 8% below usual, 7 km/h | 0.85 | 0.80 | 0.90 | 0.850 (floor) | **34.00** |
| Hard strength session, no heart rate, no distance | 1.30 | 1.00 | 1.00 | 1.075 | **41.95** (Evidence Index 67, so 65% of +3.00) |

Safeguards: without any heart rate the multiplier cannot pass x1.21; weak evidence still shrinks the
bonus in either direction; the daily bands still stop one long day deciding a week.

## Versions side by side

A challenge is scored by the rules it locked. `scores.ENGINES` maps the stored template to its
module; `rules.check_current` refuses to settle under any other fingerprint. All three are pinned in
`api/tests/test_sweat3.py`:

- v1 `43143b25...2ab180` and v2 `b9bd8375...c661a6`: unchanged. `api/sweat.py` and the numbers in
  `api/sweat2.py` must stay as they are.
- v3 `3d0021d7...b261c9`. Once a v3 challenge exists on the deployed server, any further change to a
  number needs a v4.

`NEW_CHALLENGE_RULES` stays unset on Render (the default is now v3).

## The website's sample receipt uses the same arithmetic

The public calculator runs in the browser (`web/src/sweatMath.ts`). It holds no scoring numbers:
they come from `web/src/sweatRules.json`, generated from `sweat3.rules()`. `web/scripts/sweat-vectors.json`
holds 519 made-up workouts scored by the server's real functions (`api/sweat_sample.py`, which calls
`scores.score_rows` and `scores.sweat2_detail`).

- `pytest` fails if either file is out of date.
- `npm run check:sweat` (in `web/`, Node 22.18+) fails if the browser gives a different answer for any of them.
- After changing a rule: `python sweat_sample.py write` in `api/`, then both checks, and commit the two files.

## What Solana does and does not do

Unchanged from v2. Workouts are verified offchain by Rival's server. The program holds the entry
fees, the locked rules hash and the hash of the signed score sheet, and enforces the payout. It never
sees or verifies health data, and Oura's record is a device recording, not cryptographic proof.

## Not yet done

No v3 challenge has been run against a real Oura account or settled on devnet. The live test
checklist in the v2 document applies as written.
