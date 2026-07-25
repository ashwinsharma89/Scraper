"use strict";
// MarketLens SPA — vanilla JS, no build step. Talks to the FastAPI /api surface.

const State = { projectId: null, project: null, mode: "solo", user: null, view: "overview",
                channels: null, health: null, dash: null };

// Which channels are ready with no extra setup vs. what each one needs.
const CHREQ = {
  news:            { ready: true,  needs: "" },
  gdelt:           { ready: true,  needs: "" },
  reddit:          { ready: true,  needs: "" },
  trends:          { ready: false, needs: "pytrends (bundled in Docker)" },
  forums:          { ready: false, needs: "your forum URLs (Source plan)" },
  quora:           { ready: false, needs: "your Quora URLs (Source plan)" },
  ecommerce:       { ready: false, needs: "your product URLs + Playwright (Docker)" },
  youtube:         { ready: false, needs: "YOUTUBE_API_KEY" },
  google_business: { ready: false, needs: "GOOGLE_PLACES_API_KEY" },
  image_analysis:  { ready: false, needs: "run E-commerce first + ANTHROPIC_API_KEY" },
};

// Short instruction shown at the top of each tab.
const HELP = {
  overview: "Your study at a glance. Follow the four numbered steps above — they must be done in order.",
  sources: "<b>Step 1.</b> Tell MarketLens <i>where</i> to look: paste RSS / e-commerce / forum URLs, edit the per-language keyword slots, then <b>Save config</b>. This does <b>not</b> collect anything — that happens in Collect.",
  collect: "<b>Step 2.</b> Run scrapers to gather data. Channels tagged <span class='ready-badge'>ready</span> work immediately; others need a key or URLs. Jobs run one at a time. Start with News, Reddit, and GDELT.",
  runlog: "The full audit trail of every run — including honest failures (blocked sites, rate limits). Nothing is ever fabricated.",
  items: "Every collected item, one row each, with its analysis tags. Search and filter here — e.g. set <b>Brand focus = target brand</b> to hide off-topic noise, or <b>Sentiment = negative</b> to read complaints.",
  analysis: "<b>Step 3.</b> Tag every collected item with sentiment, an English summary, purchase drivers, and themes. <b>Requires ANTHROPIC_API_KEY.</b> Safe to click again — already-tagged items are skipped.",
  intel: "Human-entered market facts (size, share, GDP…). Every entry needs a full citation. Optional, but it enriches the report's Market Overview.",
  manual: "Ad-library research for platforms that block automation: open the pre-built deep links, then record what you see. Tier-3 platforms are documented as gaps.",
  schedules: "Automate recurring collection (e.g. a weekly news pull). Each run is a normal, audited run.",
  export: "<b>Step 4.</b> Build the client Excel workbook and the report draft. Do <b>Collect + Analyze first</b> — without analysis the workbook has raw items but no sentiment/summary columns.",
};

// --------------------------------------------------------------------------- //
// API helper
// --------------------------------------------------------------------------- //
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) { showLogin(); throw new Error("auth required"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

function toast(msg, isErr = false) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.className = "toast" + (isErr ? " err" : "");
  setTimeout(() => t.classList.add("hidden"), 3200);
}
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const el = (id) => document.getElementById(id);

// --------------------------------------------------------------------------- //
// Boot
// --------------------------------------------------------------------------- //
async function boot() {
  const v = await api("/api/version");
  el("version-stamp").textContent = `MarketLens v${v.version} · ${v.mode} mode`;
  const m = await api("/api/mode");
  State.mode = m.mode; State.user = m.user;
  if (m.team && !m.authenticated) { showLogin(); return; }
  if (m.team) {
    el("user-chip").textContent = m.user; el("user-chip").classList.remove("hidden");
    el("logout-btn").classList.remove("hidden");
  }
  State.health = await api("/api/health").catch(() => null);
  await loadProjects();
}

function showLogin() { el("login-overlay").classList.remove("hidden"); }

el("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api("/api/auth/login", { method: "POST", body: { username: f.get("username"), password: f.get("password") } });
    el("login-overlay").classList.add("hidden");
    location.reload();
  } catch (err) { el("login-error").textContent = "Invalid credentials"; }
});
el("logout-btn").addEventListener("click", async () => { await api("/api/auth/logout", { method: "POST" }); location.reload(); });

// --------------------------------------------------------------------------- //
// Projects
// --------------------------------------------------------------------------- //
async function loadProjects() {
  const projects = await api("/api/projects");
  const sel = el("project-select");
  sel.innerHTML = "";
  if (!projects.length) {
    el("empty-state").classList.remove("hidden");
    el("main").querySelectorAll(".view").forEach(v => v.remove());
    return;
  }
  el("empty-state").classList.add("hidden");
  projects.forEach(p => {
    const o = document.createElement("option"); o.value = p.id; o.textContent = `#${p.id} · ${p.name}`;
    sel.appendChild(o);
  });
  if (!State.projectId || !projects.find(p => p.id === State.projectId)) State.projectId = projects[0].id;
  sel.value = State.projectId;
  await selectProject(State.projectId);
}

el("project-select").addEventListener("change", (e) => selectProject(parseInt(e.target.value)));

async function selectProject(pid) {
  State.projectId = pid;
  State.project = await api(`/api/projects/${pid}`);
  if (!State.channels) State.channels = await api("/api/channels");
  render();
  renderWorkflow();
}

// Wizard
function openWizard() { el("wizard-modal").classList.remove("hidden"); }
el("new-project-btn").addEventListener("click", openWizard);
el("empty-new-btn").addEventListener("click", openWizard);
document.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () =>
  el("wizard-modal").classList.add("hidden")));

el("wizard-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const csv = (s) => (f.get(s) || "").split(",").map(x => x.trim()).filter(Boolean);
  const intake = {
    name: f.get("brand"),
    market: { country: f.get("country"), languages: csv("languages").length ? csv("languages") : ["en"] },
    product: { brand: f.get("brand"), parent_company: f.get("parent_company"),
               category: f.get("category"), category_type: f.get("category_type") },
    competitors: csv("competitors"),
    keywords: { trend_terms: csv("trend_terms") },
  };
  try {
    const r = await api("/api/projects/wizard", { method: "POST", body: intake });
    el("wizard-modal").classList.add("hidden"); e.target.reset();
    State.projectId = r.id; toast(`Study "${r.name}" created — run Extensive research to populate it`);
    await loadProjects();
    // Manual layer: land on Collect so the one-click Extensive-research panel is right there.
    switchView("collect");
  } catch (err) { toast(err.message, true); }
});

// --------------------------------------------------------------------------- //
// Tab routing
// --------------------------------------------------------------------------- //
function switchView(view) {
  State.view = view;
  el("tabs").querySelectorAll("button").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  render();
}

