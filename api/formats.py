"""Competition formats: who gets paid, and how much, once the final scores are in.

Pure functions, no database or network, so every rule is easy to test.

Formats (stored off-chain on `challenges.format`; no format means winner takes all):
    winner_takes_all  The top scorer takes the pool. A tie at the top splits it equally.
    podium            The top places share the pool in fixed percentages (default 60/30/10).
                      Tied players share the percentages of the places they cover, equally.
                      Places nobody can fill (fewer players than places) go to first place.
    goal              Everyone who reaches the goal (active days, or points) splits the pool equally.
                      If nobody reaches it, every player gets their entry fee back.
    teams             Two named teams; a player picks one when joining. Team score is the
                      average of its members' points, so uneven teams are fair. The winning team's
                      members split the pool equally. A tie between teams splits it among everyone
                      on the tied teams.

Rules are fixed when the event is created and cannot be edited afterwards, and the format and its
settings are part of the score sheet whose hash goes onchain.

A payout is a list of (wallet, share in basis points). 10,000 basis points = 100%.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

FORMATS = ("winner_takes_all", "podium", "goal", "teams")
DEFAULT_FORMAT = "winner_takes_all"
FULL = 10_000  # 100% in basis points

DEFAULT_PODIUM = [60, 30, 10]
# A goal is a number of active days. Points targets were removed for new events (Nov 19): they are
# still read, paid and described for events created before that, which locked them in their rules.
GOAL_METRICS = ("active_days", "points")
DEFAULT_GOAL = {"metric": "active_days", "target": 5}
DEFAULT_TEAMS = ["Team A", "Team B"]


class FormatError(ValueError):
    """Settings that cannot be used (the message is safe to show)."""


def clean_config(fmt: str, raw: dict | None, *, league_stats: bool = False, days: int | None = None) -> dict:
    """Checks the creator's settings for a format and fills in defaults. Raises FormatError.

    `days` is the number of scoring days in the event (see scoring.day_count); when given, an active-days
    goal must be reachable within it.
    """
    raw = raw or {}
    if fmt == "winner_takes_all":
        return {}
    if fmt == "podium":
        shares = raw.get("shares", DEFAULT_PODIUM)
        if not isinstance(shares, list) or not 2 <= len(shares) <= 3:
            raise FormatError("A podium pays 2 or 3 places.")
        if not all(isinstance(s, int) and not isinstance(s, bool) and s > 0 for s in shares):
            raise FormatError("Each podium place needs a whole-number percentage above zero.")
        if sum(shares) != 100:
            raise FormatError("Podium percentages must add up to 100.")
        if any(a < b for a, b in zip(shares, shares[1:])):
            raise FormatError("A higher place cannot pay less than a lower one.")
        return {"shares": shares}
    if fmt == "goal":
        metric = raw.get("metric", DEFAULT_GOAL["metric"])
        if league_stats:
            raise FormatError("The goal format counts active days, which league stats don't have. Pick another format.")
        if metric != "active_days":
            raise FormatError("A goal is a number of active days.")
        target = raw.get("target", DEFAULT_GOAL["target"])
        if not isinstance(target, int) or isinstance(target, bool) or not 1 <= target <= 100:
            raise FormatError("The goal must be a whole number from 1 to 100.")
        if metric == "active_days" and days is not None and target > days:
            raise FormatError(f"This event has {days} day{'s' if days != 1 else ''}, so nobody can reach {target} active days.")
        return {"metric": metric, "target": target}
    if fmt == "teams":
        names = raw.get("teams", DEFAULT_TEAMS)
        if not isinstance(names, list) or len(names) != 2:
            raise FormatError("Name both teams.")
        names = [" ".join(str(n).split())[:30] for n in names]
        if not all(names) or names[0].lower() == names[1].lower():
            raise FormatError("Give the two teams different names.")
        return {"teams": names}
    raise FormatError("Unknown format.")


def of(challenge) -> tuple[str, dict]:
    """(format, settings) of a stored challenge. Older events have none: winner takes all."""
    fmt = getattr(challenge, "format", None) or DEFAULT_FORMAT
    config = json.loads(challenge.format_config) if getattr(challenge, "format_config", None) else {}
    return fmt, config


@dataclass
class Entry:
    """One player's final result, as used by the payout rules."""

    wallet: str
    points: float
    active_days: int = 0
    team: int | None = None  # index into the team names (teams format)


@dataclass
class Payout:
    shares: list[tuple[str, int]]  # (wallet, basis points) in payout order (rank order); adds up to FULL
    note: str  # one plain sentence for the feed and the result screen
    # True: pay with the program's plain `settle`, which splits the pool equally down to the last unit.
    # False: a podium, paid with `settle_split`; the program works the shares out again from the split
    # locked at creation and `groups`, and pays only if they match.
    equal: bool = True
    goal_missed: bool = False  # goal format: nobody made it, so everyone got their entry fee back
    groups: list[int] | None = None  # podium: how many players share each paid rank, in order

    @property
    def wallets(self) -> list[str]:
        return [w for w, _ in self.shares]


