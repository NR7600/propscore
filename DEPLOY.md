# Deploying Da Real Big Homie Props

The cheapest easy path is a **free Render web service**. It gives you an
`https://….onrender.com` URL with TLS, which a phone needs before
“Add to Home Screen” will install the PWA. No credit card is required
for the free compute plan.

Render’s free web services spin down after 15 minutes idle and take
about a minute to wake. Local files are lost on restart, so the app
regenerates today’s board on boot if it is missing, and also runs a
10:00 AM America/New_York refresh while the service is awake. Free
cron jobs are not included; if you later want a guaranteed daily
rebuild while the app is asleep, upgrade or hit `POST /api/refresh`.

## What you need to do

1. **Create a free Render account** at [https://render.com/register](https://render.com/register).
   Signing in with GitHub is the easiest path. You do not need a
   credit card for a free web service.
2. **Put this project in a GitHub repository** (a new public or private
   repo that contains this `propscore` folder at the root — `run.py`,
   `app/`, `propscore/`, `requirements.txt`, and `render.yaml` should
   all be visible in the repo root).
3. In the Render dashboard, click **New → Blueprint**. Connect the
   GitHub account if prompted, select the repo, and apply `render.yaml`.
   **Or** click **New → Web Service**, select the repo, and set:
   - Language: Python
   - Instance type: **Free**
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Click **Deploy**. When it finishes, open the `*.onrender.com` URL
   on your phone. The first visit after a sleep can take about a minute.
5. On iPhone: Safari → Share → **Add to Home Screen**. On Android:
   Chrome → menu → **Install app** / **Add to Home Screen**.

Optional: in the Render service’s Environment tab, set `ODDS_API_KEY`
to your Odds API key if you want live US sportsbook lines. Paste it only
in Render’s env UI — do not put it in the repo. The app works without
it: missing books fall back to a player-specific **estimated line**
(70% L10 median + 30% season average, rounded to a half-point), labeled
“est. line”. Render’s free disk is wiped when the service sleeps, so
boot-time board generation will **not** call the Odds API (that would
re-spend the daily credit budget on every wake). Use **Manual Deploy**
plus a later `POST /api/refresh` (or the 10:00 AM ET job if the service
is awake) to pull lines, subject to the daily cap. Set
`ODDS_FETCH_ON_BOOT=1` only if you accept spending up to the daily
budget on each cold start.

### Odds API budget (free plan → paid)

The official event-odds cost is `(unique markets returned) × (regions)`.
Player props are not available on the cheaper bulk `/odds` endpoint, and
adding regions (or `us_dfs`) multiplies the cost, so we request
`region=us` only. There is no supported trick that yields more real
player-prop lines per credit.

On the free Starter plan (500 credits/month) the defaults are:

- `ODDS_DAILY_BUDGET=15` (15 × 30 days = 450, plus a 30-credit reserve)
- Market order: NBA `player_points`, `player_first_basket`, then
  rebounds / assists / threes / PRA; NHL only if credits remain
- A typical 6-game NBA night spends 12 credits on points + first
  basket and stops. Other stats use estimated lines that day.

**When you upgrade the Odds API plan**, you only need to raise the
budget in Render’s Environment tab and redeploy or refresh:

```
ODDS_DAILY_BUDGET=80
```

That is enough to walk further down the market list (rebounds, assists,
threes, PRA, then NHL). You do not have to change code.

Optional extras, only if you want to customize the list:

```
ODDS_MARKETS=nba:player_points,player_first_basket,player_rebounds,player_assists,player_threes,player_points_rebounds_assists;nhl:player_shots_on_goal,player_points,player_total_saves
ODDS_RESERVE=30
ODDS_REGION=us
```

`ODDS_MARKETS=all` is the same as the built-in full list. Never put the
API key in the repo or in this file.

Optional: also set `REFRESH_TOKEN` to a secret string. Then a rebuild is:

```bash
curl -X POST https://YOUR-APP.onrender.com/api/refresh \
  -H "X-Refresh-Token: YOUR_SECRET"
```

## Other options

- **Railway**: also easy (New Project → Deploy from GitHub). Their
  free trial / hobby credits change over time and often ask for a
  card; Render’s free web service is the more predictable $0 start.
- **Fly.io**: `fly launch` with the included `Dockerfile` if you already have a Fly account. Not the cheapest first step.
- **Docker** anywhere:

  ```bash
  docker build -t propscore .
  docker run -p 8000:8000 propscore
  ```

Do not use a static host (Vercel, Netlify, GitHub Pages) as the only
deploy. The app needs the Python API so the phone never downloads the
full 3 MB board JSON.
