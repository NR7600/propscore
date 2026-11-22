"""NHL adapter: ESPN public JSON (free, no key).

Scoreboard, rosters, injuries, and athlete game logs all work from
site.api / site.web.api. ESPN's season year is the year the season
ends, so 2026-27 is `2027`.

Skater logs include goals, assists, points, shots, and time on ice.
They do not include hits or blocked shots, so those props are omitted.
Goalie logs include games started, TOI, and saves.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ..http import HttpClient
from .base import Game, GameLog, Injury, Player, merge_season_logs

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams/{team_id}/roster"
INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"
GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/hockey/nhl/athletes/{player_id}/gamelog"

# ESPN season filter year is the year the season *ends*.
SEASON_YEAR = 2027

SKATER_INDEX = {
    "goals": 0,
    "assists": 1,
    "points": 2,
    "shots": 5,
    "toi": 12,
}

GOALIE_INDEX = {
    "started": 0,
    "toi": 1,
    "saves": 9,
}

SKATER_PROPS = ["goals", "assists", "points", "shots"]
GOALIE_PROPS = ["saves"]


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _et_label(utc_iso: str) -> str:
    dt = _parse_iso(utc_iso)
    if not dt:
        return utc_iso
    local = dt.astimezone(ET)
    return local.strftime("%-I:%M %p ET")


def _log_date(game_date: str) -> str:
    """Use ESPN's own calendar date (YYYY-MM-DD prefix)."""
    return (game_date or "")[:10]


def _parse_minutes(raw: str | int | float | None) -> float:
    if raw is None or raw == "":
        return 0.0
    text = str(raw).strip()
    if text in {"--", "DNP", "N/A", "*", "DND"}:
        return 0.0
    if ":" in text:
        try:
            minutes, seconds = text.split(":", 1)
            return int(minutes) + int(seconds) / 60.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_int(raw: str | int | float | None) -> int:
    if raw is None or raw == "" or raw == "--":
        return 0
    text = str(raw).replace(",", "").lstrip(".")
    # Save pct comes as .944 — not used as an int stat, but be safe.
    try:
        return int(float(text))
    except ValueError:
        return 0


def _stat(stats: list, index: int, default=0):
    if index >= len(stats):
        return default
    return stats[index]


def _id_from_injury_athlete(athlete: dict) -> str | None:
    if athlete.get("id"):
        return str(athlete["id"])
    headshot = (athlete.get("headshot") or {}).get("href") or ""
    m = re.search(r"/full/(\d+)\.(?:png|jpg)", headshot)
    if m:
        return m.group(1)
    for link in athlete.get("links") or []:
        href = link.get("href") or ""
        m = re.search(r"/id/(\d+)", href)
        if m:
            return m.group(1)
    return None


def _is_goalie(player: Player) -> bool:
    pos = (player.position or "").upper().strip()
    return player.role == "goalie" or pos in {"G", "GOALIE"}


def _flatten_roster(athletes: list) -> list[dict]:
    """ESPN NHL rosters are grouped by position; NBA ones are flat."""
    out: list[dict] = []
    for entry in athletes or []:
        if isinstance(entry, dict) and entry.get("id") and (
            entry.get("displayName") or entry.get("fullName")
        ):
            out.append(entry)
            continue
        items = []
        if isinstance(entry, dict):
            items = entry.get("items") or entry.get("athletes") or []
        for item in items:
            if isinstance(item, dict):
                out.append(item)
    return out


