"""Build-date helper: NFL looks ahead to the next game day."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
LOOKAHEAD = {"nfl": 7}


def today_et() -> str:
    return datetime.now(ET).date().isoformat()


def build_date_for(sport: str, explicit: str | None = None) -> str:
    """Date to build for a sport.

    NBA/NHL use today. NFL looks up to 7 days ahead so a mid-week
    refresh (or boot) builds the next upcoming slate, never a past week.
    """
    if explicit:
        return explicit
    today = today_et()
    key = (sport or "").lower()
    if LOOKAHEAD.get(key, 0) <= 0:
        return today
    from .http import HttpClient
    from .sports.nfl import date_with_games

    client = HttpClient(ROOT / "cache" / "nfl" / "slate_probe")
    return date_with_games(client, today, lookahead=LOOKAHEAD[key])