el("tabs").addEventListener("click", (e) => {
  if (e.target.tagName !== "BUTTON") return;
  switchView(e.target.dataset.view);
});

// --------------------------------------------------------------------------- //
// Guided workflow stepper
// --------------------------------------------------------------------------- //
async function renderWorkflow() {
  const wf = el("workflow");
  if (!State.project) { wf.classList.add("hidden"); return; }
  wf.classList.remove("hidden");
  let dash;
  try { dash = await api(`/api/projects/${State.projectId}/dashboard`); }
  catch (e) { wf.classList.add("hidden"); return; }
  State.dash = dash;
  const hasKey = State.health && State.health.keys && State.health.keys.anthropic;
  const collected = dash.total_items > 0;
  const analyzed = dash.total_analyzed > 0 && dash.unanalyzed === 0;
  const partiallyAnalyzed = dash.total_analyzed > 0 && dash.unanalyzed > 0;

  const steps = [
    { view: "overview", n: 1, title: "Configure",
      sub: "Wizard + Source plan — define market, keywords, and where to look.",
      done: true, status: "✓ study created" },
    { view: "collect", n: 2, title: "Collect",
      sub: "Run scrapers to gather items. Start with News / Reddit / GDELT.",
      done: collected, current: !collected,
      status: collected ? `✓ ${dash.total_items} items collected` : "→ run a scraper" },
    { view: "analysis", n: 3, title: "Analyze",
      sub: hasKey ? "Tag items with sentiment, English summaries, drivers, themes."
                  : "Needs ANTHROPIC_API_KEY in .env, then restart.",
      done: analyzed,
      warn: collected && !analyzed && !hasKey,
      current: collected && !analyzed && hasKey,
      status: analyzed ? `✓ ${dash.total_analyzed} analyzed`
              : partiallyAnalyzed ? `${dash.total_analyzed} done · ${dash.unanalyzed} left`
              : !hasKey ? "⚠ set API key first" : collected ? "→ click Analyze all" : "collect first" },
    { view: "export", n: 4, title: "Export",
      sub: "Build the Excel workbook + report draft. Best after Analyze.",
      done: false, current: analyzed,
      status: analyzed ? "→ ready to export" : "richer after Analyze" },
  ];

  wf.innerHTML = steps.map(s => {
    const cls = ["step", s.done ? "done" : "", s.current ? "current" : "", s.warn ? "warn" : ""]
      .filter(Boolean).join(" ");
    return `<div class="${cls}" data-goto="${s.view}">
      <div><span class="step-n">${s.done ? "✓" : s.n}</span><span class="step-title">${s.title}</span></div>
      <div class="step-sub">${s.sub}</div>
      <div class="step-status">${esc(s.status)}</div></div>`;
  }).join("");
  wf.querySelectorAll("[data-goto]").forEach(step =>
    step.addEventListener("click", () => switchView(step.dataset.goto)));
}

// Small inline instruction banner used at the top of each view.
function helpBox(view) {
  return HELP[view] ? `<div class="help">${HELP[view]}</div>` : "";
}

function render() {
  el("main").querySelectorAll(".view").forEach(v => v.remove());
  if (!State.project) return;
  const div = document.createElement("div"); div.className = "view";
  el("main").appendChild(div);
  ({ overview: viewOverview, sources: viewSources, collect: viewCollect, runlog: viewRunLog,
     items: viewItems, analysis: viewAnalysis, intel: viewIntel, manual: viewManual,
     schedules: viewSchedules, export: viewExport }[State.view] || viewOverview)(div);
}

// --------------------------------------------------------------------------- //
// Overview
// --------------------------------------------------------------------------- //
async function viewOverview(root) {
  const cfg = State.project.config;
  root.innerHTML = helpBox("overview") + `<div class="card">
    <div class="card-head"><h2>${esc(State.project.name)}</h2>
      <a href="/api/projects/${State.projectId}/config.yaml" target="_blank" class="muted">config.yaml ↗</a></div>
    <div class="grid">
      ${stat("Brand", cfg.product.brand)}
      ${stat("Market", cfg.market.country + " (" + (cfg.market.country_code||"?") + ")")}
      ${stat("Languages", (cfg.market.languages||[]).join(", "))}
      ${stat("Category", cfg.product.category + " / " + cfg.product.category_type)}
      ${stat("Competitors", (cfg.competitors||[]).join(", ") || "—")}
      ${stat("GDELT country", cfg.market.gdelt_country || "—")}
    </div></div>
    <div class="card"><h3>Live snapshot</h3><div id="ov-stats" class="grid"><span class="muted">loading…</span></div></div>
    <div class="card"><h3>Segment applicability</h3><div id="ov-seg"></div></div>`;
  const dash = await api(`/api/projects/${State.projectId}/dashboard`);
  el("ov-stats").innerHTML =
    stat("Total items", dash.total_items) + stat("Analyzed", dash.total_analyzed) +
    stat("Awaiting analysis", dash.unanalyzed) +
    stat("Net sentiment", dash.overall_net_score + (dash.low_confidence_overall ? " ⚠" : "")) +
    stat("Languages seen", Object.keys(dash.language_breakdown || {}).join(", ") || "—");
  const seg = cfg.source_plan.segments || {};
  el("ov-seg").innerHTML = Object.entries(seg).map(([k, v]) =>
    `<span class="badge ${v ? "pos" : "neu"}">${esc(k)}: ${v ? "on" : "off"}</span>`).join(" ");
}
const stat = (lbl, num) => `<div class="stat"><div class="num">${esc(num)}</div><div class="lbl">${esc(lbl)}</div></div>`;