class NHL:
    key = "nhl"
    display_name = "NHL"
    props = {
        "goals": "G",
        "assists": "A",
        "points": "PTS",
        "shots": "SOG",
        "saves": "SV",
    }

    def __init__(self, client: HttpClient):
        self.client = client

    def qualification(self, player: Player) -> dict:
        if _is_goalie(player):
            return {
                "min_games": 5,
                "min_avg_minutes": 0,
                "starts_only": True,
                "props": list(GOALIE_PROPS),
            }
        return {
            "min_games": 5,
            "min_avg_minutes": 10.0,
            "starts_only": False,
            "props": list(SKATER_PROPS),
        }

    def fetch_slate(self, date: str) -> list[Game]:
        yyyymmdd = date.replace("-", "")
        data = self.client.get_json(
            SCOREBOARD_URL,
            params={"dates": yyyymmdd},
            cache_key=f"nhl_scoreboard_{yyyymmdd}",
            use_cache=False,
        )
        games: list[Game] = []
        for event in data.get("events") or []:
            comps = event.get("competitions") or []
            if not comps:
                continue
            comp = comps[0]
            home = away = None
            for c in comp.get("competitors") or []:
                team = c.get("team") or {}
                packed = {
                    "id": str(team.get("id") or c.get("id") or ""),
                    "abbr": team.get("abbreviation") or "",
                    "name": team.get("displayName") or team.get("name") or "",
                }
                if c.get("homeAway") == "home":
                    home = packed
                else:
                    away = packed
            if not home or not away:
                continue
            start = event.get("date") or comp.get("date") or ""
            status = (
                (event.get("status") or {}).get("type") or {}
            ).get("description") or "Scheduled"
            games.append(
                Game(
                    event_id=str(event.get("id") or comp.get("id") or ""),
                    start_utc=start,
                    start_et=_et_label(start),
                    home_id=home["id"],
                    home_abbr=home["abbr"],
                    home_name=home["name"],
                    away_id=away["id"],
                    away_abbr=away["abbr"],
                    away_name=away["name"],
                    status=status,
                )
            )
        games.sort(key=lambda g: g.start_utc)
        return games

    def fetch_injuries(self) -> list[Injury]:
        data = self.client.get_json(INJURIES_URL, cache_key="nhl_injuries")
        out: list[Injury] = []
        for team in data.get("injuries") or []:
            for item in team.get("injuries") or []:
                athlete = item.get("athlete") or {}
                details = item.get("details") or {}
                detail_parts = [
                    details.get("type"),
                    details.get("detail"),
                    (details.get("side") + " side") if details.get("side") else None,
                ]
                detail = " ".join(p for p in detail_parts if p).strip() or None
                comment = item.get("shortComment") or item.get("longComment")
                out.append(
                    Injury(
                        player_id=_id_from_injury_athlete(athlete),
                        player_name=athlete.get("displayName") or "",
                        status=item.get("status") or "",
                        detail=detail,
                        comment=comment,
                        return_date=details.get("returnDate"),
                    )
                )
        return out

    def fetch_roster(self, team_id: str, team_abbr: str, team_name: str) -> list[Player]:
        data = self.client.get_json(
            ROSTER_URL.format(team_id=team_id),
            cache_key=f"nhl_roster_{team_id}",
        )
        players: list[Player] = []
        for a in _flatten_roster(data.get("athletes") or []):
            position = a.get("position") or {}
            if isinstance(position, dict):
                pos = position.get("abbreviation") or position.get("displayName") or ""
            else:
                pos = str(position or "")
            role = "goalie" if pos.upper() in {"G", "GOALIE"} else "skater"
            headshot = (a.get("headshot") or {}).get("href") or ""
            if not headshot and a.get("id"):
                headshot = f"https://a.espncdn.com/i/headshots/nhl/players/full/{a['id']}.png"
            roster_inj = (a.get("injuries") or [None])[0] if a.get("injuries") else None
            inj_status = (roster_inj or {}).get("status") if roster_inj else None
            players.append(
                Player(
                    id=str(a.get("id") or ""),
                    name=a.get("displayName") or a.get("fullName") or "",
                    short_name=a.get("shortName") or "",
                    team_id=str(team_id),
                    team_abbr=team_abbr,
                    team_name=team_name,
                    position=pos,
                    jersey=str(a.get("jersey") or ""),
                    headshot=headshot,
                    role=role,
                    injury_status=inj_status or None,
                )
            )
        return [p for p in players if p.id and p.name]

    def apply_injuries(self, players: list[Player], injuries: list[Injury]) -> None:
        by_id = {i.player_id: i for i in injuries if i.player_id}
        by_name = {i.player_name.strip().lower(): i for i in injuries if i.player_name}
        for p in players:
            inj = by_id.get(p.id) or by_name.get(p.name.strip().lower())
            if not inj:
                continue
            p.injury_status = inj.status or p.injury_status
            p.injury_detail = inj.detail
            p.injury_comment = inj.comment
            p.injury_return = inj.return_date

    def fetch_game_logs(self, player_id: str) -> list[GameLog]:
        current = self._fetch_season_logs(player_id, SEASON_YEAR, prior=False)
        return merge_season_logs(
            current,
            lambda year: self._fetch_season_logs(player_id, year, prior=True),
            SEASON_YEAR,
        )

    def _fetch_season_logs(self, player_id: str, season_year: int, prior: bool) -> list[GameLog]:
        data = self.client.get_json(
            GAMELOG_URL.format(player_id=player_id),
            params={"season": season_year},
            cache_key=f"nhl_gamelog_{player_id}_{season_year}",
            allow_404=True,
        )
        if not data:
            return []
        labels = [str(x).upper() for x in (data.get("labels") or [])]
        is_goalie = "SV" in labels or "GS" in labels
        events_meta = data.get("events") or {}
        rows: list[GameLog] = []
        for season_type in data.get("seasonTypes") or []:
            name = (season_type.get("displayName") or "").lower()
            if "regular" not in name:
                continue
            for category in season_type.get("categories") or []:
                if category.get("type") != "event":
                    continue
                for ev in category.get("events") or []:
                    event_id = str(ev.get("eventId") or "")
                    stats = ev.get("stats") or []
                    meta = events_meta.get(event_id) or {}
                    at_vs = (meta.get("atVs") or "").strip()
                    is_home = at_vs.lower() in {"vs", "vs."}
                    opponent = (meta.get("opponent") or {}).get("abbreviation") or ""
                    if is_goalie:
                        minutes = _parse_minutes(_stat(stats, GOALIE_INDEX["toi"], "0"))
                        started = _parse_int(_stat(stats, GOALIE_INDEX["started"], 0)) == 1
                        saves = _parse_int(_stat(stats, GOALIE_INDEX["saves"], 0))
                        rows.append(
                            GameLog(
                                event_id=event_id,
                                date=_log_date(meta.get("gameDate") or ""),
                                opponent_abbr=opponent,
                                is_home=is_home,
                                minutes=round(minutes, 1),
                                points=0,
                                rebounds=0,
                                assists=0,
                                threes=0,
                                pra=0,
                                result=meta.get("gameResult"),
                                saves=saves,
                                started=started,
                                prior_season=prior,
                                season_year=season_year,
                            )
                        )
                    else:
                        minutes = _parse_minutes(_stat(stats, SKATER_INDEX["toi"], "0"))
                        goals = _parse_int(_stat(stats, SKATER_INDEX["goals"], 0))
                        assists = _parse_int(_stat(stats, SKATER_INDEX["assists"], 0))
                        points = _parse_int(_stat(stats, SKATER_INDEX["points"], 0))
                        shots = _parse_int(_stat(stats, SKATER_INDEX["shots"], 0))
                        if points == 0 and (goals or assists):
                            points = goals + assists
                        rows.append(
                            GameLog(
                                event_id=event_id,
                                date=_log_date(meta.get("gameDate") or ""),
                                opponent_abbr=opponent,
                                is_home=is_home,
                                minutes=round(minutes, 1),
                                points=points,
                                rebounds=0,
                                assists=assists,
                                threes=0,
                                pra=0,
                                result=meta.get("gameResult"),
                                goals=goals,
                                shots=shots,
                                started=minutes > 0,
                                prior_season=prior,
                                season_year=season_year,
                            )
                        )
        uniq: dict[str, GameLog] = {}
        for row in rows:
            uniq[row.event_id or f"{row.date}-{row.opponent_abbr}"] = row
        return sorted(uniq.values(), key=lambda g: (g.date, g.event_id), reverse=True)
