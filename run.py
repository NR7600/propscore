#!/usr/bin/env python3
"""Regenerate tonight's PropScore board.

Usage:
    python run.py nba
    python run.py nba --date 2026-11-21
    python run.py nba --no-cache
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from propscore.http import HttpClient
from propscore.output import write_csv, write_html, write_json
from propscore.ranking import rank_slate
from propscore.sports import get_sport

ET = ZoneInfo("America/New_York")
OUTPUT_DIR = ROOT / "output"
CACHE_DIR = ROOT / "cache"


def today_et() -> str:
    return datetime.now(ET).date().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the PropScore player-prop board.")
    parser.add_argument("sport", help="Sport to build (nba is implemented first).")
    parser.add_argument("--date", help="Slate date YYYY-MM-DD in America/New_York. Defaults to today.")
    parser.add_argument("--no-cache", action="store_true", help="Ignore cached ESPN responses.")
    parser.add_argument(
        "--skip-odds",
        action="store_true",
        help="Do not call The Odds API (still uses a same-day cache if one exists).",
    )
    parser.add_argument("--workers", type=int, default=6, help="Parallel gamelog fetches.")
    parser.add_argument(
        "--skip-pbp",
        action="store_true",
        help="Do not fetch new ESPN play-by-play; reuse the compact first-score cache only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    date = args.date or today_et()
    generated_at = datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    use_cache = not args.no_cache

    client = HttpClient(CACHE_DIR / args.sport.lower() / date)
    # HttpClient caches whenever a cache_key is set; wipe is enough for --no-cache.
    if not use_cache:
        client = HttpClient(CACHE_DIR / args.sport.lower() / f"{date}_fresh")

    if args.sport.lower() not in {"nba", "nhl"}:
        raise SystemExit(f"{args.sport} is not implemented yet. Available: nba, nhl")
    sport = get_sport(args.sport, client)

    print(f"Fetching {sport.display_name} slate for {date} (America/New_York)...")
    games = sport.fetch_slate(date)
    if not games:
        raise SystemExit(f"No {sport.display_name} games found for {date}.")
    for g in games:
        print(f"  {g.label():<16} {g.start_et:<16} {g.status}")

    print("Fetching injuries and rosters...")
    injuries = sport.fetch_injuries()
    team_ids = {}
    for g in games:
        team_ids[g.home_id] = (g.home_abbr, g.home_name)
        team_ids[g.away_id] = (g.away_abbr, g.away_name)

    players = []
    for team_id, (abbr, name) in team_ids.items():
        players.extend(sport.fetch_roster(team_id, abbr, name))
    sport.apply_injuries(players, injuries)
    print(f"  {len(players)} rostered players, {len(injuries)} injury records.")

    print(f"Fetching regular-season game logs ({args.workers} workers)...")
    logs = {}
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(sport.fetch_game_logs, p.id): p for p in players}
        done = 0
        for fut in as_completed(futs):
            player = futs[fut]
            done += 1
            try:
                logs[player.id] = fut.result()
            except Exception as exc:
                failed.append(f"{player.name}: {exc}")
                logs[player.id] = []
            if done % 20 == 0 or done == len(players):
                print(f"  {done}/{len(players)} logs")

    from propscore.context import attach_defense, attach_without_splits, games_with_context
    from propscore.defense import fetch_defense_ranks
    from propscore.odds import prefetch_slate

    print("Loading player-prop lines (Odds API if a key is set, else estimated lines)...")
    odds_report = prefetch_slate(
        sport.key,
        date,
        games,
        cache_dir=ROOT / "cache" / "odds",
        skip_fetch=args.skip_odds,
    )
    # CACHE_DIR is cache/{sport}/{date}; odds live at cache/odds/.

    qual = getattr(sport, "qualification", None)
    rows = rank_slate(
        players,
        logs,
        games,
        list(sport.props.keys()),
        sport=sport.key,
        qualification=qual,
        slate_date=date,
    )
    defense = fetch_defense_ranks(sport.key, client)
    attach_defense(rows, defense)
    attach_without_splits(rows, players, logs, slate_date=date)
    game_payloads = games_with_context(games, players)
    from propscore.first_score import build_first_score_rows

    print("Building first-basket / first-goal trends from ESPN play-by-play...")
    first_score_rows, first_score_meta, first_score_flags = build_first_score_rows(
        sport=sport.key,
        slate_date=date,
        games=games,
        players=players,
        logs=logs,
        client=client,
        cache_root=CACHE_DIR,
        skip_fetch=args.skip_pbp,
    )
    print(
        f"  First-score: {first_score_meta.get('events_used', 0)} games used "
        f"(cached {first_score_meta.get('events_cached', 0)}, "
        f"fetched {first_score_meta.get('events_fetched', 0)}, "
        f"missing {first_score_meta.get('events_missing', 0)}, "
        f"{len(first_score_rows)} ranked players)."
    )

    qualified = {r.player_id for r in rows}
    print(f"Ranked {len(rows)} prop lines across {len(qualified)} players.")
    live_rows = sum(1 for r in rows if getattr(r, "line_source", "") == "live")
    print(
        f"Live sportsbook lines on {live_rows} ranked rows "
        f"(odds report: spent {odds_report.get('credits_spent', 0)}, "
        f"remaining {odds_report.get('remaining')}, "
        f"cached={odds_report.get('cached')})."
    )

    notes = []
    if sport.key == "nhl":
        notes.append(
            "Data from ESPN public JSON (NHL scoreboard, rosters, injuries, player gamelogs). "
            "Season year 2027 = 2026-27. Skater logs include goals, assists, points, shots, "
            "and TOI; they do not include hits or blocked shots, so those props are omitted. "
            "Goalie logs include starts and saves."
        )
        notes.append(
            "When ODDS_API_KEY is set, main NHL markets (SOG, points, saves) use "
            "US sportsbook lines from The Odds API (region=us), cached for the day "
            "and capped at a small daily credit budget. Missing lines fall back to "
            "standard thresholds (G 0.5/1.5, A 0.5/1.5, PTS 0.5/1.5/2.5, "
            "SOG 1.5/2.5/3.5/4.5, SV 20.5/25.5/30.5), marked as standard. "
            "Skaters need 5 games and ~10 minutes TOI; goalies need 5 starts. "
            "The app runs without a key."
        )
        notes.append(
            "Opponent defense is team goals allowed from ESPN standings (not "
            "defense-vs-position). H2H, home/away, rest/B2B, TOI trend, and "
            "without-teammate splits are computed from ESPN player game logs."
        )
        sources = [
            "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
            "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams/{id}/roster",
            "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries",
            "https://site.web.api.espn.com/apis/common/v3/sports/hockey/nhl/athletes/{id}/gamelog",
            "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary?event={id}",
            "https://api.the-odds-api.com/v4/sports/icehockey_nhl/events (free); /events/{id}/odds (credits)",
        ]
        notes.append(
            "First Goal trends come from ESPN play-by-play (summary plays) for each "
            "team's completed games this season: who scored that team's first goal, "
            "hit rate in L5/L10/L20/season, streak, and opening-faceoff win rate. "
            "Compact extracts are cached on disk and only new games are fetched."
        )
    else:
        notes.append(
            "Data from ESPN public JSON (scoreboard, rosters, injuries, player gamelogs). "
            "cdn.nba.com returned 403 and stats.nba.com timed out from this environment."
        )
        notes.append(
            "When ODDS_API_KEY is set, main NBA markets (PTS, REB, AST, 3PM, PRA) use "
            "US sportsbook lines from The Odds API (region=us), cached for the day "
            "and capped at a small daily credit budget (NBA first). Missing lines "
            "fall back to standard thresholds, marked as standard, and displayed "
            "as half-lines (25+ is Over/Under 24.5). The app runs without a key."
        )
        notes.append(
            "Opponent defense is team points allowed from ESPN standings (not "
            "defense-vs-position). H2H, home/away, rest/B2B, minutes trend, and "
            "without-teammate splits are computed from ESPN player game logs."
        )
        sources = [
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{id}/roster",
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
            "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/gamelog",
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={id}",
            "https://api.the-odds-api.com/v4/sports/basketball_nba/events (free); /events/{id}/odds (credits)",
        ]
        notes.append(
            "First Basket trends come from ESPN play-by-play (summary plays) for each "
            "team's completed games this season: who scored that team's first basket, "
            "hit rate in L5/L10/L20/season, streak, whether the player started, and "
            "the team's opening-tip win rate. Compact extracts are cached on disk "
            "and only new games are fetched."
        )
    if failed:
        notes.append(f"Game logs failed for {len(failed)} player(s).")
        print("Failed logs:")
        for line in failed[:8]:
            print("  ", line)

    stem = OUTPUT_DIR / f"{sport.key}_{date}"
    write_json(
        stem.with_suffix(".json"),
        sport=sport.key,
        date=date,
        generated_at=generated_at,
        sources=sources,
        games=game_payloads,
        players=players,
        logs=logs,
        rows=rows,
        notes=notes,
        first_score_rows=first_score_rows,
        first_score_meta=first_score_meta,
        first_score_flags=first_score_flags,
    )
    write_csv(stem.with_suffix(".csv"), rows)
    write_html(
        stem.with_suffix(".html"),
        sport=sport.key,
        date=date,
        generated_at=generated_at,
        games=games,
        players=players,
        logs=logs,
        rows=rows,
        notes=notes,
    )

    print()
    print("Top 10 first-score trends:")
    print(f"{'#':<4}{'Player':<24}{'Line':<16}{'Season':>10}{'L10':>8}{'Strk':>6}{'Score':>8}")
    for i, r in enumerate(first_score_rows[:10], start=1):
        season = f"{r['season_hits']}/{r['season_games']}"
        print(
            f"{i:<4}{r['player']:<24}{r['line_label']:<16}{season:>10}"
            f"{r['l10']*100:7.0f}%{r['streak']:6d}{r['score']:8.1f}"
        )

    print()
    print("Wrote:")
    for ext in (".json", ".csv", ".html"):
        print(f"  {stem.with_suffix(ext)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
