"""Write tonight's ranked board to JSON, CSV, and a static HTML page."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .ranking import PropRow, WEIGHTS, MIN_AVG_MINUTES, MIN_GAMES, STREAK_CAP, VENUE_MIN_GAMES
from .sports.base import Game, GameLog, Player

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "board.html"



def _stamp_log(log: dict, flags: dict | None) -> dict:
    eid = str(log.get("event_id") or "")
    if flags and eid in flags:
        log["first_score"] = int(flags[eid])
    return log


def write_json(
    path: Path,
    *,
    sport: str,
    date: str,
    generated_at: str,
    sources: list[str],
    games: list[Game],
    players: list[Player],
    logs: dict[str, list[GameLog]],
    rows: list[PropRow],
    notes: list[str],
    first_score_rows: list[dict] | None = None,
    first_score_meta: dict | None = None,
    first_score_flags: dict | None = None,
) -> None:
    payload = {
        "sport": sport,
        "date": date,
        "timezone": "America/New_York",
        "generated_at": generated_at,
        "sources": sources,
        "formula": {
            "description": (
                "Trend score is a 0-100 blend of window hit rates and streaks: "
                "L4 16%, L5 16%, L8 14%, L10 14%, L15 10%, L20 10%, "
                f"game streak 10% (capped at {STREAK_CAP}), and the matching "
                "home or away streak 10%. Live/standard odds are not in the score."
            ),
            "weights": WEIGHTS,
            "streak_cap": STREAK_CAP,
            "min_games": MIN_GAMES,
            "min_avg_minutes": MIN_AVG_MINUTES,
            "venue_min_games": VENUE_MIN_GAMES,
        },
        "notes": notes,
        "games": [g if isinstance(g, dict) else g.to_dict() for g in games],
        "players": {
            p.id: {
                **p.to_dict(),
                "logs": [
                    _stamp_log(log.to_dict(), (first_score_flags or {}).get(p.id, {}))
                    for log in logs.get(p.id, [])
                ],
            }
            for p in players
            if str(p.id) in {str(r.player_id) for r in rows} | {str(r.get("player_id")) for r in (first_score_rows or [])}
        },
        "rows": [r.to_dict() for r in rows],
        "first_score_rows": list(first_score_rows or []),
        "first_score_meta": first_score_meta or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[PropRow]) -> None:
    fields = [
        "rank",
        "player",
        "team",
        "opponent",
        "venue",
        "game",
        "game_time_et",
        "prop",
        "side",
        "line",
        "display_line",
        "line_label",
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
        "rest_days",
        "is_b2b",
        "score",
        "games_played",
        "avg_minutes",
        "injury_status",
        "injury_detail",
        "event_id",
        "player_id",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for i, row in enumerate(rows, start=1):
            d = row.to_dict()
            writer.writerow({k: (i if k == "rank" else d.get(k, "")) for k in fields})


def write_html(
    path: Path,
    *,
    sport: str,
    date: str,
    generated_at: str,
    games: list[Game],
    players: list[Player],
    logs: dict[str, list[GameLog]],
    rows: list[PropRow],
    notes: list[str],
) -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data = {
        "sport": sport.upper(),
        "date": date,
        "generated_at": generated_at,
        "notes": notes,
        "games": [g.to_dict() for g in games],
        "players": {
            p.id: {
                "id": p.id,
                "name": p.name,
                "team": p.team_abbr,
                "team_name": p.team_name,
                "position": p.position,
                "headshot": p.headshot,
                "injury_status": p.injury_status,
                "injury_detail": p.injury_detail,
                "injury_comment": p.injury_comment,
                "logs": [log.to_dict() for log in logs.get(p.id, [])][:20],
            }
            for p in players
        },
        "rows": [r.to_dict() for r in rows],
    }
    encoded = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    html = template.replace("/*__BOARD_DATA__*/", encoded)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
