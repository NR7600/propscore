"""Load generated board JSON and serve filtered, paginated slices."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from propscore.odds import lines_for_sport, lowest_line, props_for_sport, format_american, prop_full_label
from propscore.ranking import has_perfect_window, windows_from_row, select_display_windows

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

# Fields a board card actually renders. Player-page extras are added
# only on /player responses so list endpoints stay small.
CARD_FIELDS = (
    "player_id",
    "player",
    "team",
    "opponent",
    "venue",
    "event_id",
    "game",
    "game_time_et",
    "prop",
    "prop_label",
    "prop_full",
    "line",
    "display_line",
    "line_label",
    "side",
    "line_source",
    "american_odds",
    "book_title",
    "l4",
    "l5",
    "l6",
    "l8",
    "l9",
    "l10",
    "l4_hits",
    "l4_games",
    "l5_hits",
    "l5_games",
    "l6_hits",
    "l6_games",
    "l8_hits",
    "l8_games",
    "l9_hits",
    "l9_games",
    "l10_hits",
    "l10_games",
    "l12",
    "l12_hits",
    "l12_games",
    "l15",
    "l15_hits",
    "l15_games",
    "l20",
    "l20_hits",
    "l20_games",
    "windows",
    "season",
    "season_hits",
    "season_games",
    "h2h",
    "h2h_hits",
    "h2h_games",
    "streak",
    "home_streak",
    "away_streak",
    "score",
    "n_perfect",
    "longest_perfect",
    "best_streak",
    "games_played",
    "rest_days",
    "is_b2b",
    "injury_status",
    "position",
    "matchup_tag",
    "without",
    "tip_win_rate",
    "tip_wins",
    "tip_games",
    "started_last",
    "started_games",
    "first_kind",
    "prior_games",
)

PLAYER_EXTRA_FIELDS = (
    "home_hit",
    "away_hit",
    "home_hits",
    "home_games",
    "away_hits",
    "away_games",
    "l5_avg",
    "l10_avg",
    "season_avg",
    "h2h_avg",
    "min_l5",
    "min_l10",
    "minutes_trend",
    "avg_minutes",
    "injury_detail",
    "headshot",
    "opp_def_rank",
    "opp_def_teams",
    "opp_def_value",
    "opp_def_label",
    "opp_def_stat",
    "started_rate",
    "book",
)

# Backward-compatible alias.
ROW_FIELDS = CARD_FIELDS + PLAYER_EXTRA_FIELDS

GAME_CHIP_FIELDS = (
    "event_id",
    "label",
    "start_et",
    "status",
    "home_abbr",
    "away_abbr",
    "home_id",
    "away_id",
)

LOG_FIELDS = (
    "event_id",
    "date",
    "opponent_abbr",
    "is_home",
    "venue",
    "minutes",
    "points",
    "rebounds",
    "assists",
    "threes",
    "pra",
    "steals",
    "blocked",
    "fgm",
    "goals",
    "shots",
    "saves",
    "started",
    "pass_yds",
    "pass_td",
    "completions",
    "pass_att",
    "ints",
    "rush_yds",
    "rush_att",
    "rush_td",
    "receptions",
    "rec_yds",
    "rec_td",
    "targets",
    "anytime_td",
    "turnovers",
    "long_rush",
    "long_rec",
    "first_score",
    "prior_season",
    "result",
)


def today_et() -> str:
    return datetime.now(ET).date().isoformat()


_pruned_on: str | None = None


def _date_from_board_path(path: Path, sport: str) -> str | None:
    prefix = f"{sport}_"
    stem = path.stem
    if stem.startswith(prefix):
        return stem[len(prefix):]
    return None


def prune_old_boards(*sports: str) -> list[str]:
    """Delete board files (json/csv/html) dated before today ET.

    Past slates must never be served, even as a fallback while today
    is still building.
    """
    today = today_et()
    keys = sports or ("nba", "nhl", "nfl")
    removed: list[str] = []
    for sport in keys:
        for path in list(OUTPUT_DIR.glob(f"{sport}_*.*")):
            date = _date_from_board_path(path, sport)
            if not date or date >= today:
                continue
            try:
                path.unlink()
                removed.append(path.name)
            except OSError:
                continue
    if removed:
        STORE.drop_past(today)
        try:
            from app.response_cache import clear as clear_response_cache
            clear_response_cache()
        except Exception:
            pass
    return removed


def prune_if_new_day() -> list[str]:
    """Prune at most once per ET day so a long-running process drops yesterday at midnight."""
    global _pruned_on
    today = today_et()
    if _pruned_on == today:
        return []
    removed = prune_old_boards()
    _pruned_on = today
    return removed


def available_dates(sport: str = "nba") -> list[str]:
    prune_if_new_day()
    today = today_et()
    dates = []
    for path in OUTPUT_DIR.glob(f"{sport}_*.json"):
        # sport_YYYY-MM-DD.json
        date = _date_from_board_path(path, sport)
        if date and date >= today:
            dates.append(date)
    return sorted(dates)


def resolve_date(sport: str, date: str | None) -> str | None:
    """Pick today's slate, or the next upcoming one (NFL). Never a past day."""
    dates = available_dates(sport)
    if not dates:
        return None
    today = today_et()
    if date and date >= today and date in dates:
        return date
    if today in dates:
        return today
    return dates[0]


