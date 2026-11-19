// Small helpers for showing money and time in plain words.

export const money = (n: number) => `$${n.toFixed(2)}`;
export const usdc = (n: number) => `${Number.isInteger(n) ? n : n.toFixed(2)} USDC`;

export const when = (date: Date) =>
  date.toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** "2d 4h", "3h 12m", "4m 09s" - a scoreboard-style countdown to a moment in the future. */
export function countdown(to: Date, now: number): string {
  const seconds = Math.max(0, Math.floor((to.getTime() - now) / 1000));
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function ago(iso: string, now: number): string {
  const seconds = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

/** "15 minutes", "36 hours", "1 day", "1 week", "10 days", "1 month", "365 days"... */
export function termLabel(ms: number): string {
  const minutes = Math.round(ms / 60000);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.round(minutes / 60);
  // Under a week, a length that is not whole days reads better in hours ("36 hours", not "2 days").
  if (hours < 24 || (hours < 168 && hours % 24 !== 0)) return `${hours} hour${hours === 1 ? "" : "s"}`;
  const days = Math.round(hours / 24);
  if (days === 7) return "1 week";
  if (days >= 28 && days <= 31) return "1 month";
  if (days % 7 === 0 && days <= 56) return `${days / 7} weeks`;
  return `${days} day${days === 1 ? "" : "s"}`;
}

/** Scoring days in a challenge: 24-hour blocks from the start, a partial last one counting (api/scoring.py day_count). */
export const dayCount = (seconds: number) => Math.max(1, Math.ceil(seconds / 86400));
