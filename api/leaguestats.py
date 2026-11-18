"""League stats scoring: points come from the league's stat sheet, which the organizer uploads as CSV.

The app does not read PDFs and never calls an AI service. The upload screen offers a CSV template to
fill in by hand, and a copy-paste prompt the organizer can use in Grok themselves to turn a PDF stat
sheet into the same CSV.

Rows are matched to players by name: automatically when a player's display name matches a sheet
name, and otherwise by the organizer on a matching screen. Uploading a game date again replaces that
date's rows. Stats never go onchain; only the score sheet's hash does, and the sheet records a hash of
the stats used, so players can check the organizer did not change them afterwards.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import unicodedata
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import db
import pickrounds

RULES_VERSION = "league-stats-v1"  # named in the score sheet; the weights themselves are hashed there
COLUMNS = ["game_date", "player_name", "jersey_number", "team", "goals", "assists", "points"]
TEMPLATE = (
    ",".join(COLUMNS) + "\n"
    "2026-11-21,Maya Chen,12,Blue Lines,2,1,3\n"
    "2026-11-21,Sam Ortiz,7,Blue Lines,0,2,2\n"
)
GROK_URL = "https://grok.com"
GROK_PROMPT = (
    "Convert the attached league stat sheet into CSV with exactly this header: "
    "game_date,player_name,jersey_number,team,goals,assists,points. "
    "One row per player per game. Dates as YYYY-MM-DD. Use 0 for a stat the sheet shows as blank or a dash; "
    "leave points empty if the sheet has no points column. Do not invent players or numbers. "
    "Output only the CSV, in one code block, with no commentary."
)
DEFAULT_WEIGHTS = {"goals": 2, "assists": 1, "points": 0}
MAX_ROWS = 2000
MAX_STAT = 99  # no player scores more than this in one game


class BadSheet(ValueError):
    """The CSV can't be used (the message says why and is safe to show)."""


def normalize(name: str) -> str:
    """Name for matching: no accents, lower case, single spaces."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(plain.lower().replace(".", " ").split())


def _count(value: str, column: str, line: int, blank_ok: bool = False) -> int | None:
    value = (value or "").strip()
    if value in ("", "-", "–"):
        return None if blank_ok else 0
    try:
        number = int(float(value))
    except ValueError as e:
        raise BadSheet(f"Line {line}: {column} must be a number, not \"{value}\".") from e
    if not 0 <= number <= MAX_STAT:
        raise BadSheet(f"Line {line}: {column} of {number} doesn't look right.")
    return number


def parse(text: str) -> list[dict]:
    """The CSV as clean rows. Raises BadSheet with a line number when something is off."""
    text = text.strip().lstrip("﻿")
    if text.startswith("```"):  # pasted straight from a chat answer
        text = "\n".join(line for line in text.splitlines() if not line.startswith("```"))
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in reader.fieldnames or []]
    missing = [c for c in ("game_date", "player_name") if c not in header]
    if missing:
        raise BadSheet(f"The first line must be the header: {','.join(COLUMNS)}")
    reader.fieldnames = header
    rows = []
    for line, raw in enumerate(reader, start=2):
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue
        name = " ".join((raw.get("player_name") or "").split())
        if not name:
            raise BadSheet(f"Line {line}: player_name is empty.")
        try:
            day = date.fromisoformat((raw.get("game_date") or "").strip())
        except ValueError as e:
            raise BadSheet(f"Line {line}: game_date must look like 2026-11-21.") from e
        rows.append({
            "game_date": day.isoformat(),
            "player_name": name[:60],
            "jersey_number": (raw.get("jersey_number") or "").strip()[:10] or None,
            "team": (raw.get("team") or "").strip()[:60] or None,
            "goals": _count(raw.get("goals"), "goals", line),
            "assists": _count(raw.get("assists"), "assists", line),
            "points": _count(raw.get("points"), "points", line, blank_ok=True),
        })
        if len(rows) > MAX_ROWS:
            raise BadSheet(f"That's more than {MAX_ROWS} rows. Upload one week at a time.")
    if not rows:
        raise BadSheet("The file has a header but no rows.")
    return rows


def weights(challenge: db.Challenge) -> dict[str, float]:
    return {**DEFAULT_WEIGHTS, **json.loads(challenge.stat_weights or "{}")}


def row_points(row: db.LeagueStat, w: dict[str, float]) -> float:
    return row.goals * w["goals"] + row.assists * w["assists"] + (row.points or 0) * w["points"]


def challenge_dates(challenge: db.Challenge) -> tuple[str, str]:
    """First and last game dates that count, in North American Central time."""
    first = db.utc(challenge.start_time).astimezone(pickrounds.CENTRAL).date()
    last = db.utc(challenge.end_time).astimezone(pickrounds.CENTRAL).date()
    return first.isoformat(), last.isoformat()


def players(session: Session, challenge: db.Challenge) -> list[tuple[db.User, db.Participant]]:
    return list(session.execute(
        select(db.User, db.Participant)
        .join(db.Participant, db.Participant.user_id == db.User.id)
        .where(db.Participant.challenge_id == challenge.id)
    ).tuples())


def auto_match(session: Session, challenge: db.Challenge, display_name) -> None:
    """Links players to sheet names that match their display name, unless the organizer already chose."""
    names = {normalize(n): n for n in session.scalars(
        select(db.LeagueStat.player_name).where(db.LeagueStat.challenge_id == challenge.id).distinct()
    )}
    taken = {normalize(p.stat_name) for _u, p in players(session, challenge) if p.stat_name}
    for user, participant in players(session, challenge):
        key = normalize(display_name(user))
        if participant.stat_name is None and key in names and key not in taken:
            participant.stat_name = names[key]
            taken.add(key)
    session.commit()


def upload(session: Session, challenge: db.Challenge, text: str, display_name) -> dict:
    """Stores the sheet's rows (replacing any earlier rows for the same game dates) and matches names."""
    rows = parse(text)
    first, last = challenge_dates(challenge)
    kept = [r for r in rows if first <= r["game_date"] <= last]
    skipped = len(rows) - len(kept)
    if not kept:
        raise BadSheet(f"No rows are dated inside this event ({first} to {last}).")
    dates = sorted({r["game_date"] for r in kept})
    session.execute(delete(db.LeagueStat).where(
        db.LeagueStat.challenge_id == challenge.id, db.LeagueStat.game_date.in_(dates)
    ))
    session.add_all(db.LeagueStat(challenge_id=challenge.id, **r) for r in kept)
    session.commit()
    auto_match(session, challenge, display_name)
    return {"rows": len(kept), "dates": dates, "skipped_outside_dates": skipped}


