"""Pick'em tiebreaker, powered by Gemini Prediction Markets.

Before a challenge starts, each player may make one free pick: who wins an upcoming game. The games
and their odds come live from Gemini's public market data (no account or key needed). If the fitness
contest ends in a tie, a tied player whose pick was right wins instead of splitting the pool. Gemini's
settlement of the market tells us which side was right.

Only public market data flows in. Nothing about our users or their fitness data is sent to Gemini.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

import db

log = logging.getLogger("loser_buys")
EVENTS_URL = "https://api.gemini.com/v1/prediction-markets/events"
CACHE_SECONDS = 60  # Gemini allows 120 public requests a minute; we make about one
MAX_GAMES = 12
LOOK_AHEAD = timedelta(days=7)
_cache: dict = {"at": 0.0, "games": []}


def fetch(path: str = "", params: dict | None = None):
    """One GET to Gemini's public prediction-markets API."""
    response = httpx.get(EVENTS_URL + path, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def _time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _chance(contract: dict) -> int | None:
    """The market's current chance of this side winning, as a percentage (a price of 0.62 means 62%)."""
    prices = contract.get("prices") or {}
    try:
        if prices.get("bestBid") and prices.get("bestAsk"):
            price = (float(prices["bestBid"]) + float(prices["bestAsk"])) / 2
        else:
            price = float(prices["lastTradePrice"])
    except (KeyError, TypeError, ValueError):
        return None
    return max(1, min(99, round(price * 100)))


def _game(event: dict) -> dict | None:
    """A Gemini event as a simple two-sided game, or None if it is not one."""
    contracts = event.get("contracts") or []
    starts = _time(event.get("startTime"))
    if len(contracts) != 2 or starts is None or not event.get("ticker"):
        return None
    return {
        "ticker": event["ticker"],
        "title": event.get("title") or "",
        "league": (event.get("subcategory") or {}).get("name") or "Sports",
        "starts": starts.isoformat(),
        "options": [{"id": c["id"], "label": c.get("label") or "", "chance": _chance(c)} for c in contracts],
    }


def list_games() -> list[dict]:
    """Upcoming two-sided sports games with live odds, soonest first. Cached for a minute."""
    if time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["games"]
    now = datetime.now(timezone.utc)
    events = fetch(params={"status": "active", "category": "Sports", "limit": 100}).get("data", [])
    games = [g for g in map(_game, events) if g and now < _time(g["starts"]) < now + LOOK_AHEAD]
    games.sort(key=lambda g: g["starts"])
    _cache.update(at=time.time(), games=games[:MAX_GAMES])
    return _cache["games"]


def winning_option(ticker: str) -> str | None:
    """The ID of the side Gemini settled as the winner, or None while the market is unsettled."""
    event = fetch("/" + ticker)
    for contract in event.get("contracts") or []:
        if contract.get("resolutionSide") == "yes":
            return contract["id"]
    return None


def save_pick(session: Session, challenge: db.Challenge, user_id: int, ticker: str, option_id: str) -> db.Pick:
    """Stores (or replaces) a player's pick. Raises ValueError if the game or side is not on offer."""
    game = next((g for g in list_games() if g["ticker"] == ticker), None)
    option = next((o for o in game["options"] if o["id"] == option_id), None) if game else None
    if option is None:
        raise ValueError("That game is no longer open for picks.")
    pick = session.scalar(
        select(db.Pick).where(db.Pick.challenge_id == challenge.id, db.Pick.user_id == user_id)
    ) or db.Pick(challenge_id=challenge.id, user_id=user_id)
    pick.event_ticker, pick.event_title = ticker, game["title"]
    pick.option_id, pick.option_label, pick.chance = option_id, option["label"], option["chance"]
    session.add(pick)
    session.commit()
    return pick


def picks_of(session: Session, challenge: db.Challenge) -> dict[int, db.Pick]:
    """{user ID: pick} for one challenge."""
    return {p.user_id: p for p in session.scalars(select(db.Pick).where(db.Pick.challenge_id == challenge.id))}


def pick_view(pick: db.Pick | None) -> dict | None:
    if pick is None:
        return None
    return {"ticker": pick.event_ticker, "game": pick.event_title, "option_id": pick.option_id,
            "pick": pick.option_label, "chance": pick.chance}


def break_tie(session: Session, challenge: db.Challenge, tied: list[str]) -> tuple[list[str], dict | None]:
    """Narrows tied winners to those whose pick was right.

    Returns (winners, record for the score sheet). The tie stands (everyone splits) when nobody
    picked, when no tied player was right, when all of them were, or when the games are unsettled.
    """
    if len(tied) < 2:
        return tied, None
    wallets = {u.id: u.wallet_address for u in session.scalars(select(db.User).where(db.User.wallet_address.in_(tied)))}
    picks = {wallets[user_id]: p for user_id, p in picks_of(session, challenge).items() if user_id in wallets}
    if not picks:
        return tied, None
    results, outcomes = {}, {}
    for wallet in tied:
        pick = picks.get(wallet)
        if pick is None:
            continue
        if pick.event_ticker not in outcomes:
            try:
                outcomes[pick.event_ticker] = winning_option(pick.event_ticker)
            except Exception:
                log.exception("Could not read the result of %s from Gemini", pick.event_ticker)
                outcomes[pick.event_ticker] = None
        winner = outcomes[pick.event_ticker]
        results[wallet] = None if winner is None else winner == pick.option_id
    right = [wallet for wallet in tied if results.get(wallet) is True]
    decided = 0 < len(right) < len(tied)
    record = {
        "source": "Gemini Prediction Markets",
        "decided": decided,
        "picks": [
            {"wallet": w, "game": picks[w].event_title, "pick": picks[w].option_label, "correct": results[w]}
            for w in tied if w in picks
        ],
    }
    return (right if decided else tied), record
