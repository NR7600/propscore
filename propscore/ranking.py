"""Shared ranking core (sport-agnostic).

Trend score formula (0-100)
---------------------------
A weighted blend of hit rates and the current hit streak, using only
games the player actually played (minutes > 0):

    score = 100 * (
        0.30 * L5 hit rate
      + 0.25 * L10 hit rate
      + 0.15 * L20 hit rate
      + 0.10 * season hit rate
      + 0.10 * venue hit rate      # home or away, matching tonight
      + 0.10 * min(hit streak, 5) / 5
    )

Hit rate in a window uses however many played games exist if the
player has fewer than 5/10/20. Venue rate falls back to the season
rate when the player has fewer than 3 games at that venue. Players
with fewer than MIN_GAMES played games, or a season minutes average
below MIN_AVG_MINUTES, are skipped.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .odds import PROP_LABELS, get_lines, line_label
from .sports.base import Game, GameLog, Player

MIN_GAMES = 5
MIN_AVG_MINUTES = 12.0

# Must sum to 1.0.
WEIGHTS = {
    "l5": 0.30,
    "l10": 0.25,
    "l20": 0.15,
    "season": 0.10,
    "venue": 0.10,
    "streak": 0.10,
}
STREAK_CAP = 5
VENUE_MIN_GAMES = 3


@dataclass
class PropRow:
    player_id: str
    player: str
    team: str
    team_name: str
    opponent: str
    venue: str  # "H" or "A"
    event_id: str
    game: str
    game_time_et: str
    prop: str
    prop_label: str
    line: float
    line_label: str
    l5: float
    l10: float
    l20: float
    season: float
    venue_hit: float
    streak: int
    score: float
    games_played: int
    avg_minutes: float
    l5_hits: int
    l5_games: int
    l10_hits: int
    l10_games: int
    l20_hits: int
    l20_games: int
    season_hits: int
    season_games: int
    venue_hits: int
    venue_games: int
    injury_status: str | None = None
    injury_detail: str | None = None
    position: str = ""
    headshot: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _played(logs: list[GameLog]) -> list[GameLog]:
    # Newest first. Callers should already pass them that way, but
    # sort defensively so streak always starts at the most recent game.
    played = [g for g in logs if g.minutes and g.minutes > 0]
    return sorted(played, key=lambda g: (g.date, g.event_id), reverse=True)


def _hit_rate(logs: list[GameLog], stat: str, line: float) -> tuple[float, int, int]:
    if not logs:
        return 0.0, 0, 0
    hits = sum(1 for g in logs if g.value(stat) >= line)
    n = len(logs)
    return hits / n, hits, n


def _hit_streak(logs_newest_first: list[GameLog], stat: str, line: float) -> int:
    streak = 0
    for g in logs_newest_first:
        if g.value(stat) >= line:
            streak += 1
        else:
            break
    return streak


def _window(logs_newest_first: list[GameLog], n: int) -> list[GameLog]:
    return logs_newest_first[:n]


def trend_score(
    l5: float,
    l10: float,
    l20: float,
    season: float,
    venue: float,
    streak: int,
) -> float:
    raw = (
        WEIGHTS["l5"] * l5
        + WEIGHTS["l10"] * l10
        + WEIGHTS["l20"] * l20
        + WEIGHTS["season"] * season
        + WEIGHTS["venue"] * venue
        + WEIGHTS["streak"] * min(streak, STREAK_CAP) / STREAK_CAP
    )
    return round(100.0 * raw, 1)


def qualify(logs: list[GameLog]) -> tuple[list[GameLog], float] | None:
    played = _played(logs)
    if len(played) < MIN_GAMES:
        return None
    avg_min = sum(g.minutes for g in played) / len(played)
    if avg_min < MIN_AVG_MINUTES:
        return None
    return played, avg_min


def rank_player_props(
    player: Player,
    logs: list[GameLog],
    game: Game,
    props: list[str],
    sport: str = "nba",
) -> list[PropRow]:
    qualified = qualify(logs)
    if qualified is None:
        return []
    played, avg_min = qualified
    is_home = player.team_id == game.home_id
    venue_logs = [g for g in played if g.is_home == is_home]
    opponent = game.away_abbr if is_home else game.home_abbr
    venue_flag = "H" if is_home else "A"

    rows: list[PropRow] = []
    player_payload = {
        "name": player.name,
        "event_id": game.event_id,
        "team_abbr": player.team_abbr,
    }
    for prop in props:
        for line in get_lines(player_payload, prop, sport=sport):
            l5_r, l5_h, l5_n = _hit_rate(_window(played, 5), prop, line)
            l10_r, l10_h, l10_n = _hit_rate(_window(played, 10), prop, line)
            l20_r, l20_h, l20_n = _hit_rate(_window(played, 20), prop, line)
            sea_r, sea_h, sea_n = _hit_rate(played, prop, line)
            if len(venue_logs) >= VENUE_MIN_GAMES:
                ven_r, ven_h, ven_n = _hit_rate(venue_logs, prop, line)
            else:
                ven_r, ven_h, ven_n = sea_r, sea_h, sea_n
            streak = _hit_streak(played, prop, line)
            score = trend_score(l5_r, l10_r, l20_r, sea_r, ven_r, streak)
            rows.append(
                PropRow(
                    player_id=player.id,
                    player=player.name,
                    team=player.team_abbr,
                    team_name=player.team_name,
                    opponent=opponent,
                    venue=venue_flag,
                    event_id=game.event_id,
                    game=game.label(),
                    game_time_et=game.start_et,
                    prop=prop,
                    prop_label=PROP_LABELS.get(prop, prop.upper()),
                    line=line,
                    line_label=line_label(prop, line),
                    l5=round(l5_r, 4),
                    l10=round(l10_r, 4),
                    l20=round(l20_r, 4),
                    season=round(sea_r, 4),
                    venue_hit=round(ven_r, 4),
                    streak=streak,
                    score=score,
                    games_played=len(played),
                    avg_minutes=round(avg_min, 1),
                    l5_hits=l5_h,
                    l5_games=l5_n,
                    l10_hits=l10_h,
                    l10_games=l10_n,
                    l20_hits=l20_h,
                    l20_games=l20_n,
                    season_hits=sea_h,
                    season_games=sea_n,
                    venue_hits=ven_h,
                    venue_games=ven_n,
                    injury_status=player.injury_status,
                    injury_detail=player.injury_detail,
                    position=player.position,
                    headshot=player.headshot,
                )
            )
    return rows


def rank_slate(
    players: list[Player],
    logs_by_player: dict[str, list[GameLog]],
    games: list[Game],
    props: list[str],
    sport: str = "nba",
) -> list[PropRow]:
    game_by_team = {}
    for g in games:
        game_by_team[g.home_id] = g
        game_by_team[g.away_id] = g

    rows: list[PropRow] = []
    for player in players:
        game = game_by_team.get(player.team_id)
        if not game:
            continue
        logs = logs_by_player.get(player.id) or []
        rows.extend(rank_player_props(player, logs, game, props, sport=sport))

    rows.sort(key=lambda r: (-r.score, -r.l10, -r.streak, r.player, r.line))
    return rows
