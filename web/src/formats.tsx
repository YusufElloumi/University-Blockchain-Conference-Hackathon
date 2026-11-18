// Competition formats: how the prize pool is paid. Stored by our server; the program only sees who is paid and how much.

import { Medal, Swords, Target, Trophy, type LucideIcon } from "lucide-react";

export type Format = "winner_takes_all" | "podium" | "goal" | "teams";

export type FormatConfig = {
  shares?: number[]; // podium: percent per place
  metric?: "active_days" | "points"; // goal
  target?: number; // goal
  teams?: string[]; // teams: the two names
};

export const FORMATS: Format[] = ["winner_takes_all", "podium", "goal", "teams"];

export const FORMAT_INFO: Record<Format, { title: string; Icon: LucideIcon; line: string; example: string }> = {
  winner_takes_all: {
    title: "Winner takes all",
    Icon: Trophy,
    line: "Top scorer takes the whole pool.",
    example: "Ties split it.",
  },
  podium: {
    title: "Podium",
    Icon: Medal,
    line: "The top places share the pool.",
    example: "e.g. 60% / 30% / 10%",
  },
  goal: {
    title: "Goal",
    Icon: Target,
    line: "Everyone who hits the goal splits it.",
    example: "e.g. 5 active days",
  },
  teams: {
    title: "Team vs team",
    Icon: Swords,
    line: "Best team average wins.",
    example: "The winning team splits it.",
  },
};

export const PODIUM_PRESETS = [
  [60, 30, 10],
  [50, 30, 20],
  [70, 30],
];

export const goalUnit = (metric: FormatConfig["metric"], n?: number) =>
  metric === "points" ? (n === 1 ? "point" : "points") : n === 1 ? "active day" : "active days";

/** The last screen of the join intro and the join card: how this event pays. */
export function payoutTitle(format: Format): string {
  if (format === "podium") return "The top places share the";
  if (format === "goal") return "Hit the goal, share the";
  if (format === "teams") return "The best team takes the";
  return "First place takes the";
}
