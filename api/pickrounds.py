"""Prediction rounds: one Gemini market per round, free picks, and points for a correct pick.

The organizer chooses themes (Basketball, Soccer, Hockey, Football, General) and how often a round
opens (every day or every week). When a round opens, the server picks one market automatically:

    1. Eligible: a game-winner market in a selected theme, kicking off inside the round and at least
       10 minutes from now, expected to finish before the challenge ends (and on a Sunday, before
       midnight Eastern), with a live price on every side, not used earlier in this challenge.
    2. Ranked: same-day games first, then later ones; then bigger leagues (Champions League, EPL,
       La Liga, then NFL and NBA); then total trading volume (the "big games"); then the closest odds.
       General ranks by 24-hour volume only ("the hottest market right now").
    3. Themes take turns round by round, so a mix of themes shows up over the challenge.

A correct pick earns 1 / probability of the side picked, capped at MAX_PICK_POINTS: a 50% side pays
2 points, a 25% side 4. A wrong pick earns 0. The probability is saved when the pick is made, because
Gemini has no API for past prices. Picks lock at kick-off.

Points only: no money is staked on a pick. Only public market data comes from Gemini; nothing about
our users or their fitness data is sent to it.
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import db

log = logging.getLogger("loser_buys")

EVENTS_URL = "https://api.gemini.com/v1/prediction-markets/events"


def fetch(path: str = "", params: dict | None = None):
    """One GET to Gemini's public prediction-markets API (no key needed). `path` is "/<ticker>" for one event."""
    response = httpx.get(EVENTS_URL + path, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


THEMES = {
    "basketball": {"label": "Basketball", "sport": "basketball"},
    "soccer": {"label": "Soccer", "sport": "soccer"},
    "hockey": {"label": "Hockey", "sport": "hockey"},
    "football": {"label": "Football", "sport": "american_football"},
    "general": {"label": "General", "sport": None},  # the most traded markets right now, any kind
}
ROUND_CHOICES = (24, 168)  # one round a day, or one a week
MAX_PICK_POINTS = 5.0  # a side under 20% pays as if it were 20%, so one lucky long shot can't decide a week
MIN_LEAD = timedelta(minutes=10)  # a market must kick off at least this long after the round is chosen
MAX_SPREAD = 0.10  # skip markets where buyers and sellers are more than 10 cents apart (too thin to trust)
RESULT_WAIT = timedelta(hours=6)  # after the challenge ends, wait this long for results; then a round is void
RECHECK = timedelta(minutes=5)  # how often to ask Gemini for a result that is not in yet
CACHE_SECONDS = 60
MARKET_PAGE = "https://www.gemini.com/predictions/"  # + ticker: the market's page on Gemini (checked Nov 17)
EASTERN = ZoneInfo("America/New_York")
CENTRAL = ZoneInfo("America/Chicago")  # "today" for ranking; most of our players are in North America

# How long a game usually lasts, used to check it ends in time. Results arrive about this long after
# kick-off (measured Nov 17: NBA 2.5 h, college basketball 2.1 h, NHL 2.9 h, NFL 3.2 h).
GAME_HOURS = {"basketball": 2.5, "hockey": 3.0, "american_football": 3.5, "soccer": 2.0}
# Bigger leagues rank higher. Soccer: the Premier League, La Liga and the Champions League first.
LEAGUE_WEIGHT = {"Champions League": 3, "EPL": 3, "La Liga": 3, "Pro Football": 2, "Pro Basketball": 2}
GENERAL_CATEGORIES = ("Crypto", "Commodities")  # daily price markets; politics etc. resolve months away

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, load):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = load()
    _cache[key] = (time.time(), value)
    return value


def _time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mid(contract: dict) -> float | None:
    """The middle of the best buy and sell prices for "yes" on this contract, or None if too thin."""
    prices = contract.get("prices") or {}
    bid, ask = _num(prices.get("bestBid")), _num(prices.get("bestAsk"))
    if bid is None or ask is None or ask - bid > MAX_SPREAD:
        return None
    return (bid + ask) / 2


def probabilities(contracts: list[dict]) -> list[float] | None:
    """Each side's chance, scaled so the sides add up to 1. None if any side has no usable price."""
    mids = [_mid(c) for c in contracts]
    if not mids or any(m is None or m <= 0 for m in mids):
        return None
    total = sum(mids)
    return [m / total for m in mids]


def pick_points(probability: float) -> float:
    """What a correct pick pays: 1 / probability, capped, to one decimal place."""
    return round(min(MAX_PICK_POINTS, 1 / max(probability, 1e-9)), 1)


