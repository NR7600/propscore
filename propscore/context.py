"""Post-ranking context: opponent defense, without-teammate splits, game news."""

from __future__ import annotations

from .defense import fetch_defense_ranks, matchup_tag
from .ranking import PropRow, _is_hit, _played
from .sports.base import Game, GameLog, Injury, Player

OUT_STATUSES = {
    "out",
    "ofs",
    "ir",
    "ir-lt",
    "ltir",
    "injured reserve",
    "injured reserve - long-term",
}


def _is_out(status: str | None) -> bool:
    if not status:
        return False
    text = status.strip().lower()
    if text in OUT_STATUSES:
        return True
    return "injured reserve" in text


def attach_defense(rows: list[PropRow], ranks: dict[str, dict]) -> None:
    for row in rows:
        info = ranks.get((row.opponent or "").upper())
        if not info:
            continue
        row.opp_def_rank = info.get("rank")
        row.opp_def_teams = info.get("teams")
        row.opp_def_value = info.get("value")
        row.opp_def_stat = info.get("stat") or ""
        row.opp_def_label = info.get("label") or ""
        row.matchup_tag = matchup_tag(row.opp_def_rank, row.opp_def_teams, row.side)


def attach_without_splits(
    rows: list[PropRow],
    players: list[Player],
    logs_by_player: dict[str, list[GameLog]],
    slate_date: str = "",
) -> None:
    """Hit rate in games where a currently-out teammate did not play.

    Needs a teammate who is listed Out/OFS/IR and at least 3 overlapping
    games where that teammate logged 0 minutes or has no log.
    """
    by_team: dict[str, list[Player]] = {}
    for player in players:
        by_team.setdefault(player.team_id, []).append(player)

    out_by_team: dict[str, list[Player]] = {}
    for team_id, roster in by_team.items():
        missing = [p for p in roster if _is_out(p.injury_status)]
        if missing:
            out_by_team[team_id] = missing

    if not out_by_team:
        return

    # Precompute event ids where each out teammate actually played.
    played_events: dict[str, set[str]] = {}
    for team_id, missing in out_by_team.items():
        for mate in missing:
            evs = set()
            for log in _played(logs_by_player.get(mate.id) or [], before_date=slate_date):
                if log.event_id:
                    evs.add(log.event_id)
            played_events[mate.id] = evs

    player_by_id = {p.id: p for p in players}
    cache: dict[tuple[str, str, float, str, str], list[dict]] = {}

    for row in rows:
        player = player_by_id.get(row.player_id)
        if not player:
            continue
        mates = [m for m in out_by_team.get(player.team_id, []) if m.id != player.id]
        if not mates:
            continue
        key = (row.player_id, row.prop, row.line, row.side)
        # Mates are the same for every row of this player; include them in the key
        # so the cache still works across props.
        mate_key = key + (tuple(m.id for m in mates),)
        if mate_key not in cache:
            played = _played(logs_by_player.get(player.id) or [], before_date=slate_date)
            splits = []
            for mate in mates:
                without = [
                    g
                    for g in played
                    if not g.event_id or g.event_id not in played_events.get(mate.id, set())
                ]
                if len(without) < 3:
                    continue
                hits = sum(1 for g in without if _is_hit(g, row.prop, row.line, row.side))
                n = len(without)
                avg = sum(g.value(row.prop) for g in without) / n
                splits.append(
                    {
                        "player_id": mate.id,
                        "player": mate.name,
                        "status": mate.injury_status,
                        "games": n,
                        "hits": hits,
                        "rate": round(hits / n, 4),
                        "avg": round(avg, 2),
                    }
                )
            cache[mate_key] = splits
        # Recompute per prop/line/side — the cache key already includes those,
        # but splits inside were computed with this row's prop/line/side. Good.
        row.without = cache[mate_key]


def games_with_context(
    games: list[Game],
    players: list[Player],
) -> list[dict]:
    """Attach both-team injury lists (and comment-as-news) to each game."""
    by_team: dict[str, list[Player]] = {}
    for player in players:
        by_team.setdefault(player.team_id, []).append(player)

    payloads = []
    for game in games:
        injuries = []
        news = []
        for team_id, abbr in (
            (game.away_id, game.away_abbr),
            (game.home_id, game.home_abbr),
        ):
            for player in by_team.get(team_id, []):
                if not player.injury_status:
                    continue
                item = {
                    "player_id": player.id,
                    "player": player.name,
                    "team": abbr,
                    "team_id": team_id,
                    "position": player.position,
                    "status": player.injury_status,
                    "detail": player.injury_detail,
                    "comment": player.injury_comment,
                    "return_date": player.injury_return,
                }
                injuries.append(item)
                if player.injury_comment:
                    news.append(item)
        payload = game.to_dict()
        payload["injuries"] = injuries
        payload["news"] = news
        payloads.append(payload)
    return payloads