def _load_file(sport: str, date: str) -> dict[str, Any]:
    path = OUTPUT_DIR / f"{sport}_{date}.json"
    if not path.exists():
        raise FileNotFoundError(f"No {sport} board for {date}")
    return json.loads(path.read_text(encoding="utf-8"))


class BoardStore:
    """In-memory cache of the latest generated board, reloaded on file change."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    def drop_past(self, today: str | None = None) -> None:
        cutoff = today or today_et()
        for key in [k for k in self._cache if k[1] < cutoff]:
            self._cache.pop(key, None)

    def get(self, sport: str, date: str) -> dict[str, Any]:
        path = OUTPUT_DIR / f"{sport}_{date}.json"
        if not path.exists():
            raise FileNotFoundError(f"No {sport} board for {date}")
        mtime = path.stat().st_mtime
        key = (sport, date)
        hit = self._cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        data = _load_file(sport, date)
        for player in (data.get("players") or {}).values():
            logs = player.get("logs")
            if isinstance(logs, list) and len(logs) > 30:
                player["logs"] = logs[:30]
        # Keep only the board we just loaded for this sport so a fat
        # leftover file cannot pin hundreds of MB in the API process.
        for cached_key in [k for k in self._cache if k[0] == sport and k != key]:
            self._cache.pop(cached_key, None)
        self._cache[key] = (mtime, data)
        return data

    def token(self, sport: str, date: str) -> str:
        path = OUTPUT_DIR / f"{sport}_{date}.json"
        mtime = path.stat().st_mtime if path.exists() else 0
        return f"{sport}:{date}:{mtime}"

    def meta(self, sport: str, date: str) -> dict[str, Any]:
        data = self.get(sport, date)
        return {
            "sport": data.get("sport", sport),
            "date": data.get("date", date),
            "timezone": data.get("timezone", "America/New_York"),
            "generated_at": data.get("generated_at"),
            "stale": bool(data.get("date") and data.get("date") < today_et()),
            "available_dates": available_dates(sport),
            "games": _slim_games(data.get("games") or []),
            "row_count": len(data.get("rows") or []),
            "player_count": len(data.get("players") or {}),
            "formula": (data.get("formula") or {}).get("description"),
            "props": props_for_sport(sport),
        }

    def query_board(
        self,
        sport: str,
        date: str,
        *,
        stat: str = "",
        game: str = "",
        min_l10: float = 0.0,
        hide_out: bool = False,
        hide_gimme: bool = False,
        view: str = "value",
        q: str = "",
        side: str = "",
        perfect: bool = False,
        sort: str = "score",
        min_odds: int | None = None,
        tab: str = "",
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        data = self.get(sport, date)
        first_mode = _is_first_tab(tab, stat)
        source = (data.get("first_score_rows") or []) if first_mode else (data.get("rows") or [])
        rows = _filter_rows(
            source,
            sport=sport,
            stat="" if first_mode else stat,
            game=game,
            min_l10=0.0 if first_mode else min_l10,
            hide_out=hide_out,
            hide_gimme=False if first_mode else hide_gimme,
            view="all" if first_mode else view,
            q=q,
            side="" if first_mode else side,
            perfect=perfect,
            sort=sort,
            min_odds=None if first_mode else min_odds,
            first_mode=first_mode,
        )
        top = _top10(rows, first_mode=first_mode)
        top_out = []
        for i, r in enumerate(top):
            item = _compact_row(r)
            item["rank"] = i + 1
            top_out.append(item)
        # Hard cap: every board list is ranks 1-10 only. No "more trends".
        total = len(top_out)
        page = 1
        page_size = 10
        total_pages = 1
        slice_: list[dict] = []
        return {
            "sport": data.get("sport", sport),
            "date": data.get("date", date),
            "timezone": data.get("timezone", "America/New_York"),
            "generated_at": data.get("generated_at"),
            "stale": bool(data.get("date") and data.get("date") < today_et()),
            "view": "first_score" if first_mode else ("value" if view == "value" else "all"),
            "view_label": (
                _first_view_label(sport)
                if first_mode
                else _view_label(view, min_l10)
            ),
            "games": _slim_games(data.get("games") or []),
            "filters": {
                "stat": stat or "",
                "game": game or "",
                "min_l10": 0.0 if first_mode else min_l10,
                "hide_out": hide_out,
                "hide_gimme": False if first_mode else hide_gimme,
                "q": q or "",
                "side": "" if first_mode else (side or ""),
                "perfect": perfect,
                "sort": sort or "score",
                "min_odds": None if first_mode else min_odds,
                "tab": "first_score" if first_mode else (side or "all"),
            },
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_more": False,
            "props": props_for_sport(sport),
            "top": top_out,
            "top_count": len(top_out),
            "rows": slice_,
            "first_score_meta": data.get("first_score_meta") or {},
            "first_mode": first_mode,
            "games_remaining": _games_remaining(data.get("games") or []),
            "slate_message": _slate_message(data.get("games") or [], first_mode, len(top_out), sport=sport),
        }

    def player(self, sport: str, date: str, player_id: str) -> dict[str, Any] | None:
        data = self.get(sport, date)
        player = (data.get("players") or {}).get(str(player_id))
        if not player:
            # Still allow a lookup from rows if the player was filtered out of
            # the players map for some reason.
            return None
        rows = [
            _compact_row(r, detail=True)
            for r in (data.get("rows") or [])
            if str(r.get("player_id")) == str(player_id)
        ]
        first_rows = [
            _compact_row(r, detail=True)
            for r in (data.get("first_score_rows") or [])
            if str(r.get("player_id")) == str(player_id)
        ]
        rows.extend(first_rows)
        # Prefer a score-sorted list so the detail page can pick a default line.
        rows.sort(key=lambda r: (
            -(r.get("score") or 0),
            -(r.get("l10") or 0),
            -(r.get("streak") or 0),
        ))
        featured, more = _player_featured(rows)
        featured = [_compact_row(r, detail=True) for r in featured]
        more = [_compact_row(r, detail=True) for r in more]
        game = None
        source = featured or more or rows
        if source:
            event_id = source[0].get("event_id")
            game = next((g for g in (data.get("games") or []) if str(g.get("event_id")) == str(event_id)), None)
        return {
            "sport": data.get("sport", sport),
            "date": data.get("date", date),
            "player": {k: v for k, v in player.items() if k != "logs"},
            "game": _slim_game(game),
            "rows": featured,
            "more_rows": more,
        }

    def player_logs(self, sport: str, date: str, player_id: str) -> dict[str, Any] | None:
        data = self.get(sport, date)
        player = (data.get("players") or {}).get(str(player_id))
        if not player:
            return None
        slim = []
        for g in (player.get("logs") or [])[:30]:
            if not isinstance(g, dict):
                g = g.to_dict() if hasattr(g, "to_dict") else dict(g)
            slim.append(_slim_log(g))
        return {
            "sport": sport,
            "date": date,
            "player_id": str(player_id),
            "logs": slim,
        }

    def game_context(self, sport: str, date: str, event_id: str) -> dict[str, Any] | None:
        data = self.get(sport, date)
        game = next(
            (g for g in (data.get("games") or []) if str(g.get("event_id")) == str(event_id)),
            None,
        )
        if not game:
            return None
        injuries = []
        for item in game.get("injuries") or []:
            injuries.append(
                _omit_empty(
                    {
                        "player_id": item.get("player_id"),
                        "player": item.get("player"),
                        "team": item.get("team"),
                        "position": item.get("position"),
                        "status": item.get("status"),
                        "detail": item.get("detail"),
                        "comment": item.get("comment"),
                        "return_date": item.get("return_date"),
                    }
                )
            )
        news = [i for i in injuries if i.get("comment")]
        payload = _slim_game(game)
        payload["injuries"] = injuries
        payload["news"] = news
        payload["injuries_updated_at"] = data.get("generated_at")
        payload["matchup"] = _matchup_payload(data, game)
        return payload

    def prop_report(self, sport: str, date: str, player_id: str, prop: str, side: str, line: float | None) -> dict[str, Any] | None:
        data = self.get(sport, date)
        pool = list(data.get("rows") or [])
        if prop in {"first_basket", "first_goal", "first_td"}:
            pool = list(data.get("first_score_rows") or [])
        matches = [
            r for r in pool
            if str(r.get("player_id")) == str(player_id) and str(r.get("prop") or "") == str(prop)
            and str(r.get("side") or "over") == str(side or "over")
        ]
        if line is not None:
            exact = [r for r in matches if abs(float(r.get("line") or 0) - float(line)) < 1e-9]
            if exact:
                matches = exact
        if not matches:
            return None
        row = max(matches, key=lambda r: r.get("score") or 0)
        windows = _row_windows(row)
        name = row.get("player") or ""
        shown = row.get("display_line") if row.get("display_line") is not None else row.get("line")
        full = row.get("prop_full") or prop_full_label(str(prop))
        side_word = "under" if (row.get("side") or "over") == "under" else "over"
        possess = _his_or_her(name)
        trend_lines: list[str] = []
        for w in windows:
            hits = int(w.get("hits") or 0)
            games = int(w.get("games") or 0)
            rate = (hits / games) if games else 0
            trend_lines.append(
                f"{name} has gone {side_word} {shown} {full} in {hits} of {possess} last {games} games ({_pct(rate)}%)."
            )
        if row.get("streak"):
            trend_lines.append(
                f"{name} is on a {int(row['streak'])}-game {side_word} streak for {shown} {full}."
            )
        venue = (row.get("venue") or "H").upper()
        venue_streak = int(row.get("home_streak") or 0) if venue == "H" else int(row.get("away_streak") or 0)
        if venue_streak:
            loc = "home" if venue == "H" else "away"
            trend_lines.append(
                f"{name} is on a {venue_streak}-game {loc} {side_word} streak for {shown} {full}."
            )
        same = [
            r for r in pool
            if str(r.get("prop") or "") == str(prop) and str(r.get("side") or "over") == str(row.get("side") or "over")
        ]
        same = _one_per_player(same)
        game_pool = [r for r in same if str(r.get("event_id")) == str(row.get("event_id"))]
        data_game = _rank_in_pool(row, game_pool, odds=False)
        odds_game = _rank_in_pool(row, game_pool, odds=True)
        data_league = _rank_in_pool(row, same, odds=False)
        odds_league = _rank_in_pool(row, same, odds=True)
        live = row.get("line_source") == "live" and row.get("american_odds") is not None
        venue_word = "at" if venue == "A" else "vs"
        header_line = f"{row.get('line_label') or ''} · {venue_word} {row.get('opponent') or ''}".strip(" ·")
        return {
            "title": "PROP REPORT",
            "player": name,
            "team": row.get("team"),
            "header": header_line,
            "prop": prop,
            "prop_label": row.get("prop_label"),
            "prop_full": full,
            "side": row.get("side"),
            "line": row.get("line"),
            "display_line": shown,
            "line_label": row.get("line_label"),
            "american_odds": row.get("american_odds") if live else None,
            "american_odds_label": format_american(row.get("american_odds")) if live else "",
            "line_source": row.get("line_source"),
            "game": row.get("game"),
            "trend_count": len(trend_lines),
            "trend_lines": trend_lines,
            "game_ranks": {
                "data": None if not data_game else {"label": data_game[0], "place": data_game[1], "total": data_game[2]},
                "odds": None if not (live and odds_game) else {"label": odds_game[0], "place": odds_game[1], "total": odds_game[2]},
            },
            "league_ranks": {
                "data": None if not data_league else {"label": data_league[0], "place": data_league[1], "total": data_league[2]},
                "odds": None if not (live and odds_league) else {"label": odds_league[0], "place": odds_league[1], "total": odds_league[2]},
            },
            "blurbs": {
                "data": (
                    "Data Rank is this prop's place among the same stat and side "
                    "in tonight's game, or across the whole slate, ranked by trend "
                    "strength — recent window hit rates plus current streaks."
                ),
                "odds": (
                    "Odds Rank is this prop's place among those same props that "
                    "have a live sportsbook price. Longer American odds rank higher. "
                    "It is only shown when a real line exists."
                ),
            },
        }



def _view_label(view: str, min_l10: float) -> str:
    if view == "value":
        if min_l10 and min_l10 > 0:
            pct = int(round(min_l10 * 100))
            return (
                f"Best value: for each player and stat, the highest line still "
                f"clearing {pct}% of his last 10 games, ranked by strong trends (perfect windows and current streaks)."
            )
        return "Best value: one line per player and stat, ranked by strong trends (perfect windows and current streaks)."
    return "All qualifying lines, ranked by strong trends (perfect windows and current streaks)."


def _is_out(status: str | None) -> bool:
    if not status:
        return False
    text = status.strip().lower()
    if text in {"out", "ofs", "ir", "ir-lt", "ltir", "injured reserve"}:
        return True
    return "injured reserve" in text


def _filter_rows(
    rows: list[dict[str, Any]],
    *,
    sport: str = "nba",
    stat: str,
    game: str,
    min_l10: float,
    hide_out: bool,
    hide_gimme: bool,
    view: str,
    q: str,
    side: str = "",
    perfect: bool = False,
    sort: str = "score",
    min_odds: int | None = None,
    first_mode: bool = False,
) -> list[dict[str, Any]]:
    needle = (q or "").strip().lower()
    stat = (stat or "").strip().lower()
    game = (game or "").strip()
    out: list[dict[str, Any]] = []
    excluded = set() if (stat or first_mode) else _all_stats_exclude(sport)
    for r in rows:
        if excluded and str(r.get("prop") or "") in excluded:
            continue
        if stat and str(r.get("prop", "")).lower() != stat:
            continue
        if game and str(r.get("event_id")) != game:
            continue
        if (r.get("l10") or 0) < min_l10:
            continue
        if hide_out and _is_out(r.get("injury_status")):
            continue
        if hide_gimme and _is_gimme(r, sport):
            continue
        if side and str(r.get("side") or "over") != side:
            continue
        if perfect and not _row_has_perfect(r):
            continue
        if min_odds is not None and r.get("line_source") == "live":
            price = r.get("american_odds")
            if price is None or int(price) < int(min_odds):
                continue
        if needle:
            hay = " ".join(
                str(r.get(k) or "")
                for k in ("player", "team", "opponent", "line_label", "prop_label", "game")
            ).lower()
            if needle not in hay:
                continue
        out.append(r)

    if view == "value":
        out = _best_value(out)

    if sort == "streak":
        out.sort(
            key=lambda r: (
                -_longest_streak(r),
                -(r.get("score") or 0),
                -(r.get("l10") or 0),
                r.get("player") or "",
            )
        )
    else:
        out.sort(
            key=lambda r: (
                -(r.get("score") or 0),
                -(r.get("l10") or 0),
                -(r.get("streak") or 0),
                r.get("player") or "",
            )
        )
    return out


def _is_gimme(row: dict[str, Any], sport: str = "nba") -> bool:
    """True when L10 is 100% on the easiest threshold for that side."""
    prop = row.get("prop")
    line = row.get("line")
    if row.get("line_source") in {"live", "est", "research"}:
        return False
    if (row.get("l10") or 0) < 0.999:
        return False
    lines = lines_for_sport(sport).get(str(prop or ""))
    if not lines:
        lowest = lowest_line(str(prop or ""), sport)
        if lowest is None:
            return False
        return float(line) <= float(lowest) + 1e-9
    side = row.get("side") or "over"
    # Easiest over is the lowest line; easiest under is the highest line.
    edge = max(lines) if side == "under" else min(lines)
    return abs(float(line) - float(edge)) <= 1e-9


def _best_value(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per player+stat+side.

    Overs: the highest line that already passed filters (default L10 >= 70%).
    Unders: the lowest line that still clears that rate (harder under).
    """
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in rows:
        side = str(r.get("side") or "over")
        key = (str(r.get("player_id")), str(r.get("prop")), side)
        prev = best.get(key)
        line = float(r.get("line") or 0)
        if prev is None:
            best[key] = r
            continue
        prev_line = float(prev.get("line") or 0)
        better = line < prev_line if side == "under" else line > prev_line
        if better:
            best[key] = r
        elif line == prev_line and (r.get("score") or 0) > (prev.get("score") or 0):
            best[key] = r
    return list(best.values())


