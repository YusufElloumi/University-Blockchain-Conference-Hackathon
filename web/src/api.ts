// Calls to our own API server. Every call carries the Privy login token.

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export type Me = {
  wallet: string;
  email: string | null;
  test_funds_used: boolean;
  test_funds_amount: number;
  usdc: number | null;
  ready?: boolean;
  signature?: string;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function post(path: string, token: string): Promise<Me> {
  let response: Response;
  try {
    response = await fetch(API_URL + path, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, body.detail || "Something went wrong. Try again.");
  return body as Me;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Registers the user with the server. Retries while Privy is still creating their wallet (HTTP 409). */
export async function setupAccount(getToken: () => Promise<string | null>): Promise<Me> {
  for (let attempt = 0; ; attempt++) {
    const token = await getToken();
    if (!token) throw new ApiError(401, "Please sign in again.");
    try {
      return await post("/me/setup", token);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && attempt < 10) await sleep(1500);
      else throw e;
    }
  }
}

export async function addTestFunds(token: string): Promise<Me> {
  return post("/me/fund", token);
}
