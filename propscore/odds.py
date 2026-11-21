"""Prop line source.

Default: standard over-thresholds per stat (no odds key required).

To drop in live sportsbook lines later, set ODDS_API_KEY to a
The Odds API key (https://the-odds-api.com). `_fetch_odds_api_lines`
is the hook — it is a best-effort stub today and always falls back
to the standard thresholds if the key is missing, the plan doesn't
include player props, or the request fails.
"""

from __future__ import annotations

import os
from typing import Iterable

# Over thresholds, keyed by sport then stat. A live odds feed can
# replace these lists per player without touching the ranking core.
LINES_BY_SPORT: dict[str, dict[str, list[float]]] = {
    "nba": {
        "points": [10, 15, 20, 25],
        "rebounds": [4, 6, 8, 10],
        "assists": [2, 4, 6, 8],
        "threes": [1, 2, 3, 4],
        "pra": [15, 20, 25, 30],
    },
    "nhl": {
        "goals": [0.5, 1.5],
        "assists": [0.5, 1.5],
        "points": [0.5, 1.5, 2.5],
        "shots": [1.5, 2.5, 3.5, 4.5],
        "saves": [20.5, 25.5, 30.5],
    },
}

# Backward-compatible alias (NBA defaults).
STANDARD_LINES = LINES_BY_SPORT["nba"]

PROP_LABELS = {
    "points": "PTS",
    "rebounds": "REB",
    "assists": "AST",
    "threes": "3PM",
    "pra": "PRA",
    "goals": "G",
    "shots": "SOG",
    "saves": "SV",
    "blocked": "BLK",
    "hits": "HIT",
}


def lines_for_sport(sport: str) -> dict[str, list[float]]:
    return LINES_BY_SPORT.get(sport, LINES_BY_SPORT["nba"])


def props_for_sport(sport: str) -> list[dict[str, str]]:
    table = lines_for_sport(sport)
    return [{"key": key, "label": PROP_LABELS.get(key, key.upper())} for key in table]


def lowest_line(prop: str, sport: str = "nba") -> float | None:
    lines = lines_for_sport(sport).get(prop)
    return min(lines) if lines else None


def get_lines(player: dict, prop: str, sport: str = "nba") -> list[float]:
    """Return over-lines for this player and prop.

    `player` may include event_id, name, and team so a live odds
    lookup can match a sportsbook market later.
    """
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if key:
        live = _fetch_odds_api_lines(player, prop, sport, key)
        if live:
            return live
    return list(lines_for_sport(sport).get(prop, []))


def line_label(prop: str, line: float) -> str:
    short = PROP_LABELS.get(prop, prop.upper())
    number = int(line) if float(line).is_integer() else line
    return f"{short} {number}+"


def _fetch_odds_api_lines(
    player: dict,
    prop: str,
    sport: str,
    api_key: str,
) -> list[float] | None:
    """Stub for The Odds API player-prop markets.

    Left unimplemented on purpose: player-prop markets are a paid
    Odds API feature, and this project must run with free sources only.
    """
    _ = (player, prop, sport, api_key)
    return None


def all_standard_props(sport: str = "nba") -> Iterable[str]:
    return lines_for_sport(sport).keys()
