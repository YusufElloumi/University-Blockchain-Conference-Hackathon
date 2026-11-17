// The three play modes. Mode is our server's record only; the Solana program does not know about it.

export type Mode = "league" | "public" | "private";

export const MODES: Mode[] = ["league", "public", "private"];

export const MODE_INFO: Record<
  Mode,
  { title: string; badge: string; icon: string; line: string; create: string; noun: string; inviteOnly: boolean }
> = {
  league: {
    title: "League Play",
    badge: "League",
    icon: "🏟️",
    line: "Hosted by a gym, club or tournament. Join with the organizer's code.",
    create: "Create a league",
    noun: "league",
    inviteOnly: true,
  },
  public: {
    title: "Public Events",
    badge: "Public",
    icon: "🌍",
    line: "Open to anyone. Community and city-wide, with bigger pots.",
    create: "Create a public event",
    noun: "public event",
    inviteOnly: false,
  },
  private: {
    title: "Private Play",
    badge: "Private",
    icon: "🔒",
    line: "Your friends, team or office. Invite only, never listed.",
    create: "Create a private game",
    noun: "private game",
    inviteOnly: true,
  },
};

export const isMode = (value: string | null | undefined): value is Mode => MODES.includes(value as Mode);

/** The small coloured label shown on event cards and the event page. */
export function ModeBadge({ mode }: { mode: Mode }) {
  return (
    <span className={`mode-badge mode-${mode}`}>
      {MODE_INFO[mode].icon} {MODE_INFO[mode].badge}
    </span>
  );
}