def _league(event: dict) -> str:
    path = (event.get("subcategory") or {}).get("path") or []
    return path[-1] if len(path) > 1 else (event.get("subcategory") or {}).get("name") or event.get("category") or ""


def _game_market(event: dict, theme: str) -> dict | None:
    """A sports game-winner event as a market we can offer, or None."""
    sports = event.get("sportsMarket") or {}
    if (sports.get("scope") or {}).get("type") not in ("full_contest", "regulation"):
        return None  # quarter and half markets
    starts = _time(event.get("startTime"))
    contracts = event.get("contracts") or []
    if starts is None or not event.get("ticker") or len(contracts) not in (2, 3):
        return None
    chances = probabilities(contracts)
    if chances is None:
        return None
    hours = GAME_HOURS.get(sports.get("sport"), 3.0)
    return {
        "ticker": event["ticker"],
        "title": event.get("title") or "",
        "theme": theme,
        "league": _league(event),
        "starts": starts,
        "ends": starts + timedelta(hours=hours),
        "volume": _num(event.get("volume")) or 0.0,  # all-time; a future game has little 24-hour volume yet
        "volume24h": _num(event.get("volume24h")) or 0.0,
        "options": [
            {"id": c["id"], "label": c.get("label") or "", "chance": p} for c, p in zip(contracts, chances)
        ],
    }


def _price_market(event: dict) -> dict | None:
    """A daily price ladder ("BTC price today?") as one yes/no question: the level nearest a coin flip."""
    expires = _time(event.get("expiryDate"))
    if expires is None or not event.get("ticker"):
        return None
    best = None
    for contract in event.get("contracts") or []:
        mid = _mid(contract)
        if mid is None or not 0.05 <= mid <= 0.95:
            continue
        if best is None or abs(mid - 0.5) < abs(best[1] - 0.5):
            best = (contract, mid)
    if best is None:
        return None
    contract, yes = best
    # A price can't be "watched" like a game, so picks lock 3 hours before the market closes.
    return {
        "ticker": event["ticker"],
        "title": f"{event.get('title') or ''} {contract.get('label') or ''}".strip(),
        "theme": "general",
        "league": event.get("category") or "Markets",
        "starts": expires - timedelta(hours=3),
        "ends": expires,
        "volume": _num(event.get("volume")) or 0.0,
        "volume24h": _num(event.get("volume24h")) or 0.0,
        "options": [
            {"id": f"{contract['id']}:yes", "label": "Yes", "chance": yes},
            {"id": f"{contract['id']}:no", "label": "No", "chance": 1 - yes},
        ],
    }


def _sport_markets(theme: str) -> list[dict]:
    sport = THEMES[theme]["sport"]
    params = {"status": "active", "sport": sport, "sports_market_type": "moneyline", "limit": 500}
    events = _cached(f"sport:{sport}", lambda: fetch(params=params).get("data", []))
    return [m for m in (_game_market(e, theme) for e in events) if m]


def _general_markets() -> list[dict]:
    markets = []
    for theme in ("basketball", "soccer", "hockey", "football"):
        markets += [{**m, "theme": "general"} for m in _sport_markets(theme)]
    for category in GENERAL_CATEGORIES:
        params = {"status": "active", "category": category, "limit": 500}
        events = _cached(f"category:{category}", lambda: fetch(params=params).get("data", []))
        markets += [m for m in (_price_market(e) for e in events) if m]
    return markets


def markets_for(theme: str) -> list[dict]:
    return _general_markets() if theme == "general" else _sport_markets(theme)


def _ends_in_time(market: dict, challenge_end: datetime) -> bool:
    if market["ends"] > challenge_end:
        return False
    local = market["starts"].astimezone(EASTERN)
    if local.weekday() == 6:  # Sunday: only markets that finish before the day ends
        midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return market["ends"] <= midnight
    return True


def _rank(market: dict, now: datetime) -> tuple:
    if market["theme"] == "general":
        return (-market["volume24h"],)
    same_day = market["starts"].astimezone(CENTRAL).date() == now.astimezone(CENTRAL).date()
    closeness = max(o["chance"] for o in market["options"])  # lower = closer game
    # Trading volume is the best sign of a "big game"; close odds break a tie.
    return (not same_day, -LEAGUE_WEIGHT.get(market["league"], 1), -market["volume"], closeness)


