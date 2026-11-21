"""NFL adapter: ESPN public football JSON (free, no key).

Scoreboard, rosters, injuries, and athlete gamelogs. ESPN's NFL season
year is the year the season *starts*, so 2026-27 is `2026`.

Only skill-position players (QB, RB, FB, WR, TE) are loaded from the
offense / IR groups. Game logs are parsed by ESPN's `names` list because
QB, RB, and WR columns differ. When this season has fewer than 20
regular-season games, last season is appended and marked prior_season.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..http import HttpClient
from .base import Game, GameLog, Injury, Player

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"
INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{player_id}/gamelog"

# ESPN NFL season year is the year the season starts.
SEASON_YEAR = 2026
PRIOR_SEASON_YEAR = SEASON_YEAR - 1

SKILL_POS = {"QB", "RB", "FB", "WR", "TE", "HB", "TB", "WB"}
SKIP_GROUPS = {"defense", "specialteam", "specialteams", "practicesquad"}

PASS_PROPS = ["pass_yds", "pass_td", "completions", "pass_att", "ints"]
RUSH_PROPS = ["rush_yds", "rush_att"]
REC_PROPS = ["receptions", "rec_yds"]
COMBO_PROPS = ["rush_rec_yds", "anytime_td"]

MIN_SEASON_GAMES = 3
MIN_PASS_ATT = 8.0
MIN_RUSH_ATT = 5.0
MIN_TARGETS = 3.0
MIN_RECEPTIONS = 2.0
LOOKAHEAD_DAYS = 3


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
    return (game_date or "")[:10]


def _parse_int(raw: str | int | float | None) -> int:
    if raw is None or raw == "" or raw == "--" or raw == "-":
        return 0
    text = str(raw).replace(",", "").lstrip(".")
    try:
        return int(float(text))
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


def _pos_abbr(athlete: dict) -> str:
    position = athlete.get("position") or {}
    if isinstance(position, dict):
        return (position.get("abbreviation") or position.get("displayName") or "").upper()
    return str(position or "").upper()


def _is_skill(athlete: dict) -> bool:
    return _pos_abbr(athlete) in SKILL_POS


def _stat(stats: list, index: dict[str, int], name: str) -> int:
    idx = index.get(name)
    if idx is None or idx >= len(stats):
        return 0
    return _parse_int(stats[idx])


def _played_role(log: GameLog) -> bool:
    return (
        (log.pass_att or 0) > 0
        or (log.rush_att or 0) > 0
        or (log.receptions or 0) > 0
        or (log.targets or 0) > 0
        or (log.pass_yds or 0) != 0
        or (log.rush_yds or 0) != 0
        or (log.rec_yds or 0) != 0
        or (log.anytime_td or 0) > 0
    )


def _events_from_gamelog(data: dict, season_year: int, prior: bool) -> list[GameLog]:
    names = [str(n) for n in (data.get("names") or [])]
    index = {name: i for i, name in enumerate(names)}
    events_meta = data.get("events") or {}
    rows: list[GameLog] = []
    for season_type in data.get("seasonTypes") or []:
        label = (season_type.get("displayName") or "").lower()
        if "regular" not in label:
            continue
        for category in season_type.get("categories") or []:
            if category.get("type") != "event":
                continue
            for ev in category.get("events") or []:
                event_id = str(ev.get("eventId") or "")
                stats = ev.get("stats") or []
                meta = events_meta.get(event_id) or {}
                pass_yds = _stat(stats, index, "passingYards")
                pass_td = _stat(stats, index, "passingTouchdowns")
                completions = _stat(stats, index, "completions")
                pass_att = _stat(stats, index, "passingAttempts")
                ints = _stat(stats, index, "interceptions")
                rush_yds = _stat(stats, index, "rushingYards")
                rush_att = _stat(stats, index, "rushingAttempts")
                rush_td = _stat(stats, index, "rushingTouchdowns")
                rec = _stat(stats, index, "receptions")
                rec_yds = _stat(stats, index, "receivingYards")
                rec_td = _stat(stats, index, "receivingTouchdowns")
                targets = _stat(stats, index, "receivingTargets")
                anytime = rush_td + rec_td
                at_vs = (meta.get("atVs") or "").strip()
                is_home = at_vs.lower() in {"vs", "vs."}
                opponent = (meta.get("opponent") or {}).get("abbreviation") or ""
                row = GameLog(
                    event_id=event_id,
                    date=_log_date(meta.get("gameDate") or ""),
                    opponent_abbr=opponent,
                    is_home=is_home,
                    minutes=0.0,
                    points=0,
                    rebounds=0,
                    assists=0,
                    threes=0,
                    pra=0,
                    result=meta.get("gameResult"),
                    pass_yds=pass_yds,
                    pass_td=pass_td,
                    completions=completions,
                    pass_att=pass_att,
                    ints=ints,
                    rush_yds=rush_yds,
                    rush_att=rush_att,
                    rush_td=rush_td,
                    receptions=rec,
                    rec_yds=rec_yds,
                    rec_td=rec_td,
                    targets=targets,
                    anytime_td=anytime,
                    prior_season=prior,
                    season_year=season_year,
                )
                if not _played_role(row):
                    continue
                row.minutes = 1.0
                rows.append(row)
    return rows


def _parse_games(data: dict) -> list[Game]:
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
        status = ((event.get("status") or {}).get("type") or {}).get("description") or "Scheduled"
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


def date_with_games(client: HttpClient, start_date: str, lookahead: int = LOOKAHEAD_DAYS) -> str:
    """First date on or after start_date (ET) that has NFL games, up to lookahead days."""
    try:
        day = date.fromisoformat(start_date)
    except ValueError:
        return start_date
    sport = NFL(client)
    for i in range(max(0, lookahead) + 1):
        candidate = (day + timedelta(days=i)).isoformat()
        if sport.fetch_slate(candidate):
            return candidate
    return start_date


class NFL:
    key = "nfl"
    display_name = "NFL"
    props = {
        "pass_yds": "PASS YDS",
        "pass_td": "PASS TD",
        "completions": "CMP",
        "pass_att": "PASS ATT",
        "ints": "INT",
        "rush_yds": "RUSH YDS",
        "rush_att": "RUSH ATT",
        "receptions": "REC",
        "rec_yds": "REC YDS",
        "rush_rec_yds": "RUSH+REC",
        "anytime_td": "ANY TD",
    }

    def __init__(self, client: HttpClient):
        self.client = client

    def qualification(self, player: Player) -> dict:
        return {
            "min_games": MIN_SEASON_GAMES,
            "min_avg_minutes": 0,
            "starts_only": False,
            "min_season_games": MIN_SEASON_GAMES,
            "props": list(self.props.keys()),
            "role_filter": True,
        }

    def props_for_logs(self, logs: list[GameLog]) -> list[str]:
        current = [g for g in logs if not getattr(g, "prior_season", False)]
        sample = current or logs
        if not sample:
            return []
        n = len(sample)
        avg_att = sum(g.pass_att for g in sample) / n
        avg_rush = sum(g.rush_att for g in sample) / n
        avg_tgt = sum(g.targets for g in sample) / n
        avg_rec = sum(g.receptions for g in sample) / n
        out: list[str] = []
        if avg_att >= MIN_PASS_ATT:
            out.extend(PASS_PROPS)
        if avg_rush >= MIN_RUSH_ATT:
            out.extend(RUSH_PROPS)
        if avg_tgt >= MIN_TARGETS or avg_rec >= MIN_RECEPTIONS:
            out.extend(REC_PROPS)
        if avg_rush + avg_rec >= MIN_RUSH_ATT or any(p in out for p in RUSH_PROPS + REC_PROPS):
            if "rush_rec_yds" not in out:
                out.append("rush_rec_yds")
        if out:
            if "anytime_td" not in out:
                out.append("anytime_td")
        return out

    def fetch_slate(self, date: str) -> list[Game]:
        yyyymmdd = date.replace("-", "")
        data = self.client.get_json(
            SCOREBOARD_URL,
            params={"dates": yyyymmdd},
            cache_key=f"nfl_scoreboard_{yyyymmdd}",
            use_cache=False,
        )
        return _parse_games(data)

    def fetch_injuries(self) -> list[Injury]:
        data = self.client.get_json(INJURIES_URL, cache_key="nfl_injuries")
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
            cache_key=f"nfl_roster_{team_id}",
        )
        players: list[Player] = []
        for group in data.get("athletes") or []:
            group_name = str(
                (group.get("position") or group.get("name") or group.get("displayName") or "")
            ).lower().replace(" ", "")
            items = group.get("items") or group.get("athletes") or []
            if not items and group.get("id"):
                items = [group]
            if group_name in SKIP_GROUPS:
                continue
            for a in items:
                if not _is_skill(a):
                    continue
                pos = _pos_abbr(a)
                headshot = (a.get("headshot") or {}).get("href") or ""
                if not headshot and a.get("id"):
                    headshot = f"https://a.espncdn.com/i/headshots/nfl/players/full/{a['id']}.png"
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
                        role="skill",
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
        played_now = [g for g in current if _played_role(g)]
        rows = list(current)
        if 3 <= len(played_now) < 20:
            prior = self._fetch_season_logs(player_id, PRIOR_SEASON_YEAR, prior=True)
            rows.extend(prior)
        uniq: dict[str, GameLog] = {}
        for row in rows:
            uniq[row.event_id or f"{row.date}-{row.opponent_abbr}"] = row
        return sorted(uniq.values(), key=lambda g: (g.date, g.event_id), reverse=True)

    def _fetch_season_logs(self, player_id: str, season_year: int, prior: bool) -> list[GameLog]:
        data = self.client.get_json(
            GAMELOG_URL.format(player_id=player_id),
            params={"season": season_year},
            cache_key=f"nfl_gamelog_{player_id}_{season_year}",
        )
        return _events_from_gamelog(data or {}, season_year, prior)