// --------------------------------------------------------------------------- //
// Source plan editor
// --------------------------------------------------------------------------- //
function viewSources(root) {
  const sp = State.project.config.source_plan;
  const listEditor = (key, label, hint) => `
    <label>${label} <span class="muted">${hint}</span>
      <textarea data-sp="${key}" rows="3">${esc((sp[key]||[]).join("\n"))}</textarea></label>`;
  const mkt = State.project.config.market || {};
  root.innerHTML = helpBox("sources") + `<div class="card">
    <div class="card-head"><h2>Source plan</h2>
      <div class="actions">
        <button id="suggest-sources" class="ghost">✨ Suggest sources (AI)</button>
        <button id="save-sources">Save config</button>
      </div></div>
    <div id="suggest-results"></div>
    <div class="note">🌏 <b>Market filter</b> — news items must show a signal they're in
      <b>${esc(mkt.country||'the market')}</b> (a market term appears, or the outlet uses <b>${esc(mkt.cctld||'the country domain')}</b>);
      otherwise they're dropped (this is what removes e.g. Indian coverage from a Malaysia study).
      Add cities/regions to sharpen it.</div>
    <label>Market terms (comma-separated) <span class="muted">country name matches its demonym automatically</span>
      <input id="market-terms" value="${esc((mkt.market_terms||[]).join(', '))}" placeholder="e.g. Malaysia, Kuala Lumpur, KL, Selangor, Penang, Johor" /></label>
    <hr style="border:none;border-top:1px solid var(--border);margin:.8rem 0" />
    <div class="note">📎 <b>Add sources here — one per line.</b> URLs vary per study and are never
      fixed in the tool; this is where every channel's links live. Prefer keyword-search where
      URLs change constantly (e.g. e-commerce): give a <b>template with <code>{q}</code></b> +
      keywords instead of pasting a URL per product. Use ✨ Suggest sources to auto-propose &amp; validate.</div>
    ${listEditor("rss_feeds", "Direct RSS feeds", "(feed-health-checked)")}
    ${listEditor("ecommerce_urls", "E-commerce — explicit product/category/search URLs", "")}
    ${listEditor("ecommerce_search", "E-commerce — search-URL templates", "use {q} for the keyword, e.g. https://shopee.com.my/search?keyword={q}")}
    ${listEditor("ecommerce_keywords", "E-commerce — keywords for the templates above", "defaults to relevance terms if empty")}
    ${listEditor("forum_urls", "Forum thread/listing URLs", "")}
    ${listEditor("quora_topics", "Quora question URLs", "")}
    ${listEditor("subreddits", "Subreddits (confirm candidates)", "")}
    <div class="row" style="margin-top:.6rem">
      <button id="feed-health" class="ghost">Run feed health check</button>
    </div>
    <div id="feed-results"></div>
  </div>
  <div class="card"><h3>Google News feeds (generated)</h3>
    <div class="table-wrap"><table><thead><tr><th>Lang</th><th>Structure</th><th>Query</th></tr></thead>
    <tbody>${(sp.google_news_feeds||[]).map(f =>
      `<tr><td>${esc(f.language)}</td><td>${esc(f.structure)}</td><td>${esc(f.query)}</td></tr>`).join("") ||
      `<tr><td colspan="3" class="muted">No feeds — add native-language keyword terms below.</td></tr>`}</tbody></table></div>
  </div>
  <div class="card"><h3>Keyword slots per language</h3>${keywordEditor()}</div>`;

  el("save-sources").addEventListener("click", saveSources);
  el("feed-health").addEventListener("click", runFeedHealth);
  el("suggest-sources").addEventListener("click", suggestSources);
}

// --------------------------------------------------------------------------- //
// AI source discovery
// --------------------------------------------------------------------------- //
async function suggestSources() {
  const box = el("suggest-results");
  box.innerHTML = `<div class="note">Asking Claude for candidate sources for
    <b>${esc((State.project.config.product||{}).brand||'')}</b> in
    <b>${esc((State.project.config.market||{}).country||'')}</b>, then validating each link…
    (needs ANTHROPIC_API_KEY; ~10–25s)</div>`;
  try {
    const s = await api(`/api/projects/${State.projectId}/suggest-sources`, { method: "POST" });
    renderSuggestions(s);
  } catch (e) {
    box.innerHTML = `<div class="note">Could not suggest sources: ${esc(e.message)}
      ${/ANTHROPIC/i.test(e.message) ? "— set the key in .env and restart." : ""}</div>`;
  }
}

function _suggRow(channel, value, label, valid, note, why) {
  const badge = valid === true ? `<span class="ready-badge">✓ valid</span>`
    : valid === false ? `<span class="flag">✗ ${esc(note||'unverified')}</span>`
    : `<span class="badge neu">${esc(note||'candidate')}</span>`;
  return `<div class="channel-row" style="padding:.35rem 0">
    <label style="flex:1;font-weight:400;display:flex;gap:.5rem;align-items:flex-start;margin:0">
      <input type="checkbox" data-sugg="${channel}" value="${esc(value)}" ${valid !== false ? "checked" : ""}
        style="width:auto;margin-top:.2rem" />
      <span><b>${esc(label)}</b> ${badge}<br><span class="muted">${esc(value)}${why?` — ${esc(why)}`:''}</span></span>
    </label></div>`;
}

function renderSuggestions(s) {
  const section = (title, rows) => rows
    ? `<div class="card"><h3>${title}</h3>${rows}</div>` : "";
  const rss = (s.news_rss||[]).map(c => _suggRow("news_rss", c.url, c.outlet||c.url, c.valid, c.note, c.why)).join("");
  const ecom = (s.ecommerce||[]).map(c => _suggRow("ecommerce", c.url, c.platform||c.url, c.valid, c.note, c.why)).join("");
  const forums = (s.forums||[]).map(c => _suggRow("forums", c.url, c.name||c.url, c.valid, c.note, c.why)).join("");
  const subs = (s.subreddits||[]).map(n => _suggRow("subreddits", n, "r/"+n, null, "confirmed on run", "")).join("");
  const qc = (s.quick_commerce||[]).map(c =>
    `<div class="channel-row" style="padding:.35rem 0"><div class="channel-meta">
      <b>${esc(c.platform||"")}</b> ${c.web_scrapable ? '<span class="badge tier1">web</span>'
        : '<span class="badge tier3">app-only → Tier-3 gap</span>'}
      <div class="lim">${esc(c.note||"")}</div></div></div>`).join("");

  el("suggest-results").innerHTML = `<div class="card" style="border-color:var(--navy)">
    <div class="card-head"><h2>✨ Suggested sources</h2>
      <button id="add-suggested">Add checked to source plan</button></div>
    <p class="muted">AI-proposed candidates, each validated by the tool. Uncheck any you don't want.
      App-only quick-commerce/social platforms are shown as documented gaps, not scrapers.</p>
    </div>
    ${section("News RSS feeds — "+((s._summary||{}).news_rss||0), rss)}
    ${section("E-commerce search URLs — "+((s._summary||{}).ecommerce||0), ecom)}
    ${section("Forums — "+((s._summary||{}).forums||0), forums)}
    ${section("Subreddits — "+((s._summary||{}).subreddits||0), subs)}
    ${qc ? section("Quick-commerce / delivery", qc + `<div class="note">${esc(s.social_note||"")}</div>`)
         : (s.social_note ? `<div class="note">${esc(s.social_note)}</div>` : "")}`;
  el("add-suggested").addEventListener("click", addSelectedSources);
}

async function addSelectedSources() {
  const cfg = JSON.parse(JSON.stringify(State.project.config));
  const keyFor = { news_rss: "rss_feeds", ecommerce: "ecommerce_urls", forums: "forum_urls",
                   subreddits: "subreddits" };
  let added = 0;
  document.querySelectorAll("[data-sugg]:checked").forEach(cb => {
    const key = keyFor[cb.dataset.sugg];
    if (!key) return;
    const cur = cfg.source_plan[key] || [];
    if (!cur.includes(cb.value)) { cur.push(cb.value); added++; }
    cfg.source_plan[key] = cur;
  });
  try {
    await api(`/api/projects/${State.projectId}/config`, { method: "PUT", body: { config: cfg } });
    toast(`Added ${added} source(s) to the plan`);
    State.project = await api(`/api/projects/${State.projectId}`);
    render();
  } catch (e) { toast(e.message, true); }
}

