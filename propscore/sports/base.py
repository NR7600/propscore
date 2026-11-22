"""Shared dataclasses and the adapter interface every sport implements."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Protocol


@dataclass
class Game:
    event_id: str
    start_utc: str
    start_et: str
    home_id: str
    home_abbr: str
    home_name: str
    away_id: str
    away_abbr: str
    away_name: str
    status: str

    def label(self) -> str:
        return f"{self.away_abbr} @ {self.home_abbr}"

    def vs_label(self) -> str:
        # Slipscore-style "PHI vs MIL" (home vs away).
        return f"{self.home_abbr} vs {self.away_abbr}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.vs_label()
        d["away_at_home"] = self.label()
        return d


@dataclass
class Injury:
    player_id: str | None
    player_name: str
    status: str
    detail: str | None = None
    comment: str | None = None
    return_date: str | None = None


@dataclass
class Player:
    id: str
    name: str
    short_name: str
    team_id: str
    team_abbr: str
    team_name: str
    position: str
    jersey: str
    headshot: str
    role: str = "skater"  # "skater" or "goalie"
    injury_status: str | None = None
    injury_detail: str | None = None
    injury_comment: str | None = None
    injury_return: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class GameLog:
    event_id: str
    date: str
    opponent_abbr: str
    is_home: bool
    minutes: float
    points: int
    rebounds: int
    assists: int
    threes: int
    pra: int
    result: str | None = None
    # Hockey (and future sports). Basketball leaves these at defaults.
    goals: int = 0
    shots: int = 0
    blocked: int = 0
    hits: int = 0
    saves: int = 0
    started: bool = False
    steals: int = 0
    fgm: int = 0
    # Football. Basketball / hockey leave these at defaults.
    pass_yds: int = 0
    pass_td: int = 0
    completions: int = 0
    pass_att: int = 0
    ints: int = 0
    rush_yds: int = 0
    rush_att: int = 0
    rush_td: int = 0
    receptions: int = 0
    rec_yds: int = 0
    rec_td: int = 0
    targets: int = 0
    anytime_td: int = 0
    turnovers: int = 0
    long_rush: int = 0
    long_rec: int = 0
    fg_made: int = 0
    prior_season: bool = False
    season_year: int = 0

    def value(self, stat: str) -> float:
        if stat == "blocks":
            raw = self.blocked
        elif stat == "pts_reb":
            raw = self.points + self.rebounds
        elif stat == "pts_ast":
            raw = self.points + self.assists
        elif stat == "reb_ast":
            raw = self.rebounds + self.assists
        elif stat == "pra":
            raw = self.pra if self.pra else (self.points + self.rebounds + self.assists)
        elif stat == "rush_rec_yds":
            raw = self.rush_yds + self.rec_yds
        elif stat == "anytime_td":
            raw = self.anytime_td if self.anytime_td else (self.rush_td + self.rec_td)
        elif stat == "stl_blk":
            raw = self.steals + self.blocked
        elif stat == "turnovers":
            raw = self.turnovers
        elif stat == "long_rush":
            raw = self.long_rush
        elif stat == "long_rec":
            raw = self.long_rec
        elif stat == "fg_made":
            raw = self.fg_made
        else:
            raw = getattr(self, stat, 0)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["venue"] = "H" if self.is_home else "A"
        return d


# Render free tier is 512 MB. Rank from a short history and persist
# only the recent games the game-log modal actually reads.
MAX_RANK_LOGS = 80
STORED_LOG_LIMIT = 30
SECOND_PRIOR_BELOW = 30

# Fields the board UI / report / box score read. Everything else is dropped.
STORED_LOG_FIELDS = (
    "event_id",
    "date",
    "opponent_abbr",
    "is_home",
    "venue",
    "minutes",
    "points",
    "rebounds",
    "assists",
    "threes",
    "pra",
    "steals",
    "blocked",
    "fgm",
    "goals",
    "shots",
    "saves",
    "started",
    "pass_yds",
    "pass_td",
    "completions",
    "pass_att",
    "ints",
    "rush_yds",
    "rush_att",
    "rush_td",
    "receptions",
    "rec_yds",
    "rec_td",
    "targets",
    "anytime_td",
    "turnovers",
    "long_rush",
    "long_rec",
    "first_score",
    "prior_season",
    "result",
)
# False is a real value for these; other empty/zero defaults are omitted.
_KEEP_FALSE = {"is_home"}


def _played_count(rows: list[GameLog]) -> int:
    return sum(1 for g in rows if g.minutes and g.minutes > 0)


def merge_season_logs(
    current: list[GameLog],
    fetch_prior,
    current_year: int,
    *,
    max_logs: int = MAX_RANK_LOGS,
    second_prior_below: int = SECOND_PRIOR_BELOW,
) -> list[GameLog]:
    """Current season plus at most one prior year.

    A second prior year is fetched only when the player still has fewer
    than `second_prior_below` played games (rookies / short history).
    Rank-time history is capped at `max_logs` played games, newest first.
    """
    rows = list(current or [])
    played = _played_count(rows)
    if played < max_logs:
        rows.extend(fetch_prior(current_year - 1) or [])
        played = _played_count(rows)
    if played < second_prior_below:
        rows.extend(fetch_prior(current_year - 2) or [])
    uniq: dict[str, GameLog] = {}
    for row in rows:
        uniq[row.event_id or f"{row.date}-{row.opponent_abbr}"] = row
    ordered = sorted(uniq.values(), key=lambda g: (g.date, g.event_id), reverse=True)
    kept: list[GameLog] = []
    n_played = 0
    for game in ordered:
        kept.append(game)
        if game.minutes and game.minutes > 0:
            n_played += 1
            if n_played >= max_logs:
                break
    return kept


def slim_stored_log(log: dict) -> dict:
    """Keep only UI fields and drop empty defaults so board JSON stays small."""
    out: dict = {}
    for key in STORED_LOG_FIELDS:
        if key not in log:
            continue
        value = log[key]
        if value is None or value == "":
            continue
        # False == 0 in Python, so venue flags must be checked first.
        if key in _KEEP_FALSE:
            out[key] = value
            continue
        if value is False or value == 0 or value == 0.0:
            continue
        out[key] = value
    return out


@dataclass
class Slate:
    date: str  # YYYY-MM-DD in America/New_York
    games: list[Game] = field(default_factory=list)
    players: list[Player] = field(default_factory=list)
    logs: dict[str, list[GameLog]] = field(default_factory=dict)


class Sport(Protocol):
    key: str
    display_name: str
    # stat key -> (short label, output field name on GameLog)
    props: dict[str, str]

    def fetch_slate(self, date: str) -> list[Game]:
        ...

    def fetch_injuries(self) -> list[Injury]:
        ...

    def fetch_roster(self, team_id: str, team_abbr: str, team_name: str) -> list[Player]:
        ...

    def fetch_game_logs(self, player_id: str) -> list[GameLog]:
        ...
