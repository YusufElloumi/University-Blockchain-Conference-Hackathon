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
