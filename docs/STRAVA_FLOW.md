# Strava flow (intended design)

**Status on Nov 14, 2026: not built.** Creating a Strava API app needs a Strava subscription, and nobody on the team has one. The app runs on the mock and manual sources. This file describes how the Strava source would work, so it can be added without touching anything outside `api/fitness/`.

The rules behind this design are in `docs/ARCHITECTURE.md` section 5.

## Where it plugs in

Every fitness source implements `FitnessProvider` (`api/fitness/base.py`):

| Method | Mock / manual today | Strava |
|---|---|---|
| `connect_url(user)` | Nothing to link | Returns Strava's authorization address |
| `handle_callback(user, params)` | Not used | Swaps the code for tokens and stores them encrypted |
| `fetch_activities(user, start, end)` | Reads `logged_activities` | Calls Strava's API, returns `Activity` objects, stores nothing raw |
| `log_activity(...)` | Stores the activity | Refused: activities come from Strava only |
| `disconnect(user)` | Deletes the user's logged activities | Deauthorizes at Strava and deletes the tokens |

Setting `FITNESS_PROVIDER=strava` in `.env` selects it. Scoring, the leaderboard, and the endpoints stay the same, because they only see `Activity` objects.

For Strava, the provider sets `counts_manual = False` and `requires_device = True`, so hand-typed Strava activities and activities with no device name earn nothing.

## Step by step

1. **Connect.** The user taps the official "Connect with Strava" button. The API sends them to `https://www.strava.com/oauth/authorize` with our client ID, the scope `activity:read`, and a random `state` value tied to their login.
2. **Callback.** Strava sends the user back to `GET /fitness/callback` with a `code`. The API checks `state`, swaps the code for an access token (lasts 6 hours) and a refresh token at `POST https://www.strava.com/oauth/token`, and stores both encrypted in `fitness_connections` with the athlete ID.
3. **Webhook.** One subscription for the whole app (`POST https://www.strava.com/api/v3/push_subscriptions`). Strava calls `POST /webhooks/strava` when an athlete creates, changes, or deletes an activity, or removes our app. The endpoint must answer within 2 seconds, so it only notes the athlete and returns.
4. **Score.** For that athlete, the API refreshes the token if needed, calls `fetch_activities` for each challenge they are in, and reruns the scoring. Only points and activity IDs are written to `score_entries`.
5. **Before settling.** The API fetches every player's activities once more, in case a webhook was missed. If Strava is down, it waits instead of settling on partial data.
6. **Disconnect.** The user taps "Disconnect", or removes our app inside Strava (which arrives through the webhook). The API calls `POST https://www.strava.com/oauth/deauthorize`, deletes their tokens, and deletes their points in unsettled challenges. They stay in the pool with zero points; the join screen says so.

## Rules the code must keep

| Rule | How |
|---|---|
| A user's Strava data is shown only to that user | `GET /me/activities` returns the caller's own activities. The leaderboard returns name, points, and daily ticks only |
| Others see points only after consent | Joining requires ticking "Share my challenge points with this group"; the time is stored in `participants.consent_at` |
| No Strava data to any AI | Nothing in `api/fitness/` calls an AI service, and no other code may import Strava code |
| Keep nothing raw beyond 7 days | Raw activities are fetched, scored, and dropped. Only points and activity IDs are stored |
| Delete on disconnect | `scores.forget_user` deletes the connection and points |
| Nothing personal onchain | The program gets winner addresses and a salted hash of the score sheet |
| Branding | Official "Connect with Strava" button, "Powered by Strava" mark, "View on Strava" links on the owner's own activities |

## Limits to plan around

- A new app holds 1 athlete; we can raise it to 10 ourselves. Enough for a demo, not for a launch.
- 200 requests per 15 minutes and 2,000 per day.
- Access tokens last 6 hours.

## Open questions for Strava

Not answered before the deadline; listed in `DEVELOPMENT_PLAN.md` under "Open questions". The main one: whether friends may see each other's app-computed points with explicit consent. Until Strava answers, demos use the mock source.
