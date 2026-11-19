"""A challenge's ruleset: every rule that decides who gets paid, fixed before anyone pays.

The ruleset is a small JSON object written in canonical form (compact, sorted keys, ASCII; the same
form as `attest.canonical`). Its SHA-256 is the `rules_hash` stored onchain in the challenge's
`Rules` account by `create_challenge`. `join_challenge` must quote that hash, so a deposit is tied
to the rules the player saw, and the verifier's signed result names it, so the payout is too.

The ruleset itself is stored offchain (`challenges.ruleset`) and served to anyone who can see the
challenge, so anyone can re-hash it. It holds no fitness or personal data.

Flow:
    1. The browser sends the settings to POST /rules and gets back the canonical ruleset, its hash
       and the payout terms (format kind and podium split).
    2. It creates the challenge onchain with that hash, payout terms and our verifier key.
    3. POST /challenges reads the chain, rebuilds the ruleset from the same settings and the onchain
       length and player cap, and refuses the challenge unless the hashes and terms match.
"""

from __future__ import annotations

import hashlib
import json

import attest
import chain
import config
import leaguestats
import scoring

SCHEMA = "rival.ruleset.v1"
PAYOUT_KINDS = ["winner_takes_all", "podium", "goal", "teams"]  # same order as the program's PayoutKind

# Which workout states count towards points (scoring.ScoreSheet.verdict).
WORKOUTS = {"count": ["verified", "flagged"], "never_count": ["rejected"]}


class RulesError(ValueError):
    """Settings that cannot be used (the message is safe to show)."""


def scoring_rules(source: str) -> dict:
    """The scoring rules a new challenge commits to: the version in force now and its fingerprint."""
    if source == "league_stats":
        return {"source": "league_stats", "version": leaguestats.RULES_VERSION, "sha256": None}
    return {"source": "fitness", "version": scoring.RULES_VERSION, "sha256": scoring.rules_fingerprint()}


def build(
    *,
    mode: str,
    length_seconds: int,
    max_players: int,
    fmt: str,
    format_config: dict,
    scoring_source: str = "fitness",
    stat_weights: dict | None = None,
    pick_themes: list[str] | None = None,
    round_hours: int | None = None,
    verifier: str | None = None,
) -> dict:
    """The ruleset as a dict. `format_config` must already be cleaned (formats.clean_config)."""
    return {
        "schema": SCHEMA,
        "network": "solana-devnet",
        "program": str(chain.PROGRAM_ID),
        "mode": mode,
        "length_seconds": int(length_seconds),
        "max_players": int(max_players),
        "scoring": {
            **scoring_rules(scoring_source),
            "stat_weights": {**leaguestats.DEFAULT_WEIGHTS, **(stat_weights or {})}
            if scoring_source == "league_stats" else None,
        },
        "workouts": WORKOUTS,
        "consent_required": True,  # a player who never agrees to share points scores zero
        "format": {"name": fmt, **format_config},
        "payout": payout_terms(fmt, format_config),
        "prediction_rounds": {"themes": list(pick_themes), "round_hours": round_hours} if pick_themes else None,
        "verifier": verifier or config.VERIFIER_PUBLIC_KEY,
    }


def payout_terms(fmt: str, format_config: dict) -> dict:
    """What the program stores as values: the format kind and, for a podium, the split in basis points."""
    split = [p * 100 for p in format_config["shares"]] if fmt == "podium" else []
    return {"kind": fmt, "split_bps": split}


def canonical(ruleset: dict) -> str:
    return attest.canonical(ruleset)


def rules_hash(ruleset: dict) -> bytes:
    return hashlib.sha256(canonical(ruleset).encode()).digest()


def of(challenge) -> dict | None:
    """The stored ruleset of a challenge, or None for challenges created before rules were locked."""
    text = getattr(challenge, "ruleset", None)
    return json.loads(text) if text else None


def check_current(ruleset: dict) -> None:
    """Refuses to score a challenge whose committed scoring rules are not the ones this server runs.

    A challenge keeps the rules version it committed to. If the server's rules have changed since,
    settling would re-score it under rules nobody agreed to, so we stop instead.
    """
    committed = ruleset["scoring"]
    current = scoring_rules(committed["source"])
    if (committed["version"], committed["sha256"]) != (current["version"], current["sha256"]):
        raise RulesError(
            f"This challenge locked scoring rules {committed['version']}, but this server now runs "
            f"{current['version']}. It will not be re-scored under different rules. Run a server with "
            f"{committed['version']} to settle it, or let it refund 72 hours after the end."
        )


def kind_index(fmt: str) -> int:
    return PAYOUT_KINDS.index(fmt)


def describe_payout(terms: dict) -> str:
    """'60 / 30 / 10' for a podium; a short phrase otherwise."""
    if terms["kind"] == "podium":
        return " / ".join(str(s // 100) for s in terms["split_bps"])
    return {"winner_takes_all": "winner takes all", "goal": "equal split among everyone who reaches the goal",
            "teams": "equal split across the winning team"}[terms["kind"]]

