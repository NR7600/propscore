# Da Real Big Homie Props

A Slipscore-style player prop research app (the code and repo are still named `propscore`). It pulls tonight’s NBA or NHL slate,
recent game logs, and injury tags, then ranks standard over-lines by trend
strength. Use it in the browser or install it to a phone’s Home Screen.

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

For each player and stat, it keeps only the **highest line that still hit in
at least 70% of the player’s last 10 games** (the Min L10 slider changes that
cutoff). That is the most ambitious threshold the player is still clearing at
a strong rate — so a big scorer shows “PTS 25+” at 80%, not a perfect “PTS
10+” at 100%. Turn off **Best value** to see every qualifying line, optionally
hiding 100% hits on the lowest threshold.

## API

| Endpoint | What it returns |
| --- | --- |
| `GET /api/nba/board` | Paginated ranked props. Query: `date`, `stat`, `game`, `min_l10`, `hide_out`, `hide_gimme`, `view=value\|all`, `q`, `page`, `page_size` |
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

The 2026-27 NBA and NHL seasons are ESPN season year `2027`.

NHL standard over-thresholds:

- Goals: 0.5 / 1.5
- Assists: 0.5 / 1.5
- Points: 0.5 / 1.5 / 2.5
- Shots on goal: 1.5 / 2.5 / 3.5 / 4.5
- Goalie saves: 20.5 / 25.5 / 30.5

Skaters need 5 games and about 10 minutes average TOI; goalies need 5 starts.
ESPN skater game logs do not include hits or blocked shots, so those props are omitted.

Lines are **standard over-thresholds**, not sportsbook numbers:

- Points: 10+ / 15+ / 20+ / 25+
- Rebounds: 4+ / 6+ / 8+ / 10+
- Assists: 2+ / 4+ / 6+ / 8+
- Threes made: 1+ / 2+ / 3+ / 4+
- PRA: 15+ / 20+ / 25+ / 30+

To swap in live odds later, set `ODDS_API_KEY` and fill in the hook in
`propscore/odds.py`.

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
propscore/odds.py       # standard lines + ODDS_API_KEY stub
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
