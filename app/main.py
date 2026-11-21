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

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.board_store import STORE, available_dates, resolve_date, today_et

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
REFRESH_HOUR = int(os.environ.get("PROPSCORE_REFRESH_HOUR", "10"))
SPORTS = [
    {"key": "nba", "name": "NBA", "available": True},
    {"key": "nhl", "name": "NHL", "available": True},
    {"key": "nfl", "name": "NFL", "available": False, "status": "Coming soon"},
]
AVAILABLE_SPORTS = [s["key"] for s in SPORTS if s["available"]]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("propscore")

_refresh_lock = threading.Lock()
_refresh_state: dict = {"running": False, "last": None, "error": None}

app = FastAPI(title="Da Real Big Homie Props", version="1.2.0", docs_url="/api/docs", redoc_url=None)
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
                "Tonight's board is being generated. Refresh in about a minute.",
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
        "refresh": _refresh_state,
        "features": "trends-v2",
        "app": "Da Real Big Homie Props",
    }


@app.get("/api/sports")
def list_sports():
    return {"sports": SPORTS, "today": today_et()}


@app.get("/api/{sport}/meta")
def board_meta(sport: str, date: Optional[str] = None):
    sport = _sport_or_404(sport)
    resolved = _board_date(sport, date)
    return STORE.meta(sport, resolved)


@app.get("/api/{sport}/board")
def board(
    sport: str,
    date: Optional[str] = None,
    stat: str = "",
    game: str = "",
    min_l10: float = Query(0.7, ge=0, le=1),
    hide_out: bool = True,
    hide_gimme: bool = False,
    view: str = Query("value", pattern="^(value|all)$"),
    q: str = "",
    side: str = Query("", pattern="^(|over|under)$"),
    perfect: bool = False,
    sort: str = Query("score", pattern="^(score|streak)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=50),
):
    sport = _sport_or_404(sport)
    resolved = _board_date(sport, date)
    return STORE.query_board(
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
        page=page,
        page_size=page_size,
    )


@app.get("/api/{sport}/player/{player_id}")
def player(sport: str, player_id: str, date: Optional[str] = None):
    sport = _sport_or_404(sport)
    resolved = _board_date(sport, date)
    payload = STORE.player(sport, resolved, player_id)
    if not payload:
        raise HTTPException(404, "Player not on this slate (or not enough games to rank).")
    return payload


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
        return JSONResponse({"ok": False, "status": "already_running"}, status_code=409)
    thread = threading.Thread(target=_run_refresh_sports, args=(sports, date), daemon=True)
    thread.start()
    return {"ok": True, "status": "started", "sports": sports, "date": date or today_et()}


def _run_one_sport(sport: str, date: Optional[str]) -> None:
    cmd = [sys.executable, str(ROOT / "run.py"), sport]
    if date:
        cmd.extend(["--date", date])
    log.info("Refreshing board: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:] or proc.stdout[-2000:] or f"exit {proc.returncode}")


def _run_refresh_sports(sports: list[str], date: Optional[str]) -> None:
    if not _refresh_lock.acquire(blocking=False):
        return
    _refresh_state["running"] = True
    _refresh_state["error"] = None
    started = datetime.now(ET)
    try:
        for sport in sports:
            _run_one_sport(sport, date)
        _refresh_state["last"] = datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET")
        log.info("Refresh finished in %ss", int((datetime.now(ET) - started).total_seconds()))
    except Exception as exc:
        log.exception("Refresh failed")
        _refresh_state["error"] = str(exc)
    finally:
        _refresh_state["running"] = False
        _refresh_lock.release()


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
    thread = threading.Thread(target=_scheduler_loop, name="propscore-scheduler", daemon=True)
    thread.start()
    # Fresh deploys have no output/: generate any missing today's boards
    # in the background so the first visit does not have to trigger a rebuild.
    missing = [s for s in AVAILABLE_SPORTS if today_et() not in available_dates(s)]
    if missing and not _refresh_state["running"]:
        log.info("No board for today (%s) in %s; generating in the background", today_et(), ", ".join(missing))
        threading.Thread(target=_run_refresh_sports, args=(missing, None), daemon=True).start()


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
