"""Load generated board JSON and serve filtered, paginated slices."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from propscore.odds import lines_for_sport, lowest_line, props_for_sport

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

# Compact fields sent in list responses so phones never download logs.
ROW_FIELDS = (
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
    "book",
    "book_title",
    "l4",
    "l5",
    "l8",
    "l10",
    "l15",
    "l20",
    "l4_hits",
    "l4_games",
    "l8_hits",
    "l8_games",
    "l15_hits",
    "l15_games",
    "season",
    "h2h",
    "venue_hit",
    "home_hit",
    "away_hit",
    "streak",
    "home_streak",
    "away_streak",
    "score",
    "games_played",
    "avg_minutes",
    "l5_hits",
    "l5_games",
    "l10_hits",
    "l10_games",
    "l20_hits",
    "l20_games",
    "season_hits",
    "season_games",
    "h2h_hits",
    "h2h_games",
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
    "rest_days",
    "is_b2b",
    "injury_status",
    "injury_detail",
    "position",
    "headshot",
    "opp_def_rank",
    "opp_def_teams",
    "opp_def_value",
    "opp_def_label",
    "opp_def_stat",
    "matchup_tag",
    "without",
    "tip_win_rate",
    "tip_wins",
    "tip_games",
    "started_rate",
    "started_games",
    "started_last",
    "first_kind",
)


def today_et() -> str:
    return datetime.now(ET).date().isoformat()


def available_dates(sport: str = "nba") -> list[str]:
    dates = []
    for path in OUTPUT_DIR.glob(f"{sport}_*.json"):
        # sport_YYYY-MM-DD.json
        stem = path.stem
        prefix = f"{sport}_"
        if stem.startswith(prefix):
            dates.append(stem[len(prefix) :])
    return sorted(dates)


def resolve_date(sport: str, date: str | None) -> str | None:
    dates = available_dates(sport)
    if not dates:
        return None
    if date and date in dates:
        return date
    today = today_et()
    if today in dates:
        return today
    return dates[-1]


def _load_file(sport: str, date: str) -> dict[str, Any]:
    path = OUTPUT_DIR / f"{sport}_{date}.json"
    if not path.exists():
        raise FileNotFoundError(f"No {sport} board for {date}")
    return json.loads(path.read_text(encoding="utf-8"))


class BoardStore:
    """In-memory cache of the latest generated board, reloaded on file change."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

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
        self._cache[key] = (mtime, data)
        return data

    def meta(self, sport: str, date: str) -> dict[str, Any]:
        data = self.get(sport, date)
        return {
            "sport": data.get("sport", sport),
            "date": data.get("date", date),
            "timezone": data.get("timezone", "America/New_York"),
            "generated_at": data.get("generated_at"),
            "stale": data.get("date") != today_et(),
            "available_dates": available_dates(sport),
            "games": data.get("games") or [],
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
        )
        top = _top10(rows, first_mode=first_mode)
        top_ids = {_row_id(r) for r in top}
        more = [r for r in rows if _row_id(r) not in top_ids]
        page = max(1, page)
        page_size = min(max(1, page_size), 50)
        total = len(more)
        total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
        if page > total_pages:
            page = total_pages
        start = (page - 1) * page_size
        slice_ = [_compact_row(r) for r in more[start : start + page_size]]
        top_out = []
        for i, r in enumerate(top):
            item = _compact_row(r)
            item["rank"] = i + 1
            top_out.append(item)
        return {
            "sport": data.get("sport", sport),
            "date": data.get("date", date),
            "timezone": data.get("timezone", "America/New_York"),
            "generated_at": data.get("generated_at"),
            "stale": data.get("date") != today_et(),
            "view": "first_score" if first_mode else ("value" if view == "value" else "all"),
            "view_label": (
                "Ranked 1-10 by trend strength: L4/L5/L8/L10/L15/L20 hit rates "
                "plus game and home/away streaks. First FGM is the first field "
                "goal of the game (free throws do not count)."
                if first_mode
                else _view_label(view, min_l10)
            ),
            "games": data.get("games") or [],
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
            "has_more": page < total_pages,
            "props": props_for_sport(sport),
            "top": top_out,
            "top_count": len(top_out),
            "rows": slice_,
            "first_score_meta": data.get("first_score_meta") or {},
            "first_mode": first_mode,
            "games_remaining": _games_remaining(data.get("games") or []),
            "slate_message": _slate_message(data.get("games") or [], first_mode, len(top_out) + total),
        }

    def player(self, sport: str, date: str, player_id: str) -> dict[str, Any] | None:
        data = self.get(sport, date)
        player = (data.get("players") or {}).get(str(player_id))
        if not player:
            # Still allow a lookup from rows if the player was filtered out of
            # the players map for some reason.
            return None
        rows = [
            _compact_row(r)
            for r in (data.get("rows") or [])
            if str(r.get("player_id")) == str(player_id)
        ]
        first_rows = [
            _compact_row(r)
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
        game = None
        source = featured or more or rows
        if source:
            event_id = source[0].get("event_id")
            game = next((g for g in (data.get("games") or []) if g.get("event_id") == event_id), None)
        logs = list(player.get("logs") or [])
        # Newest first already; cap to 20 for the chart.
        return {
            "sport": data.get("sport", sport),
            "date": data.get("date", date),
            "player": {k: v for k, v in player.items() if k != "logs"},
            "game": game,
            "logs": logs[:20],
            "rows": featured,
            "more_rows": more,
        }


def _view_label(view: str, min_l10: float) -> str:
    if view == "value":
        if min_l10 and min_l10 > 0:
            pct = int(round(min_l10 * 100))
            return (
                f"Best value: for each player and stat, the highest line still "
                f"clearing {pct}% of his last 10 games, ranked by trend strength."
            )
        return "Best value: one line per player and stat, ranked by trend strength."
    return "All qualifying lines, ranked by trend strength."


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
) -> list[dict[str, Any]]:
    needle = (q or "").strip().lower()
    stat = (stat or "").strip().lower()
    game = (game or "").strip()
    out: list[dict[str, Any]] = []
    for r in rows:
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
        if perfect and (r.get("l10") or 0) < 0.999:
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
                -(r.get("streak") or 0),
                -(r.get("l10") or 0),
                -(r.get("score") or 0),
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


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in ROW_FIELDS}



