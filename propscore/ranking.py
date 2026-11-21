"""Shared ranking core (sport-agnostic).

Trend score formula (0-100)
---------------------------
A weighted blend of hit rates and the current hit streak, using only
games the player actually played (minutes > 0):

    score = 100 * (
        0.16 * L4 hit rate
      + 0.16 * L5 hit rate
      + 0.14 * L8 hit rate
      + 0.14 * L10 hit rate
      + 0.10 * L15 hit rate
      + 0.10 * L20 hit rate
      + 0.10 * min(game streak, 5) / 5
      + 0.10 * min(venue streak, 5) / 5   # home streak tonight if home, else away
    )

Odds and live/standard line source are never part of the score or the
sort key. Cards may still display a sportsbook price when one exists.

Hit rate in a window uses however many played games exist if the
player has fewer than 5/10/20. Venue rate falls back to the season
rate when the player has fewer than 3 games at that venue. Players
with fewer than MIN_GAMES played games, or a season minutes average
below MIN_AVG_MINUTES, are skipped.

Each player gets one line per stat (a live sportsbook number, or an
estimated line from his recent games) ranked on both the Over and the Under.
An over hits when value >= line; an under hits when value < line.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date as date_cls

from .odds import PROP_LABELS, get_offers, line_label, prop_full_label
from .sports.base import Game, GameLog, Player

MIN_GAMES = 5
MIN_AVG_MINUTES = 12.0

# Must sum to 1.0.
WEIGHTS = {
    "l4": 0.16,
    "l5": 0.16,
    "l8": 0.14,
    "l10": 0.14,
    "l15": 0.10,
    "l20": 0.10,
    "streak": 0.10,
    "venue_streak": 0.10,
}
STREAK_CAP = 5
VENUE_MIN_GAMES = 3
H2H_MIN_GAMES = 2


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
    prop_full: str
    line: float
    display_line: float
    line_label: str
    side: str  # "over" or "under"
    l5: float
    l10: float
    l20: float
    season: float
    venue_hit: float
    home_hit: float
    away_hit: float
    h2h: float
    streak: int
    home_streak: int
    away_streak: int
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
    home_hits: int
    home_games: int
    away_hits: int
    away_games: int
    h2h_hits: int
    h2h_games: int
    l5_avg: float
    l10_avg: float
    season_avg: float
    h2h_avg: float
    min_l5: float
    min_l10: float
    minutes_trend: list[float] = field(default_factory=list)
    rest_days: int | None = None
    is_b2b: bool = False
    injury_status: str | None = None
    injury_detail: str | None = None
    position: str = ""
    headshot: str = ""
    # Filled in after ranking (standings / teammate splits).
    opp_def_rank: int | None = None
    opp_def_teams: int | None = None
    opp_def_value: float | None = None
    opp_def_label: str = ""
    opp_def_stat: str = ""
    matchup_tag: str = ""
    without: list[dict] = field(default_factory=list)
    line_source: str = "standard"
    american_odds: int | None = None
    book: str = ""
    book_title: str = ""
    l4: float = 0.0
    l8: float = 0.0
    l15: float = 0.0
    l4_hits: int = 0
    l4_games: int = 0
    l8_hits: int = 0
    l8_games: int = 0
    l15_hits: int = 0
    l15_games: int = 0
    prior_games: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _played(logs: list[GameLog], before_date: str = "") -> list[GameLog]:
    # Newest first. Callers should already pass them that way, but
    # sort defensively so streak always starts at the most recent game.
    # Logs on or after the slate date are dropped so a same-day ESPN
    # date prefix (or today's finished game) does not zero out rest
    # or leak into pregame L5/L10.
    played = [g for g in logs if g.minutes and g.minutes > 0]
    if before_date:
        played = [g for g in played if (g.date or "")[:10] < before_date]
    return sorted(played, key=lambda g: (g.date, g.event_id), reverse=True)


def _is_hit(game: GameLog, stat: str, line: float, side: str) -> bool:
    value = game.value(stat)
    if side == "under":
        return value < line
    return value >= line


def _hit_rate(
    logs: list[GameLog], stat: str, line: float, side: str
) -> tuple[float, int, int]:
    if not logs:
        return 0.0, 0, 0
    hits = sum(1 for g in logs if _is_hit(g, stat, line, side))
    n = len(logs)
    return hits / n, hits, n


def _hit_streak(
    logs_newest_first: list[GameLog], stat: str, line: float, side: str
) -> int:
    streak = 0
    for g in logs_newest_first:
        if _is_hit(g, stat, line, side):
            streak += 1
        else:
            break
    return streak


def _avg(logs: list[GameLog], stat: str) -> float:
    if not logs:
        return 0.0
    return sum(g.value(stat) for g in logs) / len(logs)


def _window(logs_newest_first: list[GameLog], n: int) -> list[GameLog]:
    return logs_newest_first[:n]


def _rest(played_newest_first: list[GameLog], slate_date: str) -> tuple[int | None, bool]:
    if not played_newest_first or not slate_date:
        return None, False
    last = (played_newest_first[0].date or "")[:10]
    try:
        last_d = date_cls.fromisoformat(last)
        slate_d = date_cls.fromisoformat(slate_date)
    except ValueError:
        return None, False
    delta = (slate_d - last_d).days
    if delta < 0:
        return None, False
    # Played yesterday → 0 days of rest, back-to-back.
    rest = max(delta - 1, 0)
    return rest, delta == 1


def trend_score(
    l4: float,
    l5: float,
    l8: float,
    l10: float,
    l15: float,
    l20: float,
    streak: int,
    venue_streak: int,
) -> float:
    raw = (
        WEIGHTS["l4"] * l4
        + WEIGHTS["l5"] * l5
        + WEIGHTS["l8"] * l8
        + WEIGHTS["l10"] * l10
        + WEIGHTS["l15"] * l15
        + WEIGHTS["l20"] * l20
        + WEIGHTS["streak"] * min(streak, STREAK_CAP) / STREAK_CAP
        + WEIGHTS["venue_streak"] * min(venue_streak, STREAK_CAP) / STREAK_CAP
    )
    return round(100.0 * raw, 1)


def qualify(
    logs: list[GameLog],
    min_games: int = MIN_GAMES,
    min_avg_minutes: float = MIN_AVG_MINUTES,
    starts_only: bool = False,
    slate_date: str = "",
    min_season_games: int | None = None,
) -> tuple[list[GameLog], float] | None:
    played = _played(logs, before_date=slate_date)
    if starts_only:
        played = [g for g in played if getattr(g, "started", False)]
    current = [g for g in played if not getattr(g, "prior_season", False)]
    needed = min_season_games if min_season_games is not None else min_games
    if len(current) < needed:
        return None
    if min_season_games is None and len(played) < min_games:
        return None
    avg_min = sum(g.minutes for g in played) / len(played) if played else 0.0
    if min_avg_minutes and avg_min < min_avg_minutes:
        return None
    return played, avg_min


def rank_player_props(
    player: Player,
    logs: list[GameLog],
    game: Game,
    props: list[str],
    sport: str = "nba",
    min_games: int = MIN_GAMES,
    min_avg_minutes: float = MIN_AVG_MINUTES,
    starts_only: bool = False,
    slate_date: str = "",
    min_season_games: int | None = None,
    props_from_logs=None,
) -> list[PropRow]:
    qualified = qualify(
        logs,
        min_games=min_games,
        min_avg_minutes=min_avg_minutes,
        starts_only=starts_only,
        slate_date=slate_date,
        min_season_games=min_season_games,
    )
    if qualified is None:
        return []
    played, avg_min = qualified
    if callable(props_from_logs):
        props = props_from_logs(played) or []
        if not props:
            return []
    is_home = player.team_id == game.home_id
    opponent = game.away_abbr if is_home else game.home_abbr
    venue_flag = "H" if is_home else "A"
    venue_logs = [g for g in played if g.is_home == is_home]
    home_logs = [g for g in played if g.is_home]
    away_logs = [g for g in played if not g.is_home]
    h2h_logs = [
        g
        for g in played
        if (g.opponent_abbr or "").upper() == (opponent or "").upper()
    ]
    rest_days, is_b2b = _rest(played, slate_date)
    minutes_trend = [round(g.minutes, 1) for g in played[:10]]
    min_l5 = round(sum(g.minutes for g in played[:5]) / max(len(played[:5]), 1), 1)
    min_l10 = round(sum(g.minutes for g in played[:10]) / max(len(played[:10]), 1), 1)

    rows: list[PropRow] = []
    player_payload = {
        "name": player.name,
        "event_id": game.event_id,
        "team_abbr": player.team_abbr,
    }
    for prop in props:
        for offer in get_offers(player_payload, prop, sport=sport, logs=played):
            line = offer.line
            shown = offer.display_line
            l5_avg = round(_avg(_window(played, 5), prop), 2)
            l10_avg = round(_avg(_window(played, 10), prop), 2)
            season_avg = round(_avg(played, prop), 2)
            h2h_avg = round(_avg(h2h_logs, prop), 2) if h2h_logs else 0.0
            for side in ("over", "under"):
                price = offer.price_for(side)
                l4_r, l4_h, l4_n = _hit_rate(_window(played, 4), prop, line, side)
                l5_r, l5_h, l5_n = _hit_rate(_window(played, 5), prop, line, side)
                l8_r, l8_h, l8_n = _hit_rate(_window(played, 8), prop, line, side)
                l10_r, l10_h, l10_n = _hit_rate(_window(played, 10), prop, line, side)
                l15_r, l15_h, l15_n = _hit_rate(_window(played, 15), prop, line, side)
                l20_r, l20_h, l20_n = _hit_rate(_window(played, 20), prop, line, side)
                current = [g for g in played if not getattr(g, "prior_season", False)]
                sea_r, sea_h, sea_n = _hit_rate(current or played, prop, line, side)
                prior_n = sum(1 for g in played if getattr(g, "prior_season", False))
                if len(venue_logs) >= VENUE_MIN_GAMES:
                    ven_r, ven_h, ven_n = _hit_rate(venue_logs, prop, line, side)
                else:
                    ven_r, ven_h, ven_n = sea_r, sea_h, sea_n
                home_r, home_h, home_n = _hit_rate(home_logs, prop, line, side) if home_logs else (0.0, 0, 0)
                away_r, away_h, away_n = _hit_rate(away_logs, prop, line, side) if away_logs else (0.0, 0, 0)
                h2h_r, h2h_h, h2h_n = _hit_rate(h2h_logs, prop, line, side) if h2h_logs else (0.0, 0, 0)
                streak = _hit_streak(played, prop, line, side)
                home_streak = _hit_streak(home_logs, prop, line, side)
                away_streak = _hit_streak(away_logs, prop, line, side)
                venue_streak = home_streak if venue_flag == "H" else away_streak
                score = trend_score(l4_r, l5_r, l8_r, l10_r, l15_r, l20_r, streak, venue_streak)
                rows.append(
                    PropRow(
                        player_id=player.id,
                        player=player.name,
                        team=player.team_abbr,
                        team_name=player.team_name,
                        opponent=opponent,
                        venue=venue_flag,
                        event_id=game.event_id,
                        game=game.vs_label(),
                        game_time_et=game.start_et,
                        prop=prop,
                        prop_label=PROP_LABELS.get(prop, prop.upper()),
                        prop_full=prop_full_label(prop),
                        line=line,
                        display_line=shown,
                        line_label=line_label(prop, line, side, price=price, source=offer.source),
                        side=side,
                        l5=round(l5_r, 4),
                        l10=round(l10_r, 4),
                        l20=round(l20_r, 4),
                        l4=round(l4_r, 4),
                        l8=round(l8_r, 4),
                        l15=round(l15_r, 4),
                        l4_hits=l4_h,
                        l4_games=l4_n,
                        l8_hits=l8_h,
                        l8_games=l8_n,
                        l15_hits=l15_h,
                        l15_games=l15_n,
                        season=round(sea_r, 4),
                        venue_hit=round(ven_r, 4),
                        home_hit=round(home_r, 4),
                        away_hit=round(away_r, 4),
                        h2h=round(h2h_r, 4),
                        streak=streak,
                        home_streak=home_streak,
                        away_streak=away_streak,
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
                        home_hits=home_h,
                        home_games=home_n,
                        away_hits=away_h,
                        away_games=away_n,
                        h2h_hits=h2h_h,
                        h2h_games=h2h_n,
                        l5_avg=l5_avg,
                        l10_avg=l10_avg,
                        season_avg=season_avg,
                        h2h_avg=h2h_avg,
                        min_l5=min_l5,
                        min_l10=min_l10,
                        minutes_trend=minutes_trend,
                        rest_days=rest_days,
                        is_b2b=is_b2b,
                        injury_status=player.injury_status,
                        injury_detail=player.injury_detail,
                        position=player.position,
                        headshot=player.headshot,
                        prior_games=prior_n,
                        line_source=offer.source,
                        american_odds=price,
                        book=offer.book,
                        book_title=offer.book_title,
                    )
                )
    return rows


def rank_slate(
    players: list[Player],
    logs_by_player: dict[str, list[GameLog]],
    games: list[Game],
    props: list[str],
    sport: str = "nba",
    qualification=None,
    slate_date: str = "",
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
        opts = qualification(player) if qualification else {}
        player_props = opts.get("props") or props
        role_fn = None
        if opts.get("role_filter") and hasattr(qualification, "__self__"):
            sport_obj = qualification.__self__
            if hasattr(sport_obj, "props_for_logs"):
                role_fn = sport_obj.props_for_logs
        rows.extend(
            rank_player_props(
                player,
                logs,
                game,
                player_props,
                sport=sport,
                min_games=opts.get("min_games", MIN_GAMES),
                min_avg_minutes=opts.get("min_avg_minutes", MIN_AVG_MINUTES),
                starts_only=opts.get("starts_only", False),
                slate_date=slate_date,
                min_season_games=opts.get("min_season_games"),
                props_from_logs=role_fn,
            )
        )

    rows.sort(key=lambda r: (-r.score, -r.l10, -r.streak, r.player, r.line))
    return rows
