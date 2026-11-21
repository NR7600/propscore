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
    parser.add_argument("--workers", type=int, default=6, help="Parallel gamelog fetches.")
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

    if args.sport.lower() not in {"nba"}:
        raise SystemExit(f"{args.sport} is not implemented yet. Start with: python run.py nba")
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

    rows = rank_slate(players, logs, games, list(sport.props.keys()), sport=sport.key)
    qualified = {r.player_id for r in rows}
    print(f"Ranked {len(rows)} prop lines across {len(qualified)} players.")

    notes = []
    notes.append(
        "Data from ESPN public JSON (scoreboard, rosters, injuries, player gamelogs). "
        "cdn.nba.com returned 403 and stats.nba.com timed out from this environment."
    )
    notes.append(
        "No free odds feed is wired in; lines are standard over-thresholds "
        "(PTS 10/15/20/25, REB 4/6/8/10, AST 2/4/6/8, 3PM 1/2/3/4, PRA 15/20/25/30). "
        "Set ODDS_API_KEY later to swap in sportsbook lines."
    )
    if failed:
        notes.append(f"Game logs failed for {len(failed)} player(s).")
        print("Failed logs:")
        for line in failed[:8]:
            print("  ", line)

    stem = OUTPUT_DIR / f"{sport.key}_{date}"
    sources = [
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{id}/roster",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
        "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/gamelog",
    ]
    write_json(
        stem.with_suffix(".json"),
        sport=sport.key,
        date=date,
        generated_at=generated_at,
        sources=sources,
        games=games,
        players=players,
        logs=logs,
        rows=rows,
        notes=notes,
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
    print("Top 10 by trend score:")
    print(f"{'#':<4}{'Player':<24}{'Prop':<12}{'L10':>6}{'Strk':>6}{'Score':>8}")
    for i, r in enumerate(rows[:10], start=1):
        print(f"{i:<4}{r.player:<24}{r.line_label:<12}{r.l10*100:5.0f}%{r.streak:6d}{r.score:8.1f}")

    print()
    print("Wrote:")
    for ext in (".json", ".csv", ".html"):
        print(f"  {stem.with_suffix(ext)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