def _is_first_tab(tab: str, stat: str) -> bool:
    token = (tab or stat or "").strip().lower()
    return token in {"first", "first_score", "first_basket", "first_goal"}


def _row_id(row: dict[str, Any]) -> tuple:
    return (
        str(row.get("player_id")),
        str(row.get("prop") or ""),
        str(row.get("side") or "over"),
        str(row.get("line") or ""),
    )


def _trend_key(row: dict[str, Any], first_mode: bool = False) -> tuple:
    # Pure trend strength. Odds / live-vs-standard are never a sort key.
    return (
        float(row.get("score") or 0),
        float(row.get("l10") or 0),
        int(row.get("streak") or 0),
        float(row.get("l5") or 0),
        float(row.get("l4") or 0),
        float(row.get("season") or 0),
    )


def _top10(rows: list[dict[str, Any]], first_mode: bool = False) -> list[dict[str, Any]]:
    """One strongest trend per player, live lines preferred, capped at 10."""
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        pid = str(r.get("player_id") or "")
        if not pid:
            continue
        prev = best.get(pid)
        if prev is None or _trend_key(r, first_mode) > _trend_key(prev, first_mode):
            best[pid] = r
    ranked = sorted(best.values(), key=lambda r: _trend_key(r, first_mode), reverse=True)
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


def _slate_message(games: list[dict[str, Any]], first_mode: bool, row_count: int) -> str:
    if not first_mode:
        return ""
    remaining = _games_remaining(games)
    if row_count > 0:
        return ""
    if remaining > 0:
        return (
            "First-basket trends are still generating, or play-by-play "
            "has not loaded yet. Keep this tab open and refresh in a minute "
            f"— {remaining} game(s) still on tonight's slate."
        )
    if games:
        return "No games left today. Check back tomorrow for the next slate."
    return "No games on tonight's slate."



STORE = BoardStore()
