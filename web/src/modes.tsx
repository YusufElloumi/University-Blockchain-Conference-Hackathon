// The three play modes. Mode is our server's record only; the Solana program does not know about it.

import { Building2, Globe, Lock, type LucideIcon } from "lucide-react";

export type Mode = "league" | "public" | "private";

export const MODES: Mode[] = ["league", "public", "private"];

export const MODE_INFO: Record<
  Mode,
  {
    title: string;
    nav: string;
    badge: string;
    Icon: LucideIcon;
    line: string;
    create: string;
    noun: string;
    inviteOnly: boolean;
  }
> = {
  league: {
    title: "League Play",
    nav: "Leagues",
    badge: "League",
    Icon: Building2,
    line: "Hosted by a gym, club or tournament. Join with the organizer's code.",
    create: "Create a league",
    noun: "league",
    inviteOnly: true,
  },
  public: {
    title: "Public Events",
    nav: "Public",
    badge: "Public",
    Icon: Globe,
    line: "Open to anyone. Community and city-wide, with bigger prize pools.",
    create: "Create a public event",
    noun: "public event",
    inviteOnly: false,
  },
  private: {
    title: "Private Play",
    nav: "Private",
    badge: "Private",
    Icon: Lock,
    line: "Your friends, team or office. Invite only, never listed.",
    create: "Create a private game",
    noun: "private game",
    inviteOnly: true,
  },
};

export const isMode = (value: string | null | undefined): value is Mode => MODES.includes(value as Mode);

/** The small label shown on event cards and the event page. */
export function ModeBadge({ mode }: { mode: Mode }) {
  const { Icon, badge } = MODE_INFO[mode];
  return (
    <span className="badge">
      <Icon size={12} strokeWidth={2} aria-hidden />
      {badge}
    </span>
  );
}