def _equal(wallets: list[str]) -> list[tuple[str, int]]:
    """Splits 100% equally; rounding goes to the first wallet."""
    each = FULL // len(wallets)
    shares = [(w, each) for w in wallets]
    shares[0] = (wallets[0], each + FULL - each * len(wallets))
    return shares


def _ordered(entries: list[Entry]) -> list[Entry]:
    return sorted(entries, key=lambda e: (-e.points, e.wallet))


def winner_takes_all(entries: list[Entry]) -> Payout:
    best = max(e.points for e in entries)
    top = [e.wallet for e in _ordered(entries) if e.points == best]
    return Payout(_equal(top), "Top scorer takes the pool." if len(top) == 1 else "A tie at the top splits the pool.")


def podium_shares(split_bps: list[int], player_count: int, groups: list[int]) -> list[int]:
    """Podium shares in basis points, in rank order. The same rule the program applies in `settle_split`
    (onchain/programs/loser_buys/src/instructions/settle.rs, `podium_shares`); keep the two identical.

    Places nobody can fill (fewer players than places) go to first place. Players tied at a rank share
    the places they cover equally; the rounding goes to the first of them.
    """
    places = [s for s in split_bps if s][:player_count]
    places[0] += FULL - sum(places)
    shares: list[int] = []
    rank = 0
    for size in groups:
        if size < 1 or rank >= len(places):
            raise ValueError("every tie group must start on a paid place")
        pot = sum(places[rank : rank + size])  # the places they cover (may run past the paid places)
        each = pot // size
        shares += [pot - each * (size - 1)] + [each] * (size - 1)
        rank += size
    if rank < len(places):
        raise ValueError("the tie groups must cover every paid place")
    return shares


def podium(entries: list[Entry], percents: list[int]) -> Payout:
    ranked = _ordered(entries)
    paid_places = min(len(percents), len(ranked))
    groups: list[int] = []
    i = 0
    while i < paid_places:
        groups.append(sum(1 for e in ranked[i:] if e.points == ranked[i].points))  # everyone tied at this rank
        i += groups[-1]
    shares = podium_shares([p * 100 for p in percents], len(ranked), groups)
    winners = [e.wallet for e in ranked[:i]]  # rank order, as the program pays them
    return Payout(list(zip(winners, shares)), f"Podium split {'/'.join(map(str, percents))}.", equal=False,
                  groups=groups)


def goal_progress(entry: Entry, config: dict) -> float:
    return entry.active_days if config["metric"] == "active_days" else entry.points


def goal(entries: list[Entry], config: dict) -> Payout:
    made_it = [e.wallet for e in _ordered(entries) if goal_progress(e, config) >= config["target"]]
    if not made_it:
        # Equal shares of a pool everyone paid the same into: each player gets their entry fee back.
        return Payout(_equal([e.wallet for e in _ordered(entries)]), "Nobody reached the goal, so entry fees went back.",
                      goal_missed=True)
    return Payout(_equal(made_it), "Everyone who reached the goal splits the pool.")


def team_scores(entries: list[Entry], names: list[str]) -> list[dict]:
    """Each team with its average points and member count, best first. Empty teams are left out."""
    rows = []
    for index, name in enumerate(names):
        members = [e for e in entries if e.team == index]
        if members:
            average = sum(e.points for e in members) / len(members)
            rows.append({"team": index, "name": name, "average": round(average, 1), "members": len(members)})
    rows.sort(key=lambda r: (-r["average"], r["team"]))
    for i, row in enumerate(rows):
        row["rank"] = rows[i - 1]["rank"] if i and rows[i - 1]["average"] == row["average"] else i + 1
    return rows


def teams(entries: list[Entry], names: list[str]) -> Payout:
    table = team_scores(entries, names)
    if not table:  # nobody picked a team (cannot happen through the app): fall back to the top scorer
        return winner_takes_all(entries)
    winning = {r["team"] for r in table if r["rank"] == 1}
    wallets = [e.wallet for e in _ordered(entries) if e.team in winning]
    if len(winning) > 1:
        return Payout(_equal(wallets), "The teams tied, so the pool is split among everyone.")
    return Payout(_equal(wallets), f"{names[winning.pop()]} won; its players split the pool.")


def payout(fmt: str, config: dict, entries: list[Entry]) -> Payout:
    """Who gets paid and their share, for any format. `entries` must not be empty."""
    if fmt == "podium":
        return podium(entries, config["shares"])
    if fmt == "goal":
        return goal(entries, config)
    if fmt == "teams":
        return teams(entries, config["teams"])
    return winner_takes_all(entries)


def describe(fmt: str, config: dict) -> str:
    """One short line about how the pool is paid, for the event screen."""
    if fmt == "podium":
        return "Top places share the pool: " + " / ".join(f"{p}%" for p in config["shares"]) + "."
    if fmt == "goal":
        unit = "active days" if config["metric"] == "active_days" else "points"
        return f"Reach {config['target']} {unit} to share the pool. If nobody does, everyone gets their fee back."
    if fmt == "teams":
        return f"{config['teams'][0]} vs {config['teams'][1]}. Best team average wins; its players split the pool."
    return "Top scorer takes the pool. A tie splits it."
