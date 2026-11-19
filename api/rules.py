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

Command line (from api/), used by `scripts/wsl_anchor.sh create-challenge`:
    python rules.py default <length in hours>    the default public ruleset, as POST /rules returns it
"""

from __future__ import annotations

import hashlib
import json
import sys

import attest
import chain
import config
import leaguestats
import scoring
import sweat

SCHEMA = "rival.ruleset.v1"
PAYOUT_KINDS = ["winner_takes_all", "podium", "goal", "teams"]  # same order as the program's PayoutKind

# Which workout states count towards points (scoring.ScoreSheet.verdict).
WORKOUTS = {"count": ["verified", "flagged"], "never_count": ["rejected"]}


class RulesError(ValueError):
    """Settings that cannot be used (the message is safe to show)."""


def fitness_template() -> str:
    """Which fitness rules a challenge created now uses (config.NEW_CHALLENGE_RULES). main._register
    stores the same choice on challenges.template, so the locked ruleset and the scoring always agree."""
    return sweat.TEMPLATE if config.NEW_CHALLENGE_RULES == sweat.TEMPLATE else sweat.LEGACY_TEMPLATE


def scoring_rules(source: str, name: str | None = None) -> dict:
    """The scoring rules a challenge commits to: their name, version in force and fingerprint.

    Fitness rules are Proof of Sweat (Oura-verified workouts only) or the earlier Daily Mover rules.
    `name` picks one; by default, the one new challenges use now.
    """
    if source == "league_stats":
        return {"source": "league_stats", "version": leaguestats.RULES_VERSION, "sha256": None}
    if (name or fitness_template()) == sweat.TEMPLATE:
        return {"source": "fitness", "name": sweat.TEMPLATE, "version": sweat.RULES_VERSION,
                "sha256": sweat.rules_fingerprint()}
    return {"source": "fitness", "name": sweat.LEGACY_TEMPLATE, "version": scoring.RULES_VERSION,
            "sha256": scoring.rules_fingerprint()}


def workouts_policy(scoring_rules_: dict) -> dict:
    """Which workout results count. Proof of Sweat counts only workouts synced from Oura that passed its checks."""
    if scoring_rules_.get("name") == sweat.TEMPLATE:
        return {"count": ["verified"], "never_count": ["rejected", "pending", "entered_in_app"]}
    return WORKOUTS


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
    scored = scoring_rules(scoring_source)
    return {
        "schema": SCHEMA,
        "network": "solana-devnet",
        "program": str(chain.PROGRAM_ID),
        "mode": mode,
        "length_seconds": int(length_seconds),
        "max_players": int(max_players),
        "scoring": {
            **scored,
            "stat_weights": {**leaguestats.DEFAULT_WEIGHTS, **(stat_weights or {})}
            if scoring_source == "league_stats" else None,
        },
        "workouts": workouts_policy(scored),
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
    # Rulesets locked before Proof of Sweat existed have no name: they are Daily Mover rules.
    current = scoring_rules(committed["source"], committed.get("name") or sweat.LEGACY_TEMPLATE)
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



def preview(ruleset: dict) -> dict:
    """What POST /rules returns for a ruleset."""
    terms = ruleset["payout"]
    return {"ruleset": canonical(ruleset), "rules_hash": rules_hash(ruleset).hex(),
            "payout": {**terms, "kind_index": kind_index(terms["kind"])}, "verifier": ruleset["verifier"]}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "default":
        sys.exit(__doc__)
    length = round(float(sys.argv[2]) * 3600)
    print(json.dumps(preview(build(mode="public", length_seconds=length, max_players=8,
                                   fmt="winner_takes_all", format_config={}))))