function keywordEditor() {
  const kw = State.project.config.keywords.by_language || {};
  return Object.entries(kw).map(([lang, slots]) => `
    <fieldset><legend>${esc(lang)}</legend>
      ${Object.entries(slots).map(([s, terms]) =>
        `<label>${esc(s)} <input data-kw="${esc(lang)}|${esc(s)}" value="${esc((terms||[]).join(", "))}" /></label>`).join("")}
    </fieldset>`).join("");
}

async function saveSources() {
  const cfg = JSON.parse(JSON.stringify(State.project.config));
  document.querySelectorAll("[data-sp]").forEach(t => {
    cfg.source_plan[t.dataset.sp] = t.value.split("\n").map(x => x.trim()).filter(Boolean);
  });
  document.querySelectorAll("[data-kw]").forEach(inp => {
    const [lang, slot] = inp.dataset.kw.split("|");
    cfg.keywords.by_language[lang][slot] = inp.value.split(",").map(x => x.trim()).filter(Boolean);
  });
  // Market terms (drives the off-market news filter).
  const mt = el("market-terms");
  if (mt) { cfg.market = cfg.market || {}; cfg.market.market_terms = mt.value.split(",").map(x => x.trim()).filter(Boolean); }
  // Regenerate Google News feeds from the edited keyword slots.
  try {
    await api(`/api/projects/${State.projectId}/config`, { method: "PUT", body: { config: cfg } });
    // Re-run wizard-style regeneration by re-saving through a fresh wizard call is overkill;
    // instead ask the user to note feeds regenerate on next edit. Reload project.
    toast("Config saved. (Google News feeds regenerate when you recreate keyword structures.)");
    State.project = await api(`/api/projects/${State.projectId}`);
    render();
  } catch (e) { toast(e.message, true); }
}

async function runFeedHealth() {
  const urls = (el("feed-results").dataset.urls) || "";
  const feeds = document.querySelector('[data-sp="rss_feeds"]').value.split("\n").map(x => x.trim()).filter(Boolean);
  el("feed-results").innerHTML = `<p class="muted">Checking ${feeds.length} feed(s)…</p>`;
  try {
    const r = await api(`/api/projects/${State.projectId}/feed-health`, { method: "POST", body: { urls: feeds } });
    el("feed-results").innerHTML = `<div class="table-wrap"><table><thead><tr><th>Feed</th><th>Status</th>
      <th>Entries</th><th>Health</th></tr></thead><tbody>${r.results.map(f =>
      `<tr><td>${esc(f.url)}</td><td>${esc(f.status||"—")}</td><td>${f.entries}</td>
       <td>${f.healthy ? '<span class="badge pos">healthy</span>' :
         '<span class="flag">DEAD: '+esc(f.reason)+'</span>'}</td></tr>`).join("")}</tbody></table></div>`;
  } catch (e) { toast(e.message, true); }
}

// --------------------------------------------------------------------------- //
// Collect
// --------------------------------------------------------------------------- //
let jobPoll = null;
async function viewCollect(root) {
  const info = State.channels.info;
  const mkt = (State.project.config.market || {});
  const yr = new Date().getFullYear();
  root.innerHTML = helpBox("collect") + `<div class="card" style="border-color:var(--navy)">
    <div class="card-head"><h2>🔬 Extensive research (one click)</h2></div>
    <p class="muted">Full-year, month-by-month collection across the chosen channels
      (monthly chunking beats Google News's ~100-results cap), market-filtered and
      de-duplicated. You pick the channels and year — this never auto-fires.</p>
    <div class="row">
      <label style="flex:0 0 120px">Year <input id="ext-year" type="number" value="${yr}" min="2015" max="${yr}" /></label>
      <div style="flex:1">
        <div style="font-weight:600;font-size:13px;margin-bottom:.2rem">Channels</div>
        <label style="font-weight:400;display:inline-block;margin-right:1rem"><input type="checkbox" class="ext-ch" value="news" checked style="width:auto"/> News</label>
        <label style="font-weight:400;display:inline-block;margin-right:1rem"><input type="checkbox" class="ext-ch" value="gdelt" checked style="width:auto"/> GDELT</label>
        <label style="font-weight:400;display:inline-block;margin-right:1rem"><input type="checkbox" class="ext-ch" value="reddit" checked style="width:auto"/> Reddit</label>
        <label style="font-weight:400;display:inline-block;margin-right:1rem"><input type="checkbox" class="ext-ch" value="forums" style="width:auto"/> Forums</label>
        <label style="font-weight:400;display:inline-block;margin-right:1rem"><input type="checkbox" class="ext-ch" value="ecommerce" style="width:auto"/> E-commerce</label>
      </div>
    </div>
    <div class="actions" style="margin-top:.6rem">
      <button id="run-extensive">Run extensive research</button>
      <span id="ext-status" class="muted"></span>
    </div>
    <div class="note">Forums/E-commerce only run if you've added their URLs in Source plan.
      Reddit/GDELT need network that isn't bot-blocked (works from a normal connection).</div>
  </div>
  <div class="card"><div class="card-head"><h2>Collect a single channel</h2>
    <span id="active-job" class="muted"></span></div>
    <label style="font-weight:600"><input type="checkbox" id="market-only" checked
        style="width:auto;margin-right:.4rem" />
      Restrict news to ${esc(mkt.country||'the target market')} (drop off-market items, e.g. other countries)</label>
    <p class="muted" style="margin:.2rem 0 .6rem">Uses market terms
      <b>${esc((mkt.market_terms||[]).join(', ')||mkt.country||'—')}</b> and domain <b>${esc(mkt.cctld||'—')}</b>.
      Edit these in Source plan. Uncheck to collect globally.</p>
    <div id="channel-list"></div></div>
    <div class="card"><h3>Recent jobs</h3><div id="job-list"></div></div>`;
  // Sort ready-now channels to the top so the user knows where to start.
  const list = el("channel-list");
  const ordered = [...State.channels.channels].sort((a, b) =>
    (CHREQ[b]?.ready ? 1 : 0) - (CHREQ[a]?.ready ? 1 : 0));
  list.innerHTML = ordered.map(ch => {
    const i = info[ch] || {};
    const req = CHREQ[ch] || { ready: false, needs: "" };
    const badge = req.ready
      ? `<span class="ready-badge">ready — no setup</span>`
      : `<span class="needs-badge">needs: ${esc(req.needs)}</span>`;
    return `<div class="channel-row"><div class="channel-meta">
      <b>${esc(i.name||ch)}</b> <span class="badge tier1">Tier ${esc(i.tier||"1")}</span> ${badge}
      <div class="lim">${esc(i.method||"")}</div>
      <div class="lim">⚠ ${esc(i.limitation||"")}</div></div>
      <div><button data-collect="${ch}">Run</button></div></div>`;
  }).join("");
  list.querySelectorAll("[data-collect]").forEach(b => b.addEventListener("click", () => runCollect(b.dataset.collect)));
  el("run-extensive").addEventListener("click", runExtensive);
  refreshJobs();
}