def choose_market(themes: list[str], number: int, window: tuple[datetime, datetime], challenge_end: datetime,
                  used: set[str], now: datetime) -> dict | None:
    """The best market for round `number`, trying its turn's theme first, then the others."""
    if not themes:
        return None
    turn = number % len(themes)
    for theme in themes[turn:] + themes[:turn]:
        try:
            markets = markets_for(theme)
        except Exception:
            log.exception("Could not load %s markets from Gemini", theme)
            continue
        eligible = [
            m for m in markets
            if m["ticker"] not in used
            and max(window[0], now + MIN_LEAD) <= m["starts"] < window[1]
            and _ends_in_time(m, challenge_end)
        ]
        if eligible:
            return min(eligible, key=lambda m: _rank(m, now))
    return None


# ---------- rounds in the database ----------


def settings(challenge: db.Challenge) -> tuple[list[str], int | None]:
    themes = [t for t in json.loads(challenge.pick_themes or "[]") if t in THEMES]
    return themes, (challenge.round_hours if themes else None)


def round_count(challenge: db.Challenge) -> int:
    _themes, hours = settings(challenge)
    if not hours:
        return 0
    length = db.utc(challenge.end_time) - db.utc(challenge.start_time)
    return max(1, math.ceil(length / timedelta(hours=hours)))


def window(challenge: db.Challenge, number: int) -> tuple[datetime, datetime]:
    _themes, hours = settings(challenge)
    start = db.utc(challenge.start_time) + timedelta(hours=hours * number)
    return start, min(start + timedelta(hours=hours), db.utc(challenge.end_time))


def rounds_of(session: Session, challenge: db.Challenge) -> list[db.PickRound]:
    return list(session.scalars(
        select(db.PickRound).where(db.PickRound.challenge_id == challenge.id).order_by(db.PickRound.number)
    ))


def open_due_round(session: Session, challenge: db.Challenge, now: datetime | None = None) -> db.PickRound | None:
    """Chooses the market for the round that is on now, if it has none yet. Returns the new round."""
    themes, hours = settings(challenge)
    now = now or datetime.now(timezone.utc)
    if not hours or challenge.status != "open":
        return None
    start, end = db.utc(challenge.start_time), db.utc(challenge.end_time)
    if not start <= now < end:
        return None
    number = int((now - start) / timedelta(hours=hours))
    existing = rounds_of(session, challenge)
    if any(r.number == number for r in existing):
        return None
    market = choose_market(themes, number, window(challenge, number), end, {r.event_ticker for r in existing}, now)
    if market is None:
        return None  # nothing on yet; asked again on the next poll (Gemini lists some games on the day)
    round_ = db.PickRound(
        challenge_id=challenge.id, number=number, event_ticker=market["ticker"], event_title=market["title"],
        theme=market["theme"], league=market["league"], locks_at=market["starts"], expected_end=market["ends"],
        options=json.dumps([{**o, "chance": round(o["chance"], 4)} for o in market["options"]]), status="open",
    )
    session.add(round_)
    try:
        session.commit()
    except IntegrityError:  # another request opened it a moment ago
        session.rollback()
        return None
    return round_


def _is_yes_no(options: list[dict]) -> bool:
    return bool(options) and options[0]["id"].endswith(":yes")


def _event(ticker: str) -> dict:
    return _cached(f"event:{ticker}", lambda: fetch("/" + ticker))


def live_options(round_: db.PickRound, fresh: bool = False) -> list[dict]:
    """The round's sides with the current chance of each. Falls back to the chances when it opened."""
    stored = json.loads(round_.options)
    try:
        if fresh:
            _cache.pop(f"event:{round_.event_ticker}", None)
        by_id = {c.get("id"): c for c in _event(round_.event_ticker).get("contracts") or []}
        if _is_yes_no(stored):  # one level of a price ladder, asked as yes / no
            contract = by_id.get(stored[0]["id"][: -len(":yes")])
            mid = _mid(contract) if contract else None
            if mid is not None:
                return [{**stored[0], "chance": mid}, {**stored[1], "chance": 1 - mid}]
        else:
            contracts = [by_id.get(o["id"]) for o in stored]
            chances = probabilities(contracts) if all(contracts) else None
            if chances:
                return [{**o, "chance": p} for o, p in zip(stored, chances)]
    except Exception:
        log.warning("Could not refresh the odds for %s", round_.event_ticker)
    return stored


def save_pick(session: Session, round_: db.PickRound, user_id: int, option_id: str,
              now: datetime | None = None) -> db.RoundPick:
    """Stores (or changes) a pick at the current price. Raises ValueError when it can't be taken."""
    now = now or datetime.now(timezone.utc)
    if round_.status != "open" or now >= db.utc(round_.locks_at):
        raise ValueError("Picks for this round are locked.")
    option = next((o for o in live_options(round_, fresh=True) if o["id"] == option_id), None)
    if option is None:
        raise ValueError("That side is not on offer.")
    pick = session.scalar(
        select(db.RoundPick).where(db.RoundPick.round_id == round_.id, db.RoundPick.user_id == user_id)
    ) or db.RoundPick(round_id=round_.id, user_id=user_id)
    pick.option_id, pick.option_label = option_id, option["label"]
    pick.probability, pick.picked_at = round(option["chance"], 4), now
    session.add(pick)
    session.commit()
    return pick


