# Proof of Sweat v2

Multi-signal evidence and effort-weighted scoring. This extends v1 ([PROOF_OF_SWEAT.md](PROOF_OF_SWEAT.md));
the import, the mandatory checks, the sync and the settlement flow are the same. Read that first.

Status: built and covered by automated tests with **synthetic data only**. Not yet run with a real
Oura account or settled on devnet. Screens were reviewed with clearly labelled sample data.

In one paragraph: *Oura supplies externally recorded workout evidence. Rival validates several
independent signals, calculates a transparent effort-weighted score, signs the result, and commits
the final competition outcome to Solana, which controls escrow settlement. The wearable evidence and
scoring are evaluated offchain; the blockchain makes the final committed settlement verifiable.*

## Two outputs and how they meet

**Final points = base activity points + potential effort bonus x evidence reliability**

| | Evidence Index (0-100) | Sweat Score |
|---|---|---|
| Answers | How complete and consistent is the recording? | How many competition points? |
| Built from | provenance, timing, movement data present, heart-rate coverage | eligible minutes, then effort |
| Is it a probability? | **No.** 88 does not mean "88% likely real" | n/a |
| Where they meet | Sets how much of the effort bonus counts | Base points never depend on the index |

| Evidence Index | Share of the effort bonus that counts |
|---|---:|
| 90-100 | 100% |
| 75-89 | 85% |
| 50-74 | 65% |
| below 50 | 40% |
| any required check failed | the workout scores zero |

- **Base activity points** are the workout's effective minutes (below). Missing heart rate never
  reduces them.
- **Potential effort bonus** is `base x (effort multiplier - 1)`: what Oura's intensity label,
  relative heart rate and pace suggest on top. It is negative for an easy session.
- **Reliability** scales that adjustment towards neutral, in both directions: with thin evidence the
  score leans less on an uncorroborated "hard" (or "easy"). It never turns a bonus into a penalty.
- **No double counting.** Heart rate answers two different questions from different inputs. Effort:
  how does this session's median compare with your own reference? Evidence: how many minutes have
  usable, exercise-tagged, well-spread, clean samples? More samples never raise the effort factor, a
  higher pulse never raises the Evidence Index, and one high reading does nothing at all (tests
  `test_more_samples_or_a_higher_pulse_do_not_buy_points_on_their_own`).
- **Bounds.** The multiplier is clamped to 0.85-1.25 (the real factors reach 0.910-1.128), so a bonus
  is at most 25% of base, and a day's base is capped at 111 by the minute bands.

A perfectly recorded easy walk is not vigorous because its evidence is good; a hard-labelled session
with no supporting heart rate keeps its full base and a reduced bonus.

Required checks come first and are unchanged from v1 (recorded by Oura and not hand-entered, mapped
activity, valid times, 10 minutes inside the challenge, no minute counted twice, believable speed).
A workout that fails one is rejected whatever its index. A workout with no heart rate at all is
still eligible.

## Evidence Index

| Part | Max | Rule |
|---|---:|---|
| Provenance | 35 | Oura's own recorded sources 35; third-party heart-rate source 20 |
| Timing and integrity | 25 | all required checks pass 25; 20 if part of it overlapped another workout |
| Movement | 15 | usable distance for a sport with pace 15; otherwise "not observed" 7 |
| Heart-rate signal | 25 | coverage of one-minute bins up to 15, any sample tagged as exercise 5, samples in 3+ quarters of the workout 3, no dropped samples 2. None at all: "not observed", 0 |

Label: **strong** needs exercise-tagged samples in at least half the minutes, 5+ covered minutes,
10+ usable samples, a native Oura source and an index of 80 or more. Otherwise **limited**, with the
reasons listed. 35 + 25 + 7 + 0 = 67 is a normal, eligible, limited-evidence workout.

## Sweat Score

**Effective minutes** per 24-hour challenge day, over the day's unique eligible minutes in time order:

| Minutes of the day | Weight |
|---|---:|
| 1-60 | 1.00 |
| 61-120 | 0.60 |
| 121-180 | 0.25 |
| beyond 180 | 0 |

So 30 -> 30, 60 -> 60, 90 -> 78, 120 -> 96, 180 or more -> 111. A game rule, not exercise advice.

**Effort multiplier** per workout:

`clamp(0.85, 1.25, 0.40 x provider + 0.40 x heart + 0.20 x movement)`

| Signal | Values | When unavailable |
|---|---|---|
| Provider: Oura's intensity label | easy 0.90, moderate 1.00, hard 1.12. Shown as "Oura's estimate": Oura may default to moderate | 1.00 |
| Heart: session relative to the player's own reference | `1 + 1.25 x (session median / reference median - 1)`, kept in 0.90-1.15. 8% above your usual level gives 1.10 | 1.00 |
| Movement: average speed in the sport's own bands | 0.95 to 1.10 (hike 0.97 to 1.05). Run 8/10/12 km/h, walk 4/5.5/6.5, ride 15/22/28, swim 1.5/2.5/3.2, hike 3/4.5 | 1.00 |

An unavailable signal is exactly 1.00 and the others are **not** scaled up to fill the gap, so a
sensor gap is never an advantage. With the real factor ranges the multiplier spans 0.910 to 1.128.

**The heart signal, carefully.** There is no pulse target, no age formula, no resting or maximum
heart rate. A session's median (taken per minute first, so dense sampling does not dominate) is
compared with the player's "personal observed workout reference": the median of the medians of
their 4 to 10 most recent qualifying workouts in the 30 days **before the challenge started**. It
is frozen per player per challenge at the start, so effort inside the challenge cannot move it. It
needs exercise-tagged samples in at least half the workout's minutes and 10 minutes. Without a
session signal or a reference, the factor is neutral and the receipt says why. No within-session
pattern is used as a substitute: with the data available it could not be defended.