async function runExtensive() {
  const channels = [...document.querySelectorAll(".ext-ch:checked")].map(c => c.value);
  const year = parseInt(el("ext-year").value) || new Date().getFullYear();
  if (!channels.length) { toast("Pick at least one channel", true); return; }
  const mo = el("market-only") ? el("market-only").checked : true;
  el("ext-status").textContent = `Queuing ${channels.length} channel(s) for all of ${year}…`;
  try {
    const r = await api(`/api/projects/${State.projectId}/collect-extensive`, { method: "POST",
      body: { channels, year, market_only: mo } });
    toast(`Extensive research queued: ${r.jobs.map(j => j.channel).join(", ")} (${year})`);
    el("ext-status").textContent = `Running ${channels.length} channel(s) for ${year} — monthly chunks, this can take a few minutes. Watch “Recent jobs”.`;
    // Poll the last job so the stepper/jobs refresh as they finish.
    r.jobs.forEach(j => pollJob(j.job_id));
    refreshJobs();
  } catch (e) { el("ext-status").textContent = ""; toast(e.message, true); }
}

async function runCollect(channel) {
  try {
    const params = {};
    // The market gate applies to news; pass the checkbox state.
    const mo = el("market-only");
    if (channel === "news" && mo) params.market_only = mo.checked;
    const r = await api(`/api/projects/${State.projectId}/collect`, { method: "POST", body: { channel, params } });
    toast(`Queued ${channel} (job #${r.job_id})`);
    pollJob(r.job_id);
    refreshJobs();
  } catch (e) { toast(e.message, true); }
}

async function pollJob(jobId) {
  if (jobPoll) clearInterval(jobPoll);
  jobPoll = setInterval(async () => {
    try {
      const j = await api(`/api/jobs/${jobId}`);
      const ab = el("active-job");
      if (ab) ab.textContent = `job #${jobId}: ${j.status}`;
      if (j.status === "done" || j.status === "error") {
        clearInterval(jobPoll); jobPoll = null;
        const s = j.summary || {};
        toast(`Job #${jobId} ${j.status}: +${s.new||0} new / ${s.duplicate||0} dup`);
        refreshJobs();
        renderWorkflow();  // step 2 turns green once items land
      }
    } catch (e) { clearInterval(jobPoll); jobPoll = null; }
  }, 1500);
}

async function refreshJobs() {
  if (State.view !== "collect") return;
  const jobs = await api(`/api/projects/${State.projectId}/jobs`);
  const box = el("job-list"); if (!box) return;
  box.innerHTML = `<div class="table-wrap"><table><thead><tr><th>#</th><th>Channel</th><th>Status</th>
    <th>By</th><th>New</th><th>Dup</th></tr></thead><tbody>${jobs.map(j => {
      const s = j.summary || {};
      return `<tr><td>${j.id}</td><td>${esc(j.channel)}</td><td>${esc(j.status)}</td>
        <td>${esc(j.triggered_by||"")}</td><td>${s.new??"—"}</td><td>${s.duplicate??"—"}</td></tr>`;
    }).join("") || `<tr><td colspan="6" class="muted">No jobs yet.</td></tr>`}</tbody></table></div>`;
}

// --------------------------------------------------------------------------- //
// Run log
// --------------------------------------------------------------------------- //
async function viewRunLog(root) {
  root.innerHTML = helpBox("runlog") + `<div class="card"><h2>Run log — full audit trail</h2><div id="rl"></div></div>`;
  const runs = await api(`/api/projects/${State.projectId}/runs`);
  el("rl").innerHTML = `<div class="table-wrap"><table><thead><tr><th>#</th><th>Channel</th><th>Status</th>
    <th>Started</th><th>Returned</th><th>New</th><th>Dup</th><th>By</th><th>Errors</th></tr></thead>
    <tbody>${runs.map(r => `<tr><td>${r.id}</td><td>${esc(r.channel)}</td><td>${esc(r.status)}</td>
      <td>${esc((r.started_at||"").slice(0,19))}</td><td>${r.rows_returned}</td><td>${r.rows_new}</td>
      <td>${r.rows_duplicate}</td><td>${esc(r.triggered_by||"")}</td>
      <td class="muted">${esc((r.errors_json||"[]").slice(0,120))}</td></tr>`).join("") ||
      `<tr><td colspan="9" class="muted">No runs yet.</td></tr>`}</tbody></table></div>`;
}

// --------------------------------------------------------------------------- //
// Items browser
// --------------------------------------------------------------------------- //
const ItemsFilter = { source: "", brand_focus: "", sentiment: "", q: "" };

