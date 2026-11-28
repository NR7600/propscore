"""Cheap ESPN scoreboard status, cached about 2 minutes.

Used at request time to hide finished games and roll a sport forward
to its next open slate. Does not fetch gamelogs or call The Odds API.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .http import DEFAULT_HEADERS

ET = ZoneInfo("America/New_York")

log = logging.getLogger("propscore.live_status")

TTL_SEC = 120
ERROR_TTL_SEC = 30
LOOKAHEAD_DAYS = 7

SCOREBOARD_URLS = {
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "nhl": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
}

CLOSED_STATES = {"post"}
CLOSED_WORDS = {
    "final",
    "postponed",
    "canceled",
    "cancelled",
    "forfeit",
    "suspended",
    "cancelled",
    "canceled",
}

# status type.state == "in", or these descriptions.
LIVE_WORDS = {"in progress", "halftime", "end of period", "end of quarter", "overtime", "warm-up", "warmup"}

_lock = threading.Lock()
# (sport, date) -> (expires_at, statuses_dict | None)
_cache: dict[tuple[str, str], tuple[float, dict[str, dict[str, Any]] | None]] = {}


def classify_status(raw: str | None, state: str | None = None, completed: bool | None = None) -> dict[str, Any]:
    """Normalize an ESPN (or stored) status into closed / live flags."""
    text = str(raw or "").strip()
    lowered = text.lower()
    st = str(state or "").strip().lower()
    is_completed = bool(completed)
    closed = bool(
        is_completed
        or st in CLOSED_STATES
        or any(word in lowered for word in ("final", "postponed", "canceled", "cancelled", "forfeit"))
        or lowered in {"post", "completed", "status_final"}
    )
    live = (not closed) and (st == "in" or lowered in LIVE_WORDS or "in progress" in lowered or lowered in {"halftime", "end of period", "end of quarter"})
    label = text or "Scheduled"
    if live:
        display = "LIVE"
    elif closed and "final" in lowered:
        display = text or "Final"
    else:
        display = label
    return {
        "status": display if live else (text or label),
        "state": st or ("post" if closed else ("in" if live else "pre")),
        "live": live,
        "closed": closed,
    }


def cache_tag() -> str:
    """Changes about every two minutes so API response caches drop stale status."""
    return str(int(time.time() // TTL_SEC))


def game_statuses(sport: str, slate_date: str) -> dict[str, dict[str, Any]] | None:
    """Return {event_id: classify_status(...)} or None if the scoreboard could not be fetched."""
    key = ((sport or "").lower(), slate_date)
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    fetched = _fetch_scoreboard(key[0], slate_date)
    ttl = TTL_SEC if fetched is not None else ERROR_TTL_SEC
    with _lock:
        _cache[key] = (now + ttl, fetched)
    return fetched


def apply_live_status(sport: str, slate_date: str, games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy games, overlay fresh ESPN status, and set live/closed flags.

    If the scoreboard cannot be reached, flags are derived from the stored status.
    """
    live_map = game_statuses(sport, slate_date)
    out: list[dict[str, Any]] = []
    for raw in games or []:
        game = dict(raw)
        eid = str(game.get("event_id") or "")
        info = (live_map or {}).get(eid)
        if info is None:
            typ = classify_status(game.get("status"))
        else:
            typ = info
        game["status"] = typ["status"] if typ["live"] else typ.get("status") or game.get("status")
        if typ["live"]:
            game["status"] = "LIVE"
        game["live"] = typ["live"]
        game["closed"] = typ["closed"]
        out.append(game)
    return out


def open_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [g for g in games or [] if not g.get("closed")]


def slate_is_complete(games: list[dict[str, Any]]) -> bool:
    """True when there is at least one game and every game is closed."""
    if not games:
        return False
    return all(g.get("closed") for g in games)


def next_slate_date(sport: str, after: str) -> str:
    """First ET date after `after` that still has a game not yet finished."""
    try:
        start = date.fromisoformat(after) + timedelta(days=1)
    except ValueError:
        start = date.fromisoformat(_today()) + timedelta(days=1)
    last = start
    for i in range(LOOKAHEAD_DAYS):
        candidate = (start + timedelta(days=i)).isoformat()
        last = start + timedelta(days=i)
        statuses = game_statuses(sport, candidate)
        if not statuses:
            continue
        if any(not info.get("closed") for info in statuses.values()):
            return candidate
        # Events exist but all are closed; keep looking.
    return last.isoformat() if last else start.isoformat()


def open_slate_date(sport: str, start: str | None = None) -> str:
    """The current ET open slate: today if any game remains, else the next game day."""
    day = start or today_et()
    statuses = game_statuses(sport, day)
    if statuses and any(not info.get("closed") for info in statuses.values()):
        return day
    if statuses and all(info.get("closed") for info in statuses.values()):
        return next_slate_date(sport, day)
    # No scoreboard rows (or a fetch miss). For NFL, still look ahead; for
    # other sports keep today so a 5 AM build is not skipped if ESPN is late.
    if (sport or "").lower() == "nfl":
        nxt = next_slate_date(sport, day)
        return nxt
    return day


def today_et() -> str:
    return datetime.now(ET).date().isoformat()


def _today() -> str:
    return today_et()


def _fetch_scoreboard(sport: str, slate_date: str) -> dict[str, dict[str, Any]] | None:
    url = SCOREBOARD_URLS.get(sport)
    if not url:
        return None
    yyyymmdd = slate_date.replace("-", "")
    try:
        resp = requests.get(
            url,
            params={"dates": yyyymmdd},
            headers=DEFAULT_HEADERS,
            timeout=8,
        )
        if resp.status_code != 200:
            log.warning("Scoreboard %s %s HTTP %s", sport, slate_date, resp.status_code)
            return None
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Scoreboard %s %s failed: %s", sport, slate_date, exc)
        return None
    out: dict[str, dict[str, Any]] = {}
    for event in data.get("events") or []:
        typ = (event.get("status") or {}).get("type") or {}
        eid = str(event.get("id") or "")
        if not eid:
            comps = event.get("competitions") or []
            if comps:
                eid = str(comps[0].get("id") or "")
        if not eid:
            continue
        out[eid] = classify_status(
            typ.get("description") or typ.get("name") or typ.get("detail"),
            state=typ.get("state"),
            completed=typ.get("completed"),
        )
    return out