def winning_option(round_: db.PickRound) -> str | None | bool:
    """The winning side's ID, None while unsettled, or False if the market settled with no winner."""
    event = fetch("/" + round_.event_ticker)
    contracts = event.get("contracts") or []
    stored = json.loads(round_.options)
    if _is_yes_no(stored):
        contract_id = stored[0]["id"][: -len(":yes")]
        contract = next((c for c in contracts if c.get("id") == contract_id), None)
        side = (contract or {}).get("resolutionSide")
        return f"{contract_id}:{side}" if side in ("yes", "no") else None
    for contract in contracts:
        if contract.get("resolutionSide") == "yes":
            return contract["id"]
    if event.get("status") == "settled":
        return False
    return None


def resolve(session: Session, challenge: db.Challenge, now: datetime | None = None, give_up: bool = False) -> bool:
    """Reads results for finished rounds and scores their picks. Returns True when no round is waiting.

    `give_up`: every round still without a result is void (scores nothing for anyone).
    """
    now = now or datetime.now(timezone.utc)
    waiting = False
    for round_ in rounds_of(session, challenge):
        if round_.status != "open":
            continue
        result = None
        due = now >= db.utc(round_.expected_end)
        recently = round_.checked_at and now - db.utc(round_.checked_at) < RECHECK
        if due and not recently:
            round_.checked_at = now
            try:
                result = winning_option(round_)
            except Exception:
                log.exception("Could not read the result of %s from Gemini", round_.event_ticker)
        if result:
            round_.status, round_.winning_option_id, round_.resolved_at = "resolved", result, now
            for pick in session.scalars(select(db.RoundPick).where(db.RoundPick.round_id == round_.id)):
                pick.points = pick_points(pick.probability) if pick.option_id == result else 0.0
        elif result is False or give_up:
            round_.status, round_.resolved_at = "void", now
            for pick in session.scalars(select(db.RoundPick).where(db.RoundPick.round_id == round_.id)):
                pick.points = 0.0
        else:
            waiting = True
    session.commit()
    return not waiting


def points_by_user(session: Session, challenge: db.Challenge) -> dict[int, float]:
    """Pick points earned so far, per user."""
    totals: dict[int, float] = {}
    rows = session.execute(
        select(db.RoundPick.user_id, db.RoundPick.points)
        .join(db.PickRound, db.PickRound.id == db.RoundPick.round_id)
        .where(db.PickRound.challenge_id == challenge.id, db.RoundPick.points.is_not(None))
    )
    for user_id, points in rows:
        totals[user_id] = round(totals.get(user_id, 0.0) + points, 1)
    return totals


def round_view(session: Session, round_: db.PickRound, user_id: int, names: dict[int, str],
               now: datetime | None = None, live: bool = False) -> dict:
    """What a player sees about one round. Other players' picks stay hidden until the round locks."""
    now = now or datetime.now(timezone.utc)
    locked = now >= db.utc(round_.locks_at) or round_.status != "open"
    options = live_options(round_) if live and not locked else json.loads(round_.options)
    picks = list(session.scalars(select(db.RoundPick).where(db.RoundPick.round_id == round_.id)))
    mine = next((p for p in picks if p.user_id == user_id), None)
    labels = {o["id"]: o["label"] for o in options}
    return {
        "number": round_.number + 1,
        "title": round_.event_title,
        "theme": round_.theme,
        "theme_label": THEMES.get(round_.theme, {}).get("label", round_.theme),
        "league": round_.league,
        "market_url": MARKET_PAGE + round_.event_ticker,
        "locks_at": db.utc(round_.locks_at).isoformat(),
        "locked": locked,
        "status": round_.status,
        "winner": labels.get(round_.winning_option_id) if round_.winning_option_id else None,
        "options": [
            {"id": o["id"], "label": o["label"], "chance": round(o["chance"] * 100), "pays": pick_points(o["chance"])}
            for o in options
        ],
        "picks_made": len(picks),
        "yours": None if mine is None else {
            "option_id": mine.option_id, "pick": mine.option_label, "chance": round(mine.probability * 100),
            "pays": pick_points(mine.probability), "points": mine.points,
        },
        "everyone": [
            {"name": names.get(p.user_id, "Player"), "pick": p.option_label, "points": p.points}
            for p in picks
        ] if locked else None,
    }
