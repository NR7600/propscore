/* Da Real Big Homie Props — mobile board + player detail. */
(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    sport: "nba",
    date: null,
    side: "over",
    stat: "",
    game: "",
    q: "",
    minL10: 0.7,
    minOdds: null,
    hideOut: true,
    hideGimme: false,
    viewValue: true,
    perfect: false,
    sortStreak: false,
    page: 1,
    totalPages: 1,
    total: 0,
    rows: [],
    games: [],
    props: [],
    meta: null,
    player: null,
    playerTab: "box",
    selectedKey: null,
    loading: false,
  };

  const SLIP_KEY = "bhp-slip-v1";

  function loadSlip() {
    try {
      return JSON.parse(localStorage.getItem(SLIP_KEY) || "[]");
    } catch {
      return [];
    }
  }
  function saveSlip(legs) {
    localStorage.setItem(SLIP_KEY, JSON.stringify(legs));
    renderSlip();
  }
  function slipId(row) {
    return [row.player_id, row.prop, row.side, row.line, row.event_id].join(":");
  }
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 1800);
  }

  function pct(rate) {
    return Math.round((rate || 0) * 100);
  }
  function frac(hits, games) {
    return `${hits || 0}/${games || 0}`;
  }
  function restLabel(row) {
    if (row.is_b2b) return "B2B";
    if (row.rest_days == null) return "";
    if (row.rest_days === 0) return "0 days rest";
    if (row.rest_days === 1) return "1 day rest";
    return `${row.rest_days} days rest`;
  }
  function venueWord(row) {
    return row.venue === "H" ? "vs" : "@";
  }
  function matchupText(row) {
    return row.game || `${row.team} ${venueWord(row)} ${row.opponent}`;
  }

  function parseHash() {
    const raw = (location.hash || "#/").replace(/^#/, "");
    const parts = raw.split("/").filter(Boolean);
    const sport = (parts[0] || "nba").toLowerCase();
    if (sport === "nfl") return { sport: "nfl", playerId: null };
    const playerId = parts[1] === "player" && parts[2] ? parts[2] : null;
    const params = new URLSearchParams(raw.split("?")[1] || location.hash.split("?")[1] || "");
    return {
      sport: sport === "nhl" ? "nhl" : "nba",
      playerId,
      prop: params.get("prop") || "",
      side: params.get("side") || "",
      line: params.get("line") || "",
    };
  }

  function setHash(sport, playerId, query) {
    let path = `#/${sport}`;
    if (playerId) path += `/player/${playerId}`;
    if (query) {
      const q = new URLSearchParams(query);
      const s = q.toString();
      if (s) path += `?${s}`;
    }
    if (location.hash !== path) history.pushState(null, "", path);
  }

  async function api(path) {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || body.message || detail;
      } catch {}
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  function boardQuery(page) {
    const p = new URLSearchParams();
    if (state.date) p.set("date", state.date);
    if (state.stat) p.set("stat", state.stat);
    if (state.game) p.set("game", state.game);
    if (state.q) p.set("q", state.q);
    if (state.side) p.set("side", state.side);
    p.set("min_l10", String(state.minL10));
    p.set("hide_out", state.hideOut ? "true" : "false");
    p.set("hide_gimme", state.hideGimme ? "true" : "false");
    p.set("view", state.viewValue ? "value" : "all");
    p.set("perfect", state.perfect ? "true" : "false");
    p.set("sort", state.sortStreak ? "streak" : "score");
    if (state.minOdds != null) p.set("min_odds", String(state.minOdds));
    p.set("page", String(page));
    p.set("page_size", "25");
    return `/api/${state.sport}/board?${p.toString()}`;
  }

  async function loadBoard({ append } = {}) {
    if (state.sport === "nfl") {
      $("list").innerHTML = `<p class="soon-msg">NFL is coming soon.</p>`;
      $("count").textContent = "";
      $("empty").hidden = true;
      $("more").hidden = true;
      return;
    }
    if (!append) {
      state.page = 1;
      state.rows = [];
      $("list").innerHTML = "";
    }
    state.loading = true;
    $("status").textContent = append ? "Loading more…" : "Loading trends…";
    $("empty").hidden = true;
    try {
      const data = await api(boardQuery(state.page));
      state.date = data.date;
      state.total = data.total;
      state.totalPages = data.total_pages;
      state.games = data.games || [];
      state.props = data.props || state.props;
      if (append) state.rows = state.rows.concat(data.rows || []);
      else state.rows = data.rows || [];
      $("date-line").textContent = data.stale
        ? `Showing ${data.date} • Ranked by trend strength`
        : `Updated ${data.date} • Ranked by trend strength`;
      $("view-note").textContent = data.view_label || "";
      renderGames();
      renderStatPills();
      renderList(append);
      $("count").textContent = `${data.total} trends`;
      $("empty").hidden = data.total > 0;
      $("more").hidden = !data.has_more;
      $("gimme-wrap").hidden = !(state.viewValue === false && state.minL10 < 0.99);
      $("status").textContent = "";
    } catch (err) {
      $("status").textContent = err.message || "Could not load the board.";
    } finally {
      state.loading = false;
    }
  }

  function renderGames() {
    const host = $("games");
    const chips = [`<button type="button" class="game-chip ${state.game ? "" : "on"}" data-game="">All games</button>`];
    for (const g of state.games) {
      const label = g.label || `${g.away_abbr} @ ${g.home_abbr}`;
      const on = state.game === String(g.event_id) ? "on" : "";
      chips.push(`<button type="button" class="game-chip ${on}" data-game="${g.event_id}">${label}</button>`);
    }
    host.innerHTML = chips.join("");
  }

  function renderStatPills() {
    const host = $("stats");
    const items = [{ key: "", label: "All Stats" }, ...(state.props || [])];
    host.innerHTML = items
      .map((p) => {
        const key = p.key || "";
        const on = state.stat === key ? "on" : "";
        return `<button type="button" class="pill ${on}" data-stat="${key}">${p.label || "All Stats"}</button>`;
      })
      .join("");
  }

  function renderList(append) {
    const host = $("list");
    const start = append ? host.children.length : 0;
    const html = state.rows
      .slice(start)
      .map((row, i) => cardHTML(row, start + i + 1))
      .join("");
    if (append) host.insertAdjacentHTML("beforeend", html);
    else host.innerHTML = html;
  }

  function cardHTML(row, rank) {
    const over = (row.side || "over") === "over";
    const windows = [
      [row.l5_hits, row.l5_games, row.l5],
      [row.l10_hits, row.l10_games, row.l10],
      [row.l20_hits, row.l20_games, row.l20],
    ]
      .filter((w) => w[1])
      .map(([h, n, r]) => {
        const cls = r >= 0.999 ? "" : r >= 0.7 ? "" : "muted";
        return `<div class="rate ${cls}">${frac(h, n)} games <b>${pct(r)}%</b></div>`;
      })
      .join("");
    const streaks = [];
    if (row.streak) streaks.push(`${row.streak}x game streak`);
    if (row.home_streak) streaks.push(`${row.home_streak}x home streak`);
    if (row.away_streak) streaks.push(`${row.away_streak}x away streak`);
    const chips = [];
    if (row.h2h_games) chips.push(`H2H ${frac(row.h2h_hits, row.h2h_games)} ${pct(row.h2h)}%`);
    const rest = restLabel(row);
    if (rest) chips.push(rest);
    if (row.matchup_tag) chips.push(`${row.matchup_tag} matchup`);
    if (row.injury_status) chips.push(row.injury_status);
    if (row.without && row.without.length) {
      const w = row.without[0];
      chips.push(`W/O ${w.player.split(" ").slice(-1)[0]} ${pct(w.rate)}%`);
    }
    const inSlip = loadSlip().some((l) => l.id === slipId(row));
    return `<article class="card" data-player="${row.player_id}" data-prop="${row.prop}" data-side="${row.side}" data-line="${row.line}">
      <div class="card-top">
        <div class="rank-wrap">
          <div class="rank"><small>RANK</small><b>${rank}</b></div>
          <div class="who">
            <div class="name">${escapeHtml(row.player)}</div>
            <div class="meta">${escapeHtml(row.game || matchupText(row))}${row.game_time_et ? " · " + escapeHtml(row.game_time_et) : ""}${row.position ? " · " + escapeHtml(row.position) : ""}</div>
          </div>
        </div>
        <span class="side ${over ? "" : "under"}">${over ? "Over" : "Under"}</span>
      </div>
      <div class="market">${escapeHtml(row.line_label)}${row.book_title && row.line_source === "live" ? ` · ${escapeHtml(row.book_title)}` : ""}${row.line_source === "standard" ? `<span class="std-badge">standard</span>` : ""}</div>
      <div class="rates-grid">${windows}</div>
      ${streaks.length ? `<div class="streaks">${streaks.map(escapeHtml).join(" · ")}</div>` : ""}
      ${chips.length ? `<div class="chips">${chips.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join("")}</div>` : ""}
      <div class="card-foot">
        <button type="button" class="view-log" data-open="${row.player_id}">VIEW GAME LOG</button>
        <button type="button" class="add-slip" data-slip="${encodeURIComponent(JSON.stringify({
          id: slipId(row),
          player: row.player,
          label: row.line_label,
          game: row.game,
          sport: state.sport,
        }))}">${inSlip ? "On slip" : "+ Slip"}</button>
      </div>
    </article>`;
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function loadPlayer(playerId, hint) {
    $("board-view").hidden = true;
    $("player-view").hidden = false;
    $("player-header").textContent = "Loading player…";
    $("player-lines").innerHTML = "";
    $("chart-wrap").innerHTML = "";
    $("player-stats").innerHTML = "";
    $("player-context").innerHTML = "";
    $("player-panel").innerHTML = "";
    try {
      const data = await api(`/api/${state.sport}/player/${playerId}${state.date ? `?date=${state.date}` : ""}`);
      state.player = data;
      const rows = data.rows || [];
      let selected = rows[0];
      if (hint) {
        selected =
          rows.find(
            (r) =>
              r.prop === hint.prop &&
              String(r.side) === String(hint.side || r.side) &&
              (hint.line === "" || String(r.line) === String(hint.line))
          ) ||
          rows.find((r) => r.prop === hint.prop) ||
          selected;
      }
      state.selectedKey = selected ? `${selected.prop}:${selected.side}:${selected.line}` : null;
      renderPlayer();
    } catch (err) {
      $("player-header").innerHTML = `<p class="status">${escapeHtml(err.message)}</p>`;
    }
  }

  function selectedRow() {
    const rows = (state.player && state.player.rows) || [];
    return rows.find((r) => `${r.prop}:${r.side}:${r.line}` === state.selectedKey) || rows[0];
  }

  function renderPlayer() {
    const data = state.player;
    const row = selectedRow();
    if (!data || !row) return;
    const p = data.player || {};
    const game = data.game || {};
    const next = game.label || row.game || "";
    const at = row.venue === "H" ? "vs" : "@";
    $("player-header").innerHTML = `
      <div class="player-head">
        <h1>${escapeHtml(p.name || row.player)}</h1>
        <p class="sub">${escapeHtml(row.prop_full || row.prop_label)} vs ${escapeHtml(String(row.display_line))} line</p>
        <p class="next">Next game: ${escapeHtml(at + " " + (row.opponent || next))}${row.game_time_et ? " · " + escapeHtml(row.game_time_et) : ""}</p>
      </div>`;
    const rows = data.rows || [];
    const propOrder = [];
    const seenProp = new Set();
    for (const r of rows) {
      if (!seenProp.has(r.prop)) { seenProp.add(r.prop); propOrder.push(r.prop); }
    }
    const currentProp = row.prop;
    const propPills = propOrder.map((prop) => {
      const sample = rows.find((r) => r.prop === prop) || {};
      const on = prop === currentProp ? "on" : "";
      return `<button type="button" class="pill ${on}" data-propkey="${prop}">${escapeHtml(sample.prop_label || prop)}</button>`;
    }).join("");
    const linePills = rows
      .filter((r) => r.prop === currentProp)
      .map((r) => {
        const key = `${r.prop}:${r.side}:${r.line}`;
        const on = key === state.selectedKey ? "on" : "";
        return `<button type="button" class="pill ${on}" data-linekey="${key}">${escapeHtml(r.side === "under" ? "Under" : "Over")} ${escapeHtml(String(r.display_line))}</button>`;
      })
      .join("");
    $("player-lines").innerHTML = `<div class="stat-pills wrap">${propPills}</div><div class="stat-pills wrap" style="padding-top:0">${linePills}</div>`;
    renderChart(data.logs || [], row);
    $("player-stats").innerHTML = [
      rateBox("L5", row.l5, row.l5_hits, row.l5_games, row.l5_avg),
      rateBox("L10", row.l10, row.l10_hits, row.l10_games, row.l10_avg),
      rateBox("L20", row.l20, row.l20_hits, row.l20_games, row.l20_avg),
      rateBox("Season", row.season, row.season_hits, row.season_games, row.season_avg),
      rateBox("H2H", row.h2h, row.h2h_hits, row.h2h_games, row.h2h_avg),
    ].join("");
    renderContext(row, p);
    renderPanel();
  }

  function rateBox(label, rate, hits, games, avg) {
    const extra = games ? `${frac(hits, games)}${avg != null ? " · avg " + avg : ""}` : "—";
    return `<div class="rate-box"><div class="k">${label}</div><div class="v">${games ? pct(rate) + "%" : "—"}</div><div class="s">${extra}</div></div>`;
  }

  function logValue(log, prop) {
    if (prop === "pts_reb") return (log.points || 0) + (log.rebounds || 0);
    if (prop === "pts_ast") return (log.points || 0) + (log.assists || 0);
    if (prop === "reb_ast") return (log.rebounds || 0) + (log.assists || 0);
    if (prop === "pra") return log.pra ?? ((log.points || 0) + (log.rebounds || 0) + (log.assists || 0));
    if (prop === "blocks") return log.blocked || 0;
    if (prop === "threes") return log.threes || 0;
    return log[prop] ?? 0;
  }

  function isHit(log, row) {
    const v = Number(logValue(log, row.prop));
    return row.side === "under" ? v < row.line : v >= row.line;
  }

  function renderChart(logs, row) {
    const recent = (logs || []).slice(0, 10);
    if (!recent.length) {
      $("chart-wrap").innerHTML = `<p class="status">No game log yet.</p>`;
      return;
    }
    const values = recent.map((g) => Number(logValue(g, row.prop)));
    const max = Math.max(row.display_line || row.line || 1, ...values, 1);
    const bars = recent
      .map((g, i) => {
        const v = values[i];
        const hit = isHit(g, row);
        const h = Math.max(12, Math.round((v / max) * 130));
        const date = (g.date || "").slice(5);
        const opp = `${g.venue === "H" || g.is_home ? "vs" : "@"} ${g.opponent_abbr || ""}`;
        return `<div class="bar-col">
          <div class="bar ${hit ? "hit" : "miss"}" style="height:${h}px">${v}</div>
          <div class="bar-lab">${escapeHtml(date)}<br>${escapeHtml(opp)}</div>
        </div>`;
      })
      .join("");
    const line = row.display_line ?? row.line;
    $("chart-wrap").innerHTML = `<div class="chart">
      <div class="bars">${bars}</div>
      <div class="legend">
        <span><i class="dot hit"></i>Over ${escapeHtml(String(line))}</span>
        <span><i class="dot miss"></i>Under ${escapeHtml(String(line))}</span>
      </div>
    </div>`;
  }

  function renderContext(row, player) {
    const bits = [];
    bits.push(`<div class="ctx"><div class="lbl">Home / Away</div>
      Home ${row.home_games ? frac(row.home_hits, row.home_games) + " " + pct(row.home_hit) + "%" : "—"}
      · Away ${row.away_games ? frac(row.away_hits, row.away_games) + " " + pct(row.away_hit) + "%" : "—"}
      · Tonight: ${row.venue === "H" ? "Home" : "Away"}</div>`);
    const unit = state.sport === "nhl" ? "TOI" : "Minutes";
    const trend = (row.minutes_trend && row.minutes_trend.length)
      ? row.minutes_trend
      : ((state.player.logs || []).slice(0, 10).map((g) => g.minutes || 0));
    const maxM = Math.max(...trend, 1);
    const spark = trend
      .map((m) => `<span class="min-bar" style="height:${Math.max(2, Math.round((m / maxM) * 36))}px" title="${m}"></span>`)
      .join("");
    bits.push(`<div class="ctx"><div class="lbl">${unit} trend</div>
      L5 ${row.min_l5 ?? "—"} · L10 ${row.min_l10 ?? "—"} · Season ${row.avg_minutes ?? "—"}
      <div class="min-trend">${spark}</div></div>`);
    const rest = restLabel(row) || "—";
    bits.push(`<div class="ctx"><div class="lbl">Rest</div>${escapeHtml(rest)}</div>`);
    if (row.opp_def_label) {
      bits.push(`<div class="ctx"><div class="lbl">Opponent defense (team ${escapeHtml(row.opp_def_stat || "points/goals allowed")})</div>
        ${escapeHtml(row.opp_def_label)}${row.matchup_tag ? " · " + escapeHtml(row.matchup_tag) + " for this " + row.side : ""}
        <div class="s" style="color:var(--muted);margin-top:4px">Team allowed rank from ESPN standings — not defense-vs-position.</div></div>`);
    }
    if (row.h2h_games) {
      bits.push(`<div class="ctx"><div class="lbl">H2H vs ${escapeHtml(row.opponent)}</div>
        ${frac(row.h2h_hits, row.h2h_games)} (${pct(row.h2h)}%), avg ${row.h2h_avg}</div>`);
    } else {
      bits.push(`<div class="ctx"><div class="lbl">H2H vs ${escapeHtml(row.opponent || "opp")}</div>No games vs this opponent in the current season log.</div>`);
    }
    if (row.without && row.without.length) {
      const lines = row.without
        .map((w) => `${escapeHtml(w.player)} (${escapeHtml(w.status || "Out")}): ${frac(w.hits, w.games)} ${pct(w.rate)}%, avg ${w.avg}`)
        .join("<br>");
      bits.push(`<div class="ctx"><div class="lbl">Without teammate (currently out)</div>${lines}</div>`);
    }
    $("player-context").innerHTML = bits.join("");
  }

  function renderPanel() {
    const tab = state.playerTab;
    document.querySelectorAll(".detail-tab").forEach((b) => {
      b.classList.toggle("on", b.dataset.tab === tab);
    });
    const data = state.player;
    const row = selectedRow();
    const game = data.game || {};
    if (tab === "box") return renderBox(data.logs || [], row);
    if (tab === "injuries") return renderInjuries(game);
    return renderNews(game);
  }

  function renderBox(logs, row) {
    const cols = boxCols(state.sport, (state.player.player || {}).role, row && row.prop);
    const body = (logs || [])
      .slice(0, 20)
      .map((g) => {
        const hit = row ? isHit(g, row) : false;
        const date = (g.date || "").slice(5);
        const cells = cols
          .map((c) => `<td>${escapeHtml(String(c.value(g)))}</td>`)
          .join("");
        return `<tr class="${hit ? "hit" : "miss"}"><td>${escapeHtml(date)}</td>${cells}</tr>`;
      })
      .join("");
    $("player-panel").innerHTML = `<div class="box-wrap"><table class="box">
      <thead><tr><th>DATE</th>${cols.map((c) => `<th>${c.label}</th>`).join("")}</tr></thead>
      <tbody>${body || `<tr><td colspan="${cols.length + 1}">No games</td></tr>`}</tbody>
    </table></div>`;
  }

  function boxCols(sport, role, prop) {
    if (sport === "nhl" && role === "goalie") {
      return [
        { label: "TOI", value: (g) => g.minutes },
        { label: "SV", value: (g) => g.saves },
        { label: "GS", value: (g) => (g.started ? "1" : "0") },
      ];
    }
    if (sport === "nhl") {
      return [
        { label: "TOI", value: (g) => g.minutes },
        { label: "G", value: (g) => g.goals },
        { label: "A", value: (g) => g.assists },
        { label: "PTS", value: (g) => g.points },
        { label: "SOG", value: (g) => g.shots },
      ];
    }
    return [
      { label: "MIN", value: (g) => g.minutes },
      { label: "PTS", value: (g) => g.points },
      { label: "REB", value: (g) => g.rebounds },
      { label: "AST", value: (g) => g.assists },
      { label: "FGM", value: (g) => g.fgm || 0 },
      { label: "3PM", value: (g) => g.threes },
      { label: "STL", value: (g) => g.steals || 0 },
      { label: "BLK", value: (g) => g.blocked || 0 },
    ];
  }

  function renderInjuries(game) {
    const inj = game.injuries || [];
    const teams = [...new Set(inj.map((i) => i.team).filter(Boolean))];
    const pills = teams
      .map((t) => `<span class="pill on" style="pointer-events:none">${escapeHtml(t)}</span>`)
      .join("");
    const rows = inj
      .map((i) => `<div class="inj-row"><div><b>${escapeHtml(i.player)}</b><div class="meta" style="color:var(--muted);font-size:12px">${escapeHtml([i.team, i.position, i.detail].filter(Boolean).join(" · "))}</div></div><span class="badge">${escapeHtml(i.status || "Out")}</span></div>`)
      .join("");
    $("player-panel").innerHTML = `<div class="inj-list">
      <div class="inj-teams">${pills || ""}</div>
      ${rows || `<p class="status">No injury listings for this matchup.</p>`}
      <div class="updated">From ESPN injury report</div>
    </div>`;
  }

  function renderNews(game) {
    const news = (game.news && game.news.length ? game.news : (game.injuries || []).filter((i) => i.comment)) || [];
    const cards = news
      .map((i) => `<article class="news-card">
        <div style="display:flex;justify-content:space-between;gap:8px">
          <div><b>${escapeHtml(i.player)}</b><div style="color:var(--muted);font-size:12px">${escapeHtml([i.team, i.position].filter(Boolean).join(" · "))}</div></div>
          <span class="badge">${escapeHtml(i.status || "Out")}</span>
        </div>
        <p>${escapeHtml(i.comment || i.detail || "")}</p>
      </article>`)
      .join("");
    $("player-panel").innerHTML = `${cards || `<p class="status">No game-level injury notes on this matchup.</p>`}
      <div class="updated">Injury comments from ESPN — not a live news wire.</div>`;
  }

  function renderSlip() {
    const legs = loadSlip();
    $("slip").hidden = false;
    $("slip-count").textContent = String(legs.length);
    const body = $("slip-body");
    if (!legs.length) {
      $("slip-legs").innerHTML = `<p class="slip-note">Add trends from a card. Saved on this device.</p>`;
      return;
    }
    $("slip-legs").innerHTML = legs
      .map(
        (l, i) => `<div class="slip-leg"><div><b>${escapeHtml(l.player)}</b><div>${escapeHtml(l.label)}</div><div class="slip-note">${escapeHtml(l.game || "")}</div></div>
        <button type="button" data-remove="${i}" aria-label="Remove">✕</button></div>`
      )
      .join("");
  }

  function openPlayerFromCard(card) {
    const id = card.dataset.player;
    const query = { prop: card.dataset.prop, side: card.dataset.side, line: card.dataset.line };
    setHash(state.sport, id, query);
    loadPlayer(id, query);
  }

  function bind() {
    document.querySelectorAll(".sport").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sport = btn.dataset.sport;
        if (sport === "nfl") {
          document.querySelectorAll(".sport").forEach((b) => b.classList.toggle("on", b.dataset.sport === "nfl"));
          state.sport = "nfl";
          setHash("nfl");
          $("board-view").hidden = false;
          $("player-view").hidden = true;
          $("date-line").textContent = "NFL is coming soon";
          loadBoard();
          return;
        }
        state.sport = sport;
        state.stat = "";
        state.game = "";
        state.date = null;
        document.querySelectorAll(".sport").forEach((b) => b.classList.toggle("on", b.dataset.sport === sport));
        setHash(sport);
        $("board-view").hidden = false;
        $("player-view").hidden = true;
        loadBoard();
      });
    });
    document.querySelectorAll(".trend-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.side = btn.dataset.side || "";
        document.querySelectorAll(".trend-tab").forEach((b) => b.classList.toggle("on", b === btn));
        loadBoard();
      });
    });
    $("games").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-game]");
      if (!btn) return;
      state.game = btn.dataset.game || "";
      loadBoard();
    });
    $("stats").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-stat]");
      if (!btn) return;
      state.stat = btn.dataset.stat || "";
      loadBoard();
    });
    $("q").addEventListener("input", debounce(() => {
      state.q = $("q").value.trim();
      loadBoard();
    }, 250));
    $("perfect").addEventListener("change", () => {
      state.perfect = $("perfect").checked;
      loadBoard();
    });
    $("sort-streak").addEventListener("change", () => {
      state.sortStreak = $("sort-streak").checked;
      loadBoard();
    });
    $("view-value").addEventListener("change", () => {
      state.viewValue = $("view-value").checked;
      loadBoard();
    });
    $("hide-out").addEventListener("change", () => {
      state.hideOut = $("hide-out").checked;
      loadBoard();
    });
    $("hide-gimme").addEventListener("change", () => {
      state.hideGimme = $("hide-gimme").checked;
      loadBoard();
    });
    $("min-l10").addEventListener("input", () => {
      $("min-label").textContent = `${$("min-l10").value}%`;
    });
    $("min-l10").addEventListener("change", () => {
      state.minL10 = Number($("min-l10").value) / 100;
      loadBoard();
    });
    function oddsLabel(v) {
      const n = Number(v);
      if (n <= -200) return "any";
      return n > 0 ? `+${n}` : String(n);
    }
    $("min-odds").addEventListener("input", () => {
      $("odds-label").textContent = oddsLabel($("min-odds").value);
    });
    $("min-odds").addEventListener("change", () => {
      const n = Number($("min-odds").value);
      state.minOdds = n <= -200 ? null : n;
      loadBoard();
    });
    $("more").addEventListener("click", () => {
      if (state.loading || state.page >= state.totalPages) return;
      state.page += 1;
      loadBoard({ append: true });
    });
    $("list").addEventListener("click", (e) => {
      const add = e.target.closest("[data-slip]");
      if (add) {
        e.preventDefault();
        e.stopPropagation();
        const leg = JSON.parse(decodeURIComponent(add.dataset.slip));
        const legs = loadSlip();
        if (legs.some((l) => l.id === leg.id)) toast("Already on your slip");
        else {
          legs.push(leg);
          saveSlip(legs);
          toast("Added to slip");
          add.textContent = "On slip";
        }
        return;
      }
      const open = e.target.closest("[data-open], .card");
      const card = e.target.closest(".card");
      if (card && (e.target.closest("[data-open]") || e.target.closest(".card-top, .market, .rates-grid, .streaks"))) {
        openPlayerFromCard(card);
      }
    });
    $("back").addEventListener("click", () => {
      setHash(state.sport);
      $("player-view").hidden = true;
      $("board-view").hidden = false;
    });
    $("player-lines").addEventListener("click", (e) => {
      const propBtn = e.target.closest("[data-propkey]");
      if (propBtn) {
        const prop = propBtn.dataset.propkey;
        const best = (state.player.rows || []).filter((r) => r.prop === prop)
          .sort((a, b) => (b.score || 0) - (a.score || 0))[0];
        if (!best) return;
        state.selectedKey = `${best.prop}:${best.side}:${best.line}`;
        setHash(state.sport, state.player.player.id, { prop: best.prop, side: best.side, line: best.line });
        renderPlayer();
        return;
      }
      const btn = e.target.closest("[data-linekey]");
      if (!btn) return;
      state.selectedKey = btn.dataset.linekey;
      const [prop, side, line] = state.selectedKey.split(":");
      setHash(state.sport, state.player.player.id, { prop, side, line });
      renderPlayer();
    });
    document.querySelectorAll(".detail-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.playerTab = btn.dataset.tab;
        renderPanel();
      });
    });
    $("slip-toggle").addEventListener("click", () => {
      $("slip-body").hidden = !$("slip-body").hidden;
    });
    $("slip-clear").addEventListener("click", () => saveSlip([]));
    $("slip-legs").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-remove]");
      if (!btn) return;
      const legs = loadSlip();
      legs.splice(Number(btn.dataset.remove), 1);
      saveSlip(legs);
    });
    $("install-dismiss").addEventListener("click", () => {
      $("install").hidden = true;
      localStorage.setItem("bhp-install-dismissed", "1");
    });
    window.addEventListener("hashchange", onRoute);
  }

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  function maybeInstall() {
    if (localStorage.getItem("bhp-install-dismissed")) return;
    const stand = window.matchMedia("(display-mode: standalone)").matches
      || window.navigator.standalone;
    if (!stand) $("install").hidden = false;
  }

  async function onRoute() {
    const route = parseHash();
    state.sport = route.sport === "nfl" ? "nfl" : route.sport;
    document.querySelectorAll(".sport").forEach((b) => b.classList.toggle("on", b.dataset.sport === state.sport));
    if (route.playerId && state.sport !== "nfl") {
      await loadPlayer(route.playerId, route);
    } else {
      $("player-view").hidden = true;
      $("board-view").hidden = false;
      if (!state.rows.length || route.sport !== state.sport) await loadBoard();
    }
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  bind();
  renderSlip();
  maybeInstall();
  onRoute();
})();