def _omit_empty(d: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in d.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        out[k] = v
    return out


def _slim_without(items: Any, limit: int = 1) -> list[dict[str, Any]]:
    out = []
    for item in (items or [])[:limit]:
        if not isinstance(item, dict):
            continue
        out.append(
            _omit_empty(
                {
                    "player": item.get("player"),
                    "status": item.get("status"),
                    "games": item.get("games"),
                    "hits": item.get("hits"),
                    "rate": item.get("rate"),
                    "avg": item.get("avg"),
                }
            )
        )
    return out


def _compact_row(row: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    fields = ROW_FIELDS if detail else CARD_FIELDS
    out = {k: row.get(k) for k in fields}
    limit = 3 if detail else 1
    if out.get("without"):
        out["without"] = _slim_without(out.get("without"), limit=limit)
    return _omit_empty(out)


def _slim_game(game: dict[str, Any] | None) -> dict[str, Any]:
    if not game:
        return {}
    return _omit_empty({k: game.get(k) for k in GAME_CHIP_FIELDS})


def _slim_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_slim_game(g) for g in games or []]


def _slim_log(log: dict[str, Any]) -> dict[str, Any]:
    return _omit_empty({k: log.get(k) for k in LOG_FIELDS})



def _is_first_tab(tab: str, stat: str) -> bool:
    token = (tab or stat or "").strip().lower()
    return token in {"first", "first_score", "first_basket", "first_goal", "first_td"}


def _row_id(row: dict[str, Any]) -> tuple:
    return (
        str(row.get("player_id")),
        str(row.get("prop") or ""),
        str(row.get("side") or "over"),
        str(row.get("line") or ""),
    )


def _trend_key(row: dict[str, Any], first_mode: bool = False) -> tuple:
    # First-score lists with a live price are odds-driven: longer
    # American odds rank higher. Regular-stat lists stay on score.
    if first_mode and row.get("line_source") == "live" and row.get("american_odds") is not None:
        return (
            1,
            int(row.get("american_odds") or 0),
            float(row.get("score") or 0),
            int(row.get("streak") or 0),
        )
    return (
        0 if first_mode else 1,
        float(row.get("score") or 0),
        int(row.get("best_streak") or _longest_streak(row)),
        float(row.get("l10") or 0),
        int(row.get("streak") or 0),
        float(row.get("l5") or 0),
        float(row.get("l4") or 0),
        float(row.get("season") or 0),
    )


def _top10(rows: list[dict[str, Any]], first_mode: bool = False) -> list[dict[str, Any]]:
    """Hard cap at 10 cards. The same player may appear more than once.

    When a slate has live sportsbook lines, the regular-stat top 10 is
    drawn from those live rows so estimated gimme unders cannot occupy
    every rank. First-score lists already sort on odds when a price exists.
    """
    pool = rows
    if not first_mode and any(r.get("line_source") == "live" for r in rows):
        live = [r for r in rows if r.get("line_source") == "live"]
        if live:
            pool = live
    ranked = sorted(pool, key=lambda r: _trend_key(r, first_mode), reverse=True)
    return ranked[:10]


FEATURED_CAP = 6


def _player_featured(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Max one line per stat type, about 4-6 total; extras go behind More lines."""
    best: dict[str, dict[str, Any]] = {}
    extras: list[dict[str, Any]] = []
    for r in rows:
        prop = str(r.get("prop") or "")
        prev = best.get(prop)
        if prev is None:
            best[prop] = r
            continue
        if _trend_key(r) > _trend_key(prev):
            extras.append(prev)
            best[prop] = r
        else:
            extras.append(r)
    featured = sorted(best.values(), key=_trend_key, reverse=True)
    if len(featured) > FEATURED_CAP:
        extras = featured[FEATURED_CAP:] + extras
        featured = featured[:FEATURED_CAP]
    extras.sort(key=_trend_key, reverse=True)
    return featured, extras



def _game_is_final(game: dict[str, Any]) -> bool:
    status = str(game.get("status") or "").lower()
    return "final" in status or status in {"post", "completed", "status_final"}


def _games_remaining(games: list[dict[str, Any]]) -> int:
    return sum(1 for g in games if not _game_is_final(g))


def _first_view_label(sport: str) -> str:
    base = (
        "Ranked 1-10 by strong trends: longest perfect windows "
        "(4/4, 5/5, 8/8, 10/10, 15/15, 20/20), current game or home/away "
        "streak, then L20/L10 hit rate. Weak and mixed rates fall out of the top 10. "
    )
    if sport == "nfl":
        return base + "First TD is the first touchdown of the game (field goals and safeties do not count)."
    if sport == "nhl":
        return base + "First Goal is the first goal of the game."
    return base + "First FGM is the first field goal of the game (free throws do not count)."


def _slate_message(games: list[dict[str, Any]], first_mode: bool, row_count: int, sport: str = "nba") -> str:
    if not first_mode:
        return ""
    remaining = _games_remaining(games)
    if row_count > 0:
        return ""
    kind = {"nfl": "First-TD", "nhl": "First-goal"}.get(sport, "First-basket")
    if remaining > 0:
        return (
            f"{kind} trends are still generating, or play-by-play "
            "has not loaded yet. Keep this tab open and refresh in a minute "
            f"— {remaining} game(s) still on this slate."
        )
    if games:
        return "No games left on this slate. Check back tomorrow for the next one."
    return "No games on this slate."


def _all_stats_exclude(sport: str) -> set[str]:
    if sport == "nhl":
        return {"first_goal", "goals"}
    if sport == "nfl":
        return {"first_td", "anytime_td"}
    return {"first_basket"}


def _row_windows(row: dict[str, Any]) -> list[dict]:
    stored = row.get("windows")
    if isinstance(stored, list) and stored:
        return stored
    return select_display_windows(windows_from_row(row))


def _row_has_perfect(row: dict[str, Any]) -> bool:
    stored = row.get("windows")
    if isinstance(stored, list) and stored:
        return has_perfect_window(stored)
    return has_perfect_window(windows_from_row(row))


def _longest_streak(row: dict[str, Any]) -> int:
    return max(
        int(row.get("streak") or 0),
        int(row.get("home_streak") or 0),
        int(row.get("away_streak") or 0),
        int(row.get("best_streak") or 0),
    )


def _matchup_payload(data: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    ranks = data.get("team_ranks") or {}
    home = (game.get("home_abbr") or "").upper()
    away = (game.get("away_abbr") or "").upper()
    teams = 0
    for info in ranks.values():
        if isinstance(info, dict) and info.get("teams"):
            teams = int(info["teams"])
            break
    def pack(abbr: str) -> dict[str, Any]:
        info = ranks.get(abbr) or {}
        return {
            "abbr": abbr,
            "name": info.get("name") or abbr,
            "defense": info.get("defense") or {},
            "offense": info.get("offense") or {},
        }
    return {
        "teams": teams,
        "legend": f"Ranked out of {teams or 30} teams · Red = tough, Green = smash",
        "home": pack(home),
        "away": pack(away),
        "shooting": None,
    }


def _pct(rate: float) -> int:
    return int(round((rate or 0) * 100))


def _his_or_her(name: str) -> str:
    return "his"


def _rank_label(place: int, tied: bool, total: int) -> str:
    prefix = "T-" if tied else ""
    return f"{prefix}{place} of {total}"


def _rank_in_pool(row: dict[str, Any], pool: list[dict[str, Any]], *, odds: bool) -> tuple[str, int, int] | None:
    if not pool:
        return None
    pid = str(row.get("player_id"))
    if odds:
        eligible = [r for r in pool if r.get("line_source") == "live" and r.get("american_odds") is not None]
        if row.get("line_source") != "live" or row.get("american_odds") is None:
            return None
        eligible.sort(key=lambda r: (-int(r.get("american_odds") or 0), r.get("player") or ""))
        key_fn = lambda r: int(r.get("american_odds") or 0)
    else:
        eligible = list(pool)
        eligible.sort(key=lambda r: (-(r.get("score") or 0), -(r.get("best_streak") or 0), r.get("player") or ""))
        key_fn = lambda r: float(r.get("score") or 0)
    total = len(eligible)
    scores = [key_fn(r) for r in eligible]
    place = None
    my = key_fn(row)
    for i, r in enumerate(eligible, start=1):
        if str(r.get("player_id")) == pid:
            place = i
            # walk back for ties
            while place > 1 and scores[place - 2] == my:
                place -= 1
            break
    if place is None:
        return None
    tied = scores.count(my) > 1
    return _rank_label(place, tied, total), place, total


def _one_per_player(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        pid = str(r.get("player_id") or "")
        prev = best.get(pid)
        if prev is None or (r.get("score") or 0) > (prev.get("score") or 0):
            best[pid] = r
    return list(best.values())



STORE = BoardStore()
