"""Opponent points/goals-allowed ranks from ESPN public standings (no key)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("propscore")

STANDINGS_URL = {
    "nba": "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings",
    "nhl": "https://site.api.espn.com/apis/v2/sports/hockey/nhl/standings",
    "nfl": "https://site.api.espn.com/apis/v2/sports/football/nfl/standings",
}

# Rank 1 = fewest points/goals allowed (toughest over matchup).
OUT_STAT = {
    "nba": ("avgPointsAgainst", "PPG allowed"),
    "nhl": ("pointsAgainst", "goals allowed"),
    "nfl": ("avgPointsAgainst", "PPG allowed"),
}


def _stat_map(entry: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for item in entry.get("stats") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        if item.get("value") is not None:
            out[name] = item.get("value")
        elif item.get("displayValue") is not None:
            out[name] = item.get("displayValue")
    return out


def _walk_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "team" in node and "stats" in node:
                found.append(node)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def fetch_defense_ranks(sport: str, client) -> dict[str, dict[str, Any]]:
    """Map team abbreviation -> {rank, teams, value, label, stat}.

    Rank 1 allows the fewest points (NBA) or goals (NHL). For NHL we
    divide goals against by games played when GP is present so teams
    with extra games are not punished.
    """
    key = (sport or "").lower()
    url = STANDINGS_URL.get(key)
    if not url:
        return {}
    try:
        data = client.get_json(url, cache_key=f"{key}_standings")
    except Exception as exc:
        log.warning("standings fetch failed for %s: %s", key, exc)
        return {}

    rows = []
    for entry in _walk_entries(data):
        team = entry.get("team") or {}
        abbr = (team.get("abbreviation") or "").upper()
        if not abbr:
            continue
        stats = _stat_map(entry)
        if key in {"nba", "nfl"}:
            value = stats.get("avgPointsAgainst")
            stat_label = "PPG allowed"
        else:
            ga = stats.get("pointsAgainst")
            gp = stats.get("gamesPlayed") or 0
            try:
                ga_f = float(ga)
                gp_f = float(gp)
                value = (ga_f / gp_f) if gp_f else ga_f
            except (TypeError, ValueError):
                value = ga
            stat_label = "GA/G"
        try:
            value_f = float(value)
        except (TypeError, ValueError):
            continue
        rows.append((abbr, value_f, stat_label, team.get("displayName") or abbr))

    # Unique by abbreviation (conferences can repeat a team).
    uniq: dict[str, tuple] = {}
    for abbr, value, stat_label, name in rows:
        uniq[abbr] = (value, stat_label, name)
    ranked = sorted(uniq.items(), key=lambda kv: kv[1][0])
    teams = len(ranked)
    out: dict[str, dict[str, Any]] = {}
    for i, (abbr, (value, stat_label, name)) in enumerate(ranked, start=1):
        out[abbr] = {
            "rank": i,
            "teams": teams,
            "value": round(value, 1),
            "stat": stat_label,
            "label": f"{abbr} allows {value:.1f} {stat_label} ({_ordinal(i)} of {teams})",
        }
    return out


def _ordinal(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def matchup_tag(rank: int | None, teams: int | None, side: str) -> str:
    """Coarse tag from team points/goals allowed. Not defense-vs-position."""
    if not rank or not teams or teams < 3:
        return ""
    # Lower rank = stingier defense = tougher for overs, better for unders.
    third = max(teams // 3, 1)
    if rank <= third:
        over_tag, under_tag = "Tough", "Favorable"
    elif rank > teams - third:
        over_tag, under_tag = "Favorable", "Tough"
    else:
        return "Neutral"
    return under_tag if side == "under" else over_tag
