/* Da Real Big Homie Props — mobile board + player detail. */
(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    sport: "nba",
    date: null,
    side: "",
    tab: "all",
    top: [],
    moreRows: [],
    showMoreLines: false,
    stat: "",
    game: "",
    q: "",
    minL10: 0,
    minOdds: null,
    hideOut: false,
    hideGimme: false,
    viewValue: false,
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
  const boardCache = new Map();
  let inflight;
  let lastGamesKey = "";
  let lastStatsKey = "";
  let slateRetry = 0;

  function todayEt() {
    return new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
  }
  function isLiveSlate(data) {
    const date = data && data.date;
    if (!date || data.stale) return false;
    return date >= todayEt();
  }
  function currentDateParam() {
    return state.date && state.date >= todayEt() ? state.date : "";
  }
  function showLoadingSlate() {
    state.games = [];
    state.top = [];
    state.rows = [];
    state.date = null;
    lastGamesKey = "";
    $("games").innerHTML = "";
    $("list").innerHTML = "";
    $("date-line").textContent = "Loading today's slate…";
    $("count").textContent = "";
    $("view-note").textContent = "";
    $("empty").hidden = false;
    $("empty").textContent = "Loading today's slate…";
    showSkeletons();
  }
  function scheduleSlateRetry() {
    clearTimeout(slateRetry);
    slateRetry = setTimeout(() => {
      if (!$("board-view").hidden) loadBoard();
    }, 5000);
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


  function firstMeta(sport) {
    if (sport === "nhl") return { key: "first_goal", chip: "1G (First Goal)", all: "All Stats (No Goals)", title: "First Goal" };
    if (sport === "nfl") return { key: "first_td", chip: "1TD (First TD)", all: "All Stats (No TDs)", title: "First TD" };
    return { key: "first_basket", chip: "1FG (First Basket)", all: "All Stats (No 1FG)", title: "First FGM" };
  }
  function isFirstProp(prop) {
    return prop === "first_basket" || prop === "first_goal" || prop === "first_td";
  }
  function formatSlateDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-").map(Number);
    if (!y || !m || !d) return iso;
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  }

  function parseHash() {
    const raw = (location.hash || "#/").replace(/^#/, "");
    const parts = raw.split("/").filter(Boolean);
    const sportRaw = (parts[0] || "nba").toLowerCase();
    const sport = ["nba", "nhl", "nfl"].includes(sportRaw) ? sportRaw : "nba";
    const playerId = parts[1] === "player" && parts[2] ? parts[2] : null;
    const params = new URLSearchParams(raw.split("?")[1] || location.hash.split("?")[1] || "");
    return {
      sport,
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

  async function api(path, { signal } = {}) {
    const res = await fetch(path, { headers: { Accept: "application/json" }, signal });
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
    if (state.stat) p.set("stat", state.stat);
    if (state.game) p.set("game", state.game);
    if (state.q) p.set("q", state.q);
    if (state.side) p.set("side", state.side);
    if (state.tab) p.set("tab", state.tab);
    p.set("min_l10", "0");
    p.set("hide_out", state.hideOut ? "true" : "false");
    p.set("hide_gimme", state.hideGimme ? "true" : "false");
    p.set("view", state.viewValue ? "value" : "all");
    p.set("perfect", state.perfect ? "true" : "false");
    p.set("sort", state.sortStreak ? "streak" : "score");
    p.set("page", String(page));
    p.set("page_size", "10");
    return `/api/${state.sport}/board?${p.toString()}`;
  }

  function showSkeletons() {
    const card = `<article class="card skeleton" aria-hidden="true"><div class="sk-line w60"></div><div class="sk-line w80"></div><div class="sk-line w30"></div></article>`;
    $("top-list").innerHTML = card + card + card;
    $("list").innerHTML = "";
    $("top-wrap").hidden = false;
    $("empty").hidden = true;
  }

  function applyBoard(data, { append } = {}) {
    state.date = data.date;
    state.total = data.total;
    state.totalPages = data.total_pages;
    if (data.games && data.games.length) state.games = data.games;
    state.props = data.props || state.props;
    if (!append) {
      state.top = data.top || [];
      state.rows = data.rows || [];
    } else {
      state.rows = state.rows.concat(data.rows || []);
    }
    const meta = firstMeta(state.sport);
    const first = !!data.first_mode || isFirstProp(state.stat);
    $("board-view").classList.toggle("first-mode", first);
    const slate = formatSlateDate(data.date);
    const upcoming = data.date && data.date > todayEt();
    const label = slate ? (upcoming ? `${slate} slate` : slate) : "Today";
    $("date-line").textContent = `${label} • Updated Daily • Ranked By Trend Strength`;
    $("view-note").textContent = data.view_label || "";
    const firstLabel = meta.title;
    $("top-title").textContent = first ? `Top 10 ${firstLabel}` : "Top 10 Trends";
    state.slateMessage = data.slate_message || "";
    renderGames();
    renderStatPills();
    if (!append) renderTop();
    renderList(append);
    const topCount = (state.top || []).length;
    $("count").textContent = topCount ? `Top ${topCount}` : "No strong trends for these filters";
    const emptyEl = $("empty");
    const hasRows = topCount > 0;
    emptyEl.hidden = hasRows;
    emptyEl.textContent = hasRows ? "No props match these filters." : (state.slateMessage || "No strong trends match these filters.");
    $("top-wrap").hidden = topCount === 0;
    const moreBlock = $("more-block");
    if (moreBlock) moreBlock.hidden = true;
    $("gimme-wrap").hidden = first || state.viewValue !== false;
    $("status").textContent = "";
  }

  async function loadBoard({ append } = {}) {
    if (inflight && !append) inflight.abort();
    const controller = new AbortController();
    inflight = controller;
    if (!append) state.page = 1;
    const path = boardQuery(state.page);
    const cached = !append ? boardCache.get(path) : null;
    const liveCached = cached && isLiveSlate(cached) ? cached : null;
    if (liveCached) {
      applyBoard(liveCached, { append: false });
    } else if (!append) {
      showLoadingSlate();
    }
    if (!append) $("board-view").classList.add("is-loading");
    else $("status").textContent = "Loading more…";
    state.loading = true;
    try {
      const data = await api(path, { signal: controller.signal });
      if (!isLiveSlate(data)) {
        throw Object.assign(new Error("Today's slate is being generated."), { status: 503 });
      }
      clearTimeout(slateRetry);
      if (!append) {
        boardCache.set(path, data);
        if (boardCache.size > 40) boardCache.delete(boardCache.keys().next().value);
      }
      applyBoard(data, { append });
    } catch (err) {
      if (err.name === "AbortError") return;
      if (!append) {
        showLoadingSlate();
        const building = err.status === 503 || err.status === 404;
        $("empty").textContent = building
          ? "Loading today's slate…"
          : (err.message || "Could not load today's slate.");
        if (building) scheduleSlateRetry();
        $("status").textContent = "";
      } else {
        $("status").textContent = err.message || "Could not load the board.";
      }
    } finally {
      if (inflight === controller) {
        state.loading = false;
        $("board-view").classList.remove("is-loading");
      }
    }
  }

  function renderGames() {
    const host = $("games");
    const key = (state.games || []).map((g) => g.event_id).join(",") + "|" + (state.game || "");
    if (key === lastGamesKey && host.children.length) return;
    lastGamesKey = key;
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
    const fm = firstMeta(state.sport);
    const key = state.sport + "|" + (state.stat || "") + "|" + (state.props || []).map((p) => p.key).join(",");
    if (key === lastStatsKey && host.children.length) return;
    lastStatsKey = key;
    const firstKey = fm.key;
    const firstLabel = fm.chip;
    const allLabel = fm.all;
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

  function isOutStatus(status) {
    if (!status) return false;
    const text = String(status).trim().toLowerCase();
    if (["out", "ofs", "ir", "ir-lt", "ltir", "injured reserve"].includes(text)) return true;
    return text.includes("injured reserve");
  }

  function displayWindows(row) {
    if (Array.isArray(row.windows) && row.windows.length) return row.windows.slice(0, 6);
    const all = [4, 5, 6, 8, 9, 10, 12, 15, 20];
    const items = [];
    for (const n of all) {
      const hits = row[`l${n}_hits`];
      const games = row[`l${n}_games`];
      if (!games) continue;
      const rate = row[`l${n}`] != null ? row[`l${n}`] : hits / games;
      items.push({ n, hits, games, rate });
    }
    items.sort((a, b) => (b.rate - a.rate) || (b.games - a.games) || (b.n - a.n));
    const seen = new Set();
    const unique = [];
    for (const item of items) {
      if (item.games < item.n) {
        const key = `${item.hits}/${item.games}`;
        if (seen.has(key)) continue;
        seen.add(key);
      }
      unique.push(item);
      if (unique.length >= 6) break;
    }
    return unique;
  }

  function streakLines(row) {
    const game = row.streak || 0;
    const home = row.home_streak || 0;
    const away = row.away_streak || 0;
    const venueN = row.venue === "H" ? home : away;
    const venueLabel = row.venue === "H" ? "home" : "away";
    if (state.sortStreak) {
      const cands = [];
      if (game) cands.push({ n: game, label: `${game}x game streak` });
      if (home) cands.push({ n: home, label: `${home}x home streak` });
      if (away) cands.push({ n: away, label: `${away}x away streak` });
      if (!cands.length) return [];
      cands.sort((a, b) => b.n - a.n);
      return [cands[0].label];
    }
    const lines = [];
    if (game) lines.push(`${game}x game streak`);
    if (venueN) lines.push(`${venueN}x ${venueLabel} streak`);
    return lines;
  }

  function cardHTML(row, rank, featured) {
    const first = isFirstProp(row.prop) || row.first_kind;
    const over = (row.side || "over") === "over";
    const wins = displayWindows(row);
    const cell = (w) => {
      if (!w || !w.games) return `<div class="rate muted">—</div>`;
      const r = w.rate != null ? w.rate : (w.hits / w.games);
      const cls = r >= 0.999 ? "" : r >= 0.7 ? "" : "muted";
      return `<div class="rate ${cls}">${frac(w.hits, w.games)} games <b>${pct(r)}%</b></div>`;
    };
    const mid = Math.ceil(wins.length / 2) || 0;
    const leftCol = wins.slice(0, mid).map(cell).join("");
    const rightCol = wins.slice(mid).map(cell).join("");
    const windows = `<div class="rates-col">${leftCol}</div><div class="rates-col">${rightCol}</div>`;
    const streaks = streakLines(row);
    const streakHtml = streaks.length
      ? `<div class="streaks">${streaks.map(escapeHtml).join(" · ")}</div>`
      : `<div class="streaks none">No streaks</div>`;
    const chips = [];
    if (row.h2h_games) chips.push(`H2H ${frac(row.h2h_hits, row.h2h_games)} ${pct(row.h2h)}%`);
    const rest = restLabel(row);
    if (rest) chips.push(rest);
    if (row.matchup_tag) chips.push(`${row.matchup_tag} matchup`);
    if (row.without && row.without.length) {
      const w = row.without[0];
      chips.push(`W/O ${w.player.split(" ").slice(-1)[0]} ${pct(w.rate)}%`);
    }
    if (row.prior_games) chips.push(`Includes ${row.prior_games} game${row.prior_games === 1 ? "" : "s"} from a prior season`);
    if (first) {
      if (row.season_games) chips.unshift(`${frac(row.season_hits, row.season_games)} games (${pct(row.season)}%)`);
      if (row.started_last) chips.push("Starter last game");
      else if (row.started_games) chips.push(`Started ${frac(row.started_games, row.games_played || row.season_games)}`);
      if (row.tip_games) {
        const tipName = row.prop === "first_goal" ? "FO win" : "Tip win";
        chips.push(`Team ${tipName} ${frac(row.tip_wins, row.tip_games)} ${pct(row.tip_win_rate)}%`);
      }
    }
    const sideCls = first ? "first" : (over ? "" : "under");
    const sideTxt = first ? (row.prop_label || "1st") : (over ? "Over" : "Under");
    const outBadge = isOutStatus(row.injury_status) ? `<span class="badge-out">OUT</span>` : "";
    return `<article class="card ${featured ? "top-card" : ""}" data-player="${row.player_id}" data-prop="${row.prop}" data-side="${row.side}" data-line="${row.line}" data-event="${row.event_id || ""}">
      <div class="card-top">
        <div class="rank-wrap">
          <div class="rank"><small>RANK</small><b>${rank}</b></div>
          <div class="who">
            <div class="name">${escapeHtml(row.player)}${outBadge}</div>
            <div class="meta">${escapeHtml(row.team ? row.team + " · " : "")}${escapeHtml(row.game || matchupText(row))}${row.game_time_et ? " · " + escapeHtml(row.game_time_et) : ""}${row.position ? " · " + escapeHtml(row.position) : ""}</div>
          </div>
        </div>
        <span class="side ${sideCls}">${escapeHtml(sideTxt)}</span>
      </div>
      <div class="market">${escapeHtml(row.line_label)}${row.book_title && row.line_source === "live" ? ` · ${escapeHtml(row.book_title)}` : ""}${row.line_source === "est" ? `<span class="est-badge">est. line</span>` : ""}</div>
      <div class="rates-grid">${windows}</div>
      ${streakHtml}
      ${chips.length ? `<div class="chips">${chips.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join("")}</div>` : ""}
      <div class="card-foot">
        <button type="button" class="view-log" data-open-log>VIEW GAME LOG</button>
        <button type="button" class="gen-report" data-open-report>Generate Report</button>
        <button type="button" class="full-hist" data-open-log>full history &gt;</button>
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
    $("chart-wrap").innerHTML = `<p class="status">Loading chart…</p>`;
    $("player-stats").innerHTML = "";
    $("player-context").innerHTML = "";
    $("player-panel").innerHTML = "";
    try {
      const q = currentDateParam() ? `?date=${currentDateParam()}` : "";
      const data = await api(`/api/${state.sport}/player/${playerId}${q}`);
      state.player = data;
      state.player.logs = state.player.logs || [];
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
      const eventId = (data.game && data.game.event_id) || (selected && selected.event_id);
      Promise.all([
        api(`/api/${state.sport}/player/${playerId}/logs${q}`).catch(() => null),
        eventId ? api(`/api/${state.sport}/game/${eventId}${q}`).catch(() => null) : null,
      ]).then(([logsData, gameData]) => {
        const currentId = String((state.player && state.player.player && state.player.player.id) || "");
        if (currentId && currentId !== String(playerId)) return;
        if (logsData && logsData.logs) state.player.logs = logsData.logs;
        if (gameData) state.player.game = Object.assign({}, state.player.game || {}, gameData);
        renderPlayer();
      });
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
    const first = isFirstProp(row.prop) || row.first_kind;
    const sub = first
      ? escapeHtml(row.prop_full || row.prop_label)
      : `${escapeHtml(row.prop_full || row.prop_label)} vs ${escapeHtml(String(row.display_line))} ${row.line_source === "est" ? "est. line" : "line"}`;
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
        const firstLine = isFirstProp(r.prop);
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
      rateBox("L4", row.l4, row.l4_hits, row.l4_games),
      rateBox("L5", row.l5, row.l5_hits, row.l5_games, row.l5_avg),
      rateBox("L6", row.l6, row.l6_hits, row.l6_games),
      rateBox("L8", row.l8, row.l8_hits, row.l8_games),
      rateBox("L9", row.l9, row.l9_hits, row.l9_games),
      rateBox("L10", row.l10, row.l10_hits, row.l10_games, row.l10_avg),
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
    if (isFirstProp(prop)) return log.first_score == null ? null : Number(log.first_score);
    if (prop === "pts_reb") return (log.points || 0) + (log.rebounds || 0);
    if (prop === "pts_ast") return (log.points || 0) + (log.assists || 0);
    if (prop === "reb_ast") return (log.rebounds || 0) + (log.assists || 0);
    if (prop === "pra") return log.pra ?? ((log.points || 0) + (log.rebounds || 0) + (log.assists || 0));
    if (prop === "blocks") return log.blocked || 0;
    if (prop === "threes") return log.threes || 0;
    if (prop === "rush_rec_yds") return (log.rush_yds || 0) + (log.rec_yds || 0);
    if (prop === "anytime_td") return log.anytime_td ?? ((log.rush_td || 0) + (log.rec_td || 0));
    if (prop === "stl_blk") return (log.steals || 0) + (log.blocked || 0);
    if (prop === "turnovers") return log.turnovers || 0;
    if (prop === "long_rush") return log.long_rush || 0;
    if (prop === "long_rec") return log.long_rec || 0;
    return log[prop] ?? 0;
  }

  function isHit(log, row) {
    if (isFirstProp(row.prop)) return Number(log.first_score) === 1;
    const v = Number(logValue(log, row.prop));
    return row.side === "under" ? v < row.line : v >= row.line;
  }

  function chartHTML(logs, row) {
    const first = isFirstProp(row.prop);
    let recent = (logs || []).filter((g) => g.minutes || g.first_score != null).slice(0, 10);
    if (first) recent = (logs || []).filter((g) => g.first_score != null).slice(0, 10);
    if (!recent.length) return `<p class="status">No game log yet.</p>`;
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
    return `<div class="chart">
      <div class="bars">${bars}</div>
      <div class="legend">${legend}</div>
    </div>`;
  }

  function renderChart(logs, row) {
    $("chart-wrap").innerHTML = chartHTML(logs, row);
  }

  function renderContext(row, player) {
    const bits = [];
    bits.push(`<div class="ctx"><div class="lbl">Home / Away</div>
      Home ${row.home_games ? frac(row.home_hits, row.home_games) + " " + pct(row.home_hit) + "%" : "—"}
      · Away ${row.away_games ? frac(row.away_hits, row.away_games) + " " + pct(row.away_hit) + "%" : "—"}
      · Tonight: ${row.venue === "H" ? "Home" : "Away"}</div>`);
    if (state.sport !== "nfl") {
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
    } else if (row.prior_games) {
      bits.push(`<div class="ctx"><div class="lbl">Sample</div>Season windows use this season; L9/L10 include ${row.prior_games} game${row.prior_games === 1 ? "" : "s"} from last season.</div>`);
    }
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
    if (tab === "matchup") return renderMatchup(game, "player-panel");
    if (tab === "injuries") return renderInjuries(game, "player-panel");
    return renderNews(game, "player-panel");
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
    if (sport === "nfl") {
      return [
        { label: "OPP", value: (g) => `${g.venue === "H" || g.is_home ? "vs" : "@"} ${g.opponent_abbr || ""}` },
        { label: "CMP", value: (g) => g.completions || 0 },
        { label: "ATT", value: (g) => g.pass_att || 0 },
        { label: "PYD", value: (g) => g.pass_yds || 0 },
        { label: "PTD", value: (g) => g.pass_td || 0 },
        { label: "INT", value: (g) => g.ints || 0 },
        { label: "CAR", value: (g) => g.rush_att || 0 },
        { label: "RYD", value: (g) => g.rush_yds || 0 },
        { label: "REC", value: (g) => g.receptions || 0 },
        { label: "REY", value: (g) => g.rec_yds || 0 },
        { label: "LR", value: (g) => g.long_rush || 0 },
        { label: "LREC", value: (g) => g.long_rec || 0 },
        { label: "TD", value: (g) => g.anytime_td ?? ((g.rush_td || 0) + (g.rec_td || 0)) },
      ];
    }
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
      { label: "OPP", value: (g) => `${g.venue === "H" || g.is_home ? "vs" : "@"} ${g.opponent_abbr || ""}` },
      { label: "MIN", value: (g) => g.minutes },
      { label: "PTS", value: (g) => g.points },
      { label: "REB", value: (g) => g.rebounds },
      { label: "AST", value: (g) => g.assists },
      { label: "FGM", value: (g) => g.fgm || 0 },
      { label: "3PM", value: (g) => g.threes },
      { label: "STL", value: (g) => g.steals || 0 },
      { label: "BLK", value: (g) => g.blocked || 0 },
      { label: "TO", value: (g) => g.turnovers || 0 },
      { label: "1FG", value: (g) => g.first_score == null ? "—" : (Number(g.first_score) === 1 ? "Yes" : "No") },
    ];
  }

  function updatedAgo(iso) {
    if (!iso) return "";
    let t = Date.parse(iso);
    if (!Number.isFinite(t)) {
      const m = String(iso).match(/^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s*(AM|PM)/i);
      if (m) {
        let h = parseInt(m[2], 10);
        const min = parseInt(m[3], 10);
        if (/pm/i.test(m[4]) && h !== 12) h += 12;
        if (/am/i.test(m[4]) && h === 12) h = 0;
        t = new Date(`${m[1]}T${String(h).padStart(2, "0")}:${String(min).padStart(2, "0")}:00`).getTime();
      }
    }
    if (!Number.isFinite(t)) return "";
    const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
    if (mins < 1) return "Updated just now";
    if (mins === 1) return "Updated 1 min ago";
    if (mins < 60) return `Updated ${mins} min ago`;
    const hrs = Math.round(mins / 60);
    return hrs === 1 ? "Updated 1 hr ago" : `Updated ${hrs} hr ago`;
  }

  function rankTone(rank, teams, kind) {
    if (!rank || !teams) return "neutral";
    const third = Math.max(Math.floor(teams / 3), 1);
    if (kind === "defense") {
      if (rank <= third) return "tough";
      if (rank > teams - third) return "smash";
      return "neutral";
    }
    if (rank <= third) return "smash";
    if (rank > teams - third) return "tough";
    return "neutral";
  }

  function renderMatchup(game, targetId) {
    const host = $(targetId || "player-panel");
    const m = game.matchup || {};
    const teams = m.teams || 30;
    const legend = m.legend || `Ranked out of ${teams} teams · Red = tough, Green = smash`;
    const block = (side, label) => {
      if (!side || !side.abbr) return "";
      const def = side.defense || {};
      const off = side.offense || {};
      const defTone = rankTone(def.rank, def.teams || teams, "defense");
      const offTone = rankTone(off.rank, off.teams || teams, "offense");
      const defTxt = def.label || (def.rank ? `${side.abbr} defense ${def.rank} of ${def.teams || teams}` : "—");
      const offTxt = off.label || (off.rank ? `${side.abbr} offense ${off.rank} of ${off.teams || teams}` : "—");
      return `<div class="matchup-team">
        <h4>${escapeHtml(label)} · ${escapeHtml(side.abbr)}</h4>
        <div class="match-row"><span>Defense</span><span class="${defTone}">${escapeHtml(defTxt)}</span></div>
        <div class="match-row"><span>Offense</span><span class="${offTone}">${escapeHtml(offTxt)}</span></div>
        <div class="match-row"><span>Shooting</span><span class="neutral">Not in ESPN standings</span></div>
      </div>`;
    };
    host.innerHTML = `<p class="matchup-legend">${escapeHtml(legend)}</p>
      ${block(m.away, "Away")}${block(m.home, "Home")}` || `<p class="status">No matchup ranks for this game.</p>`;
  }

  function renderInjuries(game, targetId) {
    const host = $(targetId || "player-panel");
    const inj = game.injuries || [];
    const selected = game._injTeam || "";
    const teams = [...new Set(inj.map((i) => i.team).filter(Boolean))];
    const pills = teams
      .map((t) => `<button type="button" class="pill ${!selected || selected === t ? "on" : ""}" data-inj-team="${escapeHtml(t)}">${escapeHtml(t)}</button>`)
      .join("");
    const shown = selected ? inj.filter((i) => i.team === selected) : inj;
    const rows = shown
      .map((i) => `<div class="inj-row"><div><b>${escapeHtml(i.player)}</b><div class="meta" style="color:var(--muted);font-size:12px">${escapeHtml([i.team, i.position, i.detail].filter(Boolean).join(" · "))}</div></div><span class="badge">${escapeHtml(i.status || "Out")}</span></div>`)
      .join("");
    const stamp = updatedAgo(game.injuries_updated_at) || "Updated from the ESPN injury report";
    host.innerHTML = `<div class="inj-list">
      <div class="inj-teams">${pills || ""}</div>
      ${rows || `<p class="status">No injury listings for this matchup.</p>`}
      <div class="inj-stamp">${escapeHtml(stamp)}</div>
    </div>`;
  }

  function renderNews(game, targetId) {
    const host = $(targetId || "player-panel");
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
    host.innerHTML = `${cards || `<p class="status">No game-level injury notes on this matchup.</p>`}
      <div class="updated">Injury comments from ESPN — not a live news wire.</div>`;
  }



  function closeModal() {
    const root = $("modal-root");
    if (root) root.hidden = true;
    $("modal-body").innerHTML = "";
    state.modal = null;
  }

  function openModal(html) {
    $("modal-body").innerHTML = html;
    $("modal-root").hidden = false;
  }

  function cardFromEl(el) {
    const card = el.closest(".card");
    if (!card) return null;
    const pid = card.dataset.player;
    const prop = card.dataset.prop;
    const side = card.dataset.side;
    const line = card.dataset.line;
    const rows = (state.top || []).concat(state.rows || []);
    return rows.find((r) => String(r.player_id) === String(pid) && String(r.prop) === String(prop) && String(r.side) === String(side) && String(r.line) === String(line)) || null;
  }

  async function openReport(row) {
    if (!row) return;
    openModal(`<p class="report-title">PROP REPORT</p><p class="status">Loading report…</p>`);
    const q = new URLSearchParams({ prop: row.prop, side: row.side || "over", line: String(row.line) });
    const dateParam = currentDateParam();
    if (dateParam) q.set("date", dateParam);
    try {
      const data = await api(`/api/${state.sport}/report/${row.player_id}?${q.toString()}`);
      state.modal = { type: "report", data, row };
      const gameData = data.game_ranks || {};
      const league = data.league_ranks || {};
      const rankBox = (title, info) => {
        if (!info) return "";
        return `<div class="rank-box"><div class="k">${escapeHtml(title)}</div><div class="v">${escapeHtml(info.label)}</div></div>`;
      };
      const trend = (data.trend_lines || []).map((line) => `<p class="trend-line">${escapeHtml(line)}</p>`).join("");
      const oddsGame = gameData.odds ? rankBox("Odds Rank", gameData.odds) : "";
      const oddsLeague = league.odds ? rankBox("Odds Rank", league.odds) : "";
      $("modal-body").innerHTML = `
        <p class="report-title">PROP REPORT</p>
        <h2 class="report-player">${escapeHtml(data.player)}</h2>
        <p class="report-meta">${escapeHtml(data.team || "")}</p>
        <p class="report-market">${escapeHtml(data.header || data.line_label || "")}</p>
        <div class="report-section">
          <h3>Trend Data (${data.trend_count || 0} found)</h3>
          ${trend || "<p class='status'>No trend windows for this prop.</p>"}
        </div>
        <div class="report-section">
          <h3>Rank Comparison by Game</h3>
          <div class="rank-grid">
            ${rankBox("Data Rank", gameData.data)}
            ${oddsGame}
          </div>
        </div>
        <div class="report-section">
          <h3>League Wide</h3>
          <div class="rank-grid">
            ${rankBox("Data Rank", league.data)}
            ${oddsLeague}
          </div>
          <p class="blurb">${escapeHtml((data.blurbs && data.blurbs.data) || "")}</p>
          ${oddsLeague || oddsGame ? `<p class="blurb">${escapeHtml((data.blurbs && data.blurbs.odds) || "")}</p>` : ""}
        </div>`;
    } catch (err) {
      $("modal-body").innerHTML = `<p class="report-title">PROP REPORT</p><p class="status">${escapeHtml(err.message || "Could not load the report.")}</p>`;
    }
  }

  function boxHTML(logs, row, sport, role) {
    const cols = boxCols(sport, role, row && row.prop);
    const body = (logs || [])
      .slice(0, 20)
      .map((g) => {
        const hit = row ? isHit(g, row) : false;
        const date = (g.date || "").slice(5);
        const cells = cols.map((c) => `<td>${escapeHtml(String(c.value(g)))}</td>`).join("");
        return `<tr class="${hit ? "hit" : "miss"}"><td>${escapeHtml(date)}</td>${cells}</tr>`;
      })
      .join("");
    return `<div class="box-wrap"><table class="box">
      <thead><tr><th>DATE</th>${cols.map((c) => `<th>${c.label}</th>`).join("")}</tr></thead>
      <tbody>${body || `<tr><td colspan="${cols.length + 1}">No games</td></tr>`}</tbody>
    </table></div>`;
  }

  async function openGameLog(row) {
    if (!row) return;
    state.modal = { type: "log", row, tab: "box", logs: [], game: {}, player: { name: row.player } };
    openModal(`<div class="log-head"><h2>${escapeHtml(row.player)}</h2><p>${escapeHtml(row.line_label || "")}</p></div><p class="status">Loading game log…</p>`);
    const q = currentDateParam() ? `?date=${currentDateParam()}` : "";
    try {
      const [playerData, logsData, gameData] = await Promise.all([
        api(`/api/${state.sport}/player/${row.player_id}${q}`).catch(() => null),
        api(`/api/${state.sport}/player/${row.player_id}/logs${q}`).catch(() => null),
        row.event_id ? api(`/api/${state.sport}/game/${row.event_id}${q}`).catch(() => null) : null,
      ]);
      const logs = (logsData && logsData.logs) || [];
      const game = Object.assign({}, (playerData && playerData.game) || {}, gameData || {});
      const player = (playerData && playerData.player) || { name: row.player, role: "" };
      state.modal = { type: "log", row, tab: "box", logs, game, player };
      renderLogModal();
    } catch (err) {
      $("modal-body").innerHTML = `<p class="status">${escapeHtml(err.message || "Could not load the game log.")}</p>`;
    }
  }

  function renderLogModal() {
    const modal = state.modal;
    if (!modal || modal.type !== "log") return;
    const { row, tab, logs, game, player } = modal;
    const tabs = ["box", "matchup", "injuries", "news"]
      .map((id) => {
        const label = { box: "Box Score", matchup: "Matchup", injuries: "Injuries", news: "News" }[id];
        return `<button type="button" class="detail-tab ${tab === id ? "on" : ""}" data-log-tab="${id}">${label}</button>`;
      })
      .join("");
    $("modal-body").innerHTML = `
      <div class="log-head">
        <h2>${escapeHtml((player && player.name) || row.player)}</h2>
        <p>${escapeHtml(row.line_label || "")} · ${escapeHtml(row.game || matchupText(row))}</p>
      </div>
      ${chartHTML(logs, row)}
      <div class="detail-tabs" role="tablist">${tabs}</div>
      <div id="log-panel"></div>`;
    if (tab === "box") $("log-panel").innerHTML = boxHTML(logs, row, state.sport, player && player.role);
    else if (tab === "matchup") renderMatchup(game, "log-panel");
    else if (tab === "injuries") renderInjuries(game, "log-panel");
    else renderNews(game, "log-panel");
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
        state.sport = sport;
        state.stat = "";
        state.game = "";
        state.date = null;
        boardCache.clear();
        lastGamesKey = "";
        lastStatsKey = "";
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
    const moreBtn = $("more");
    if (moreBtn) moreBtn.hidden = true;
    function onBoardCardClick(e) {
      const card = e.target.closest(".card");
      if (!card) return;
      if (e.target.closest("[data-open-report]")) {
        e.preventDefault();
        openReport(cardFromEl(card));
        return;
      }
      if (e.target.closest("[data-open-log]")) {
        e.preventDefault();
        openGameLog(cardFromEl(card));
        return;
      }
      if (e.target.closest(".card-top, .market, .rates-grid, .streaks, .who")) {
        openPlayerFromCard(card);
      }
    }
    $("modal-root").addEventListener("click", (e) => {
      if (e.target.closest("[data-close-modal]")) {
        closeModal();
        return;
      }
      const inj = e.target.closest("[data-inj-team]");
      if (inj && state.modal && state.modal.type === "log") {
        const team = inj.dataset.injTeam;
        state.modal.game._injTeam = state.modal.game._injTeam === team ? "" : team;
        renderLogModal();
        return;
      }
      const tab = e.target.closest("[data-log-tab]");
      if (tab && state.modal && state.modal.type === "log") {
        state.modal.tab = tab.dataset.logTab;
        renderLogModal();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && $("modal-root") && !$("modal-root").hidden) closeModal();
    });
    $("list").addEventListener("click", onBoardCardClick);
    $("top-list").addEventListener("click", onBoardCardClick);
    $("back").addEventListener("click", () => {
      setHash(state.sport);
      $("player-view").hidden = true;
      $("board-view").hidden = false;
    });
    $("player-panel").addEventListener("click", (e) => {
      const inj = e.target.closest("[data-inj-team]");
      if (!inj || !state.player) return;
      state.player.game = state.player.game || {};
      const team = inj.dataset.injTeam;
      state.player.game._injTeam = state.player.game._injTeam === team ? "" : team;
      renderInjuries(state.player.game, "player-panel");
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
    state.sport = route.sport;
    document.querySelectorAll(".sport").forEach((b) => b.classList.toggle("on", b.dataset.sport === state.sport));
    if (route.playerId) {
      await loadPlayer(route.playerId, route);
    } else {
      $("player-view").hidden = true;
      $("board-view").hidden = false;
      const stale = !state.date || state.date < todayEt();
      if (stale || !state.rows.length || route.sport !== state.sport) await loadBoard();
    }
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
    navigator.serviceWorker.addEventListener("message", (event) => {
      if (!event.data || event.data.type !== "api-update") return;
      const url = event.data.url || "";
      if (!url.includes(`/api/${state.sport}/board`)) return;
      // Drop memory cache so the next render picks up the fresh board.
      boardCache.clear();
    });
  }

  bind();
  maybeInstall();
  onRoute();
})();