def match(session: Session, challenge: db.Challenge, choices: dict[int, str | None]) -> None:
    """The organizer's matching: {user ID: sheet name, or None to unlink}. One sheet name per player."""
    names = {normalize(n): n for n in session.scalars(
        select(db.LeagueStat.player_name).where(db.LeagueStat.challenge_id == challenge.id).distinct()
    )}
    picked = [normalize(n) for n in choices.values() if n]
    if len(picked) != len(set(picked)):
        raise BadSheet("Each name on the sheet can belong to one player only.")
    by_user = {u.id: p for u, p in players(session, challenge)}
    for user_id, name in choices.items():
        if user_id not in by_user:
            raise BadSheet("That person isn't a player in this event.")
        if name and normalize(name) not in names:
            raise BadSheet(f"\"{name}\" isn't on the uploaded sheet.")
        by_user[user_id].stat_name = names[normalize(name)] if name else None
    taken = {normalize(p.stat_name): uid for uid, p in by_user.items() if p.stat_name}
    if len(taken) != sum(1 for p in by_user.values() if p.stat_name):
        session.rollback()
        raise BadSheet("Each name on the sheet can belong to one player only.")
    session.commit()


def points_by_user(session: Session, challenge: db.Challenge) -> dict[int, float]:
    """Stat points per user, from the rows matched to them."""
    w = weights(challenge)
    by_name: dict[str, float] = {}
    for row in session.scalars(select(db.LeagueStat).where(db.LeagueStat.challenge_id == challenge.id)):
        key = normalize(row.player_name)
        by_name[key] = by_name.get(key, 0) + row_points(row, w)
    return {
        p.user_id: round(by_name.get(normalize(p.stat_name), 0), 1)
        for _u, p in players(session, challenge) if p.stat_name
    }


def stats_hash(session: Session, challenge: db.Challenge) -> str:
    """SHA-256 of every stored row, in a fixed order. Goes into the score sheet."""
    rows = sorted(
        (r.game_date, r.player_name, r.jersey_number or "", r.team or "", r.goals, r.assists, r.points)
        for r in session.scalars(select(db.LeagueStat).where(db.LeagueStat.challenge_id == challenge.id))
    )
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def summary(session: Session, challenge: db.Challenge, display_name) -> dict:
    """What the organizer sees: the sheet names, who is matched to whom, and dates uploaded."""
    rows = list(session.scalars(select(db.LeagueStat).where(db.LeagueStat.challenge_id == challenge.id)))
    names = sorted({r.player_name for r in rows}, key=str.lower)
    w = weights(challenge)
    return {
        "dates": sorted({r.game_date for r in rows}),
        "rows": len(rows),
        "sheet_names": names,
        "weights": w,
        "players": [
            {"user_id": u.id, "name": display_name(u), "stat_name": p.stat_name}
            for u, p in players(session, challenge)
        ],
        "unmatched": [n for n in names if normalize(n) not in {
            normalize(p.stat_name) for _u, p in players(session, challenge) if p.stat_name
        }],
        "grok_url": GROK_URL,
        "grok_prompt": GROK_PROMPT,
        "first_date": challenge_dates(challenge)[0],
        "last_date": challenge_dates(challenge)[1],
    }
