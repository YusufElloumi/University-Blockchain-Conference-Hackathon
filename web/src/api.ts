// Calls to our own API server. Calls about a person carry their Privy login token.

import type { Format, FormatConfig } from "./formats";
import type { Mode } from "./modes";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export type Me = {
  wallet: string;
  email: string | null;
  name: string;
  test_funds_used: boolean;
  test_funds_amount: number;
  is_admin?: boolean;
  usdc: number | null;
  ready?: boolean;
  signature?: string;
};

export type AppConfig = {
  oracle: string;
  usdc_mint: string;
  fitness: { source: string; label: string; can_add: boolean; types: string[] };
  /** Rules a challenge created now will use. Proof of Sweat: points come only from Oura-verified workouts. */
  new_challenge_rules?: { proof_of_sweat: boolean; summary: string | null };
  pick_themes: { id: string; label: string }[];
  max_pick_points: number;
};

export type StatWeights = { goals: number; assists: number; points: number };

export type ChallengeView = {
  address: string;
  name: string;
  mode: Mode;
  organizer_name: string | null; // league events only
  template: string;
  buy_in: number;
  start: string;
  end: string;
  status: "open" | "settled" | "refunded";
  invite_code: string;
  scoring_source: "fitness" | "league_stats";
  stat_weights: StatWeights | null;
  pick_themes: string[];
  round_hours: number | null; // a prediction round every this many hours; null = no rounds
  round_count: number;
  format: Format; // how the pool is paid; fixed when the event was created
  format_config: FormatConfig;
  format_summary: string; // one plain sentence
  /** Which fitness rules apply, fixed at creation. */
  rules?: { name: string; version: string; sha256: string | null; proof_of_sweat: boolean; summary: string };
};

/** One of "my" events in a mode: joined, created, or invited to. */
export type MyEvent = ChallengeView & { joined: boolean; is_creator: boolean };

/** An open public event in the browsable list. */
export type PublicEvent = ChallengeView & { player_count: number; max_players: number; pot: number };

export type PlayerRow = {
  rank: number;
  name: string;
  points: number;
  base_points: number; // fitness or league-stat points
  pick_points: number; // prediction pick points
  ticks: boolean[];
  team: number | null; // teams format: index into format_config.teams
  projected_share: number; // percent of the pool this player would win if it ended now
  goal_progress: number | null; // goal format: active days or points so far
  is_you: boolean;
  /** Proof of Sweat challenges: is this player's Oura linked and synced? Nothing about their workouts. */
  oura?: "none" | "waiting" | "synced" | null;
};

/** One prediction round: a Gemini market, its sides, and (after kick-off) everyone's picks. */
export type PickRound = {
  number: number;
  title: string;
  theme: string;
  theme_label: string;
  league: string;
  market_url: string;
  locks_at: string;
  locked: boolean;
  status: "open" | "resolved" | "void";
  winner: string | null;
  options: { id: string; label: string; chance: number; pays: number }[];
  picks_made: number;
  yours: { option_id: string; pick: string; chance: number; pays: number; points: number | null } | null;
  everyone: { name: string; pick: string; points: number | null }[] | null;
};

/** What the organizer sees about the uploaded stat sheet. */
export type StatsSummary = {
  dates: string[];
  rows: number;
  sheet_names: string[];
  weights: StatWeights;
  players: { user_id: number; name: string; stat_name: string | null }[];
  unmatched: string[];
  grok_url: string;
  grok_prompt: string;
  first_date: string;
  last_date: string;
  skipped_outside_dates?: number;
};

export type FeedItem = { kind: string; text: string; signature: string; time: string };

export type ChallengeState = {
  challenge: ChallengeView | null;
  you: { joined: boolean; deposit_confirmed: boolean; is_creator: boolean; is_admin: boolean };
  settle_tx: string | null;
  pool: number | null;
  player_count: number | null;
  players: PlayerRow[] | null; // null unless you are a player
  format: {
    format: Format;
    summary: string;
    goal_missed?: boolean; // goal format: nobody has reached it (yet)
    teams?: { team: number; name: string; average: number | null; members: number; rank: number | null }[];
  } | null;
  rounds: { total: number; max_points: number; list: PickRound[] } | null;
  /** Proof of Sweat challenges: when the scores get fixed (the end plus a sync grace period). */
  sweat?: { grace_seconds: number; scores_final_after: string; awaiting_final_sync: boolean } | null;
  feed: FeedItem[];
};

export type ActivityView = {
  id: string;
  type: string;
  start: string;
  minutes: number;
  distance_km: number;
  device: string | null;
  verified: boolean;
  source: string;
  source_label: string;
  // Only when asked for one challenge: did it count there, and why not.
  status?: "verified" | "flagged" | "rejected";
  reason?: string | null;
};

export type ActivityResult = {
  activity: ActivityView;
  challenges: { address: string; name: string; points: number; counted: boolean; reason: string | null }[];
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** One request to the API. `Call` is this with the login token already filled in. */
export type Call = <T>(method: "GET" | "POST" | "DELETE", path: string, body?: unknown) => Promise<T>;

export async function request<T>(method: string, path: string, token: string | null, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(API_URL + path, {
      method,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "Something went wrong. Try again.";
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Repeats a call while the server says "not yet" (HTTP 409), for example while a deposit is still landing. */
export async function retryWhileNotReady<T>(action: () => Promise<T>, attempts = 10): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await action();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && attempt < attempts) await sleep(1500);
      else throw e;
    }
  }
}

export const API_BASE = API_URL;

export const getAppConfig = () => request<AppConfig>("GET", "/app-config", null);
