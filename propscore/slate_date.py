"""Build-date helper: pick the current open slate, never a past day."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def today_et() -> str:
    return datetime.now(ET).date().isoformat()


def build_date_for(sport: str, explicit: str | None = None) -> str:
    """Date to build for a sport.

    Uses today's ET slate if any game has not yet finished. When every
    game today is Final (or postponed/canceled), rolls forward: NBA/NHL
    to the next day that has games, NFL to the next NFL game day.
    Never returns a date before today.
    """
    if explicit:
        return explicit
    from .live_status import open_slate_date

    day = open_slate_date(sport)
    today = today_et()
    return day if day >= today else today
