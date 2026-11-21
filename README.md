# Da Real Big Homie Props

A Slipscore-style player prop research app (the code and repo are still named `propscore`). It pulls tonight’s NBA or NHL slate,
recent game logs, and injury tags, then ranks standard over **and** under
lines by trend strength. Cards show L5/L10/L20/season/H2H hit rates, home/away
and game streaks, rest/B2B, and a player page with a hit/miss bar chart, box
score, both-team injuries, and an on-device slip builder. Use it in the
browser or install it to a phone’s Home Screen.

A sourced inventory of Slipscore’s public features is in
[SLIPSCORE_FEATURES.md](SLIPSCORE_FEATURES.md).

**21+. Research only. This is not a sportsbook and not betting advice.**

## Run the app

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py nba          # (re)build tonight’s NBA board
.venv/bin/python run.py nhl          # (re)build tonight’s NHL board
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). The JSON API is
paginated so a phone never downloads the full 3 MB board file.

Restart the same way if the server is stopped:

```bash
cd /workspace/propscore
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The process also rebuilds the NBA board every day at 10:00 AM America/New_York
(while it is running) and on `POST /api/refresh`. To regenerate by hand:

```bash
.venv/bin/python run.py nba
.venv/bin/python run.py nba --date 2026-11-21
.venv/bin/python run.py nba --no-cache
```

Public hosting is covered in [DEPLOY.md](DEPLOY.md) (Render free web service).

## Default board: “Best value”

The generator still writes every standard line (PTS 10+/15+/20+/25+, and so
on) to `output/`. The app’s default view does **not** list all of them.

For each player, stat, and side, overs keep the **highest line that still hit
in at least 70% of the player’s last 10 games**; unders keep the **lowest**
line that still clears that rate (the Min L10 slider changes the cutoff).
Integer thresholds are shown as half-lines (25+ is Over/Under 24.5). Turn off
**Best value** to see every qualifying line, optionally hiding 100% hits on
the easiest threshold. **All / Over / Under** tabs, **100% Trends**, and
**Longest Streaks** match the Slipscore board filters we could verify.

## API

| Endpoint | What it returns |
| --- | --- |
| `GET /api/nba/board` | Paginated ranked props. Query: `date`, `stat`, `game`, `min_l10`, `hide_out`, `hide_gimme`, `view=value\|all`, `side=over\|under`, `perfect`, `sort=score\|streak`, `q`, `page`, `page_size` |
| `GET /api/nba/player/{id}` | Player bio, injury, last-20 logs, and all of their lines |
| `GET /api/nba/meta` | Games, date, generated-at |
| `GET /api/sports` | NBA and NHL live; NFL marked coming soon |
| `POST /api/refresh` | Rebuild the board (`X-Refresh-Token` if `REFRESH_TOKEN` is set) |
| `GET /health` | Liveness, plus `nba_dates` and `nhl_dates` |

## Data sources

Free public ESPN JSON only. No paid keys are required.

| Need | Endpoint | Status |
| --- | --- | --- |
| Tonight's slate | `site.api.espn.com/.../nba/scoreboard?dates=YYYYMMDD` | Works |
| Rosters | `site.api.espn.com/.../nba/teams/{id}/roster` | Works |
| Injuries | `site.api.espn.com/.../nba/injuries` | Works |
| Game logs | `site.web.api.espn.com/.../athletes/{id}/gamelog?season=2027` | Works |
| `cdn.nba.com` live scoreboard | — | 403 from this environment |
| `stats.nba.com` playergamelogs | — | Timed out from this environment |
| NHL slate / rosters / injuries | `site.api.espn.com/.../hockey/nhl/...` | Works |
| NHL game logs | `site.web.api.espn.com/.../hockey/nhl/athletes/{id}/gamelog?season=2027` | Works |
| NBA/NHL standings (team points or goals allowed) | `site.api.espn.com/apis/v2/sports/.../standings` | Works |

The 2026-27 NBA and NHL seasons are ESPN season year `2027`.

NHL standard over-thresholds:

- Goals: 0.5 / 1.5
- Assists: 0.5 / 1.5
- Points: 0.5 / 1.5 / 2.5
- Shots on goal: 1.5 / 2.5 / 3.5 / 4.5
- Goalie saves: 20.5 / 25.5 / 30.5

Skaters need 5 games and about 10 minutes average TOI; goalies need 5 starts.
ESPN skater game logs do not include hits or blocked shots, so those props are omitted.

If `ODDS_API_KEY` is set, The Odds API supplies today's US sportsbook
lines (region `us`) for the main markets: NBA points, rebounds, assists,
threes, and PRA; NHL shots, points, and goalie saves — in that priority
order. Cards show the book and American odds, e.g. `PTS Over 21.5 (-130)`.
A **Min odds** slider filters juicy live prices (standard-threshold rows
are left alone).

The free Starter plan is 500 credits/month. Event-odds cost is
(markets returned) × (regions). We use one region and cache the slate
to `cache/odds/` so restarts on the same disk do not refetch. A daily
budget (default 15 credits) and a reserve (default 30) stop fetching
when the month is tight. That is enough for about two NBA markets on a
6-game night; it is **not** enough for every NBA and NHL market every
day, so NBA is filled first. Props without a live line keep the
standard thresholds below and are marked **standard**.

The app runs fine with no key. Never commit the key or put it in a file.

Standard-threshold fallbacks:

- Points: 10+ / 15+ / 20+ / 25+
- Rebounds: 4+ / 6+ / 8+ / 10+
- Assists: 2+ / 4+ / 6+ / 8+
- Threes made: 1+ / 2+ / 3+ / 4+
- PRA: 15+ / 20+ / 25+ / 30+

## Trend score

Players need at least **5 played games** (minutes > 0) and a season average
of **12+ minutes**. Games with 0 minutes are dropped.

```
score = 100 × (
    0.30 × L5
  + 0.25 × L10
  + 0.15 × L20
  + 0.10 × season
  + 0.10 × venue
  + 0.10 × min(hit streak, 5) / 5
)
```

## Project layout

```
run.py                  # python3 run.py nba
app/main.py             # FastAPI server + PWA
app/board_store.py      # filters, best-value view, pagination
app/static/             # mobile SPA, manifest, service worker
propscore/ranking.py    # shared scoring
propscore/odds.py       # Odds API lines (budgeted) + standard fallback
propscore/sports/nba.py # NBA slate, rosters, logs, injuries
propscore/sports/nhl.py # NHL slate, rosters, logs, injuries
output/                 # generated boards
DEPLOY.md               # Render free-tier steps
```

## Adding a sport (NFL next)

1. Add `propscore/sports/<sport>.py` with the same surface as `NBA`.
2. Register it in `propscore/sports/__init__.py`.
3. Flip that sport to `available: True` in `app/main.py` (`SPORTS`).
4. Add standard lines in `odds.py` and run `python3 run.py nhl`.
