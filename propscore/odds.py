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

# Over thresholds. Keep the shape (stat -> list[float]) stable so a
# live odds feed can replace these lists per player without touching
# the ranking core.
STANDARD_LINES: dict[str, list[float]] = {
    "points": [10, 15, 20, 25],
    "rebounds": [4, 6, 8, 10],
    "assists": [2, 4, 6, 8],
    "threes": [1, 2, 3, 4],
    "pra": [15, 20, 25, 30],
}

PROP_LABELS = {
    "points": "PTS",
    "rebounds": "REB",
    "assists": "AST",
    "threes": "3PM",
    "pra": "PRA",
}


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
    return list(STANDARD_LINES.get(prop, []))


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

    Intended call (not made unless this function is filled in):

        GET https://api.the-odds-api.com/v4/sports/basketball_nba/events/{eventId}/odds
            ?apiKey=...&regions=us
            &markets=player_points,player_rebounds,player_assists,player_threes,player_points_rebounds_assists
            &oddsFormat=american

    Parse bookmaker outcomes whose description matches the player
    name and return the unique over-points for `prop`. Return None
    on any miss so the caller falls back to STANDARD_LINES.

    Left unimplemented on purpose: player-prop markets are a paid
    Odds API feature, and this project must run with free sources only.
    """
    _ = (player, prop, sport, api_key)
    return None


def all_standard_props() -> Iterable[str]:
    return STANDARD_LINES.keys()