async function viewItems(root) {
  root.innerHTML = helpBox("items") + `<div class="card">
    <div class="card-head"><h2>Items</h2><span id="items-count" class="muted"></span></div>
    <div class="row">
      <label>Search <input id="if-q" placeholder="title, text, or summary…" value="${esc(ItemsFilter.q)}" /></label>
      <label>Channel <select id="if-source"></select></label>
      <label>Brand focus <select id="if-bf">
        <option value="">any</option>
        <option>target brand</option><option>named competitor</option>
        <option>category-generic</option><option>corporate</option><option>unrelated</option>
      </select></label>
      <label>Sentiment <select id="if-sent">
        <option value="">any</option><option>positive</option><option>negative</option>
        <option>neutral</option><option>mixed</option></select></label>
    </div>
    <div id="items-table" class="table-wrap"><p class="muted">Loading…</p></div>
  </div>`;

  // Populate channel filter from known sources.
  const dash = State.dash || {};
  const sources = Object.keys((await api(`/api/projects/${State.projectId}/items-table?limit=1`)).sources || {});
  const srcSel = el("if-source");
  srcSel.innerHTML = `<option value="">all</option>` + sources.map(s => `<option>${esc(s)}</option>`).join("");
  srcSel.value = ItemsFilter.source;
  el("if-bf").value = ItemsFilter.brand_focus;
  el("if-sent").value = ItemsFilter.sentiment;

  const reload = async () => {
    ItemsFilter.q = el("if-q").value;
    ItemsFilter.source = el("if-source").value;
    ItemsFilter.brand_focus = el("if-bf").value;
    ItemsFilter.sentiment = el("if-sent").value;
    await loadItemsTable();
  };
  el("if-q").addEventListener("input", debounce(reload, 300));
  ["if-source", "if-bf", "if-sent"].forEach(id => el(id).addEventListener("change", reload));
  await loadItemsTable();
}

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function loadItemsTable() {
  const p = new URLSearchParams();
  if (ItemsFilter.source) p.set("source", ItemsFilter.source);
  if (ItemsFilter.brand_focus) p.set("brand_focus", ItemsFilter.brand_focus);
  if (ItemsFilter.sentiment) p.set("sentiment", ItemsFilter.sentiment);
  if (ItemsFilter.q) p.set("q", ItemsFilter.q);
  const data = await api(`/api/projects/${State.projectId}/items-table?${p.toString()}`);
  el("items-count").textContent = `showing ${data.rows.length} of ${data.matched} matched · ${data.total} total`;
  const badge = (s) => s ? `<span class="badge ${s==='positive'?'pos':s==='negative'?'neg':'neu'}">${esc(s)}</span>` : "";
  el("items-table").innerHTML = `<table><thead><tr>
    <th>#</th><th>Channel</th><th>Title</th><th>Sentiment</th><th>Lang</th><th>Brand focus</th>
    <th>Driver</th><th>Summary (EN)</th></tr></thead><tbody>${
    data.rows.map((r, i) => `<tr>
      <td>${i + 1}</td><td>${esc(r.source)}</td>
      <td>${r.link ? `<a href="${esc(r.link)}" target="_blank">${esc((r.title||'').slice(0,90))}</a>`
                    : esc((r.title||'').slice(0,90))}</td>
      <td>${badge(r.sentiment)}</td><td>${esc(r.language||'')}</td>
      <td>${esc(r.brand_focus||'—')}</td><td>${esc(r.purchase_driver||'—')}</td>
      <td class="muted">${esc((r.summary_en||r.text||'').slice(0,140))}</td></tr>`).join("") ||
    `<tr><td colspan="8" class="muted">No items match. Collect data first, or loosen the filters.</td></tr>`
  }</tbody></table>`;
}

// --------------------------------------------------------------------------- //
// Analysis
// --------------------------------------------------------------------------- //
async function viewAnalysis(root) {
  const hasKey = State.health && State.health.keys && State.health.keys.anthropic;
  const dash = State.dash || {};
  const nItems = dash.total_items || 0;
  const keyChip = hasKey
    ? `<span class="keychip ok">✓ ANTHROPIC_API_KEY detected</span>`
    : `<span class="keychip missing">⚠ ANTHROPIC_API_KEY not set</span>`;

  root.innerHTML = helpBox("analysis") + `<div class="card">
    <div class="card-head"><h2>Analysis ${keyChip}</h2>
    <div class="actions"><button id="analyze-batch" class="ghost" ${nItems ? "" : "disabled"}>Analyze one batch (12)</button>
      <button id="analyze-all" ${nItems && hasKey ? "" : "disabled"}>Analyze all</button></div></div>
    ${nItems === 0 ? `<div class="note">No items to analyze yet. Go to <b>Collect</b> and run a
        scraper first, then come back here.</div>` : ""}
    ${nItems && !hasKey ? `<div class="note">You have <b>${nItems}</b> items ready, but analysis
        needs <span class="kbd">ANTHROPIC_API_KEY</span>. Add it to <b>.env</b>, restart the app,
        then reload this page.</div>` : ""}
    <div id="an-status" class="muted"></div></div>
    <div class="card"><h3>Sentiment × channel</h3><div id="an-dash"></div></div>
    <div class="card"><h3>Brand vs. competitor · drivers · trends</h3><div id="an-aggs"></div></div>
    <div class="card"><h3>Top verbatims per theme</h3><div id="an-verb"></div></div>`;
  el("analyze-batch").addEventListener("click", () => doAnalyze("batch"));
  el("analyze-all").addEventListener("click", () => doAnalyze("all"));
  await renderAnalysis();
}

async function doAnalyze(mode) {
  el("an-status").textContent = "Analyzing… (calls the Claude API; needs ANTHROPIC_API_KEY)";
  try {
    const r = await api(`/api/projects/${State.projectId}/analyze`, { method: "POST", body: { mode } });
    if (r.status === "error") { toast("Analysis error: " + (r.error||""), true); }
    el("an-status").textContent = `Analyzed ${r.analyzed}; remaining ${r.remaining ?? "?"}.`;
    await renderAnalysis();
    renderWorkflow();  // step 3 turns green once everything is analyzed
  } catch (e) { el("an-status").textContent = ""; toast(e.message, true); }
}

async function renderAnalysis() {
  const dash = await api(`/api/projects/${State.projectId}/dashboard`);
  el("an-dash").innerHTML = `<p class="muted">Overall net ${dash.overall_net_score}
    ${dash.low_confidence_overall ? '<span class="flag">low-confidence (n<100)</span>' : ""}
    · ${dash.total_analyzed}/${dash.total_items} analyzed</p>` +
    `<div class="table-wrap"><table><thead><tr><th>Channel</th><th>n</th><th>Sentiment</th><th>Net</th>
      <th>Languages</th><th></th></tr></thead><tbody>${dash.by_channel.map(c =>
      `<tr><td>${esc(c.channel)}</td><td>${c.n}</td><td style="min-width:120px">${sentBar(c)}</td>
       <td>${c.net_score}</td><td class="muted">${esc(JSON.stringify(c.language_breakdown))}</td>
       <td>${c.low_confidence ? '<span class="flag">emerging</span>' : ""}</td></tr>`).join("") ||
      `<tr><td colspan="6" class="muted">No analyzed items yet.</td></tr>`}</tbody></table></div>`;

  const [bvc, drivers, trends] = await Promise.all([
    api(`/api/projects/${State.projectId}/analytics/brand_vs_competitor`),
    api(`/api/projects/${State.projectId}/analytics/purchase_drivers`),
    api(`/api/projects/${State.projectId}/analytics/trend_volume`),
  ]);
  el("an-aggs").innerHTML =
    `<h4>Brand focus (net sentiment, n)</h4>` + (bvc.data.map(r =>
      `<div>${esc(r.brand_focus)}: <b>${r.net_score}</b> <span class="muted">(n=${r.n})</span>
       ${r.low_confidence ? '<span class="flag">emerging</span>' : ""}</div>`).join("") || "<span class='muted'>—</span>") +
    `<h4 style="margin-top:.8rem">Top purchase drivers (n=${drivers.n})</h4>` +
      (drivers.drivers.map(d => `<span class="badge neu">${esc(d.driver)} · ${d.count}</span> `).join("") || "<span class='muted'>—</span>") +
    `<h4 style="margin-top:.8rem">Trend volume</h4>` + (trends.series.map(s =>
      `<div>${esc(s.trend_category)}: <b>${s.n}</b> ${s.low_confidence ? '<span class="flag">emerging</span>' : ""}</div>`).join("") || "<span class='muted'>—</span>");

  const verb = await api(`/api/projects/${State.projectId}/analytics/verbatims`);
  el("an-verb").innerHTML = verb.themes.map(t => `<div style="margin-bottom:.7rem">
    <b>${esc(t.theme)}</b> <span class="muted">(n=${t.n})</span>
    ${t.verbatims.map(v => `<div class="muted" style="margin-left:1rem">• “${esc(v.summary_en||v.text)}”
      <span class="badge ${v.sentiment==='positive'?'pos':v.sentiment==='negative'?'neg':'neu'}">${esc(v.sentiment)}</span>
      <i>${esc(v.source)}</i></div>`).join("")}</div>`).join("") || "<span class='muted'>No verbatims yet.</span>";
}
function sentBar(c) {
  const n = c.n || 1;
  const p = (x) => (x / n * 100).toFixed(0) + "%";
  return `<div class="bar"><div class="seg-pos" style="width:${p(c.positive)}"></div>
    <div class="seg-neg" style="width:${p(c.negative)}"></div><div class="seg-mix" style="width:${p(c.mixed)}"></div>
    <div class="seg-neu" style="width:${p(c.neutral)}"></div></div>`;
}