**Points.** A workout's contribution is `base x (1 + (multiplier - 1) x reliability)`, kept as an
exact decimal. A day's score is the sum of its contributions, rounded half up once. Scoring runs in
two passes: the first finds which workouts count and whether any overlapped (which fixes each
Evidence Index), the second applies the multipliers.

### Worked examples (synthetic)

1. 40 min, moderate, no heart rate, no distance: multiplier 1.000, potential bonus 0; **40**. Evidence 67, limited.
2. 40 min hard run at 11.1 km/h, 10% above the personal reference: `0.4x1.12 + 0.4x1.125 + 0.2x1.05 = 1.108`; base 40, potential +4.32 (intensity +1.92, heart +2.00, movement +0.40); Evidence 100 -> 100%; 44.32 -> **44**.
3. The same session with patchier heart rate, Evidence 82 -> 85%: 40 + 4.32 x 0.85 = 43.67 -> **44**; at Evidence 67 -> 65%: 42.81 -> **43**.
4. 40 min labelled hard, no heart rate, no distance: potential +1.92, Evidence 67 -> 65%: 40 + 1.25 = 41.25 -> **41**. The label alone earns a reduced bonus; the base is untouched.
5. 40 min easy walk at 4.5 km/h, no heart rate: multiplier 0.960, potential -1.60, Evidence 75 -> 85%: 40 - 1.36 = 38.64 -> **39**.
6. 90 min neutral: 60 + 30 x 0.6 = **78**. Two 45-min neutral workouts in a day: 45 + (15 + 30 x 0.6) = **78**, not 90.
7. Example 2 plus a 30-min neutral session later the same day: its last 10 minutes fall in the second hour, 20 + 6 = 26; day = 44.32 + 26 = 70.32 -> **70**.

## Versioning and the locked ruleset

- v2 is a separate rule set: `proof_of_sweat_v2`, version `proof-of-sweat-v2`, fingerprint
  `b9bd8375b87d6c704a54dc0fbd48121f31595c344ce853935b63eb7708c661a6` (SHA-256 of every constant,
  including v1's gates).
- v1 is unchanged: `proof-of-sweat-v1`, `43143b257a0d5e734c25378000ce858aaeb9d53918d12cbfdb469674672ab180`.
  Both fingerprints are pinned in `api/tests/test_sweat2.py`.
- A challenge's ruleset (`api/rules.py`) names its scoring rules and their fingerprint; its hash is
  locked in the challenge's onchain Rules account at creation. Settlement refuses to score a
  challenge under any other fingerprint. So only challenges created after deployment use v2, and
  v1 and earlier challenges settle under what they locked.
- Changing any v2 constant requires a new `RULES_VERSION`.

## What Solana does and does not do

Does (program `loser_buys`, not changed by this work): holds entry fees in escrow; stores the hash
of the ruleset at creation and makes joiners quote it; at payout requires Solana's Ed25519 check of
the verifier's signature over a message naming this challenge's rules hash, the winners and shares,
and the score-sheet hash; pays only those winners, once, after the end; refunds otherwise.

Does not: see or check any workout, heart rate, Evidence Index or effort factor; recompute points
or winners. Those are computed by Rival's server. The oracle and verifier keys are both held by that
server. The score sheet lists one salted commitment per workout receipt, and v2 receipts carry the
index and the full score breakdown, so an owner can re-hash their receipt and find it in the sheet
whose hash was signed and committed.

## Data kept (private, per imported workout)

Category, Oura's activity name and provenance label, **Oura's intensity label**, UTC start and end,
distance, check results, heart-rate minute-bin counts, and **one median** of the exercise-tagged
heart rate. Per player per v2 challenge: the frozen reference (one number and a count). No
heart-rate series, calories or Oura IDs. The API never returns a heart-rate value: receipts show a
relative percentage. Workouts from the 30 days before a joined v2 challenge are kept until its
reference is frozen; otherwise retention is as in v1. Deleted on disconnect.

## Limitations

- Oura records are not tamper-proof sensor attestations; a category or source can be confirmed or
  edited by the wearer; intensity may be Oura's default.
- The reference needs 4 earlier workouts with good heart-rate coverage, so new users and patchy
  sensors get a neutral heart factor. That is expected, and shown.
- Pace ignores terrain and stops, which is why its effect is small.
- The Evidence Index and the factors are engineering and game-design heuristics, not validated
  measures of authenticity, exertion or energy use. Nothing here is medical.
- "Goal" format challenges that target points were tuned for small numbers (target up to 100);
  with v2 a point goal is reached far sooner. Use active days as the goal, or revisit the limit.

## Live test checklist (none of this has been done yet)

1. Merge and deploy both services. Create a **new** challenge (older ones keep their rules); its
   "Rules locked onchain" card should name `proof-of-sweat-v2`. Two accounts must join.
2. During the challenge, record a workout of 10+ minutes with the ring; let it sync to the Oura app.
3. "Sync workouts". Open the workout: check the ribbon, the evidence bar, and which effort signals
   are measured and which are neutral fallbacks. With little history, expect the heart factor neutral.
4. Recompute by hand: base + potential bonus x reliability should equal the points shown.
5. Sync again after 30 seconds: nothing changes.
6. Leaderboard shows the rounded daily total.
7. After the end and the 30-minute grace: "Check result" passes, including "Your workout receipts
   are in this result", and the payout link opens a real devnet transaction.

Files: `api/sweat2.py` (math), `api/fitness/oura_sync.py` (heart summary, reference),
`api/scores.py`, `api/settlement.py`, `api/rules.py`, `web/src/Sweat.tsx` (receipt),
tests `api/tests/test_sweat2.py`, `api/tests/test_sweat2_flow.py`.
