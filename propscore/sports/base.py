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


@dataclass
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