// --------------------------------------------------------------------------- //
// Market intel (cited)
// --------------------------------------------------------------------------- //
async function viewIntel(root) {
  const data = await api(`/api/projects/${State.projectId}/market-intel`);
  root.innerHTML = helpBox("intel") + `<div class="card"><h2>Market Intelligence — cited layer</h2>
    <p class="muted">Every entry requires a full citation. No paywalled research is auto-scraped.</p>
    <form id="cited-form">
      <div class="row">
        <label>Category <select name="category">${data.categories.map(c=>`<option>${esc(c)}</option>`).join("")}</select></label>
        <label>Metric <input name="metric" placeholder="e.g. Market size 2024" /></label>
        <label>Value <input name="value" required /></label>
      </div>
      <div class="row">
        <label>Source name <input name="source_name" required /></label>
        <label>Source URL <input name="source_url" required /></label>
        <label>Confidence <select name="confidence">${data.confidence_levels.map(c=>`<option>${esc(c)}</option>`).join("")}</select></label>
      </div>
      <div class="row">
        <label>Publication date <input name="publication_date" type="date" required /></label>
        <label>Accessed date <input name="accessed_date" type="date" required /></label>
        <label>Notes <input name="notes" /></label>
      </div>
      <button type="submit">Add cited entry</button>
    </form></div>
    <div class="card"><h3>Cited entries</h3><div id="cited-list"></div></div>`;
  el("cited-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try { await api(`/api/projects/${State.projectId}/market-intel`, { method: "POST", body: f });
      toast("Cited entry added"); e.target.reset(); viewIntel(root);
    } catch (err) { toast(err.message, true); }
  });
  renderCited(data.cited);
}
function renderCited(cited) {
  el("cited-list").innerHTML = `<div class="table-wrap"><table><thead><tr><th>Category</th><th>Metric</th>
    <th>Value</th><th>Source</th><th>Pub</th><th>Conf</th><th>By</th><th></th></tr></thead>
    <tbody>${cited.map(e => `<tr><td>${esc(e.category)}</td><td>${esc(e.metric)}</td><td>${esc(e.value)}</td>
      <td><a href="${esc(e.source_url)}" target="_blank">${esc(e.source_name)}</a></td>
      <td>${esc(e.publication_date)}</td><td>${esc(e.confidence)}</td><td>${esc(e.entered_by||"")}</td>
      <td><button class="ghost" data-del="${e.id}">✕</button></td></tr>`).join("") ||
      `<tr><td colspan="8" class="muted">No cited entries yet.</td></tr>`}</tbody></table></div>`;
  el("cited-list").querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
    await api(`/api/projects/${State.projectId}/market-intel/${b.dataset.del}`, { method: "DELETE" });
    const data = await api(`/api/projects/${State.projectId}/market-intel`); renderCited(data.cited);
  }));
}

// --------------------------------------------------------------------------- //
// Manual intel (Tier-2) + Tier-3 gaps
// --------------------------------------------------------------------------- //
async function viewManual(root) {
  const plan = await api(`/api/projects/${State.projectId}/manual-plan`);
  const intel = await api(`/api/projects/${State.projectId}/market-intel`);
  root.innerHTML = helpBox("manual") + `<div class="card"><h2>Manual Intelligence (Tier-2)</h2>
    <p class="muted">These platforms are free to browse but hostile to automation. Open the deep
      links, then record observations below.</p>
    ${plan.platforms.map(p => `<div class="channel-row"><div class="channel-meta">
      <b>${esc(p.name)}</b> <span class="badge tier2">Tier 2</span>
      <div class="lim">${esc(p.note)}</div>
      <div class="deep-links">${(p.deep_links||[]).map(d =>
        `<a href="${esc(d.url)}" target="_blank">${esc(d.name)} ↗</a>`).join("") ||
        '<span class="muted">no name-search deep links</span>'}</div>
    </div></div>`).join("")}
  </div>
  <div class="card"><h3>Record an ad observation</h3>
    <form id="manual-form">
      <div class="row"><label>Advertiser <input name="advertiser" required /></label>
        <label>Platform <input name="platform" required /></label>
        <label>Creative theme <input name="creative_theme" /></label></div>
      <div class="row"><label>Format <input name="format" placeholder="video / static / carousel" /></label>
        <label>First seen <input name="first_seen_date" type="date" /></label>
        <label>Source URL <input name="source_url" /></label></div>
      <label>Notes <textarea name="notes" rows="2"></textarea></label>
      <button type="submit">Save observation</button>
    </form>
    <div id="manual-list" style="margin-top:1rem"></div>
  </div>
  <div class="card"><h3>Tier-3 — NOT covered (documented gaps)</h3>
    <div class="table-wrap"><table><thead><tr><th>Platform</th><th>Reason</th></tr></thead>
    <tbody>${plan.tier3_gaps.map(g => `<tr><td><span class="badge tier3">${esc(g.platform)}</span></td>
      <td class="muted">${esc(g.reason)}</td></tr>`).join("")}</tbody></table></div>
    <div class="note">MarketLens never claims coverage of these platforms and never fabricates data
      for a failed scrape.</div></div>`;
  el("manual-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try { await api(`/api/projects/${State.projectId}/manual-intel`, { method: "POST", body: f });
      toast("Observation saved"); e.target.reset(); viewManual(root);
    } catch (err) { toast(err.message, true); }
  });
  el("manual-list").innerHTML = intel.manual_ads.length ? `<div class="table-wrap"><table><thead><tr>
    <th>Platform</th><th>Advertiser</th><th>Theme</th><th>Format</th><th>First seen</th><th>By</th></tr></thead>
    <tbody>${intel.manual_ads.map(e => `<tr><td>${esc(e.source_name)}</td><td>${esc(e.value)}</td>
      <td>${esc(e.extra.creative_theme||"")}</td><td>${esc(e.extra.format||"")}</td>
      <td>${esc(e.extra.first_seen_date||"")}</td><td>${esc(e.entered_by||"")}</td></tr>`).join("")}</tbody></table></div>`
    : '<span class="muted">No observations yet.</span>';
}

