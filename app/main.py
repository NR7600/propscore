"""PropScore API + static PWA.

Start from the project root:

    .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.board_store import STORE, available_dates, prune_old_boards, resolve_date, today_et
from app.response_cache import json_response
from propscore.odds import odds_status

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
REFRESH_HOUR = int(os.environ.get("PROPSCORE_REFRESH_HOUR", "5"))
SPORTS = [
    {"key": "nba", "name": "NBA", "available": True},
    {"key": "nhl", "name": "NHL", "available": True},
    {"key": "nfl", "name": "NFL", "available": True},
]
AVAILABLE_SPORTS = [s["key"] for s in SPORTS if s["available"]]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("propscore")

_refresh_lock = threading.Lock()
_refresh_state: dict = {"running": False, "last": None, "error": None, "current": None, "done": []}

app = FastAPI(title="Da Real Big Homie Props", version="1.8.0", docs_url="/api/docs", redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=500)


def _sport_or_404(sport: str) -> str:
    key = sport.lower().strip()
    meta = next((s for s in SPORTS if s["key"] == key), None)
    if not meta:
        raise HTTPException(404, f"Unknown sport {sport!r}")
    if not meta["available"]:
        raise HTTPException(404, f"{meta['name']} is coming soon")
    return key


def _board_date(sport: str, date: Optional[str]) -> str:
    resolved = resolve_date(sport, date)
    if not resolved:
        if _refresh_state.get("running"):
            raise HTTPException(
                503,
                "Today's slate is being generated. Refresh in about a minute.",
            )
        raise HTTPException(
            404,
            f"No generated {sport} board yet. Run: python3 run.py {sport}",
        )
    return resolved


@app.get("/health")
def health():
    return {
        "ok": True,
        "today": today_et(),
        "nba_dates": available_dates("nba"),
        "nhl_dates": available_dates("nhl"),
        "nfl_dates": available_dates("nfl"),
        "refresh": {
            "running": _refresh_state.get("running"),
            "last": _refresh_state.get("last"),
            "error": _refresh_state.get("error"),
            "current": _refresh_state.get("current"),
            "done": list(_refresh_state.get("done") or []),
        },
        "features": "strong-v1",
        "app": "Da Real Big Homie Props",
        "odds": odds_status(),
    }


@app.get("/api/sports")
def list_sports():
    return {"sports": SPORTS, "today": today_et()}


@app.get("/api/{sport}/meta")
def board_meta(request: Request, sport: str, date: Optional[str] = None):
    sport = _sport_or_404(sport)
    resolved = _board_date(sport, date)
    token = STORE.token(sport, resolved)
    key = f"meta:{sport}:{resolved}"
    return json_response(request, key, token, build=lambda: STORE.meta(sport, resolved))


@app.get("/api/{sport}/board")
def board(
    request: Request,
    sport: str,
    date: Optional[str] = None,
    stat: str = "",
    game: str = "",
    min_l10: float = Query(0.0, ge=0, le=1),
    hide_out: bool = False,
    hide_gimme: bool = False,
    view: str = Query("value", pattern="^(value|all)$"),
    q: str = "",
    side: str = Query("", pattern="^(|over|under)$"),
    perfect: bool = False,
    sort: str = Query("score", pattern="^(score|streak)$"),
    min_odds: Optional[int] = Query(None, ge=-500, le=500),
    tab: str = Query("", max_length=32),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=50),
):
    sport = _sport_or_404(sport)
    resolved = _board_date(sport, date)
    token = STORE.token(sport, resolved)
    key = (
        f"board:{sport}:{resolved}:{stat}:{game}:{min_l10}:{hide_out}:{hide_gimme}:"
        f"{view}:{q}:{side}:{perfect}:{sort}:{min_odds}:{tab}:{page}:{page_size}"
    )
    return json_response(
        request,
        key,
        token,
        build=lambda: STORE.query_board(
            sport,
            resolved,
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
            tab=tab,
            page=page,
            page_size=page_size,
        ),
    )


@app.get("/api/{sport}/player/{player_id}")
def player(request: Request, sport: str, player_id: str, date: Optional[str] = None):
    sport = _sport_or_404(sport)
    resolved = _board_date(sport, date)
    token = STORE.token(sport, resolved)
    key = f"player:{sport}:{resolved}:{player_id}"

    def build():
        payload = STORE.player(sport, resolved, player_id)
        if not payload:
            raise HTTPException(404, "Player not on this slate (or not enough games to rank).")
        return payload

    return json_response(request, key, token, build=build)


@app.get("/api/{sport}/player/{player_id}/logs")
def player_logs(request: Request, sport: str, player_id: str, date: Optional[str] = None):
    sport = _sport_or_404(sport)
    resolved = _board_date(sport, date)
    token = STORE.token(sport, resolved)
    key = f"logs:{sport}:{resolved}:{player_id}"

    def build():
        payload = STORE.player_logs(sport, resolved, player_id)
        if not payload:
            raise HTTPException(404, "Player not on this slate.")
        return payload

    return json_response(request, key, token, build=build)


@app.get("/api/{sport}/report/{player_id}")
def prop_report(
    request: Request,
    sport: str,
    player_id: str,
    date: Optional[str] = None,
    prop: str = "",
    side: str = Query("over", pattern="^(over|under)$"),
    line: Optional[float] = None,
):
    sport = _sport_or_404(sport)
    resolved = _board_date(sport, date)
    token = STORE.token(sport, resolved)
    key = f"report:{sport}:{resolved}:{player_id}:{prop}:{side}:{line}"

    def build():
        payload = STORE.prop_report(sport, resolved, player_id, prop, side, line)
        if not payload:
            raise HTTPException(404, "No report for that player and prop on this slate.")
        return payload

    return json_response(request, key, token, build=build)


@app.get("/api/{sport}/game/{event_id}")

def game_context(request: Request, sport: str, event_id: str, date: Optional[str] = None):
    sport = _sport_or_404(sport)
    resolved = _board_date(sport, date)
    token = STORE.token(sport, resolved)
    key = f"game:{sport}:{resolved}:{event_id}"

    def build():
        payload = STORE.game_context(sport, resolved, event_id)
        if not payload:
            raise HTTPException(404, "Game not on this slate.")
        return payload

    return json_response(request, key, token, build=build)


def _sports_to_refresh(requested: str) -> list[str]:
    key = (requested or "all").lower().strip()
    if key in {"", "all"}:
        return list(AVAILABLE_SPORTS)
    return [_sport_or_404(key)]


@app.post("/api/refresh")
def refresh(
    sport: str = "all",
    date: Optional[str] = None,
    x_refresh_token: Optional[str] = Header(default=None),
):
    """Rebuild boards by running `python3 run.py <sport>`.

    Pass sport=all (the default) to rebuild every available sport.
    If REFRESH_TOKEN is set in the environment, send it as X-Refresh-Token.
    """
    expected = os.environ.get("REFRESH_TOKEN", "").strip()
    if expected and x_refresh_token != expected:
        raise HTTPException(401, "Invalid or missing X-Refresh-Token")
    sports = _sports_to_refresh(sport)
    if _refresh_state["running"]:
        _refresh_state["pending"] = {"sports": sports, "date": date}
        return JSONResponse(
            {"ok": True, "status": "queued", "sports": sports, "date": date or today_et()},
            status_code=202,
        )
    thread = threading.Thread(target=_run_refresh_sports, args=(sports, date), daemon=True)
    thread.start()
    return {"ok": True, "status": "started", "sports": sports, "date": date or today_et()}


def _run_one_sport(
    sport: str,
    date: Optional[str],
    skip_odds: bool = False,
    skip_pbp: bool = False,
) -> None:
    cmd = [sys.executable, str(ROOT / "run.py"), sport, "--json-only"]
    if date:
        cmd.extend(["--date", date])
    if skip_odds:
        cmd.append("--skip-odds")
    if skip_pbp:
        cmd.append("--skip-pbp")
    workers = os.environ.get("PROPSCORE_WORKERS", "").strip()
    if not workers and os.environ.get("RENDER"):
        workers = "3"
    if workers:
        cmd.extend(["--workers", workers])
    log.info("Refreshing board: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:] or proc.stdout[-2000:] or f"exit {proc.returncode}")


def _run_refresh_sports(
    sports: list[str],
    date: Optional[str],
    skip_odds: bool = False,
    skip_pbp: bool = False,
) -> None:
    if not _refresh_lock.acquire(blocking=False):
        return
    _refresh_state["running"] = True
    _refresh_state["error"] = None
    _refresh_state["current"] = None
    _refresh_state["done"] = []
    started = datetime.now(ET)
    try:
        from propscore.slate_date import build_date_for
        errors: list[str] = []
        for sport in sports:
            _refresh_state["current"] = sport
            sport_date = date or build_date_for(sport)
            try:
                _run_one_sport(sport, sport_date, skip_odds=skip_odds, skip_pbp=skip_pbp)
                pruned = prune_old_boards(sport)
                if pruned:
                    log.info("Pruned old %s boards: %s", sport, ", ".join(pruned))
                _refresh_state["done"] = list(_refresh_state.get("done") or []) + [sport]
                log.info("Published %s board (%s)", sport, sport_date)
            except Exception as exc:
                log.exception("Refresh failed for %s", sport)
                errors.append(f"{sport}: {exc}")
        _refresh_state["current"] = None
        if errors:
            _refresh_state["error"] = "; ".join(errors)
        else:
            _refresh_state["last"] = datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET")
        log.info("Refresh finished in %ss", int((datetime.now(ET) - started).total_seconds()))
    except Exception as exc:
        log.exception("Refresh failed")
        _refresh_state["error"] = str(exc)
        _refresh_state["current"] = None
    finally:
        _refresh_state["running"] = False
        _refresh_lock.release()
        pending = _refresh_state.pop("pending", None)
        if pending:
            threading.Thread(
                target=_run_refresh_sports,
                args=(pending["sports"], pending.get("date"), False, False),
                daemon=True,
            ).start()


def _scheduler_loop() -> None:
    log.info("Daily refresh scheduler on, targeting %02d:00 America/New_York", REFRESH_HOUR)
    while True:
        now = datetime.now(ET)
        target = now.replace(hour=REFRESH_HOUR, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        time.sleep(max(1.0, (target - now).total_seconds()))
        try:
            _run_refresh_sports(list(AVAILABLE_SPORTS), None)
        except Exception:
            log.exception("Scheduled refresh failed")


@app.on_event("startup")
def on_startup() -> None:
    (ROOT / "output").mkdir(parents=True, exist_ok=True)
    (ROOT / "cache").mkdir(parents=True, exist_ok=True)
    pruned = prune_old_boards()
    if pruned:
        log.info("Pruned old board files on startup: %s", ", ".join(pruned))
    thread = threading.Thread(target=_scheduler_loop, name="propscore-scheduler", daemon=True)
    thread.start()
    # Fresh deploys have no output/: generate any missing today's boards
    # in the background so the first visit does not have to trigger a rebuild.
    from propscore.slate_date import build_date_for
    missing = [s for s in AVAILABLE_SPORTS if build_date_for(s) not in available_dates(s)]
    if missing and not _refresh_state["running"]:
        log.info("No board for the upcoming slate in %s; generating in the background", ", ".join(missing))
        # Render's free disk is wiped on every sleep/restart. Auto-fetching
        # odds on boot would re-spend the daily credit budget each wake.
        # Manual and scheduled refresh still fetch (subject to the cap).
        on_render = bool(os.environ.get("RENDER"))
        fetch_on_boot = os.environ.get("ODDS_FETCH_ON_BOOT", "").strip().lower() in {"1", "true", "yes"}
        skip_odds = on_render and not fetch_on_boot
        # Never skip play-by-play: an empty 1FG list is worse than a
        # slightly longer first boot, and compact PBP extracts are fast.
        threading.Thread(
            target=_run_refresh_sports,
            args=(missing, None, skip_odds, False),
            daemon=True,
        ).start()


# --- static PWA assets (after API routes) ---

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(
        STATIC / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/favicon.png")
def favicon():
    return FileResponse(STATIC / "icons" / "favicon.png")


app.mount("/icons", StaticFiles(directory=STATIC / "icons"), name="icons")
app.mount("/", StaticFiles(directory=STATIC, html=False), name="static")
