/* Da Real Big Homie Props — mobile board + player detail. */
(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    sport: "nba",
    date: null,
    side: "over",
    tab: "over",
    moreOpen: false,
    top: [],
    moreRows: [],
    showMoreLines: false,
    stat: "",
    game: "",
    q: "",
    minL10: 0,
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
    p.set("min_l10", "0");
    p.set("hide_out", state.hideOut ? "true" : "false");
    p.set("hide_gimme", state.hideGimme ? "true" : "false");
    p.set("view", state.viewValue ? "value" : "all");
    p.set("perfect", state.perfect ? "true" : "false");
    p.set("sort", state.sortStreak ? "streak" : "score");
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
      $("top-wrap").hidden = true;
      $("show-more-trends").hidden = true;
      $("more-block").hidden = true;
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
      if (!append) {
        state.top = data.top || [];
        state.moreOpen = false;
      }
      if (append) state.rows = state.rows.concat(data.rows || []);
      else state.rows = data.rows || [];
      const first = !!data.first_mode || state.stat === "first_basket" || state.stat === "first_goal";
      const firstLabel = state.sport === "nhl" ? "First Goal" : "First FGM";
      $("board-view").classList.toggle("first-mode", first);
      $("date-line").textContent = "Updated Daily • Ranked By Trend Strength";
      $("view-note").textContent = data.view_label || "";
      const topTitle = first ? `Top 10 ${firstLabel}` : "Top 10 Trends";
      $("top-title").textContent = topTitle;
      $("more-title").textContent = first ? `More ${firstLabel} trends` : "More trends";
      state.slateMessage = data.slate_message || "";
      renderGames();
      renderStatPills();
      renderTop();
      renderList(append);
      const moreCount = data.total || 0;
      const topCount = (state.top || []).length;
      $("count").textContent = topCount
        ? `Top ${topCount}${moreCount ? ` · ${moreCount} more` : ""}`
        : `${moreCount} trends`;
      const emptyEl = $("empty");
      const hasRows = topCount > 0 || moreCount > 0;
      emptyEl.hidden = hasRows;
      emptyEl.textContent = hasRows ? "No props match these filters." : (state.slateMessage || "No props match these filters.");
      $("top-wrap").hidden = topCount === 0;
      $("show-more-trends").hidden = moreCount === 0 || state.moreOpen;
      $("show-more-trends").textContent = `Show more trends (${moreCount})`;
      if (!append) $("more-block").hidden = !state.moreOpen;
      $("more").hidden = !state.moreOpen || !data.has_more;
      $("gimme-wrap").hidden = first || state.viewValue !== false;
      $("status").textContent = "";
    } catch (err) {
      $("status").textContent = err.message || "Could not load the board.";
    } finally {
      state.loading = false;
    }
  }

  function renderGames() {
    const host = $("games");
    const chips = [`<span class="smart-label">Games:</span>`,`<button type="button" class="game-chip ${state.game ? "" : "on"}" data-game="">All games</button>`];
    for (const g of state.games) {
      const label = g.label || `${g.away_abbr} @ ${g.home_abbr}`;
      const on = state.game === String(g.event_id) ? "on" : "";
      chips.push(`<button type="button" class="game-chip ${on}" data-game="${g.event_id}">${label}</button>`);
    }
    host.innerHTML = chips.join("");
  }

  function renderStatPills() {
    const host = $("stats");
    const firstKey = state.sport === "nhl" ? "first_goal" : "first_basket";
    const firstLabel = state.sport === "nhl" ? "1G (First Goal)" : "1FG (First Basket)";
    const allLabel = state.sport === "nhl" ? "All Stats (No 1G)" : "All Stats (No 1FG)";
    const items = [
      { key: "", label: allLabel },
      { key: firstKey, label: firstLabel },
      ...(state.props || []),
    ];
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
      .map((row, i) => cardHTML(row, start + i + 11, false))
      .join("");
    if (append) host.insertAdjacentHTML("beforeend", html);
    else host.innerHTML = html;
  }

  function renderTop() {
    const host = $("top-list");
    host.innerHTML = (state.top || [])
      .map((row, i) => cardHTML(row, row.rank || i + 1, true))
      .join("");
  }

  function cardHTML(row, rank, featured) {
    const first = row.prop === "first_basket" || row.prop === "first_goal" || row.first_kind;
    const over = (row.side || "over") === "over";
    const cell = (h, n, r) => {
      if (!n) return `<div class="rate muted">—</div>`;
      const cls = r >= 0.999 ? "" : r >= 0.7 ? "" : "muted";
      return `<div class="rate ${cls}">${frac(h, n)} games <b>${pct(r)}%</b></div>`;
    };
    const leftCol = [
      cell(row.l4_hits, row.l4_games, row.l4),
      cell(row.l8_hits, row.l8_games, row.l8),
      cell(row.l15_hits, row.l15_games, row.l15),
    ].join("");
    const rightCol = [
      cell(row.l5_hits, row.l5_games, row.l5),
      cell(row.l10_hits, row.l10_games, row.l10),
      cell(row.l20_hits, row.l20_games, row.l20),
    ].join("");
    const windows = `<div class="rates-col">${leftCol}</div><div class="rates-col">${rightCol}</div>`;
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
    if (first) {
      if (row.season_games) chips.unshift(`${frac(row.season_hits, row.season_games)} games (${pct(row.season)}%)`);
      if (row.started_last) chips.push("Starter last game");
      else if (row.started_games) chips.push(`Started ${frac(row.started_games, row.games_played || row.season_games)}`);
      if (row.tip_games) {
        const tipName = row.prop === "first_goal" ? "FO win" : "Tip win";
        chips.push(`Team ${tipName} ${frac(row.tip_wins, row.tip_games)} ${pct(row.tip_win_rate)}%`);
      }
    }
    const inSlip = loadSlip().some((l) => l.id === slipId(row));
    const sideCls = first ? "first" : (over ? "" : "under");
    const sideTxt = first ? (row.prop_label || "1st") : (over ? "Over" : "Under");
    return `<article class="card ${featured ? "top-card" : ""}" data-player="${row.player_id}" data-prop="${row.prop}" data-side="${row.side}" data-line="${row.line}">
      <div class="card-top">
        <div class="rank-wrap">
          <div class="rank"><small>RANK</small><b>${rank}</b></div>
          <div class="who">
            <div class="name">${escapeHtml(row.player)}</div>
            <div class="meta">${escapeHtml(row.team ? row.team + " · " : "")}${escapeHtml(row.game || matchupText(row))}${row.game_time_et ? " · " + escapeHtml(row.game_time_et) : ""}${row.position ? " · " + escapeHtml(row.position) : ""}</div>
          </div>
        </div>
        <span class="side ${sideCls}">${escapeHtml(sideTxt)}</span>
      </div>
      <div class="market">${escapeHtml(row.line_label)}${row.book_title && row.line_source === "live" ? ` · ${escapeHtml(row.book_title)}` : ""}${row.line_source === "standard" ? `<span class="std-badge">standard</span>` : ""}</div>
      <div class="rates-grid">${windows}</div>
      ${streaks.length ? `<div class="streaks">${streaks.map(escapeHtml).join(" · ")}</div>` : ""}
      ${chips.length ? `<div class="chips">${chips.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join("")}</div>` : ""}
      <div class="card-foot">
        <button type="button" class="view-log" data-open="${row.player_id}">VIEW GAME LOG</button>
        <button type="button" class="full-hist" data-open="${row.player_id}">full history &gt;</button>
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
      state.moreRows = data.more_rows || [];
      const rows = playerAllRows(data);
      let selected = (data.rows || [])[0] || rows[0];
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
      const featuredIds = new Set((data.rows || []).map((r) => `${r.prop}:${r.side}:${r.line}`));
      state.showMoreLines = !!(selected && !featuredIds.has(`${selected.prop}:${selected.side}:${selected.line}`));
      state.selectedKey = selected ? `${selected.prop}:${selected.side}:${selected.line}` : null;
      renderPlayer();
    } catch (err) {
      $("player-header").innerHTML = `<p class="status">${escapeHtml(err.message)}</p>`;
    }
  }

  function playerAllRows(data) {
    const src = data || state.player || {};
    return [...(src.rows || []), ...(src.more_rows || state.moreRows || [])];
  }

  function selectedRow() {
    const rows = playerAllRows();
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
    const first = row.prop === "first_basket" || row.prop === "first_goal" || row.first_kind;
    const sub = first
      ? escapeHtml(row.prop_full || row.prop_label)
      : `${escapeHtml(row.prop_full || row.prop_label)} vs ${escapeHtml(String(row.display_line))} line`;
    $("player-header").innerHTML = `
      <div class="player-head">
        <h1>${escapeHtml(p.name || row.player)}</h1>
        <p class="sub">${sub}</p>
        <p class="next">Next game: ${escapeHtml(at + " " + (row.opponent || next))}${row.game_time_et ? " · " + escapeHtml(row.game_time_et) : ""}</p>
      </div>`;
    const featured = data.rows || [];
    const extra = data.more_rows || state.moreRows || [];
    const visible = state.showMoreLines ? featured.concat(extra) : featured;
    const propOrder = [];
    const seenProp = new Set();
    for (const r of visible) {
      if (!seenProp.has(r.prop)) { seenProp.add(r.prop); propOrder.push(r.prop); }
    }
    const currentProp = row.prop;
    const propPills = propOrder.map((prop) => {
      const sample = visible.find((r) => r.prop === prop) || {};
      const on = prop === currentProp ? "on" : "";
      return `<button type="button" class="pill ${on}" data-propkey="${prop}">${escapeHtml(sample.prop_label || prop)}</button>`;
    }).join("");
    const linePills = visible
      .filter((r) => r.prop === currentProp)
      .map((r) => {
        const key = `${r.prop}:${r.side}:${r.line}`;
        const on = key === state.selectedKey ? "on" : "";
        const firstLine = r.prop === "first_basket" || r.prop === "first_goal";
        const label = firstLine
          ? (r.prop_label || "1st")
          : `${r.side === "under" ? "Under" : "Over"} ${r.display_line}`;
        return `<button type="button" class="pill ${on}" data-linekey="${key}">${escapeHtml(label)}</button>`;
      })
      .join("");
    const moreBtn = extra.length
      ? `<button type="button" class="more-lines-btn" id="toggle-more-lines">${state.showMoreLines ? "Hide extra lines" : `More lines (${extra.length})`}</button>`
      : "";
    $("player-lines").innerHTML = `<div class="stat-pills wrap">${propPills}</div><div class="stat-pills wrap" style="padding-top:0">${linePills}</div>${moreBtn}`;
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

  function isFirstProp(prop) {
    return prop === "first_basket" || prop === "first_goal";
  }

  function logValue(log, prop) {
    if (isFirstProp(prop)) return log.first_score == null ? null : Number(log.first_score);
    if (prop === "pts_reb") return (log.points || 0) + (log.rebounds || 0);
    if (prop === "pts_ast") return (log.points || 0) + (log.assists || 0);
    if (prop === "reb_ast") return (log.rebounds || 0) + (log.assists || 0);
    if (prop === "pra") return log.pra ?? ((log.points || 0) + (log.rebounds || 0) + (log.assists || 0));
    if (prop === "blocks") return log.blocked || 0;
    if (prop === "threes") return log.threes || 0;
    return log[prop] ?? 0;
  }

  function isHit(log, row) {
    if (isFirstProp(row.prop)) return Number(log.first_score) === 1;
    const v = Number(logValue(log, row.prop));
    return row.side === "under" ? v < row.line : v >= row.line;
  }

  function renderChart(logs, row) {
    const first = isFirstProp(row.prop);
    let recent = (logs || []).slice(0, 10);
    if (first) recent = (logs || []).filter((g) => g.first_score != null).slice(0, 10);
    if (!recent.length) {
      $("chart-wrap").innerHTML = `<p class="status">No game log yet.</p>`;
      return;
    }
    const values = recent.map((g) => Number(logValue(g, row.prop) || 0));
    const max = first ? 1 : Math.max(row.display_line || row.line || 1, ...values, 1);
    const bars = recent
      .map((g, i) => {
        const v = values[i];
        const hit = isHit(g, row);
        const h = first ? (hit ? 130 : 18) : Math.max(12, Math.round((v / max) * 130));
        const date = (g.date || "").slice(5);
        const opp = `${g.venue === "H" || g.is_home ? "vs" : "@"} ${g.opponent_abbr || ""}`;
        const label = first ? (hit ? "Yes" : "No") : String(v);
        return `<div class="bar-col">
          <div class="bar ${hit ? "hit" : "miss"}" style="height:${h}px">${escapeHtml(label)}</div>
          <div class="bar-lab">${escapeHtml(date)}<br>${escapeHtml(opp)}</div>
        </div>`;
      })
      .join("");
    const line = row.display_line ?? row.line;
    const legend = first
      ? `<span><i class="dot hit"></i>${escapeHtml(row.prop_label || "1st")}</span>
         <span><i class="dot miss"></i>No</span>`
      : `<span><i class="dot hit"></i>Over ${escapeHtml(String(line))}</span>
         <span><i class="dot miss"></i>Under ${escapeHtml(String(line))}</span>`;
    $("chart-wrap").innerHTML = `<div class="chart">
      <div class="bars">${bars}</div>
      <div class="legend">${legend}</div>
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
        const tab = btn.dataset.tab || (btn.dataset.side ? (btn.dataset.side || "all") : "all");
        state.tab = tab;
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
    $("more").addEventListener("click", () => {
      if (state.loading || state.page >= state.totalPages) return;
      state.page += 1;
      loadBoard({ append: true });
    });
    $("show-more-trends").addEventListener("click", () => {
      state.moreOpen = true;
      $("more-block").hidden = false;
      $("show-more-trends").hidden = true;
      $("more").hidden = state.page >= state.totalPages;
    });
    function onBoardCardClick(e) {
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
    }
    $("list").addEventListener("click", onBoardCardClick);
    $("top-list").addEventListener("click", onBoardCardClick);
    $("back").addEventListener("click", () => {
      setHash(state.sport);
      $("player-view").hidden = true;
      $("board-view").hidden = false;
    });
    $("player-lines").addEventListener("click", (e) => {
      if (e.target.closest("#toggle-more-lines")) {
        state.showMoreLines = !state.showMoreLines;
        renderPlayer();
        return;
      }
      const propBtn = e.target.closest("[data-propkey]");
      if (propBtn) {
        const prop = propBtn.dataset.propkey;
        const best = playerAllRows().filter((r) => r.prop === prop)
          .sort((a, b) => ((b.line_source === "live") - (a.line_source === "live")) || (b.score || 0) - (a.score || 0))[0];
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
