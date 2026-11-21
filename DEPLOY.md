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

Optional: in the Render service’s Environment tab, set `REFRESH_TOKEN`
to a secret string. Then a rebuild is:

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
