"""NBA adapter: ESPN public JSON (free, no key).

cdn.nba.com and stats.nba.com were tried from this environment and
did not work (403 / timeout). ESPN's public site APIs return live
2026-27 scoreboard, rosters, injuries, and player game logs.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ..http import HttpClient
from .base import Game, GameLog, Injury, Player

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/gamelog"

# ESPN season filter year is the year the season *ends*.
SEASON_YEAR = 2027

STAT_INDEX = {
    "minutes": 0,
    "fg_made_att": 1,
    "threes_made_att": 3,
    "rebounds": 7,
    "assists": 8,
    "blocks": 9,
    "steals": 10,
    "turnovers": 12,
    "points": 13,
}

# ESPN season filter year is the year the season *ends*.
PRIOR_SEASON_YEARS = (SEASON_YEAR - 1, SEASON_YEAR - 2)


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
    """Use ESPN's own calendar date (YYYY-MM-DD prefix).

    Converting midnight-UTC or offset timestamps into America/New_York
    can shift a game back one day and scramble last-N order. The ESPN
    date prefix matches the date shown on ESPN player pages.
    """
    return (game_date or "")[:10]


def _parse_minutes(raw: str | int | float | None) -> float:
    if raw is None or raw == "":
        return 0.0
    text = str(raw).strip()
    if text in {"--", "DNP", "N/A", "*"}:
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


def _parse_made(raw: str | None) -> int:
    """'2-4' -> 2; '2' -> 2."""
    if raw is None or raw == "" or raw == "--":
        return 0
    text = str(raw)
    if "-" in text:
        text = text.split("-", 1)[0]
    try:
        return int(float(text))
    except ValueError:
        return 0


def _parse_int(raw: str | int | float | None) -> int:
    if raw is None or raw == "" or raw == "--":
        return 0
    try:
        return int(float(str(raw)))
    except ValueError:
        return 0


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



def _events_from_gamelog(data: dict, season_year: int, prior: bool) -> list[GameLog]:
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
                minutes = _parse_minutes(stats[STAT_INDEX["minutes"]] if len(stats) > STAT_INDEX["minutes"] else None)
                points = _parse_int(stats[STAT_INDEX["points"]] if len(stats) > STAT_INDEX["points"] else 0)
                rebounds = _parse_int(stats[STAT_INDEX["rebounds"]] if len(stats) > STAT_INDEX["rebounds"] else 0)
                assists = _parse_int(stats[STAT_INDEX["assists"]] if len(stats) > STAT_INDEX["assists"] else 0)
                threes = _parse_made(
                    stats[STAT_INDEX["threes_made_att"]]
                    if len(stats) > STAT_INDEX["threes_made_att"]
                    else 0
                )
                fgm = _parse_made(
                    stats[STAT_INDEX["fg_made_att"]]
                    if len(stats) > STAT_INDEX["fg_made_att"]
                    else 0
                )
                steals = _parse_int(stats[STAT_INDEX["steals"]] if len(stats) > STAT_INDEX["steals"] else 0)
                blocked = _parse_int(stats[STAT_INDEX["blocks"]] if len(stats) > STAT_INDEX["blocks"] else 0)
                turnovers = _parse_int(stats[STAT_INDEX["turnovers"]] if len(stats) > STAT_INDEX["turnovers"] else 0)
                at_vs = (meta.get("atVs") or "").strip()
                is_home = at_vs.lower() in {"vs", "vs."}
                opponent = (meta.get("opponent") or {}).get("abbreviation") or ""
                rows.append(
                    GameLog(
                        event_id=event_id,
                        date=_log_date(meta.get("gameDate") or ""),
                        opponent_abbr=opponent,
                        is_home=is_home,
                        minutes=round(minutes, 1),
                        points=points,
                        rebounds=rebounds,
                        assists=assists,
                        threes=threes,
                        pra=points + rebounds + assists,
                        result=meta.get("gameResult"),
                        steals=steals,
                        blocked=blocked,
                        fgm=fgm,
                        turnovers=turnovers,
                        prior_season=prior,
                        season_year=season_year,
                    )
                )
    return rows


class NBA:
    key = "nba"
    display_name = "NBA"
    props = {
        "points": "PTS",
        "rebounds": "REB",
        "assists": "AST",
        "threes": "3PM",
        "pra": "PRA",
        "pts_reb": "PTS+REB",
        "pts_ast": "PTS+AST",
        "reb_ast": "REB+AST",
        "steals": "STL",
        "blocks": "BLK",
        "turnovers": "TO",
        "stl_blk": "BLK+STL",
    }

    def __init__(self, client: HttpClient):
        self.client = client

    def fetch_slate(self, date: str) -> list[Game]:
        yyyymmdd = date.replace("-", "")
        data = self.client.get_json(
            SCOREBOARD_URL,
            params={"dates": yyyymmdd},
            cache_key=f"nba_scoreboard_{yyyymmdd}",
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
        data = self.client.get_json(INJURIES_URL, cache_key="nba_injuries")
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
            cache_key=f"nba_roster_{team_id}",
        )
        players: list[Player] = []
        for a in data.get("athletes") or []:
            position = a.get("position") or {}
            if isinstance(position, dict):
                pos = position.get("abbreviation") or position.get("displayName") or ""
            else:
                pos = str(position or "")
            headshot = (a.get("headshot") or {}).get("href") or ""
            if not headshot and a.get("id"):
                headshot = f"https://a.espncdn.com/i/headshots/nba/players/full/{a['id']}.png"
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
        rows = list(self._fetch_season_logs(player_id, SEASON_YEAR, prior=False))
        current_n = sum(1 for g in rows if g.minutes and g.minutes > 0)
        # Always attach two prior regular seasons so L15/L20 and long
        # home/away streaks (e.g. a 53-game road run) can form.
        for year in PRIOR_SEASON_YEARS:
            if current_n >= 80 and any(g.season_year == year for g in rows):
                break
            rows.extend(self._fetch_season_logs(player_id, year, prior=True))
        uniq: dict[str, GameLog] = {}
        for row in rows:
            uniq[row.event_id or f"{row.date}-{row.opponent_abbr}"] = row
        return sorted(uniq.values(), key=lambda g: (g.date, g.event_id), reverse=True)

    def _fetch_season_logs(self, player_id: str, season_year: int, prior: bool) -> list[GameLog]:
        data = self.client.get_json(
            GAMELOG_URL.format(player_id=player_id),
            params={"season": season_year},
            cache_key=f"nba_gamelog_{player_id}_{season_year}",
        )
        return _events_from_gamelog(data or {}, season_year, prior)