// --------------------------------------------------------------------------- //
// Schedules
// --------------------------------------------------------------------------- //
async function viewSchedules(root) {
  const scheds = await api(`/api/projects/${State.projectId}/schedules`);
  root.innerHTML = helpBox("schedules") + `<div class="card"><h2>Schedules</h2>
    <form id="sched-form" class="row">
      <label>Channel <select name="channel">${State.channels.channels.map(c=>`<option>${esc(c)}</option>`).join("")}</select></label>
      <label>Interval <select name="interval_seconds">
        <option value="3600">Hourly</option><option value="86400" selected>Daily</option>
        <option value="604800">Weekly</option></select></label>
      <button type="submit">Add schedule</button>
    </form></div>
    <div class="card"><h3>Active schedules</h3><div class="table-wrap"><table><thead><tr><th>#</th><th>Channel</th>
      <th>Every</th><th>Next run</th><th>Paused</th><th></th></tr></thead><tbody>${scheds.map(s =>
      `<tr><td>${s.id}</td><td>${esc(s.channel)}</td><td>${s.interval_seconds}s</td>
       <td>${esc((s.next_run||"").slice(0,19))}</td><td>${s.paused?"yes":"no"}</td>
       <td><button class="ghost" data-pause="${s.id}" data-p="${s.paused?0:1}">${s.paused?"Resume":"Pause"}</button>
       <button class="ghost" data-delsched="${s.id}">Delete</button></td></tr>`).join("") ||
      `<tr><td colspan="6" class="muted">No schedules.</td></tr>`}</tbody></table></div></div>`;
  el("sched-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    await api(`/api/projects/${State.projectId}/schedules`, { method: "POST",
      body: { channel: f.channel, interval_seconds: parseInt(f.interval_seconds), params: {} } });
    toast("Schedule created"); viewSchedules(root);
  });
  root.querySelectorAll("[data-pause]").forEach(b => b.addEventListener("click", async () => {
    await api(`/api/schedules/${b.dataset.pause}/pause`, { method: "POST", body: { paused: b.dataset.p === "1" } });
    viewSchedules(root);
  }));
  root.querySelectorAll("[data-delsched]").forEach(b => b.addEventListener("click", async () => {
    await api(`/api/schedules/${b.dataset.delsched}`, { method: "DELETE" }); viewSchedules(root);
  }));
}

// --------------------------------------------------------------------------- //
// Export & report
// --------------------------------------------------------------------------- //
function viewExport(root) {
  const dash = State.dash || {};
  const nItems = dash.total_items || 0;
  const nAnalyzed = dash.total_analyzed || 0;
  let readiness = "";
  if (nItems === 0) {
    readiness = `<div class="note">⚠ This study has <b>no collected items</b>. The workbook will be
      almost empty. Do <b>Collect</b> (and then <b>Analyze</b>) first.</div>`;
  } else if (nAnalyzed === 0) {
    readiness = `<div class="note">⚠ You've collected <b>${nItems}</b> items but <b>analyzed 0</b>.
      The workbook will have raw item tabs + Run Log, but <b>no sentiment / summary / driver
      columns</b> and empty Analysis Summary. Run <b>Analyze all</b> first for a useful report.</div>`;
  } else {
    readiness = `<div class="note" style="background:#f4fbf5;border-color:#bfe3c2;color:#215c26">
      ✓ Ready: <b>${nItems}</b> items collected, <b>${nAnalyzed}</b> analyzed.</div>`;
  }
  root.innerHTML = helpBox("export") + `<div class="card"><h2>Export &amp; report</h2>
    ${readiness}
    <div class="row"><label>Published after <input id="exp-after" type="date" /></label>
      <label>Published before <input id="exp-before" type="date" /></label>
      <button id="build-xlsx">Build Excel workbook</button></div>
    <div id="exp-result"></div>
    <div class="note">The Excel workbook is the client-facing artifact — it stamps the tool version
      and includes Methodology, Confidence, and Representativeness tabs (the honesty contract).
      It also has an <b>“All Items”</b> tab: every collected item across all channels in one sheet
      (id, source, title, text, link, published, run_id + all analysis columns).</div>
  </div>
  <div class="card"><div class="card-head"><h3>Report draft (five pillars)</h3>
    <div class="actions">
      <button id="gen-report" class="ghost">Generate / preview</button>
      <a class="dl-btn" href="/api/projects/${State.projectId}/report/download?fmt=docx">Download Word (.docx)</a>
      <a class="dl-btn" href="/api/projects/${State.projectId}/report/download?fmt=md">Download Markdown (.md)</a>
    </div></div>
    <p class="muted">The report is a separate narrative deliverable — it is <b>not</b> a tab in the
      Excel workbook. Download it here as Word or Markdown, or preview it below.</p>
    <pre id="report-out" class="report">Click “Generate / preview” to assemble the Markdown skeleton, or download it directly.</pre></div>
  <div class="card"><h3>Portability</h3>
    <button id="archive-export" class="ghost">Export project archive (.mlz)</button>
    <div id="archive-result"></div>
    <p class="muted">Archive = working-data transfer (config + items + analysis + intel + run log).
      Import via the API on another instance.</p></div>`;
  el("build-xlsx").addEventListener("click", async () => {
    el("exp-result").innerHTML = '<p class="muted">Building…</p>';
    try {
      const body = { published_after: el("exp-after").value || null, published_before: el("exp-before").value || null };
      const r = await api(`/api/projects/${State.projectId}/export`, { method: "POST", body });
      el("exp-result").innerHTML = `<p>Built <b>${esc(r.filename)}</b> —
        <a href="/api/projects/${State.projectId}/export/download?path=${encodeURIComponent(r.path)}">Download ↓</a></p>`;
    } catch (e) { el("exp-result").innerHTML = ""; toast(e.message, true); }
  });
  el("gen-report").addEventListener("click", async () => {
    const md = await api(`/api/projects/${State.projectId}/report/draft`);
    el("report-out").textContent = md;
  });
  el("archive-export").addEventListener("click", async () => {
    const r = await api(`/api/projects/${State.projectId}/archive/export`, { method: "POST" });
    el("archive-result").innerHTML = `<p>Archived <b>${esc(r.filename)}</b> —
      <a href="/api/projects/${State.projectId}/archive/download?path=${encodeURIComponent(r.path)}">Download ↓</a></p>`;
  });
}

boot().catch(e => console.error(e));
