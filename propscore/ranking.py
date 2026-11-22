"""Shared ranking core (sport-agnostic).

Strong-trend score
------------------
Lists are capped at ranks 1-10. Cards pick up to six windows from
L4 / L5 / L6 / L8 / L9 / L10 / L12 / L15 / L20, sorted by hit rate
descending (truncated samples are shown once), plus a game streak and
a home/away streak line — or "No streaks".

The score rewards (1) how many full windows are perfect, (2) hit
quality across all nine windows, and (3) current game and venue
streaks, with a long home/away streak able to outrank a short 4/4 or
5/5. Among cards that are 100% in every short window, the longer
current game streak still wins (14x, then 13x, then 11x…).

Trivial Under 0.5 gimmes on rare events (goals, TDs, first-score
props, interceptions, or a season average of 0.75 or less) score 0.
Meaningful unders and 0.5 overs stay in the ranking. Odds are not
part of the regular-stat score; first-score lists sort by live
American odds when a real price exists.

Hit rate in a window uses however many played games exist if the
player has fewer than the window size. Venue rate falls back to the
season rate when the player has fewer than 3 games at that venue.
Players with fewer than MIN_GAMES played games, or a season minutes
average below MIN_AVG_MINUTES, are skipped.

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

# Legacy blend kept for backtests / comparisons only. Live ranking uses
# strong_trend_score() below. Weights still sum to 1.0.
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
STREAK_CAP = 20
ALL_WINDOWS = (4, 5, 6, 8, 9, 10, 12, 15, 20)
PERFECT_WINDOWS = ALL_WINDOWS
SHORT_WINDOWS = (4, 5, 6, 8, 9, 10)
# Under 0.5 on these is a "never does this" gimme, not a strong trend.
SPARSE_UNDER_PROPS = {
    "goals",
    "anytime_td",
    "first_td",
    "first_goal",
    "first_basket",
    "pass_td",
    "rush_td",
    "rec_td",
    "ints",
}
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
    l6: float = 0.0
    l8: float = 0.0
    l9: float = 0.0
    l15: float = 0.0
    l4_hits: int = 0
    l4_games: int = 0
    l6_hits: int = 0
    l6_games: int = 0
    l8_hits: int = 0
    l8_games: int = 0
    l9_hits: int = 0
    l9_games: int = 0
    l15_hits: int = 0
    l15_games: int = 0
    prior_games: int = 0
    n_perfect: int = 0
    longest_perfect: int = 0
    best_streak: int = 0
    trivial_gimme: bool = False
    l12: float = 0.0
    l12_hits: int = 0
    l12_games: int = 0
    windows: list[dict] = field(default_factory=list)

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


# Under 0.5 on these is a "never does this" gimme unless a sportsbook
# actually posted the number (Zion Under 0.5 threes at -805).
GIMME_HALF_PROPS = {
    "threes",
    "steals",
    "blocks",
    "turnovers",
    "stl_blk",
}

def is_trivial_under(
    prop: str,
    line: float,
    side: str,
    season_avg: float | None = None,
    line_source: str = "",
) -> bool:
    """True for easy unders that are not a real market trend."""
    if (side or "").lower() != "under":
        return False
    try:
        line_f = float(line)
    except (TypeError, ValueError):
        return False
    live = (line_source or "") == "live"
    # Book-posted lines can still be long-shot unders (Zion 53x away).
    if not live and line_f <= 0.5 + 1e-9:
        if (prop or "") in SPARSE_UNDER_PROPS or (prop or "") in GIMME_HALF_PROPS:
            return True
    if (prop or "") in SPARSE_UNDER_PROPS and line_f <= 0.5 + 1e-9 and not live:
        return True
    # Estimated unders far above what the player actually posts
    # (e.g. Under 1.5 points for a 0.4-point skater). Tight book-style
    # lines such as Under 2.5 passing TDs or Under 0.5 assists stay.
    if (
        not live
        and season_avg is not None
        and line_f >= 1.0
        and float(season_avg) < 0.4 * line_f
    ):
        return True
    return False


def perfect_window_stats(windows: dict[int, tuple[int, int]]) -> tuple[int, int]:
    """Return (count of full 100% windows, longest such window)."""
    n_perfect = 0
    longest = 0
    for w in ALL_WINDOWS:
        hits, games = windows.get(w, (0, 0))
        if games >= w and hits == games:
            n_perfect += 1
            longest = w
    return n_perfect, longest


def short_windows_all_perfect(windows: dict[int, tuple[int, int]]) -> bool:
    """True when every full short window (4-10) that exists is 100%."""
    seen = 0
    for w in SHORT_WINDOWS:
        hits, games = windows.get(w, (0, 0))
        if games < w:
            continue
        seen += 1
        if hits != games:
            return False
    return seen > 0


def select_display_windows(windows: dict[int, tuple[int, int]]) -> list[dict]:
    """Up to six windows, highest hit% first. Truncated samples appear once."""
    items: list[dict] = []
    for n in ALL_WINDOWS:
        hits, games = windows.get(n, (0, 0))
        if games <= 0:
            continue
        items.append({
            "n": n,
            "hits": int(hits),
            "games": int(games),
            "rate": hits / games,
        })
    items.sort(key=lambda x: (-x["rate"], -x["games"], -x["n"]))
    seen: set[tuple[int, int]] = set()
    unique: list[dict] = []
    for item in items:
        key = (item["hits"], item["games"])
        if item["games"] < item["n"]:
            if key in seen:
                continue
            seen.add(key)
        unique.append(item)
        if len(unique) >= 6:
            break
    return unique


def has_perfect_window(windows: dict[int, tuple[int, int]] | list[dict] | None) -> bool:
    """True when at least one window is 100% (including a short sample)."""
    if not windows:
        return False
    if isinstance(windows, dict):
        pairs = windows.values()
    else:
        pairs = ((int(w.get("hits") or 0), int(w.get("games") or 0)) for w in windows)
    for hits, games in pairs:
        if games and hits == games:
            return True
    return False


def window_quality(windows: dict[int, tuple[int, int]]) -> float:
    """Sum of (hit rate)^2 times available games across all nine windows."""
    quality = 0.0
    for n in ALL_WINDOWS:
        hits, games = windows.get(n, (0, 0))
        if games <= 0:
            continue
        rate = hits / games
        quality += (rate * rate) * min(games, n)
    return quality


def strong_trend_score(
    windows: dict[int, tuple[int, int]],
    streak: int,
    venue_streak: int,
    *,
    prop: str = "",
    line: float = 0.0,
    side: str = "over",
    season_avg: float | None = None,
    line_source: str = "",
) -> tuple[float, int, int, int, bool]:
    """Return (score, n_perfect, longest_perfect, best_streak, trivial_gimme).

    Fully-perfect short-window cards (NFL #1-4 style) stay ordered by
    game streak. A very long home/away streak can still outrank a
    short 4/4 and 5/5, because venue streak is a first-class term
    rather than a 0.1 tie-break.
    """
    trivial = is_trivial_under(prop, line, side, season_avg, line_source=line_source)
    n_perfect, longest = perfect_window_stats(windows)
    game_streak = int(streak or 0)
    ven_streak = int(venue_streak or 0)
    best_streak = max(game_streak, ven_streak)
    if trivial:
        return 0.0, n_perfect, longest, best_streak, True
    quality = window_quality(windows)
    # 8 × perfect windows + quality keeps 6-for-6 cards ahead of a
    # 4-perfect 13x away card, while 0.85 × a 53-game venue streak can
    # still pass a short 4/4 and 5/5. Fully-perfect short windows also
    # get a 40-point bump so they stay ordered by game streak.
    bonus = 40.0 if short_windows_all_perfect(windows) else 0.0
    score = (
        bonus
        + 8.0 * n_perfect
        + quality
        + min(game_streak, 80)
        + 0.85 * min(ven_streak, 80)
    )
    return round(score, 2), n_perfect, longest, best_streak, False


def windows_from_row(row: dict) -> dict[int, tuple[int, int]]:
    return {
        4: (int(row.get("l4_hits") or 0), int(row.get("l4_games") or 0)),
        5: (int(row.get("l5_hits") or 0), int(row.get("l5_games") or 0)),
        6: (int(row.get("l6_hits") or 0), int(row.get("l6_games") or 0)),
        8: (int(row.get("l8_hits") or 0), int(row.get("l8_games") or 0)),
        9: (int(row.get("l9_hits") or 0), int(row.get("l9_games") or 0)),
        10: (int(row.get("l10_hits") or 0), int(row.get("l10_games") or 0)),
        12: (int(row.get("l12_hits") or 0), int(row.get("l12_games") or 0)),
        15: (int(row.get("l15_hits") or 0), int(row.get("l15_games") or 0)),
        20: (int(row.get("l20_hits") or 0), int(row.get("l20_games") or 0)),
    }


def score_row_dict(row: dict) -> float:
    """Recompute the strong-trend score from a stored board row."""
    windows = windows_from_row(row)
    venue = (row.get("venue") or "H").upper()
    venue_streak = row.get("home_streak") if venue == "H" else row.get("away_streak")
    score, *_rest = strong_trend_score(
        windows,
        int(row.get("streak") or 0),
        int(venue_streak or 0),
        prop=str(row.get("prop") or ""),
        line=float(row.get("line") or 0),
        side=str(row.get("side") or "over"),
        season_avg=row.get("season_avg"),
        line_source=str(row.get("line_source") or ""),
    )
    return score


def legacy_trend_score(
    l4: float,
    l5: float,
    l8: float,
    l10: float,
    l15: float,
    l20: float,
    streak: int,
    venue_streak: int,
) -> float:
    """Pre-strong-v1 blend (streaks capped at 5). Used only for backtests."""
    cap = 5
    raw = (
        WEIGHTS["l4"] * l4
        + WEIGHTS["l5"] * l5
        + WEIGHTS["l8"] * l8
        + WEIGHTS["l10"] * l10
        + WEIGHTS["l15"] * l15
        + WEIGHTS["l20"] * l20
        + WEIGHTS["streak"] * min(streak, cap) / cap
        + WEIGHTS["venue_streak"] * min(venue_streak, cap) / cap
    )
    return round(100.0 * raw, 1)


def trend_score(
    l4: float,
    l5: float,
    l8: float,
    l10: float,
    l15: float,
    l20: float,
    streak: int,
    venue_streak: int,
    *,
    windows: dict[int, tuple[int, int]] | None = None,
    prop: str = "",
    line: float = 0.0,
    side: str = "over",
    season_avg: float | None = None,
    line_source: str = "",
) -> float:
    """Strong-trend score. Prefer strong_trend_score() when window counts exist."""
    if windows is None:
        # Rates only — approximate counts so first-score fallback still works.
        def approx(rate: float, n: int) -> tuple[int, int]:
            return int(round(rate * n)), n
        windows = {
            4: approx(l4, 4),
            5: approx(l5, 5),
            6: approx(l8, 6),  # no l6 in this legacy signature
            8: approx(l8, 8),
            9: approx(l15, 9),
            10: approx(l10, 10),
            12: approx(l15, 12),
            15: approx(l15, 15),
            20: approx(l20, 20),
        }
    score, *_rest = strong_trend_score(
        windows,
        streak,
        venue_streak,
        prop=prop,
        line=line,
        side=side,
        season_avg=season_avg,
        line_source=line_source,
    )
    return score


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
    # Minutes qualifier is this season only, so last year's role does
    # not keep a deep-bench player in the top 10.
    minute_src = current or played
    avg_min = sum(g.minutes for g in minute_src) / len(minute_src) if minute_src else 0.0
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
                l6_r, l6_h, l6_n = _hit_rate(_window(played, 6), prop, line, side)
                l8_r, l8_h, l8_n = _hit_rate(_window(played, 8), prop, line, side)
                l9_r, l9_h, l9_n = _hit_rate(_window(played, 9), prop, line, side)
                l10_r, l10_h, l10_n = _hit_rate(_window(played, 10), prop, line, side)
                l12_r, l12_h, l12_n = _hit_rate(_window(played, 12), prop, line, side)
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
                windows = {
                    4: (l4_h, l4_n),
                    5: (l5_h, l5_n),
                    6: (l6_h, l6_n),
                    8: (l8_h, l8_n),
                    9: (l9_h, l9_n),
                    10: (l10_h, l10_n),
                    12: (l12_h, l12_n),
                    15: (l15_h, l15_n),
                    20: (l20_h, l20_n),
                }
                display = select_display_windows(windows)
                score, n_perfect, longest_perfect, best_streak, trivial = strong_trend_score(
                    windows,
                    streak,
                    venue_streak,
                    prop=prop,
                    line=line,
                    side=side,
                    season_avg=season_avg,
                    line_source=offer.source,
                )
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
                        l6=round(l6_r, 4),
                        l8=round(l8_r, 4),
                        l9=round(l9_r, 4),
                        l15=round(l15_r, 4),
                        l4_hits=l4_h,
                        l4_games=l4_n,
                        l6_hits=l6_h,
                        l6_games=l6_n,
                        l8_hits=l8_h,
                        l8_games=l8_n,
                        l9_hits=l9_h,
                        l9_games=l9_n,
                        l15_hits=l15_h,
                        l15_games=l15_n,
                        l12=round(l12_r, 4),
                        l12_hits=l12_h,
                        l12_games=l12_n,
                        windows=display,
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
                        n_perfect=n_perfect,
                        longest_perfect=longest_perfect,
                        best_streak=best_streak,
                        trivial_gimme=trivial,
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

    rows.sort(key=lambda r: (-r.score, -r.best_streak, -r.l10, -r.streak, r.player, r.line))
    return rows
