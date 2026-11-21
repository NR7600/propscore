"""Prop line source: The Odds API when a key is present, else thresholds.

The API key is read only from the ODDS_API_KEY environment variable.
It is never written to disk, logs, cache files, or URLs (the x-api-key
header is used instead of a query parameter).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

log = logging.getLogger("propscore")

ET = ZoneInfo("America/New_York")
API_HOST = "https://api.the-odds-api.com"
SPORT_KEYS = {"nba": "basketball_nba", "nhl": "icehockey_nhl", "nfl": "americanfootball_nfl"}
REGION = "us"
RESERVE_DEFAULT = 30
DAILY_BUDGET_DEFAULT = 15  # credits; see prefetch docstring for the math
PREFERRED_BOOKS = (
    "draftkings",
    "fanduel",
    "betmgm",
    "betrivers",
    "bovada",
    "espnbet",
    "hardrockbet",
    "fliff",
    "betonlineag",
    "lowvig",
    "mybookieag",
    "betus",
)

# (Odds API market key, our prop key) in fetch-priority order.
# NBA is always attempted before NHL when both sports run the same day
# (see prefetch_slate callers). Within a sport, earlier markets win the
# daily budget.
# Priority order. On the free 15-credit cap a 6-game NBA slate usually
# covers points + first_basket (12 credits) and stops. Raising
# ODDS_DAILY_BUDGET is enough to walk further down the list.
MARKETS_BY_SPORT: dict[str, list[tuple[str, str]]] = {
    "nba": [
        ("player_points", "points"),
        ("player_first_basket", "first_basket"),
        ("player_rebounds", "rebounds"),
        ("player_assists", "assists"),
        ("player_threes", "threes"),
        ("player_points_rebounds_assists", "pra"),
    ],
    "nhl": [
        ("player_shots_on_goal", "shots"),
        ("player_points", "points"),
        ("player_total_saves", "saves"),
    ],
    # Not fetched on the free 15-credit budget unless ODDS_MARKETS
    # explicitly includes an nfl: section.
    "nfl": [
        ("player_pass_yds", "pass_yds"),
        ("player_pass_tds", "pass_td"),
        ("player_pass_completions", "completions"),
        ("player_pass_attempts", "pass_att"),
        ("player_pass_interceptions", "ints"),
        ("player_rush_yds", "rush_yds"),
        ("player_rush_attempts", "rush_att"),
        ("player_receptions", "receptions"),
        ("player_reception_yds", "rec_yds"),
        ("player_rush_reception_yds", "rush_rec_yds"),
        ("player_anytime_td", "anytime_td"),
        ("player_1st_td", "first_td"),
    ],
}
MARKET_PROP = {market: prop for pairs in MARKETS_BY_SPORT.values() for market, prop in pairs}

# Over thresholds used when no live line exists for that player/stat.
LINES_BY_SPORT: dict[str, dict[str, list[float]]] = {
    "nba": {
        "points": [10, 15, 20, 25],
        "rebounds": [4, 6, 8, 10],
        "assists": [2, 4, 6, 8],
        "threes": [1, 2, 3, 4],
        "pra": [15, 20, 25, 30],
        "pts_reb": [15, 20, 25, 30],
        "pts_ast": [12, 16, 20, 25],
        "reb_ast": [6, 8, 10, 12],
        "steals": [0.5, 1.5, 2.5],
        "blocks": [0.5, 1.5, 2.5],
    },
    "nhl": {
        "goals": [0.5, 1.5],
        "assists": [0.5, 1.5],
        "points": [0.5, 1.5, 2.5],
        "shots": [1.5, 2.5, 3.5, 4.5],
        "saves": [20.5, 25.5, 30.5],
    },
    "nfl": {
        "pass_yds": [199.5, 249.5, 299.5],
        "pass_td": [0.5, 1.5, 2.5],
        "completions": [15.5, 19.5, 23.5],
        "pass_att": [29.5, 34.5, 39.5],
        "ints": [0.5, 1.5],
        "rush_yds": [39.5, 59.5, 79.5],
        "rush_att": [9.5, 14.5, 19.5],
        "receptions": [2.5, 3.5, 4.5, 5.5],
        "rec_yds": [29.5, 49.5, 69.5],
        "rush_rec_yds": [49.5, 69.5, 89.5],
        "anytime_td": [0.5],
    },
}

STANDARD_LINES = LINES_BY_SPORT["nba"]

PROP_LABELS = {
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
    "goals": "G",
    "shots": "SOG",
    "saves": "SV",
    "blocked": "BLK",
    "hits": "HIT",
    "first_basket": "First FGM",
    "first_goal": "First Goal",
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
    "first_td": "First TD",
}

PROP_FULL_LABELS = {
    "points": "Points",
    "rebounds": "Rebounds",
    "assists": "Assists",
    "threes": "Three Pointers Made",
    "pra": "Points Rebounds Assists",
    "pts_reb": "Points Rebounds",
    "pts_ast": "Points Assists",
    "reb_ast": "Rebounds Assists",
    "steals": "Steals",
    "blocks": "Blocks",
    "goals": "Goals",
    "shots": "Shots on Goal",
    "saves": "Saves",
    "first_basket": "First FGM",
    "first_goal": "First Goal",
    "pass_yds": "Passing Yards",
    "pass_td": "Passing Touchdowns",
    "completions": "Completions",
    "pass_att": "Pass Attempts",
    "ints": "Interceptions",
    "rush_yds": "Rushing Yards",
    "rush_att": "Rush Attempts",
    "receptions": "Receptions",
    "rec_yds": "Receiving Yards",
    "rush_rec_yds": "Rush + Rec Yards",
    "anytime_td": "Anytime Touchdown",
    "first_td": "First TD",
}

TEAM_ALIASES = {
    "la clippers": "los angeles clippers",
    "la lakers": "los angeles lakers",
    "ny knicks": "new york knicks",
    "ny rangers": "new york rangers",
    "ny islanders": "new york islanders",
    "nj devils": "new jersey devils",
    "tb lightning": "tampa bay lightning",
    "sj sharks": "san jose sharks",
    "sa spurs": "san antonio spurs",
    "gs warriors": "golden state warriors",
    "golden state": "golden state warriors",
    "no pelicans": "new orleans pelicans",
    "pelicans": "new orleans pelicans",
    "utah hockey club": "utah mammoth",
    "utah hc": "utah mammoth",
    "st louis blues": "st louis blues",
    "montreal canadiens": "montreal canadiens",
    "washington football": "washington commanders",
}

ROOT = Path(__file__).resolve().parent.parent
ODDS_CACHE_DIR = ROOT / "cache" / "odds"

# In-memory copy of the latest prefetch, keyed by (sport, date).
_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


@dataclass
class LineOffer:
    """A single over/under line for one player and stat."""

    line: float
    source: str  # "live", "est", "research", or legacy "standard"
    over_price: int | None = None
    under_price: int | None = None
    book: str = ""
    book_title: str = ""

    @property
    def display_line(self) -> float:
        return display_line(self.line, source=self.source)

    def price_for(self, side: str) -> int | None:
        return self.under_price if side == "under" else self.over_price


def lines_for_sport(sport: str) -> dict[str, list[float]]:
    return LINES_BY_SPORT.get(sport, LINES_BY_SPORT["nba"])


def props_for_sport(sport: str) -> list[dict[str, str]]:
    table = lines_for_sport(sport)
    return [{"key": key, "label": PROP_LABELS.get(key, key.upper())} for key in table]


def lowest_line(prop: str, sport: str = "nba") -> float | None:
    lines = lines_for_sport(sport).get(prop)
    return min(lines) if lines else None


def display_line(line: float, source: str = "est") -> float:
    """How the line should appear on a card.

    Live and estimated lines are already sportsbook-style half-points
    and are shown as stored. Legacy integer thresholds of 25 (hit if
    value >= 25) display as Over 24.5.
    """
    value = float(line)
    if source in {"live", "est", "research"}:
        return value
    if value.is_integer():
        return value - 0.5
    return value


def format_line_number(line: float, source: str = "standard") -> str:
    shown = display_line(line, source=source)
    if float(shown).is_integer():
        return str(int(shown))
    return f"{shown:.1f}"


def format_american(price: int | None) -> str:
    if price is None:
        return ""
    return f"+{price}" if price > 0 else str(price)


def line_label(
    prop: str,
    line: float,
    side: str = "over",
    price: int | None = None,
    source: str = "standard",
) -> str:
    short = PROP_LABELS.get(prop, prop.upper())
    word = "Under" if side == "under" else "Over"
    label = f"{short} {word} {format_line_number(line, source=source)}"
    odds = format_american(price)
    if odds:
        label = f"{label} ({odds})"
    return label


def prop_full_label(prop: str) -> str:
    return PROP_FULL_LABELS.get(prop, PROP_LABELS.get(prop, prop.upper()))


# Counting stats that we only post if the player actually produces them.
_SPARSE_PROPS = {"steals", "blocks", "blocked", "hits", "ints"}


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def round_book_line(value: float) -> float:
    """Nearest 0.5, then prefer a no-push x.5 sportsbook line.

    A whole-number estimate of 1, 2, 24, ... becomes 1.5, 2.5, 24.5 so
    the over is not a near-automatic 0.5 / 1.0 gimme.
    """
    half = round(float(value) * 2) / 2.0
    if abs(half - round(half)) < 1e-9:
        return 0.5 if half < 1 else half + 0.5
    return max(0.5, half)


def estimated_line(logs: list, prop: str, sport: str = "nba") -> float | None:
    """One player-specific line when no sportsbook number is cached.

    70% the median of his last 10 played games plus 30% his season
    average, rounded to a sportsbook-style half point. Steals/blocks
    (and similar sparse stats) are omitted unless that L10 median is
    at least 0.5. First FGM / first goal stay at 0.5.
    """
    if prop in {"first_basket", "first_goal", "first_td", "anytime_td"}:
        return 0.5
    values: list[float] = []
    for game in logs or []:
        try:
            values.append(float(game.value(prop)))
        except (TypeError, ValueError, AttributeError):
            continue
    if len(values) < 3:
        return None
    recent = values[:10]
    med = _median(recent)
    current_vals = []
    for game in logs or []:
        if getattr(game, "prior_season", False):
            continue
        try:
            current_vals.append(float(game.value(prop)))
        except (TypeError, ValueError, AttributeError):
            continue
    season_avg = (sum(current_vals) / len(current_vals)) if current_vals else (sum(values) / len(values))
    raw = 0.7 * med + 0.3 * season_avg
    if prop in _SPARSE_PROPS and med < 0.5:
        return None
    line = round_book_line(raw)
    if line < 0.5:
        return None
    return line


def get_offers(
    player: dict,
    prop: str,
    sport: str = "nba",
    logs: list | None = None,
) -> list[LineOffer]:
    """Return a live sportsbook line if cached, else one estimated line.

    Never calls The Odds API. `prefetch_slate` must run first (or a
    same-day cache must already be on disk) for live lines to appear.
    """
    live = _lookup_live(player, prop, sport)
    if live:
        return [live]
    est = estimated_line(logs or [], prop, sport)
    if est is None:
        return []
    return [LineOffer(line=est, source="est")]


def get_lines(player: dict, prop: str, sport: str = "nba") -> list[float]:
    return [offer.line for offer in get_offers(player, prop, sport)]


def all_standard_props(sport: str = "nba") -> Iterable[str]:
    return lines_for_sport(sport).keys()


def odds_status() -> dict[str, Any]:
    """Public, key-free snapshot for /health."""
    usage = _read_usage()
    return {
        "configured": bool(_api_key()),
        "region": os.environ.get("ODDS_REGION", REGION),
        "reserve": _reserve(),
        "daily_budget": _daily_budget(),
        "markets": [m for m, _p in markets_for_sport("nba") + markets_for_sport("nhl")],
        "requests_remaining": usage.get("requests_remaining"),
        "requests_used": usage.get("requests_used"),
        "spent_today": usage.get("spent_today"),
        "usage_day": usage.get("day"),
    }


def prefetch_slate(
    sport: str,
    date: str,
    games: list,
    *,
    cache_dir: Path | None = None,
    skip_fetch: bool = False,
) -> dict[str, Any]:
    """Load (or fetch once) tonight's player-prop lines for `sport`.

    Budget (free Starter = 500 credits/month)
    -----------------------------------------
    Event-odds cost = (unique markets returned) × (regions). We use
    region `us` only (1 region). `us_dfs` (PrizePicks/Underdog) is a
    second region and would double the cost, so it is not requested.
    `/v4/sports` and `/v4/sports/{sport}/events` are free.

    A full nightly pull of every requested market is too expensive:
      typical 6 NBA games × 5 markets = 30, plus 14 NHL × 3 = 42,
      ≈ 72 credits/day, ~2,160/month.

    So we cap spending at `ODDS_DAILY_BUDGET` (default 15) and stop
    when `x-requests-remaining` falls to `ODDS_RESERVE` (default 30).
    15 × 30 days = 450, plus a 30-credit reserve, fits in 500.
    Markets are purchased in priority order (NBA first, then NHL if credits remain). The default list is the full set; a 15-credit day typically covers NBA points + first_basket only. Raise ODDS_DAILY_BUDGET (and optionally set ODDS_MARKETS) after a plan upgrade to fill the rest. There is no cheaper official way to get player props: the bulk /odds endpoint does not include them, and extra regions multiply the cost.

    Results are cached to disk for the slate date so restarts and
    later `run.py` calls do not spend credits again.
    """
    sport = (sport or "").lower()
    cache_path = (cache_dir or ODDS_CACHE_DIR) / f"{sport}_{date}.json"
    cached = _load_json(cache_path)
    if cached and cached.get("events"):
        _CACHE[(sport, date)] = cached
        live_n = _count_live(cached)
        print(
            f"Odds cache hit for {sport} {date}: {live_n} live player-stat lines "
            f"(no API credits used)."
        )
        return {
            "ok": True,
            "cached": True,
            "live_lines": live_n,
            "credits_spent": 0,
            "remaining": (_read_usage() or {}).get("requests_remaining"),
            "path": str(cache_path),
        }

    if skip_fetch:
        print("Odds fetch skipped (--skip-odds); using cache or estimated lines.")
        return {"ok": True, "cached": False, "skipped": "skip_fetch", "live_lines": 0}

    key = _api_key()
    if not key:
        print("ODDS_API_KEY is not set; using estimated lines.")
        return {"ok": True, "cached": False, "skipped": "no_key", "live_lines": 0}

    usage = _read_usage()
    remaining = usage.get("requests_remaining")
    if remaining is not None and int(remaining) <= _reserve():
        print(
            f"Odds fetch skipped: {remaining} credits remaining is at or below "
            f"the {_reserve()}-credit reserve."
        )
        return {"ok": False, "skipped": "reserve", "remaining": remaining, "live_lines": 0}

    spent_today = _spent_today(usage, date)
    budget = _daily_budget()
    if spent_today >= budget:
        print(
            f"Odds fetch skipped: already spent {spent_today} credits today "
            f"(daily budget {budget})."
        )
        return {"ok": False, "skipped": "daily_budget", "spent_today": spent_today, "live_lines": 0}

    payload: dict[str, Any] = {
        "sport": sport,
        "date": date,
        "region": os.environ.get("ODDS_REGION", REGION),
        "fetched_at": datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET"),
        "credits_spent": 0,
        "events": {},
    }
    try:
        events = _list_events(sport, date, key)
    except Exception as exc:
        print(f"Odds events list failed ({type(exc).__name__}); using estimated lines.")
        return {"ok": False, "skipped": "events_error", "live_lines": 0}

    matched = _match_events(events, games)
    print(f"Odds events: {len(events)} listed, {len(matched)} matched to tonight's ESPN slate.")
    if not matched:
        _store_cache(sport, date, payload, cache_path)
        return {"ok": True, "cached": False, "live_lines": 0, "credits_spent": 0}

    markets = markets_for_sport(sport)
    remaining_budget = budget - spent_today
    spent = 0
    for market_key, prop in markets:
        cost = len(matched)  # 1 region × 1 market × N events, if all return
        if cost > remaining_budget:
            print(
                f"  skip {market_key}: would cost up to {cost} credits, "
                f"{remaining_budget} left in today's budget."
            )
            continue
        if not _reserve_allows():
            print(f"  stop: reached the {_reserve()}-credit reserve.")
            break
        fetched = 0
        for espn_id, ev in matched:
            if not _reserve_allows() or remaining_budget <= 0:
                break
            try:
                body, headers = _event_odds(sport, ev["id"], market_key, key)
            except _OddsHttpError as exc:
                print(f"  {market_key} event skipped (HTTP {exc.status}).")
                if exc.status in {401, 403}:
                    break
                continue
            except Exception:
                print(f"  {market_key} event skipped (request failed).")
                continue
            cost_last = _header_int(headers, "x-requests-last") or 1
            remaining_now = _header_int(headers, "x-requests-remaining")
            used_now = _header_int(headers, "x-requests-used")
            _write_usage(date, spent_delta=cost_last, remaining=remaining_now, used=used_now)
            spent += cost_last
            remaining_budget -= cost_last
            payload["credits_spent"] = spent
            if remaining_now is not None:
                payload["remaining_after"] = remaining_now
            _merge_event_odds(payload, ev, espn_id, body, prop)
            fetched += 1
            # Persist after each paid call so a later crash still caches
            # what we already paid for and does not refetch it.
            _store_cache(sport, date, payload, cache_path)
            time.sleep(0.25)
        print(
            f"  {market_key}: {fetched}/{len(matched)} events, "
            f"+{spent} credits this fetch so far."
        )

    _store_cache(sport, date, payload, cache_path)
    live_n = _count_live(payload)
    usage = _read_usage()
    print(
        f"Odds fetch done for {sport}: {live_n} live player-stat lines, "
        f"{spent} credits spent, {usage.get('requests_remaining')} remaining."
    )
    return {
        "ok": True,
        "cached": False,
        "live_lines": live_n,
        "credits_spent": spent,
        "remaining": usage.get("requests_remaining"),
        "path": str(cache_path),
    }


# ----- internals ---------------------------------------------------------


class _OddsHttpError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


def _api_key() -> str:
    return os.environ.get("ODDS_API_KEY", "").strip()


def _reserve() -> int:
    try:
        return max(0, int(os.environ.get("ODDS_RESERVE", RESERVE_DEFAULT)))
    except ValueError:
        return RESERVE_DEFAULT


def _daily_budget() -> int:
    try:
        return max(0, int(os.environ.get("ODDS_DAILY_BUDGET", DAILY_BUDGET_DEFAULT)))
    except ValueError:
        return DAILY_BUDGET_DEFAULT


def markets_for_sport(sport: str) -> list[tuple[str, str]]:
    """Markets to fetch, in priority order.

    Override with ODDS_MARKETS, e.g.
      nba:player_points,player_first_basket,player_rebounds;nhl:player_shots_on_goal
    Use ODDS_MARKETS=all for the built-in full list (same as the default;
    the daily budget is what limits how many are actually purchased).
    """
    sport = (sport or "").lower()
    default = list(MARKETS_BY_SPORT.get(sport) or [])
    raw = os.environ.get("ODDS_MARKETS", "").strip()
    # NFL stays off the free daily budget unless the operator explicitly
    # lists an nfl: section. ODDS_MARKETS=all still does not buy NFL.
    if sport == "nfl" and (not raw or raw.lower() in {"default", "all"}):
        return []
    if not raw or raw.lower() in {"default", "all"}:
        return default
    section = raw
    if ":" in raw or ";" in raw:
        picked = None
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                key, _, rest = part.partition(":")
                if key.strip().lower() == sport:
                    picked = rest.strip()
                    break
            else:
                picked = part
        if picked is None:
            return [] if sport == "nfl" else default
        section = picked
    out: list[tuple[str, str]] = []
    for token in section.split(","):
        market = token.strip()
        if not market:
            continue
        prop = MARKET_PROP.get(market)
        if not prop:
            # allow "points" as well as "player_points"
            for mk, pr in default:
                if market in {mk, pr}:
                    market, prop = mk, pr
                    break
        if prop:
            out.append((market, prop))
    return out or default


def _usage_path() -> Path:
    ODDS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return ODDS_CACHE_DIR / "usage.json"


def _read_usage() -> dict[str, Any]:
    return _load_json(_usage_path()) or {}


def _spent_today(usage: dict[str, Any], date: str) -> int:
    if usage.get("day") != date:
        return 0
    try:
        return int(usage.get("spent_today") or 0)
    except (TypeError, ValueError):
        return 0


def _write_usage(
    date: str,
    *,
    spent_delta: int,
    remaining: int | None,
    used: int | None,
) -> None:
    usage = _read_usage()
    if usage.get("day") != date:
        usage = {"day": date, "spent_today": 0}
    usage["day"] = date
    usage["spent_today"] = int(usage.get("spent_today") or 0) + int(spent_delta or 0)
    if remaining is not None:
        usage["requests_remaining"] = remaining
    if used is not None:
        usage["requests_used"] = used
    usage["last_cost"] = spent_delta
    usage["updated_at"] = datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET")
    path = _usage_path()
    path.write_text(json.dumps(usage, indent=2), encoding="utf-8")


def _reserve_allows() -> bool:
    usage = _read_usage()
    remaining = usage.get("requests_remaining")
    if remaining is None:
        return True
    try:
        return int(remaining) > _reserve()
    except (TypeError, ValueError):
        return True


def _header_int(headers: dict[str, str], name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _request_json(path: str, key: str) -> tuple[Any, dict[str, str]]:
    """GET a path on the Odds API. The key is only sent as x-api-key."""
    req = urllib.request.Request(
        API_HOST + path,
        headers={
            "x-api-key": key,
            "Accept": "application/json",
            "User-Agent": "DaRealBigHomieProps/1.0",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return json.loads(resp.read()), headers
    except urllib.error.HTTPError as exc:
        status = getattr(exc, "code", 0) or 0
        # Do not log the response URL (urllib may include headers only;
        # still avoid printing the exception object itself).
        try:
            exc.close()
        except Exception:
            pass
        raise _OddsHttpError(status) from None


def _list_events(sport: str, date: str, key: str) -> list[dict[str, Any]]:
    sport_key = SPORT_KEYS[sport]
    # commenceTimeFrom/To are ISO 8601 UTC. Cover the ET calendar day.
    start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=ET)
    end = start.replace(hour=23, minute=59, second=59)
    start_utc = start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_utc = end.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = (
        f"/v4/sports/{sport_key}/events"
        f"?commenceTimeFrom={start_utc}&commenceTimeTo={end_utc}"
    )
    body, headers = _request_json(path, key)
    # This endpoint is documented as free; still record remaining if present.
    remaining = _header_int(headers, "x-requests-remaining")
    used = _header_int(headers, "x-requests-used")
    if remaining is not None or used is not None:
        _write_usage(date, spent_delta=0, remaining=remaining, used=used)
    if not isinstance(body, list):
        return []
    return [ev for ev in body if isinstance(ev, dict) and ev.get("id")]


def _event_odds(sport: str, event_id: str, market_key: str, key: str) -> tuple[dict, dict]:
    sport_key = SPORT_KEYS[sport]
    region = os.environ.get("ODDS_REGION", REGION)
    path = (
        f"/v4/sports/{sport_key}/events/{event_id}/odds"
        f"?regions={region}&markets={market_key}&oddsFormat=american"
    )
    body, headers = _request_json(path, key)
    if not isinstance(body, dict):
        body = {}
    return body, headers


def _match_events(events: list[dict[str, Any]], games: list) -> list[tuple[str, dict]]:
    remaining = list(events)
    matched: list[tuple[str, dict]] = []
    for game in games:
        espn_id = str(getattr(game, "event_id", "") or "")
        home = _norm_team(getattr(game, "home_name", "") or "")
        away = _norm_team(getattr(game, "away_name", "") or "")
        found = None
        for ev in remaining:
            ev_home = _norm_team(ev.get("home_team") or "")
            ev_away = _norm_team(ev.get("away_team") or "")
            if ev_home == home and ev_away == away:
                found = ev
                break
            # Tolerate flipped home/away or slightly different nicknames.
            if {ev_home, ev_away} == {home, away}:
                found = ev
                break
        if found:
            remaining.remove(found)
            matched.append((espn_id, found))
        else:
            print(f"  no Odds API event match for {away} @ {home}")
    return matched


def _merge_event_odds(
    payload: dict[str, Any],
    ev: dict[str, Any],
    espn_id: str,
    body: dict[str, Any],
    prop: str,
) -> None:
    event_id = ev.get("id") or body.get("id")
    slot = payload["events"].setdefault(
        espn_id or event_id,
        {
            "odds_event_id": event_id,
            "espn_event_id": espn_id,
            "home_team": ev.get("home_team") or body.get("home_team"),
            "away_team": ev.get("away_team") or body.get("away_team"),
            "commence_time": ev.get("commence_time") or body.get("commence_time"),
            "markets": {},
        },
    )
    players = slot["markets"].setdefault(prop, {})
    offers = _offers_from_bookmakers(body.get("bookmakers") or [], prop)
    for name, offer in offers.items():
        players[name] = {
            "line": offer.line,
            "over_price": offer.over_price,
            "under_price": offer.under_price,
            "book": offer.book,
            "book_title": offer.book_title,
            "source": "live",
        }


def _offers_from_bookmakers(bookmakers: list, prop: str) -> dict[str, LineOffer]:
    """Pick one book per player, preferring well-known US books."""
    by_player: dict[str, list[LineOffer]] = {}
    for book in bookmakers:
        if not isinstance(book, dict):
            continue
        book_key = book.get("key") or ""
        book_title = book.get("title") or book_key
        for market in book.get("markets") or []:
            if not isinstance(market, dict):
                continue
            # Group Over/Under outcomes by player description.
            sides: dict[str, dict[str, Any]] = {}
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome, dict):
                    continue
                player = (outcome.get("description") or "").strip()
                name = (outcome.get("name") or "").strip().lower()
                point = outcome.get("point")
                price = outcome.get("price")
                if not player or point is None:
                    continue
                rec = sides.setdefault(player, {})
                try:
                    rec["line"] = float(point)
                except (TypeError, ValueError):
                    continue
                try:
                    price_i = int(price) if price is not None else None
                except (TypeError, ValueError):
                    price_i = None
                if name == "over":
                    rec["over_price"] = price_i
                elif name == "under":
                    rec["under_price"] = price_i
            for player, rec in sides.items():
                if "line" not in rec:
                    continue
                by_player.setdefault(player, []).append(
                    LineOffer(
                        line=rec["line"],
                        source="live",
                        over_price=rec.get("over_price"),
                        under_price=rec.get("under_price"),
                        book=book_key,
                        book_title=book_title,
                    )
                )
    picked: dict[str, LineOffer] = {}
    for player, offers in by_player.items():
        offers_sorted = sorted(
            offers,
            key=lambda o: (
                PREFERRED_BOOKS.index(o.book) if o.book in PREFERRED_BOOKS else 99,
                0 if o.over_price is not None and o.under_price is not None else 1,
            ),
        )
        picked[player] = offers_sorted[0]
    return picked


def _lookup_live(player: dict, prop: str, sport: str) -> LineOffer | None:
    date = _active_date(sport)
    payload = _CACHE.get((sport, date)) if date else None
    if not payload and date:
        path = ODDS_CACHE_DIR / f"{sport}_{date}.json"
        payload = _load_json(path)
        if payload:
            _CACHE[(sport, date)] = payload
    if not payload:
        return None
    event_id = str(player.get("event_id") or "")
    ev = (payload.get("events") or {}).get(event_id)
    if not ev:
        # Some caches may be keyed by Odds API id if ESPN id was missing.
        return None
    market = (ev.get("markets") or {}).get(prop) or {}
    if not market:
        return None
    target = _norm_player(player.get("name") or "")
    short = _norm_player(player.get("short_name") or "")
    hit = None
    for name, rec in market.items():
        norm = _norm_player(name)
        if norm == target or (short and norm == short):
            hit = rec
            break
    if hit is None:
        # Unique last-name fallback.
        last = target.split(" ")[-1] if target else ""
        cands = [
            rec
            for name, rec in market.items()
            if last and _norm_player(name).split(" ")[-1] == last
        ]
        if len(cands) == 1:
            hit = cands[0]
    if not hit:
        return None
    try:
        line = float(hit["line"])
    except (KeyError, TypeError, ValueError):
        return None
    return LineOffer(
        line=line,
        source="live",
        over_price=hit.get("over_price"),
        under_price=hit.get("under_price"),
        book=hit.get("book") or "",
        book_title=hit.get("book_title") or "",
    )


def _active_date(sport: str) -> str:
    for (cached_sport, date), payload in _CACHE.items():
        if cached_sport == sport:
            return date
    # Fall back to the newest cache file for this sport.
    newest = None
    if ODDS_CACHE_DIR.exists():
        for path in ODDS_CACHE_DIR.glob(f"{sport}_*.json"):
            if newest is None or path.stat().st_mtime > newest.stat().st_mtime:
                newest = path
    if newest:
        payload = _load_json(newest)
        if payload:
            date = payload.get("date") or newest.stem.split("_", 1)[-1]
            _CACHE[(sport, date)] = payload
            return date
    return datetime.now(ET).date().isoformat()


def _store_cache(sport: str, date: str, payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _CACHE[(sport, date)] = payload


def _count_live(payload: dict[str, Any]) -> int:
    n = 0
    for ev in (payload.get("events") or {}).values():
        for market in (ev.get("markets") or {}).values():
            n += len(market or {})
    return n


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _norm_team(name: str) -> str:
    text = _fold(name)
    return TEAM_ALIASES.get(text, text)


def _norm_player(name: str) -> str:
    text = _fold(name)
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _fold(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()
