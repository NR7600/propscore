(() => {
  const state = {
    sport: "nba",
    date: null,
    games: [],
    rows: [],
    page: 1,
    total: 0,
    totalPages: 1,
    hasMore: false,
    viewLabel: "",
    generatedAt: "",
    stale: false,
    loading: false,
    filters: {
      stat: "",
      game: "",
      min_l10: 0.7,
      hide_out: true,
      hide_gimme: false,
      view: "value",
      q: "",
    },
    route: { name: "board" },
  };

  const $ = (id) => document.getElementById(id);
  const listEl = $("list");
  const moreBtn = $("more");
  const emptyEl = $("empty");
  const statusEl = $("status");
  const countEl = $("count");
  const gamesEl = $("games");
  const toastEl = $("toast");

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.hidden = false;
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(() => { toastEl.hidden = true; }, 2800);
  }

  function pct(v) {
    return `${Math.round((v || 0) * 100)}%`;
  }

  function badge(status) {
    if (!status) return "";
    const cls = status.toLowerCase().replace(/\s+/g, "-");
    return `<span class="badge ${cls}">${escapeHtml(status)}</span>`;
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function queryString(extra = {}) {
    const f = state.filters;
    const params = new URLSearchParams();
    if (state.date) params.set("date", state.date);
    if (f.stat) params.set("stat", f.stat);
    if (f.game) params.set("game", f.game);
    params.set("min_l10", String(f.min_l10));
    params.set("hide_out", f.hide_out ? "true" : "false");
    params.set("hide_gimme", f.hide_gimme ? "true" : "false");
    params.set("view", f.view);
    if (f.q) params.set("q", f.q);
    params.set("page", String(extra.page || 1));
    params.set("page_size", "25");
    return params.toString();
  }

  async function fetchBoard({ append } = { append: false }) {
    if (state.loading) return;
    state.loading = true;
    statusEl.textContent = append ? "Loading more…" : "Loading…";
    if (!append) {
      listEl.innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
    }
    try {
      const page = append ? state.page + 1 : 1;
      const res = await fetch(`/api/${state.sport}/board?${queryString({ page })}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      state.date = data.date;
      state.games = data.games || [];
      state.page = data.page;
      state.total = data.total;
      state.totalPages = data.total_pages;
      state.hasMore = data.has_more;
      state.viewLabel = data.view_label;
      state.generatedAt = data.generated_at;
      state.stale = data.stale;
      state.rows = append ? state.rows.concat(data.rows || []) : (data.rows || []);
      if (!append) renderStatPills(data.props || []);
      renderMeta();
      renderGames();
      renderList();
    } catch (err) {
      statusEl.textContent = "Couldn’t load the board. Check the server and try again.";
      if (!append) listEl.innerHTML = "";
      console.error(err);
    } finally {
      state.loading = false;
    }
  }

  function renderMeta() {
    const date = state.date || "";
    const stale = state.stale ? " · showing latest saved slate" : "";
    $("date-line").textContent = `${(state.sport || "nba").toUpperCase()} · ${date} · ${state.games.length} games · updated ${state.generatedAt || "—"}${stale}`;
    $("view-note").textContent = state.viewLabel || "";
    $("gimme-wrap").hidden = state.filters.view === "value";
  }

  function renderGames() {
    const selected = state.filters.game;
    const allOn = !selected ? " on" : "";
    const all = `<button class="game${allOn}" data-game="" role="listitem"><div class="matchup">All games</div><div class="when">Tonight</div></button>`;
    gamesEl.innerHTML =
      all +
      state.games
        .map((g) => {
          const on = selected === g.event_id ? " on" : "";
          return `<button class="game${on}" data-game="${escapeHtml(g.event_id)}" role="listitem">
            <div class="matchup">${escapeHtml(g.label)}</div>
            <div class="when">${escapeHtml(g.start_et)}${g.status && g.status !== "Scheduled" ? " · " + escapeHtml(g.status) : ""}</div>
          </button>`;
        })
        .join("");
  }

  function renderList() {
    countEl.textContent = state.total
      ? `Showing ${state.rows.length} of ${state.total} props`
      : "";
    emptyEl.hidden = state.rows.length > 0 || state.loading;
    moreBtn.hidden = !state.hasMore;
    statusEl.textContent = "";
    listEl.innerHTML = state.rows.map(cardHtml).join("");
  }

  function cardHtml(r) {
    const venue = r.venue === "H" ? "vs" : "@";
    return `<button class="card" data-player="${escapeHtml(r.player_id)}" data-prop="${escapeHtml(r.prop)}" data-line="${escapeHtml(r.line)}">
      <div class="card-top">
        <img src="${escapeHtml(r.headshot || "/icons/icon-192.png")}" alt="" width="42" height="42" loading="lazy">
        <div class="who">
          <div class="name">${escapeHtml(r.player)} ${badge(r.injury_status)}</div>
          <div class="sub">${escapeHtml(r.team)} ${venue} ${escapeHtml(r.opponent)} · ${escapeHtml(r.game_time_et)}</div>
        </div>
        <div class="score-box">
          <div class="num">${Number(r.score).toFixed(1)}</div>
          <div class="lbl">Score</div>
        </div>
      </div>
      <div class="card-mid">
        <span class="line-pill">${escapeHtml(r.line_label)}</span>
        <span class="sub">${r.streak ? `Streak ${r.streak}` : "Streak —"}</span>
      </div>
      <div class="rates">
        ${rateCell("L5", r.l5)}${rateCell("L10", r.l10)}${rateCell("L20", r.l20)}${rateCell("Seas", r.season)}
      </div>
    </button>`;
  }

  function rateCell(label, value) {
    const hot = (value || 0) >= 0.7 ? " hot" : "";
    return `<div class="rate${hot}"><b>${pct(value)}</b><span>${label}</span></div>`;
  }

  async function openPlayer(id, prop, line) {
    $("board-view").hidden = true;
    $("player-view").hidden = false;
    $("player-header").innerHTML = '<div class="skel"></div>';
    $("player-lines").innerHTML = "";
    $("player-stats").innerHTML = "";
    $("chart-wrap").innerHTML = "";
    window.scrollTo(0, 0);
    try {
      const res = await fetch(`/api/${state.sport}/player/${encodeURIComponent(id)}${state.date ? `?date=${state.date}` : ""}`);
      if (!res.ok) throw new Error("Player not found");
      const data = await res.json();
      renderPlayer(data, prop, line);
    } catch (err) {
      $("player-header").innerHTML = "<p class='empty'>Couldn’t load this player.</p>";
      console.error(err);
    }
  }

  function renderPlayer(data, prop, line) {
    const p = data.player || {};
    const game = data.game;
    const matchup = game ? `${game.label} · ${game.start_et}` : "";
    const inj = [p.injury_status, p.injury_detail, p.injury_comment].filter(Boolean);
    $("player-header").innerHTML = `
      <div class="player-hero">
        <img src="${escapeHtml(p.headshot || "/icons/icon-192.png")}" alt="" width="64" height="64">
        <div>
          <h1>${escapeHtml(p.name)} ${badge(p.injury_status)}</h1>
          <p>${escapeHtml(p.team_name || p.team_abbr || "")} · ${escapeHtml(p.position || "")}${p.jersey ? " · #" + escapeHtml(p.jersey) : ""}<br>${escapeHtml(matchup)}</p>
        </div>
      </div>
      ${inj.length ? `<p class="injury-note">${escapeHtml(inj.join(" — "))}</p>` : ""}
    `;

    let selected = data.rows.find((r) => r.prop === prop && Number(r.line) === Number(line));
    if (!selected) selected = data.rows[0];
    $("player-lines").innerHTML = data.rows
      .map((r) => {
        const on = selected && r.prop === selected.prop && Number(r.line) === Number(selected.line) ? " on" : "";
        return `<button class="pill${on}" data-prop="${escapeHtml(r.prop)}" data-line="${escapeHtml(r.line)}">${escapeHtml(r.line_label)}</button>`;
      })
      .join("");

    if (!selected) {
      $("player-stats").innerHTML = "";
      $("chart-wrap").innerHTML = "<p class='empty'>No ranked lines for this player.</p>";
      return;
    }
    $("player-stats").innerHTML =
      rateCell("L5", selected.l5) +
      rateCell("L10", selected.l10) +
      rateCell("L20", selected.l20) +
      rateCell("Season", selected.season) +
      `<div class="rate"><b>${selected.streak || "—"}</b><span>Streak</span></div>` +
      `<div class="rate hot"><b>${Number(selected.score).toFixed(1)}</b><span>Score</span></div>`;

    $("chart-wrap").innerHTML = chartHtml(data.logs || [], selected);
    $("player-lines").onclick = (ev) => {
      const btn = ev.target.closest("[data-prop]");
      if (!btn) return;
      const next = `#/${state.sport}/player/${p.id}?prop=${encodeURIComponent(btn.dataset.prop)}&line=${encodeURIComponent(btn.dataset.line)}`;
      if (location.hash !== next) location.hash = next;
      else renderPlayer(data, btn.dataset.prop, btn.dataset.line);
    };
  }

  function chartHtml(logs, row) {
    const prop = row.prop;
    const line = Number(row.line);
    const series = logs.slice(0, 15).slice().reverse();
    if (!series.length) return "<p class='empty'>No recent game logs.</p>";
    const maxVal = Math.max(line, ...series.map((g) => Number(g[prop] || 0)), 1);
    const bars = series
      .map((g) => {
        const val = Number(g[prop] || 0);
        const over = val >= line;
        const h = Math.max(4, Math.round((val / maxVal) * 100));
        const venue = g.venue || (g.is_home ? "H" : "A");
        const label = (g.date || "").slice(5);
        return `<div class="bar-col" title="${escapeHtml(g.date)} ${venue} ${escapeHtml(g.opponent_abbr)}: ${val}">
          <div class="bar-val">${val}</div>
          <div class="bar ${over ? "over" : "under"}" style="height:${h}%"></div>
          <div class="bar-lab">${escapeHtml(label)}</div>
        </div>`;
      })
      .join("");
    return `<div class="chart-card">
      <h2>${escapeHtml(row.line_label)} — last ${series.length} games</h2>
      <p class="hint">Green bars cleared the ${escapeHtml(row.line_label)} line. Dates are newest on the right.</p>
      <div class="chart">${bars}</div>
    </div>`;
  }

  function renderStatPills(props) {
    const current = state.filters.stat;
    const buttons = ['<button class="pill' + (current ? "" : " on") + '" data-stat="">All</button>'];
    (props || []).forEach((prop) => {
      const key = prop.key || prop;
      const label = prop.label || key;
      const on = current === key ? " on" : "";
      buttons.push(`<button class="pill${on}" data-stat="${escapeHtml(key)}">${escapeHtml(label)}</button>`);
    });
    $("stats").innerHTML = buttons.join("");
  }

  function setSportTab() {
    document.querySelectorAll(".sport[data-sport]").forEach((btn) => {
      const on = btn.dataset.sport === state.sport && !btn.classList.contains("soon");
      btn.classList.toggle("on", on);
    });
  }

  function switchSport(sport) {
    if (sport === state.sport && (location.hash === "" || location.hash === "#/" || location.hash === `#/${sport}`)) {
      return;
    }
    state.sport = sport;
    state.date = null;
    state.filters.stat = "";
    state.filters.game = "";
    state.filters.q = "";
    state.rows = [];
    $("q").value = "";
    setSportTab();
    if (location.hash !== `#/${sport}`) location.hash = `#/${sport}`;
    else fetchBoard({ append: false });
  }

  function showBoard() {
    $("player-view").hidden = true;
    $("board-view").hidden = false;
  }

  function parseRoute() {
    const hash = location.hash || "#/";
    const player = hash.match(/^#\/(?:(nba|nhl)\/)?player\/([^?]+)(?:\?(.*))?$/);
    if (player) {
      const params = new URLSearchParams(player[3] || "");
      return {
        name: "player",
        sport: player[1] || state.sport || "nba",
        id: decodeURIComponent(player[2]),
        prop: params.get("prop") || "",
        line: params.get("line") || "",
      };
    }
    const board = hash.match(/^#\/(nba|nhl)\/?$/);
    if (board) return { name: "board", sport: board[1] };
    return { name: "board", sport: "nba" };
  }

  function applyRoute() {
    const prevSport = state.sport;
    state.route = parseRoute();
    if (state.route.sport && state.route.sport !== state.sport) {
      state.sport = state.route.sport;
      state.date = null;
      state.filters.stat = "";
      state.filters.game = "";
      state.rows = [];
      setSportTab();
      if (state.route.name === "board") fetchBoard({ append: false });
    }
    if (state.route.name === "player") openPlayer(state.route.id, state.route.prop, state.route.line);
    else showBoard();
    if (state.route.name === "board" && prevSport === state.sport && !state.rows.length && !state.loading) {
      fetchBoard({ append: false });
    }
    setSportTab();
  }

  // Filters
  $("q").addEventListener("input", debounce(() => {
    state.filters.q = $("q").value.trim();
    fetchBoard({ append: false });
  }, 250));

  $("stats").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-stat]");
    if (!btn) return;
    state.filters.stat = btn.dataset.stat;
    $("stats").querySelectorAll(".pill").forEach((p) => p.classList.toggle("on", p === btn));
    fetchBoard({ append: false });
  });

  gamesEl.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-game]");
    if (!btn) return;
    state.filters.game = btn.dataset.game;
    fetchBoard({ append: false });
  });

  $("view-value").addEventListener("change", (ev) => {
    state.filters.view = ev.target.checked ? "value" : "all";
    fetchBoard({ append: false });
  });
  $("hide-out").addEventListener("change", (ev) => {
    state.filters.hide_out = ev.target.checked;
    fetchBoard({ append: false });
  });
  $("hide-gimme").addEventListener("change", (ev) => {
    state.filters.hide_gimme = ev.target.checked;
    fetchBoard({ append: false });
  });
  $("min-l10").addEventListener("input", (ev) => {
    $("min-label").textContent = `${ev.target.value}%`;
  });
  $("min-l10").addEventListener("change", (ev) => {
    state.filters.min_l10 = Number(ev.target.value) / 100;
    fetchBoard({ append: false });
  });

  listEl.addEventListener("click", (ev) => {
    const card = ev.target.closest("[data-player]");
    if (!card) return;
    location.hash = `#/${state.sport}/player/${card.dataset.player}?prop=${encodeURIComponent(card.dataset.prop)}&line=${encodeURIComponent(card.dataset.line)}`;
  });

  $("more").addEventListener("click", () => fetchBoard({ append: true }));
  $("back").addEventListener("click", () => { location.hash = `#/${state.sport}`; });

  document.querySelectorAll(".sport[data-sport]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.classList.contains("soon")) {
        toast(`${btn.dataset.sport.toUpperCase()} is coming soon.`);
        return;
      }
      switchSport(btn.dataset.sport);
    });
  });

  window.addEventListener("hashchange", applyRoute);

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  // Install hint (once).
  const installEl = $("install");
  if (!localStorage.getItem("ps-install-dismissed") && !window.matchMedia("(display-mode: standalone)").matches) {
    installEl.hidden = false;
  }
  $("install-dismiss").addEventListener("click", () => {
    installEl.hidden = true;
    localStorage.setItem("ps-install-dismissed", "1");
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  applyRoute();
  fetchBoard({ append: false });
})();
