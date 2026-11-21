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
    "l5",
    "l10",
    "l20",
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
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        data = self.get(sport, date)
        rows = _filter_rows(
            data.get("rows") or [],
            sport=sport,
            stat=stat,
            game=game,
            min_l10=min_l10,
            hide_out=hide_out,
            hide_gimme=hide_gimme,
            view=view,
            q=q,
            side=side,
            perfect=perfect,
            sort=sort,
            min_odds=min_odds,
        )
        page = max(1, page)
        page_size = min(max(1, page_size), 50)
        total = len(rows)
        total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
        if page > total_pages:
            page = total_pages
        start = (page - 1) * page_size
        slice_ = [_compact_row(r) for r in rows[start : start + page_size]]
        return {
            "sport": data.get("sport", sport),
            "date": data.get("date", date),
            "timezone": data.get("timezone", "America/New_York"),
            "generated_at": data.get("generated_at"),
            "stale": data.get("date") != today_et(),
            "view": "value" if view == "value" else "all",
            "view_label": _view_label(view, min_l10),
            "games": data.get("games") or [],
            "filters": {
                "stat": stat or "",
                "game": game or "",
                "min_l10": min_l10,
                "hide_out": hide_out,
                "hide_gimme": hide_gimme,
                "q": q or "",
                "side": side or "",
                "perfect": perfect,
                "sort": sort or "score",
                "min_odds": min_odds,
            },
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_more": page < total_pages,
            "props": props_for_sport(sport),
            "rows": slice_,
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
        # Prefer a score-sorted list so the detail page can pick a default line.
        rows.sort(key=lambda r: (-(r.get("score") or 0), -(r.get("l10") or 0)))
        game = None
        if rows:
            event_id = rows[0].get("event_id")
            game = next((g for g in (data.get("games") or []) if g.get("event_id") == event_id), None)
        logs = list(player.get("logs") or [])
        # Newest first already; cap to 20 for the chart.
        return {
            "sport": data.get("sport", sport),
            "date": data.get("date", date),
            "player": {k: v for k, v in player.items() if k != "logs"},
            "game": game,
            "logs": logs[:20],
            "rows": rows,
        }


def _view_label(view: str, min_l10: float) -> str:
    pct = int(round(min_l10 * 100)) if min_l10 else 70
    if view == "value":
        return (
            f"Best value: for each player and stat, the highest line still "
            f"clearing {pct}% of his last 10 games."
        )
    return "All qualifying lines, ranked by trend score."


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
    if row.get("line_source") == "live":
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


STORE = BoardStore()
