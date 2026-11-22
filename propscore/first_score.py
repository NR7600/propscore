"""First-FGM (NBA) and first-goal (NHL) trends from ESPN play-by-play.

NBA "First FGM" is the player who made the first field goal of the
game (either team). Free throws do not count. NHL is the first goal of
the game. Summaries are large, so only a compact record is written to
disk and later runs fetch only uncached event IDs.
"""

from __future__ import annotations

import json
import re
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .http import DEFAULT_HEADERS
from .odds import get_offers, line_label
from .ranking import (
    MIN_GAMES,
    STREAK_CAP,
    VENUE_MIN_GAMES,
    _played,
    _rest,
    trend_score,
    strong_trend_score,
    select_display_windows,
)
from .sports.base import Game, GameLog, Player

log = logging.getLogger("propscore.first_score")

ET = ZoneInfo("America/New_York")
SEASON_YEAR = 2027
MIN_FIRST_GAMES = 8
# v2 stores the GAME's first field goal (NBA, FTs excluded) or first
# goal (NHL), not each team's first score. Old compact records are ignored.
CACHE_SCHEMA = 2
FETCH_BUDGET_SEC = 400
WORKERS = 6
TIMEOUT = 20
RETRIES = 2

SPORT_META = {
    "nba": {
        "path": "basketball/nba",
        "prop": "first_basket",
        "prop_label": "1FG",
        "prop_full": "First FGM",
        "line_label": "First FGM Over 0.5",
        "kind": "first_basket",
        "tab_label": "1FG (First Basket)",
        "season_year": 2027,
    },
    "nhl": {
        "path": "hockey/nhl",
        "prop": "first_goal",
        "prop_label": "1G",
        "prop_full": "First Goal",
        "line_label": "First Goal Over 0.5",
        "kind": "first_goal",
        "tab_label": "1G (First Goal)",
        "season_year": 2027,
    },
    "nfl": {
        "path": "football/nfl",
        "prop": "first_td",
        "prop_label": "1TD",
        "prop_full": "First TD",
        "line_label": "First TD Over 0.5",
        "kind": "first_td",
        "tab_label": "1TD (First TD)",
        "season_year": 2026,
    },
}


def sport_meta(sport: str) -> dict[str, str]:
    return SPORT_META[sport]


def cache_dir(root: Path, sport: str) -> Path:
    path = Path(root) / "first_score" / sport
    path.mkdir(parents=True, exist_ok=True)
    return path


def _event_path(folder: Path, event_id: str) -> Path:
    return folder / f"{event_id}.json"


def load_cached(folder: Path, event_id: str) -> dict[str, Any] | None:
    path = _event_path(folder, event_id)
    if not path.exists():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if int(rec.get("schema") or 0) < CACHE_SCHEMA:
        return None
    if not rec.get("first_fgm"):
        return None
    return rec


def save_cached(folder: Path, record: dict[str, Any]) -> None:
    eid = str(record.get("event_id") or "")
    if not eid:
        return
    path = _event_path(folder, eid)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _athlete_id(part: Any) -> str | None:
    if not isinstance(part, dict):
        return None
    ath = part.get("athlete") or part
    if not isinstance(ath, dict):
        return None
    aid = ath.get("id")
    return str(aid) if aid else None


def _athlete_name(part: Any) -> str:
    if not isinstance(part, dict):
        return ""
    ath = part.get("athlete") or {}
    return str(ath.get("displayName") or ath.get("shortName") or "")


def _play_team_id(play: dict[str, Any]) -> str | None:
    team = play.get("team") or {}
    if isinstance(team, dict) and team.get("id"):
        return str(team["id"])
    return None


def _play_type(play: dict[str, Any]) -> str:
    typ = play.get("type") or {}
    if isinstance(typ, dict):
        return str(typ.get("text") or typ.get("abbreviation") or "")
    return str(typ or "")


