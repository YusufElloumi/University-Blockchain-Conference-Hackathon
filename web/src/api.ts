// Calls to our own API server. Calls about a person carry their Privy login token.

import type { Mode } from "./modes";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export type Me = {
  wallet: string;
  email: string | null;
  name: string;
  test_funds_used: boolean;
  test_funds_amount: number;
  usdc: number | null;
  ready?: boolean;
  signature?: string;
};

export type AppConfig = {
  oracle: string;
  usdc_mint: string;
  fitness: { source: string; label: string; can_add: boolean; types: string[] };
};

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
};

/** One of "my" events in a mode: joined, created, or invited to. */
export type MyEvent = ChallengeView & { joined: boolean; is_creator: boolean };

/** An open public event in the browsable list. */
export type PublicEvent = ChallengeView & { player_count: number; max_players: number; pot: number };

export type PlayerRow = {
  rank: number;
  name: string;
  points: number;
  ticks: boolean[];
  is_you: boolean;
  pick: string | null; // their tiebreaker pick, hidden until kick-off
};

/** A game from Gemini Prediction Markets, with the market's current chance for each side. */
export type Game = {
  ticker: string;
  title: string;
  league: string;
  starts: string;
  options: { id: string; label: string; chance: number | null }[];
};
export type MyPick = { ticker: string; game: string; option_id: string; pick: string; chance: number | null };
export type FeedItem = { kind: string; text: string; signature: string; time: string };

export type ChallengeState = {
  challenge: ChallengeView | null;
  you: { joined: boolean; deposit_confirmed: boolean; is_creator: boolean; is_admin: boolean };
  settle_tx: string | null;
  pool: number | null;
  player_count: number | null;
  players: PlayerRow[] | null; // null unless you are a player
  pickem: { open: boolean; made: number; yours: MyPick | null } | null;
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

export const getAppConfig = () => request<AppConfig>("GET", "/app-config", null);