def _parse_minutes(raw: Any) -> float:
    if raw is None or raw == "":
        return 0.0
    text = str(raw).strip()
    if not text or text in {"--", "-"}:
        return 0.0
    if ":" in text:
        try:
            mins, sec = text.split(":", 1)
            return int(mins) + int(sec) / 60.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _header_date_et(header: dict[str, Any], comps: dict[str, Any]) -> str:
    raw = comps.get("date") or header.get("competitions", [{}])[0].get("date") or ""
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(ET)
        return dt.date().isoformat()
    except ValueError:
        return str(raw)[:10]


def _box_played(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for group in (data.get("boxscore") or {}).get("players") or []:
        tid = str((group.get("team") or {}).get("id") or "")
        for stat in group.get("statistics") or []:
            keys = [str(k).lower() for k in (stat.get("keys") or stat.get("names") or [])]
            min_idx = next(
                (
                    i
                    for i, k in enumerate(keys)
                    if k in {"min", "minutes", "toi", "timeonice", "time_on_ice"}
                ),
                None,
            )
            for ath in stat.get("athletes") or []:
                if ath.get("didNotPlay"):
                    continue
                a = ath.get("athlete") or {}
                pid = str(a.get("id") or "")
                if not pid:
                    continue
                mins = 0.0
                stats = ath.get("stats") or []
                if min_idx is not None and min_idx < len(stats):
                    mins = _parse_minutes(stats[min_idx])
                prev = out.get(pid)
                started = bool(ath.get("starter")) or bool(prev and prev.get("started"))
                out[pid] = {
                    "team_id": tid,
                    "name": a.get("displayName") or a.get("shortName") or "",
                    "started": started,
                    "minutes": max(mins, (prev or {}).get("minutes") or 0.0),
                }
    return out



def _is_free_throw(play: dict[str, Any]) -> bool:
    typ = _play_type(play).lower()
    text = str(play.get("text") or "").lower()
    return "free throw" in typ or "free throw" in text or typ in {"ft", "freethrow"}


def _is_made_field_goal(play: dict[str, Any]) -> bool:
    """True when this play is a made FG (not a free throw)."""
    if not play.get("scoringPlay"):
        return False
    try:
        value = float(play.get("scoreValue") or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return False
    if _is_free_throw(play):
        return False
    typ = _play_type(play).lower()
    text = str(play.get("text") or "").lower()
    if "makes" in text and "free throw" not in text:
        return True
    if play.get("shootingPlay") and "free throw" not in typ:
        return True
    tokens = ("dunk", "layup", "jumper", "jump shot", "hook", "tip", "alley", "floater")
    return any(tok in typ or tok in text for tok in tokens)


def _is_goal(play: dict[str, Any]) -> bool:
    if not play.get("scoringPlay"):
        return False
    typ = _play_type(play).lower()
    text = str(play.get("text") or "").lower()
    if "goal" in typ or typ == "g":
        return True
    try:
        value = float(play.get("scoreValue") or 0)
    except (TypeError, ValueError):
        value = 0.0
    return value > 0 and "goal" in text and "awarded" not in typ



def _is_touchdown(play: dict[str, Any]) -> bool:
    """True for a game touchdown, not a FG, safety, or extra point."""
    scoring = play.get("scoringType") or {}
    if isinstance(scoring, dict):
        name = str(scoring.get("name") or scoring.get("abbreviation") or "").lower()
        if name in {"field-goal", "fieldgoal", "fg", "safety", "sf", "extra-point", "pat"}:
            return False
        if name in {"touchdown", "td"}:
            return True
    typ = _play_type(play).lower()
    text = str(play.get("text") or "").lower()
    if "field goal" in typ or typ in {"fg", "safety"} or "safety" in typ:
        return False
    if "extra point" in typ or "extra point" in text:
        return False
    if "touchdown" in typ or typ == "td":
        return True
    return "touchdown" in text and "field goal" not in text


def _norm_name(value: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _td_scorer_name(text: str) -> str:
    raw = re.sub(r"\s*\([^)]*Kick[^)]*\)\s*$", "", text or "", flags=re.I).strip()
    patterns = (
        r"^(.+?) \d+ Yds? pass from ",
        r"^(.+?) \d+ Yds? (?:Rush|Run|Rushing)\b",
        r"^(.+?) \d+ Yds? .{0,40}Return",
        r"^(.+?) \d+ Yds? Fumble",
        r"^(.+?) \d+ Yds?\b",
    )
    for pat in patterns:
        m = re.match(pat, raw, flags=re.I)
        if m:
            return m.group(1).strip(" .")
    return ""


def _match_player_id(name: str, played: dict[str, dict[str, Any]]) -> tuple[str | None, str]:
    needle = _norm_name(name)
    if not needle:
        return None, name
    exact = []
    last = []
    n_last = needle.split()[-1]
    for pid, info in played.items():
        cand = _norm_name(info.get("name") or "")
        if not cand:
            continue
        if cand == needle:
            exact.append((pid, info.get("name") or name))
            continue
        # "Nico Collins" vs "N. Collins" / "C.J. Stroud"
        if cand.endswith(" " + n_last) or cand.split()[-1] == n_last:
            last.append((pid, info.get("name") or name))
    if len(exact) == 1:
        return exact[0]
    if len(last) == 1:
        return last[0]
    return None, name


def extract_event(data: dict[str, Any], sport: str) -> dict[str, Any] | None:
    header = data.get("header") or {}
    comps = (header.get("competitions") or [{}])[0]
    status = (comps.get("status") or {}).get("type") or {}
    completed = bool(
        status.get("completed")
        or status.get("state") == "post"
        or status.get("name") == "STATUS_FINAL"
    )
    if not completed:
        return None

    home = away = None
    for c in comps.get("competitors") or []:
        team = c.get("team") or {}
        entry = {
            "id": str(c.get("id") or team.get("id") or ""),
            "abbr": team.get("abbreviation") or "",
            "name": team.get("displayName") or team.get("name") or "",
        }
        if c.get("homeAway") == "home":
            home = entry
        else:
            away = entry
    if not home or not away or not home["id"] or not away["id"]:
        return None

    played = _box_played(data)
    team_of = {pid: info["team_id"] for pid, info in played.items()}
    name_of = {pid: info["name"] for pid, info in played.items()}

    plays = data.get("plays") or []
    tip_winner_team_id = None
    tip_winner_player_id = None
    first_fgm: dict[str, Any] | None = None

    def _scorer_from(play: dict[str, Any]) -> tuple[str | None, str]:
        parts = play.get("participants") or []
        scorer_id = None
        scorer_name = ""
        for part in parts:
            if str(part.get("type") or "") in {"scorer", "player"}:
                scorer_id = _athlete_id(part)
                scorer_name = _athlete_name(part)
                break
        if scorer_id is None and parts:
            scorer_id = _athlete_id(parts[0])
            scorer_name = _athlete_name(parts[0])
        return scorer_id, scorer_name

    for play in plays:
        typ = _play_type(play).lower()
        if tip_winner_team_id is None and (
            typ.replace(" ", "") in {"jumpball", "jump-ball"} or typ == "jump ball"
        ):
            parts = play.get("participants") or []
            text = str(play.get("text") or "")
            gained = None
            if "gains possession" in text.lower() and parts:
                gained = _athlete_id(parts[-1])
            elif parts:
                gained = _athlete_id(parts[-1])
            if gained and gained in team_of:
                tip_winner_player_id = gained
                tip_winner_team_id = team_of[gained]
        if tip_winner_team_id is None and typ.replace(" ", "") in {"faceoff", "face-off", "face off"}:
            parts = play.get("participants") or []
            winner = None
            for part in parts:
                if str(part.get("type") or "") == "face-off-winner":
                    winner = _athlete_id(part)
                    break
            if winner is None and parts:
                winner = _athlete_id(parts[0])
            if winner and winner in team_of:
                tip_winner_player_id = winner
                tip_winner_team_id = team_of[winner]

        is_nba_fg = sport == "nba" and _is_made_field_goal(play)
        is_nhl_goal = sport == "nhl" and _is_goal(play)
        is_nfl_td = sport == "nfl" and _is_touchdown(play)
        if first_fgm is None and (is_nba_fg or is_nhl_goal or is_nfl_td):
            scorer_id, scorer_name = _scorer_from(play)
            period = play.get("period") or {}
            clock = play.get("clock") or {}
            try:
                value = float(play.get("scoreValue") or 0)
            except (TypeError, ValueError):
                value = 0.0
            first_fgm = {
                "player_id": scorer_id,
                "player_name": scorer_name or name_of.get(scorer_id or "", ""),
                "team_id": _play_team_id(play),
                "period": period.get("number") if isinstance(period, dict) else period,
                "clock": clock.get("displayValue") if isinstance(clock, dict) else clock,
                "text": play.get("text") or "",
                "score_value": value,
                "started": bool((played.get(scorer_id or "") or {}).get("started")),
            }
            break

    if sport == "nfl" and first_fgm is None:
        for play in data.get("scoringPlays") or []:
            if not _is_touchdown(play):
                continue
            text = str(play.get("text") or "")
            scorer_name = _td_scorer_name(text)
            scorer_id, scorer_name = _match_player_id(scorer_name, played)
            period = play.get("period") or {}
            clock = play.get("clock") or {}
            first_fgm = {
                "player_id": scorer_id,
                "player_name": scorer_name or name_of.get(scorer_id or "", ""),
                "team_id": _play_team_id(play),
                "period": period.get("number") if isinstance(period, dict) else period,
                "clock": clock.get("displayValue") if isinstance(clock, dict) else clock,
                "text": text,
                "score_value": 6,
                "started": bool((played.get(scorer_id or "") or {}).get("started")),
            }
            break

    event_id = str(
        comps.get("id") or header.get("id") or (header.get("competitions") or [{}])[0].get("id") or ""
    )
    return {
        "event_id": event_id,
        "date": _header_date_et(header, comps),
        "sport": sport,
        "home_id": home["id"],
        "home_abbr": home["abbr"],
        "away_id": away["id"],
        "away_abbr": away["abbr"],
        "schema": CACHE_SCHEMA,
        "tip_winner_team_id": tip_winner_team_id,
        "tip_winner_player_id": tip_winner_player_id,
        "first_fgm": first_fgm,
        "played": played,
    }


def _summary_url(sport: str, event_id: str) -> str:
    path = SPORT_META[sport]["path"]
    return f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={event_id}"


def fetch_event(session: requests.Session, sport: str, event_id: str) -> dict[str, Any] | None:
    url = _summary_url(sport, event_id)
    last_error: Exception | None = None
    for attempt in range(RETRIES):
        try:
            resp = session.get(url, timeout=TIMEOUT)
            if resp.status_code in {429, 500, 502, 503, 504}:
                time.sleep(1.2 * (attempt + 1))
                last_error = RuntimeError(f"HTTP {resp.status_code}")
                continue
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            record = extract_event(data, sport)
            if record and not record.get("event_id"):
                record["event_id"] = str(event_id)
            return record
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
    log.warning("PBP fetch failed for %s event %s: %s", sport, event_id, last_error)
    return None


def _schedule_events(client: Any, sport: str, team_id: str, slate_date: str) -> list[str]:
    path = SPORT_META[sport]["path"]
    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams/{team_id}/schedule"
    try:
        data = client.get_json(
            url,
            cache_key=f"{sport}_schedule_{team_id}_{SPORT_META[sport].get('season_year', SEASON_YEAR)}",
            params={"season": SPORT_META[sport].get("season_year", SEASON_YEAR)},
        )
    except Exception as exc:  # noqa: BLE001 — keep the slate going if one team fails
        log.warning("Schedule failed for %s team %s: %s", sport, team_id, exc)
        return []
    if not data:
        return []
    out: list[str] = []
    for ev in data.get("events") or []:
        eid = str(ev.get("id") or "")
        if not eid:
            continue
        comps = (ev.get("competitions") or [{}])[0]
        status = (comps.get("status") or ev.get("status") or {}).get("type") or {}
        completed = bool(
            status.get("completed")
            or status.get("state") == "post"
            or status.get("name") == "STATUS_FINAL"
        )
        if not completed:
            continue
        raw = ev.get("date") or comps.get("date") or ""
        date = ""
        if raw:
            try:
                date = (
                    datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                    .astimezone(ET)
                    .date()
                    .isoformat()
                )
            except ValueError:
                date = str(raw)[:10]
        if date and date > slate_date:
            continue
        out.append(eid)
    return out


def collect_event_ids(
    client: Any,
    sport: str,
    games: list[Game],
    logs: dict[str, list[GameLog]],
    slate_date: str,
) -> list[str]:
    schedule_ids: list[str] = []
    seen: set[str] = set()
    team_ids = set()
    for g in games:
        team_ids.add(str(g.home_id))
        team_ids.add(str(g.away_id))
    for tid in team_ids:
        for eid in _schedule_events(client, sport, tid, slate_date):
            if eid not in seen:
                seen.add(eid)
                schedule_ids.append(eid)
    older: list[str] = []
    for entries in logs.values():
        for g in entries:
            eid = str(getattr(g, "event_id", "") or "")
            date = (getattr(g, "date", "") or "")[:10]
            if eid and (not date or date <= slate_date) and eid not in seen:
                seen.add(eid)
                # Prior-season logs go last so the PBP time budget
                # fills this season first.
                if getattr(g, "prior_season", False):
                    older.append(eid)
                else:
                    schedule_ids.append(eid)
    for g in games:
        status = (getattr(g, "status", "") or "").lower()
        if "final" in status or status in {"post", "completed", "status_final"}:
            eid = str(g.event_id)
            if eid not in seen:
                seen.add(eid)
                schedule_ids.append(eid)
    return schedule_ids + older


def load_or_fetch_events(
    *,
    sport: str,
    event_ids: list[str],
    folder: Path,
    skip_fetch: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for eid in event_ids:
        cached = load_cached(folder, eid)
        if cached and cached.get("first_fgm"):
            records[eid] = cached
        else:
            missing.append(eid)

    fetched = 0
    errors = 0
    if missing and not skip_fetch:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        deadline = time.time() + FETCH_BUDGET_SEC
        pending = list(missing)
        # Small batches so we can stop cleanly at the time budget.
        while pending and time.time() < deadline:
            batch = pending[: WORKERS * 4]
            pending = pending[WORKERS * 4 :]
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futs = {pool.submit(fetch_event, session, sport, eid): eid for eid in batch}
                for fut in as_completed(futs):
                    eid = futs[fut]
                    try:
                        rec = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        log.warning("PBP worker failed for %s: %s", eid, exc)
                        errors += 1
                        continue
                    if not rec:
                        errors += 1
                        continue
                    rec["event_id"] = rec.get("event_id") or eid
                    save_cached(folder, rec)
                    records[eid] = rec
                    fetched += 1
        if pending:
            log.warning(
                "PBP time budget reached; %s %s events left for a later refresh",
                len(pending),
                sport,
            )
        session.close()
    elif missing and skip_fetch:
        log.info("Skipping PBP fetch for %s missing %s events", len(missing), sport)

    meta = {
        "kind": SPORT_META[sport]["kind"],
        "events_needed": len(event_ids),
        "events_cached": len(event_ids) - len(missing),
        "events_fetched": fetched,
        "events_used": len(records),
        "events_missing": max(0, len(event_ids) - len(records)),
        "errors": errors,
        "skipped_fetch": bool(skip_fetch),
    }
    return records, meta


def _team_tip_rates(records: dict[str, dict[str, Any]]) -> dict[str, tuple[int, int]]:
    wins: dict[str, list[int]] = {}
    for rec in records.values():
        hid, aid = rec.get("home_id"), rec.get("away_id")
        winner = rec.get("tip_winner_team_id")
        for tid in (hid, aid):
            if not tid:
                continue
            bucket = wins.setdefault(str(tid), [0, 0])
            if winner:
                bucket[1] += 1
                if str(winner) == str(tid):
                    bucket[0] += 1
    return {tid: (w, n) for tid, (w, n) in wins.items()}


def _rate(hits: int, games: int) -> float:
    if not games:
        return 0.0
    return hits / games


def build_first_score_rows(
    *,
    sport: str,
    slate_date: str,
    games: list[Game],
    players: list[Player],
    logs: dict[str, list[GameLog]],
    client: Any,
    cache_root: Path,
    skip_fetch: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, dict[str, int]]]:
    """Return (rows, meta, log_flags[player_id][event_id] = 0|1)."""
    if sport not in SPORT_META:
        return [], {"kind": None, "events_used": 0}, {}

    meta_s = SPORT_META[sport]
    folder = cache_dir(cache_root, sport)
    event_ids = collect_event_ids(client, sport, games, logs, slate_date)
    records, meta = load_or_fetch_events(
        sport=sport, event_ids=event_ids, folder=folder, skip_fetch=skip_fetch
    )
    tip_rates = _team_tip_rates(records)
    game_by_team = {}
    for g in games:
        game_by_team[str(g.home_id)] = g
        game_by_team[str(g.away_id)] = g

    rows: list[dict[str, Any]] = []
    log_flags: dict[str, dict[str, int]] = {}

    for player in players:
        raw_played = _played(logs.get(player.id, []), before_date="")
        # Include games before the slate date, plus any completed game
        # already in the PBP cache (today's finals).
        played = []
        for g in raw_played:
            date = (g.date or "")[:10]
            eid = str(g.event_id)
            if (date and date < slate_date) or eid in records:
                played.append(g)
        if len(played) < MIN_GAMES:
            continue
        seq: list[dict[str, Any]] = []
        flags: dict[str, int] = {}
        for g in played:
            rec = records.get(str(g.event_id))
            if not rec:
                continue
            info = (rec.get("played") or {}).get(str(player.id))
            if not info:
                continue
            tid = str(info.get("team_id") or player.team_id)
            first = rec.get("first_fgm") or {}
            hit = str(first.get("player_id") or "") == str(player.id)
            flags[str(g.event_id)] = 1 if hit else 0
            seq.append(
                {
                    "log": g,
                    "hit": hit,
                    "started": bool(info.get("started")),
                    "team_id": tid,
                    "tip_win": str(rec.get("tip_winner_team_id") or "") == tid,
                }
            )
        # Gamelogs can lag a same-day final. If the player is in tonight's
        # PBP boxscore, fold that game into the windows.
        seen = {str(s["log"].event_id) for s in seq}
        for game in games:
            rec = records.get(str(game.event_id))
            if not rec or str(game.event_id) in seen:
                continue
            info = (rec.get("played") or {}).get(str(player.id))
            if not info:
                continue
            tid = str(info.get("team_id") or player.team_id)
            first = rec.get("first_fgm") or {}
            hit = str(first.get("player_id") or "") == str(player.id)
            flags[str(game.event_id)] = 1 if hit else 0
            date = rec.get("date") or slate_date
            is_home = tid == str(game.home_id)
            opp = game.away_abbr if is_home else game.home_abbr
            dummy = GameLog(
                event_id=str(game.event_id),
                date=date,
                opponent_abbr=opp,
                is_home=is_home,
                minutes=float(info.get("minutes") or 1),
                points=0,
                rebounds=0,
                assists=0,
                threes=0,
                pra=0,
            )
            seq.append(
                {
                    "log": dummy,
                    "hit": hit,
                    "started": bool(info.get("started")),
                    "team_id": tid,
                    "tip_win": str(rec.get("tip_winner_team_id") or "") == tid,
                }
            )
        seq.sort(key=lambda s: (s["log"].date or "", s["log"].event_id), reverse=True)
        log_flags[player.id] = flags
        if len(seq) < MIN_GAMES:
            continue
        hits_all = sum(1 for s in seq if s["hit"])
        if hits_all < 1:
            continue
        # Short samples (2 first baskets in 5 games) inflate the L5/L10
        # score; require a longer lookback before ranking tonight.
        if len(seq) < MIN_FIRST_GAMES:
            continue

        def window(n: int) -> list[dict[str, Any]]:
            return seq[:n]

        def wr(items: list[dict[str, Any]]) -> tuple[float, int, int]:
            n = len(items)
            h = sum(1 for s in items if s["hit"])
            return _rate(h, n), h, n

        l4, l4_h, l4_n = wr(window(4))
        l5, l5_h, l5_n = wr(window(5))
        l6, l6_h, l6_n = wr(window(6))
        l8, l8_h, l8_n = wr(window(8))
        l9, l9_h, l9_n = wr(window(9))
        l10, l10_h, l10_n = wr(window(10))
        l12, l12_h, l12_n = wr(window(12))
        l15, l15_h, l15_n = wr(window(15))
        l20, l20_h, l20_n = wr(window(20))
        current_seq = [s for s in seq if not getattr(s["log"], "prior_season", False)]
        season, season_h, season_n = wr(current_seq or seq)
        prior_n = sum(1 for s in seq if getattr(s["log"], "prior_season", False))
        home_items = [s for s in seq if s["log"].is_home]
        away_items = [s for s in seq if not s["log"].is_home]
        home_hit, home_h, home_n = wr(home_items)
        away_hit, away_h, away_n = wr(away_items)

        game = game_by_team.get(str(player.team_id))
        if not game:
            continue
        venue = "H" if str(player.team_id) == str(game.home_id) else "A"
        venue_items = home_items if venue == "H" else away_items
        if len(venue_items) >= VENUE_MIN_GAMES:
            venue_hit, venue_h, venue_n = wr(venue_items)
        else:
            venue_hit, venue_h, venue_n = season, season_h, season_n

        opp = game.away_abbr if venue == "H" else game.home_abbr
        h2h_items = [s for s in seq if (s["log"].opponent_abbr or "") == opp]
        h2h, h2h_h, h2h_n = wr(h2h_items) if h2h_items else (0.0, 0, 0)

        streak = 0
        for s in seq:
            if s["hit"]:
                streak += 1
            else:
                break
        home_streak = 0
        for s in home_items:
            if s["hit"]:
                home_streak += 1
            else:
                break
        away_streak = 0
        for s in away_items:
            if s["hit"]:
                away_streak += 1
            else:
                break

        started_n = sum(1 for s in seq if s["started"])
        started_rate = _rate(started_n, len(seq))
        started_last = bool(seq[0]["started"]) if seq else False
        tip_w, tip_n = tip_rates.get(str(player.team_id), (0, 0))
        tip_win_rate = _rate(tip_w, tip_n)
        rest_days, is_b2b = _rest(played, slate_date)
        venue_streak = home_streak if venue == "H" else away_streak
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
        offer = None
        offers = get_offers(
            {"name": player.name, "event_id": game.event_id, "team_abbr": player.team_abbr},
            meta_s["prop"],
            sport=sport,
        )
        for cand in offers:
            if cand.source == "live":
                offer = cand
                break
        score, n_perfect, longest_perfect, best_streak, trivial = strong_trend_score(
            windows,
            streak,
            venue_streak,
            prop=meta_s["prop"],
            line=0.5,
            side="over",
            line_source=(offer.source if offer else "research"),
        )
        price = offer.price_for("over") if offer else None
        shown_label = line_label(
            meta_s["prop"],
            0.5,
            side="over",
            price=price,
            source=(offer.source if offer else "research"),
        )

        rows.append(
            {
                "player_id": player.id,
                "player": player.name,
                "team": player.team_abbr,
                "team_name": player.team_name,
                "opponent": opp,
                "venue": venue,
                "event_id": game.event_id,
                "game": game.vs_label(),
                "game_time_et": game.start_et,
                "prop": meta_s["prop"],
                "prop_label": meta_s["prop_label"],
                "prop_full": meta_s["prop_full"],
                "line": 0.5,
                "display_line": 0.5,
                "line_label": shown_label,
                "side": "over",
                "line_source": (offer.source if offer else "research"),
                "american_odds": price,
                "book": (offer.book if offer else ""),
                "book_title": (offer.book_title if offer else ""),
                "l4": l4,
                "l6": l6,
                "l5": l5,
                "l8": l8,
                "l9": l9,
                "l10": l10,
                "l12": l12,
                "l15": l15,
                "l20": l20,
                "l4_hits": l4_h,
                "l4_games": l4_n,
                "l6_hits": l6_h,
                "l6_games": l6_n,
                "l8_hits": l8_h,
                "l8_games": l8_n,
                "l9_hits": l9_h,
                "l9_games": l9_n,
                "l12_hits": l12_h,
                "l12_games": l12_n,
                "l15_hits": l15_h,
                "l15_games": l15_n,
                "season": season,
                "venue_hit": venue_hit,
                "home_hit": home_hit,
                "away_hit": away_hit,
                "h2h": h2h,
                "streak": streak,
                "home_streak": home_streak,
                "away_streak": away_streak,
                "score": round(score, 2),
                "games_played": season_n,
                "avg_minutes": 0.0,
                "l5_hits": l5_h,
                "l5_games": l5_n,
                "l10_hits": l10_h,
                "l10_games": l10_n,
                "l20_hits": l20_h,
                "l20_games": l20_n,
                "season_hits": season_h,
                "season_games": season_n,
                "venue_hits": venue_h,
                "venue_games": venue_n,
                "home_hits": home_h,
                "home_games": home_n,
                "away_hits": away_h,
                "away_games": away_n,
                "h2h_hits": h2h_h,
                "h2h_games": h2h_n,
                "l5_avg": round(l5, 3),
                "l10_avg": round(l10, 3),
                "season_avg": round(season, 3),
                "h2h_avg": round(h2h, 3) if h2h_n else None,
                "min_l5": None,
                "min_l10": None,
                "minutes_trend": [],
                "rest_days": rest_days,
                "is_b2b": is_b2b,
                "injury_status": player.injury_status,
                "injury_detail": player.injury_detail,
                "position": player.position,
                "headshot": player.headshot,
                "opp_def_rank": None,
                "opp_def_teams": None,
                "opp_def_value": None,
                "opp_def_label": "",
                "opp_def_stat": "",
                "matchup_tag": "",
                "without": [],
                "tip_win_rate": round(tip_win_rate, 3) if tip_n else None,
                "tip_wins": tip_w,
                "tip_games": tip_n,
                "started_rate": round(started_rate, 3),
                "started_games": started_n,
                "started_last": started_last,
                "first_kind": meta_s["kind"],
                "prior_games": prior_n,
                "n_perfect": n_perfect,
                "longest_perfect": longest_perfect,
                "best_streak": best_streak,
                "trivial_gimme": trivial,
                "windows": display,
            }
        )

    rows.sort(key=lambda r: (-(r.get("score") or 0), -(r.get("best_streak") or 0), -(r.get("l10") or 0), r.get("player") or ""))
    meta["rows"] = len(rows)
    return rows, meta, log_flags
