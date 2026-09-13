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
  results: "Where the data actually came from and how reliable it's been: volume by channel and by site, sources currently paused after repeated failures, and what the cross-project site-intelligence ledger has learned so far for this category.",
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
let _languageOptionsLoaded = false;
async function loadLanguageOptions() {
  if (_languageOptionsLoaded) return;
  const sel = el("wizard-languages");
  sel.innerHTML = `<option disabled>Loading…</option>`;
  try {
    const langs = await api("/api/reference/languages");
    sel.innerHTML = langs.map(l => `<option value="${esc(l.code)}">${esc(l.name)} (${esc(l.code)})</option>`).join("");
    _languageOptionsLoaded = true;
  } catch (e) {
    // The "Other language codes" free-text field still works without this — but show
    // WHY the box is empty rather than leaving a silent, unexplained blank box.
    sel.innerHTML = `<option disabled>Couldn't load — ${esc(e.message)}. Use "Other" below, or reload the page.</option>`;
  }
}
let _countryOptionsLoaded = false;
async function loadCountryOptions() {
  if (_countryOptionsLoaded) return;
  const sel = el("wizard-countries");
  sel.innerHTML = `<option disabled>Loading…</option>`;
  try {
    const countries = await api("/api/reference/countries");
    sel.innerHTML = countries.map(c => `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join("");
    _countryOptionsLoaded = true;
  } catch (e) {
    // The "Other country/region" free-text field still works without this — but show
    // WHY the box is empty rather than leaving a silent, unexplained blank box.
    sel.innerHTML = `<option disabled>Couldn't load — ${esc(e.message)}. Use "Other" below, or reload the page.</option>`;
  }
}
function openWizard() {
  el("wizard-modal").classList.remove("hidden");
  loadLanguageOptions();
  loadCountryOptions();
}
el("new-project-btn").addEventListener("click", openWizard);
el("empty-new-btn").addEventListener("click", openWizard);
document.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () =>
  el("wizard-modal").classList.add("hidden")));

el("wizard-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const csv = (s) => (f.get(s) || "").split(",").map(x => x.trim()).filter(Boolean);
  const brand = (f.get("brand") || "").trim();
  const category = (f.get("category") || "").trim();
  if (!brand && !category) {
    toast("Provide a brand name, a product category, or both.", true);
    return;
  }
  // Country picker allows multi-select (same control as languages, for interaction
  // consistency), but a study targets exactly one market — so more than one selection
  // (dropdown pick(s) + the free-text "other" field) is rejected rather than silently
  // collapsed to one, which would quietly use a country the user didn't clearly intend.
  const otherCountry = (f.get("country_other") || "").trim();
  const pickedCountries = f.getAll("country").map(x => x.trim()).filter(Boolean);
  const countryCandidates = [...pickedCountries, ...(otherCountry ? [otherCountry] : [])];
  if (countryCandidates.length === 0) {
    toast("Select a country/region, or type one in \"Other\".", true);
    return;
  }
  if (countryCandidates.length > 1) {
    toast(`A study targets one country/region — you selected ${countryCandidates.length} `
      + `(${countryCandidates.join(", ")}). Pick just one.`, true);
    return;
  }
  // Selected dropdown languages (supports single AND multi-select) + any free-text
  // "other" codes for languages not in the reference list, de-duped.
  const picked = f.getAll("languages").map(x => x.trim()).filter(Boolean);
  const languages = [...new Set([...picked, ...csv("languages_other")])];
  const intake = {
    name: brand || category,
    market: { country: countryCandidates[0], languages: languages.length ? languages : ["en"] },
    product: { brand, parent_company: f.get("parent_company"),
               category, category_type: f.get("category_type") },
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
     results: viewResults, items: viewItems, analysis: viewAnalysis, intel: viewIntel,
     manual: viewManual, schedules: viewSchedules, export: viewExport }[State.view] || viewOverview)(div);
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
      ${stat("Brand", cfg.product.brand || "— (category-only study)")}
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
    <p class="muted">Chunkable by date — used for full-year extensive research.</p>
    <div class="table-wrap"><table><thead><tr><th>Lang</th><th>Structure</th><th>Query</th></tr></thead>
    <tbody>${(sp.google_news_feeds||[]).map(f =>
      `<tr><td>${esc(f.language)}</td><td>${esc(f.structure)}</td><td>${esc(f.query)}</td></tr>`).join("") ||
      `<tr><td colspan="3" class="muted">No feeds — add native-language keyword terms below.</td></tr>`}</tbody></table></div>
  </div>
  <div class="card"><h3>Bing News feeds (generated)</h3>
    <p class="muted">A second, independent index — catches sources Google News's crawl missed.
      No date-range support, so this runs once per collection (not chunked).</p>
    <div class="table-wrap"><table><thead><tr><th>Lang</th><th>Structure</th><th>Query</th></tr></thead>
    <tbody>${(sp.bing_news_feeds||[]).map(f =>
      `<tr><td>${esc(f.language)}</td><td>${esc(f.structure)}</td><td>${esc(f.query)}</td></tr>`).join("") ||
      `<tr><td colspan="3" class="muted">No feeds — add native-language keyword terms below.</td></tr>`}</tbody></table></div>
  </div>
  <div class="card"><h3>Keyword slots per language</h3>${keywordEditor()}</div>
  <div class="card"><h3>✨ Expand a term (AI)</h3>
    <p class="muted">A single narrow term (e.g. "coffee") hides everything adjacent to it:
      product variants (instant coffee, cold coffee, latte, cappuccino, americano...), real
      brand/shop names people search for instead (Starbucks, Costa Coffee...), and
      equivalents of all of that in this study's OTHER languages. Each one you add becomes
      its own keyword structure — its own feed, its own ~100-result ceiling — so this is
      also the main lever for a study's collectible volume, not just recall.</p>
    <div class="row">
      <label style="flex:1">Term to expand <span class="muted">defaults to the study's category</span>
        <input id="expand-term" value="${esc((State.project.config.product||{}).category||'')}" placeholder="e.g. coffee" /></label>
      <button id="expand-term-btn" style="align-self:flex-end;height:2.1rem">✨ Expand</button>
    </div>
    <div id="expand-results"></div>
  </div>
  <div class="card"><h3>✨ Discover local outlets (AI)</h3>
    <p class="muted">The market filter only keeps items whose outlet or text shows a signal
      they're in this market — but most real local outlets (Scroll.in, NDTV, ScoopWhoop...)
      don't carry the country's name in their own brand, unlike "Times of India"/"Indian
      Express". This finds real local outlets across news, business, tech, sports,
      lifestyle, culture, and regional/native-language press, so genuinely local coverage
      from them stops being wrongly dropped. Each one you add teaches the filter that
      outlet, market-wide — no feed changes, this only affects relevance filtering.</p>
    <button id="discover-outlets-btn">✨ Discover outlets for this market</button>
    <div id="discover-results"></div>
  </div>`;

  el("save-sources").addEventListener("click", saveSources);
  el("feed-health").addEventListener("click", runFeedHealth);
  el("suggest-sources").addEventListener("click", suggestSources);
  el("expand-term-btn").addEventListener("click", expandTerm);
  el("discover-outlets-btn").addEventListener("click", discoverOutlets);
}

// --------------------------------------------------------------------------- //
// AI source discovery
// --------------------------------------------------------------------------- //
async function suggestSources() {
  const box = el("suggest-results");
  const prod = State.project.config.product || {};
  box.innerHTML = `<div class="note">Asking Claude for candidate sources for
    <b>${esc(prod.brand || prod.category || '')}</b> in
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

// --------------------------------------------------------------------------- //
// AI term expansion
// --------------------------------------------------------------------------- //
async function expandTerm() {
  const term = (el("expand-term").value || "").trim();
  const box = el("expand-results");
  if (!term) { toast("Enter a term to expand", true); return; }
  box.innerHTML = `<div class="note">Asking Claude to expand "${esc(term)}" into variants,
    brands, and translations… (needs ANTHROPIC_API_KEY; ~10–20s)</div>`;
  try {
    const r = await api(`/api/projects/${State.projectId}/suggest-terms`, { method: "POST", body: { term } });
    renderExpansion(r);
  } catch (e) {
    box.innerHTML = `<div class="note">Could not expand term: ${esc(e.message)}
      ${/ANTHROPIC/i.test(e.message) ? "— set the key in .env and restart." : ""}</div>`;
  }
}

function renderExpansion(r) {
  const variantRows = (r.variants || []).map(v => `
    <label style="display:flex;gap:.5rem;align-items:center;font-weight:400;margin:.2rem 0">
      <input type="checkbox" data-exp-variant value="${esc(v)}" checked style="width:auto" />
      <span>${esc(v)}</span></label>`).join("");
  const brandRows = (r.brands || []).map(b => `
    <label style="display:flex;gap:.5rem;align-items:center;font-weight:400;margin:.2rem 0">
      <input type="checkbox" data-exp-brand value="${esc(b)}" checked style="width:auto" />
      <span>${esc(b)} <span class="muted">(also added as a competitor)</span></span></label>`).join("");
  const translationBlocks = Object.entries(r.translations || {}).map(([lang, entry]) => `
    <div style="margin:.4rem 0">
      <b>${esc(lang)}</b>
      ${entry.term ? `<label style="display:flex;gap:.5rem;align-items:center;font-weight:400;margin:.15rem 0 .15rem 1rem">
        <input type="checkbox" data-exp-translang="${esc(lang)}" value="${esc(entry.term)}" checked style="width:auto" />
        <span>${esc(entry.term)} <span class="muted">(base term)</span></span></label>` : ""}
      ${(entry.variants || []).map(v => `
        <label style="display:flex;gap:.5rem;align-items:center;font-weight:400;margin:.15rem 0 .15rem 1rem">
          <input type="checkbox" data-exp-transvar="${esc(lang)}" value="${esc(v)}" checked style="width:auto" />
          <span>${esc(v)}</span></label>`).join("")}
    </div>`).join("");

  el("expand-results").innerHTML = `<div class="card" style="border-color:var(--navy)">
    <div class="card-head"><h4>✨ Expansion of "${esc(r.term)}"</h4>
      <button id="apply-expand">Add checked to keywords</button></div>
    <p class="muted">AI-proposed — nothing is added until you click above. Uncheck anything
      irrelevant or wrong; a brand you check is also added to Competitors.</p>
    ${variantRows ? `<h5>Product variants (${(r.variants||[]).length})</h5>${variantRows}` : ""}
    ${brandRows ? `<h5 style="margin-top:.6rem">Real brands/shops in this market (${(r.brands||[]).length})</h5>${brandRows}` : ""}
    ${translationBlocks ? `<h5 style="margin-top:.6rem">Translations (${Object.keys(r.translations||{}).length} language(s))</h5>${translationBlocks}` : ""}
    ${!variantRows && !brandRows && !translationBlocks ? `<p class="muted">Nothing came back — try a different term.</p>` : ""}
  </div>`;
  el("apply-expand").addEventListener("click", () => applySelectedExpansion(r.term));
}

async function applySelectedExpansion(term) {
  const variants = Array.from(document.querySelectorAll("[data-exp-variant]:checked")).map(cb => cb.value);
  const brands = Array.from(document.querySelectorAll("[data-exp-brand]:checked")).map(cb => cb.value);
  const translations = {};
  document.querySelectorAll("[data-exp-translang]:checked").forEach(cb => {
    const lang = cb.dataset.expTranslang;
    (translations[lang] = translations[lang] || { term: "", variants: [] }).term = cb.value;
  });
  document.querySelectorAll("[data-exp-transvar]:checked").forEach(cb => {
    const lang = cb.dataset.expTransvar;
    const entry = (translations[lang] = translations[lang] || { term: "", variants: [] });
    entry.variants.push(cb.value);
  });
  try {
    const r = await api(`/api/projects/${State.projectId}/apply-terms`, {
      method: "POST", body: { term, variants, brands, translations },
    });
    toast(`Added — ${r.google_news_feeds} Google News + ${r.bing_news_feeds} Bing News feed(s) total now.`);
    State.project = await api(`/api/projects/${State.projectId}`);
    render();
  } catch (e) { toast(e.message, true); }
}

// --------------------------------------------------------------------------- //
// AI local-outlet discovery
// --------------------------------------------------------------------------- //
async function discoverOutlets() {
  const box = el("discover-results");
  box.innerHTML = `<div class="note">Asking Claude for real local outlets across news,
    business, tech, sports, lifestyle, and regional press for
    <b>${esc((State.project.config.market||{}).country||'')}</b>…
    (needs ANTHROPIC_API_KEY; ~10–20s)</div>`;
  try {
    const r = await api(`/api/projects/${State.projectId}/suggest-outlets`, { method: "POST" });
    renderOutletSuggestions(r);
  } catch (e) {
    box.innerHTML = `<div class="note">Could not discover outlets: ${esc(e.message)}
      ${/ANTHROPIC/i.test(e.message) ? "— set the key in .env and restart." : ""}</div>`;
  }
}

function renderOutletSuggestions(r) {
  const rows = (r.outlets || []).map(o => `
    <label style="display:flex;gap:.5rem;align-items:flex-start;font-weight:400;margin:.25rem 0">
      <input type="checkbox" data-outlet value="${esc(o.name)}" ${o.caution ? "" : "checked"} style="width:auto;margin-top:.2rem" />
      <span><b>${esc(o.name)}</b>
        ${o.caution ? '<span class="flag">⚠ short name — check before adding</span>' : ""}
        <span class="badge neu">${esc(o.category || "—")}</span>
        <span class="badge neu">${esc(o.language || "—")}</span>
        <br><span class="muted">${esc(o.domain || "")}${o.why ? " — " + esc(o.why) : ""}</span></span>
    </label>`).join("");

  const s = r._summary || {};
  el("discover-results").innerHTML = `<div class="card" style="border-color:var(--navy)">
    <div class="card-head"><h4>✨ ${s.total || 0} local outlets found</h4>
      <button id="apply-outlets">Add checked to market terms</button></div>
    <p class="muted">AI-proposed — nothing is added until you click above.
      ${s.caution ? `${s.caution} short name(s) are unchecked by default — a brief name
      that's also a common word is safer to review before trusting at scale.` : ""}</p>
    ${rows || `<p class="muted">Nothing came back — try again in a moment.</p>`}
  </div>`;
  const btn = el("apply-outlets");
  if (btn) btn.addEventListener("click", applySelectedOutlets);
}

async function applySelectedOutlets() {
  const names = Array.from(document.querySelectorAll("[data-outlet]:checked")).map(cb => cb.value);
  try {
    const r = await api(`/api/projects/${State.projectId}/apply-outlets`, {
      method: "POST", body: { names },
    });
    toast(`Added ${names.length} outlet(s) — ${r.market_terms_count} market term(s) total now.`);
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
  try {
    await api(`/api/projects/${State.projectId}/config`, { method: "PUT", body: { config: cfg } });
    // Editing keywords alone does NOT update the feed list the News scraper reads at
    // collect time (PUT .../config just stores whatever JSON it's given) — this call
    // recomputes source_plan.google_news_feeds/bing_news_feeds from what was just saved.
    const r = await api(`/api/projects/${State.projectId}/regenerate-feeds`, { method: "POST" });
    toast(`Config saved — ${r.google_news_feeds} Google News + ${r.bing_news_feeds} Bing News feed(s) regenerated.`);
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
        <label style="font-weight:400;display:inline-block;margin-right:1rem"><input type="checkbox" class="ext-ch" value="news" checked style="width:auto"/> News (Google + Bing)</label>
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
// Results dashboard (DESIGN_01_category-discovery.md §12) — volume by channel/
// site, the Access & Reliability panel (source_health), and the site-intelligence
// learning ledger's real, cross-project track record for this study's category.
// --------------------------------------------------------------------------- //
async function viewResults(root) {
  root.innerHTML = helpBox("results") + `
    <div class="card"><h3>Volume by channel</h3><div id="res-channels" class="grid"><span class="muted">Loading…</span></div></div>
    <div class="card"><h3>Top sites (generic-site discovery)</h3><div id="res-domains"></div></div>
    <div class="card"><h3>Access &amp; reliability</h3>
      <p class="muted">Sources auto-paused after repeated failures — never retried forever, never
        silently dropped (DESIGN_01 §7.4).</p>
      <div id="res-health"></div></div>
    <div class="card"><h3>Site intelligence — what this category has learned so far</h3>
      <p class="muted">The cross-project ledger for "<b id="res-category"></b>": every real site any
        study has ever tried for this category, with its accumulated track record. This is the
        literal output of the learning mechanism (DESIGN_01 §4b) — not just this study's own runs.</p>
      <div id="res-ledger"></div></div>`;

  const [byChannel, byDomain, health, ledger] = await Promise.all([
    api(`/api/projects/${State.projectId}/analytics/items_by_channel`),
    api(`/api/projects/${State.projectId}/analytics/items_by_domain`),
    api(`/api/projects/${State.projectId}/source-health`),
    api(`/api/projects/${State.projectId}/site-intelligence`),
  ]);

  el("res-channels").innerHTML = byChannel.data.length
    ? byChannel.data.map(c => stat(c.channel, `${c.n} (${c.analyzed_n} analyzed)`)).join("")
    : `<p class="muted">Nothing collected yet — run a channel from the Collect tab.</p>`;

  el("res-domains").innerHTML = byDomain.domains.length
    ? `<div class="table-wrap"><table><thead><tr><th>Domain</th><th>Items collected</th></tr></thead>
      <tbody>${byDomain.domains.map(d => `<tr><td>${esc(d.domain)}</td><td>${d.n}</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="muted">No generic-site items collected yet.</p>`;

  el("res-health").innerHTML = health.length
    ? `<div class="table-wrap"><table><thead><tr><th>Domain</th><th>Consecutive failures</th>
        <th>Paused</th><th>Last status</th><th>Last checked</th></tr></thead>
      <tbody>${health.map(h => `<tr><td>${esc(h.domain)}</td><td>${h.consecutive_failures}</td>
        <td>${h.paused ? '<span class="badge tier3">paused</span>' : '<span class="badge tier1">active</span>'}</td>
        <td class="muted">${esc(h.last_status || "")}</td>
        <td class="muted">${esc((h.last_checked_at || "").slice(0, 19))}</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="muted">No source-health history yet for this project.</p>`;

  el("res-category").textContent = ledger.category || "(no category set)";
  el("res-ledger").innerHTML = ledger.sites.length
    ? `<div class="table-wrap"><table><thead><tr><th>Domain</th><th>Times used</th>
        <th>Kept / dropped</th><th>Confidence</th><th>Blocked</th><th>Status</th></tr></thead>
      <tbody>${ledger.sites.map(s => `<tr><td>${esc(s.domain)}</td><td>${s.times_used}</td>
        <td>${s.items_kept} / ${s.items_dropped}</td>
        <td>${s.confidence == null ? "—" : Math.round(s.confidence * 100) + "%"}</td>
        <td>${s.times_blocked}</td>
        <td>${s.validated_by_human ? '<span class="badge tier1">human-validated</span>'
          : (s.times_used >= 3 && s.confidence >= 0.5) ? '<span class="badge tier1">auto-trusted</span>'
          : '<span class="needs-badge">needs validation</span>'}</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="muted">No sites in the ledger for this category yet — run the AI-guided study wizard's site discovery step, or collect via the generic-site pipeline first.</p>`;
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
  root.innerHTML = `<div class="card"><span class="muted">Loading…</span></div>`;
  const hasKey = State.health && State.health.keys && State.health.keys.anthropic;
  // Fetch fresh rather than reading the cached State.dash (only updated on project load /
  // after a collect or analyze job finishes) — reading the cache here let this panel say
  // "No items to analyze yet" and disable the Analyze buttons even when items genuinely
  // existed, simply because the cache hadn't been refreshed since they were collected.
  const dash = await api(`/api/projects/${State.projectId}/dashboard`);
  State.dash = dash;
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
async function viewExport(root) {
  root.innerHTML = `<div class="card"><span class="muted">Loading…</span></div>`;
  // Fetch fresh rather than reading the cached State.dash — same staleness bug as
  // viewAnalysis (see its comment): this readiness banner could show "no collected
  // items" even when items genuinely existed, just because nothing had refreshed the
  // cache since Collect ran.
  const dash = await api(`/api/projects/${State.projectId}/dashboard`);
  State.dash = dash;
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

// --------------------------------------------------------------------------- //
// AI-guided discovery wizard (DESIGN_01_category-discovery.md §12)
//
// Each step is client-side wizard state only — nothing is persisted as a real
// project until the final "Launch study" click calls /api/discovery/launch-study.
// Steps 4 (sites) is skipped automatically when no selected source type routes to
// generic_site_discovery — everything else (News, Reddit, ...) already has its own
// established collection mechanism and needs no site discovery here.
// --------------------------------------------------------------------------- //
function discDefaults() {
  return {
    step: 0,
    stepNames: ["Term & geo", "Category", "Languages", "Source types", "Sites", "Brand terms", "Launch"],
    term: "", brand: "", category_type: "other",
    geoLevel: "country", geoValue: "", geoCountry: "",
    category: "", confidence: null, reasoning: "", needsConfirmation: false,
    languages: [], selectedLanguages: new Set(),
    sourceTypes: [], selectedSourceTypes: new Set(),
    sites: [], selectedDomains: new Set(),
    termSuggestions: null, selectedVariants: new Set(), selectedBrands: new Set(),
    volumeCap: 500, runDaily: false,
    busy: false,
  };
}
let Disc = discDefaults();

function openDiscoveryWizard() {
  Disc = discDefaults();
  el("discovery-modal").classList.remove("hidden");
  renderDiscStep();
}
el("new-discovery-btn").addEventListener("click", openDiscoveryWizard);
document.querySelectorAll("[data-close-discovery]").forEach(b => b.addEventListener("click", () =>
  el("discovery-modal").classList.add("hidden")));

function discGeoScope() {
  if (!Disc.geoValue.trim()) return null;
  const country = Disc.geoLevel === "country" ? Disc.geoValue.trim() : Disc.geoCountry.trim();
  if (!country) return null;
  return { level: Disc.geoLevel, value: Disc.geoValue.trim(), country };
}

function discDotsHtml() {
  return Disc.stepNames.map((s, i) => {
    const cls = i < Disc.step ? "done" : i === Disc.step ? "current" : "";
    return `<div class="disc-dot ${cls}">${i + 1}. ${esc(s)}</div>`;
  }).join("");
}

function renderDiscStep() {
  el("discovery-error").textContent = "";
  el("discovery-steps").innerHTML = discDotsHtml();
  el("disc-back").disabled = Disc.step === 0 || Disc.busy;
  el("disc-next").disabled = Disc.busy;
  el("disc-next").textContent = Disc.busy ? "Working…"
    : Disc.step === Disc.stepNames.length - 1 ? "Launch study" : "Next";
  const body = el("discovery-body");
  const renderers = [discStep0, discStep1, discStep2, discStep3, discStep4, discStep5, discStep6];
  renderers[Disc.step](body);
}

// IMPORTANT: this must NOT re-render the step body. The click handler calls this
// BEFORE reading the current step's live form values into Disc — a full re-render
// here would rebuild those inputs from (still-stale) Disc state and silently wipe
// out whatever the user just typed before discAdvanceFromN() ever gets to read it.
// (Found live: the term field appeared to "not save" on every single Next click.)
function discSetBusy(isBusy) {
  Disc.busy = isBusy;
  el("disc-back").disabled = isBusy || Disc.step === 0;
  el("disc-next").disabled = isBusy;
  el("disc-next").textContent = isBusy ? "Working…"
    : Disc.step === Disc.stepNames.length - 1 ? "Launch study" : "Next";
}
function discFail(err) { Disc.busy = false; renderDiscStep(); el("discovery-error").textContent = err.message || String(err); }

// --- Step 0: term + geo-scope ------------------------------------------------
function discStep0(body) {
  body.innerHTML = `
    <label>What are you researching? <input id="d-term" placeholder="e.g. coffee, two-wheeler insurance" value="${esc(Disc.term)}" /></label>
    <label>Brand name (optional) <input id="d-brand" placeholder="e.g. Acme Cola" value="${esc(Disc.brand)}" /></label>
    <label>Geo-scope level
      <select id="d-geolevel">
        <option value="country">Country</option>
        <option value="state">State / province</option>
        <option value="region">Region</option>
        <option value="city">City</option>
      </select></label>
    <label id="d-geovalue-label">Country <input id="d-geovalue" placeholder="e.g. India" value="${esc(Disc.geoValue)}" /></label>
    <label id="d-geocountry-wrap" class="hidden">Which country is that in?
      <input id="d-geocountry" placeholder="e.g. India" value="${esc(Disc.geoCountry)}" /></label>
    <p class="muted">A city/state/region study still needs its country named, so market facts
      (currency, language defaults, etc.) resolve correctly.</p>`;
  const levelSel = el("d-geolevel"); levelSel.value = Disc.geoLevel;
  function syncGeoLabels() {
    const lvl = levelSel.value;
    el("d-geovalue-label").firstChild.textContent =
      (lvl === "country" ? "Country " : lvl === "state" ? "State / province " :
       lvl === "region" ? "Region " : "City ");
    el("d-geocountry-wrap").classList.toggle("hidden", lvl === "country");
  }
  syncGeoLabels();
  levelSel.addEventListener("change", syncGeoLabels);
}

async function discAdvanceFrom0() {
  Disc.term = el("d-term").value.trim();
  Disc.brand = el("d-brand").value.trim();
  Disc.geoLevel = el("d-geolevel").value;
  Disc.geoValue = el("d-geovalue").value.trim();
  Disc.geoCountry = Disc.geoLevel === "country" ? Disc.geoValue : el("d-geocountry").value.trim();
  if (!Disc.term) throw new Error("Tell us what you're researching (a product, category, or topic).");
  if (!Disc.geoValue) throw new Error("Geo-scope value is required.");
  if (Disc.geoLevel !== "country" && !Disc.geoCountry) throw new Error("That location's country is required.");
  const r = await api("/api/discovery/classify-category", { method: "POST",
    body: { term: Disc.term, geo_scope: discGeoScope() } });
  Disc.category = r.category; Disc.confidence = r.confidence;
  Disc.reasoning = r.reasoning; Disc.needsConfirmation = r.needs_confirmation;
}

// --- Step 1: confirm category -------------------------------------------------
function discStep1(body) {
  const confCls = Disc.confidence >= 0.8 ? "confidence-hi" : "confidence-lo";
  body.innerHTML = `
    <p>AI classification of "<b>${esc(Disc.term)}</b>":</p>
    <label>Category <input id="d-category" value="${esc(Disc.category)}" /></label>
    <p class="muted">Confidence: <span class="${confCls}">${Math.round((Disc.confidence || 0) * 100)}%</span></p>
    <p class="muted">${esc(Disc.reasoning || "")}</p>
    ${Disc.needsConfirmation ? '<div class="note">The model flagged this as a lower-confidence guess — please check the category text above before continuing.</div>' : ""}`;
}

async function discAdvanceFrom1() {
  Disc.category = el("d-category").value.trim();
  if (!Disc.category) throw new Error("Category is required.");
  const r = await api("/api/discovery/suggest-languages", { method: "POST",
    body: { category: Disc.category, geo_scope: discGeoScope() } });
  Disc.languages = r.languages;
  Disc.selectedLanguages = new Set(r.languages.map(l => l.code));
}

// --- Step 2: languages (blocks on explicit confirmation, §11) ---------------
function discStep2(body) {
  if (!Disc.languages.length) {
    body.innerHTML = `<p class="muted">No languages suggested — add at least one code manually.</p>
      <label>Language code <input id="d-lang-manual" placeholder="e.g. en" /></label>`;
    return;
  }
  body.innerHTML = `<p>Confirm which languages this study should cover:</p>
    <div class="pick-list">${Disc.languages.map(l => `
      <label class="pick-row"><input type="checkbox" data-lang="${esc(l.code)}" ${Disc.selectedLanguages.has(l.code) ? "checked" : ""} />
        <div class="pick-main"><div class="pick-name">${esc(l.name || l.code)} (${esc(l.code)})${l.known ? "" : ' <span class="badge neu">unrecognized code</span>'}</div>
        <div class="pick-why">${esc(l.why || "")}</div></div></label>`).join("")}</div>
    <label>Add another code (optional) <input id="d-lang-manual" placeholder="e.g. te" /></label>`;
  body.querySelectorAll("[data-lang]").forEach(cb => cb.addEventListener("change", () => {
    if (cb.checked) Disc.selectedLanguages.add(cb.dataset.lang); else Disc.selectedLanguages.delete(cb.dataset.lang);
  }));
}

async function discAdvanceFrom2() {
  const manual = (el("d-lang-manual")?.value || "").trim();
  if (manual) Disc.selectedLanguages.add(manual);
  if (Disc.selectedLanguages.size === 0) throw new Error("Select or add at least one language.");
  const r = await api("/api/discovery/suggest-source-types", { method: "POST",
    body: { category: Disc.category, geo_scope: discGeoScope() } });
  Disc.sourceTypes = r.source_types;
  // Tier-3/app-only platforms (Instagram, WhatsApp, ...) are shown but never
  // pre-selected -- there is no real mechanism to collect from them (CLAUDE.md's
  // documented, permanent gap), so a wizard defaulting them "on" would misleadingly
  // suggest this study will cover them.
  Disc.selectedSourceTypes = new Set(r.source_types.filter(s => s.strategy !== "unsupported").map(s => s.name));
}

// --- Step 3: source types (Layer 1 + Layer 2 routing, §2) -------------------
function discStep3(body) {
  if (!Disc.sourceTypes.length) {
    body.innerHTML = `<p class="muted">No source types suggested for this category.</p>`;
    return;
  }
  body.innerHTML = `<p>Which kinds of sources should this study collect from?</p>
    <div class="pick-list">${Disc.sourceTypes.map(s => {
      const unsupported = s.strategy === "unsupported";
      const badge = s.strategy === "existing_channel" ? `<span class="badge tier1">${esc(s.channel)} channel</span>`
        : unsupported ? '<span class="badge tier3">not supported</span>'
        : '<span class="badge tier2">new: site discovery</span>';
      return `<label class="pick-row"><input type="checkbox" data-st="${esc(s.name)}"
          ${Disc.selectedSourceTypes.has(s.name) ? "checked" : ""} ${unsupported ? "disabled" : ""} />
        <div class="pick-main"><div class="pick-name">${esc(s.name)} ${badge}</div>
        <div class="pick-why">${esc(s.why || "")}${unsupported
          ? " — app-only/anti-automation platform; MarketLens has no way to collect from this (documented gap, not a bug)." : ""}</div></div></label>`;
    }).join("")}</div>`;
  body.querySelectorAll("[data-st]:not(:disabled)").forEach(cb => cb.addEventListener("change", () => {
    if (cb.checked) Disc.selectedSourceTypes.add(cb.dataset.st); else Disc.selectedSourceTypes.delete(cb.dataset.st);
  }));
}

function discHasGenericSiteType() {
  return Disc.sourceTypes.some(s => Disc.selectedSourceTypes.has(s.name) && s.strategy === "generic_site_discovery");
}

async function discAdvanceFrom3() {
  if (Disc.selectedSourceTypes.size === 0) throw new Error("Select at least one source type.");
  if (discHasGenericSiteType()) {
    const r = await api("/api/discovery/sites", { method: "POST",
      body: { category: Disc.category, geo_scope: discGeoScope() } });
    Disc.sites = r.sites;
    Disc.selectedDomains = new Set(r.sites.filter(s => !s.needs_validation).map(s => s.domain));
  } else {
    Disc.sites = []; Disc.selectedDomains = new Set();
    Disc.step++;  // skip the sites step entirely — nothing selected routes to it
  }
}

// --- Step 4: sites (only reached when a generic-site source type was picked) -
function discStep4(body) {
  if (!Disc.sites.length) {
    body.innerHTML = `<p class="muted">No candidate sites found for this category/market.</p>`;
    return;
  }
  body.innerHTML = `<p>Confirm which real sites to actually collect from. Sites with a proven
    track record are pre-checked; new/unverified ones need your explicit OK.</p>
    <div class="pick-list">${Disc.sites.map(s => `
      <label class="pick-row"><input type="checkbox" data-site="${esc(s.domain)}" ${Disc.selectedDomains.has(s.domain) ? "checked" : ""} />
        <div class="pick-main"><div class="pick-name">${esc(s.name || s.domain)} <span class="muted">(${esc(s.domain)})</span>
          ${s.known ? '<span class="badge tier1">known</span>' : ""}
          ${s.needs_validation ? '<span class="needs-badge">needs validation</span>' : ""}
          ${s.validated_by_human ? '<span class="badge tier1">human-validated</span>' : ""}</div>
        <div class="pick-why">${esc(s.why || "")}${s.times_used ? ` · used ${s.times_used}× before, confidence ${Math.round((s.confidence || 0) * 100)}%` : ""}</div></div></label>`).join("")}</div>`;
  body.querySelectorAll("[data-site]").forEach(cb => cb.addEventListener("change", () => {
    if (cb.checked) Disc.selectedDomains.add(cb.dataset.site); else Disc.selectedDomains.delete(cb.dataset.site);
  }));
}

async function discAdvanceFrom4() {
  const draftCfg = {
    market: { country: Disc.geoCountry, languages: [...Disc.selectedLanguages] },
    product: { brand: Disc.brand, category: Disc.category, category_type: Disc.category_type },
    relevance_terms: [Disc.category],
  };
  const r = await api("/api/discovery/suggest-terms-draft", { method: "POST",
    body: { cfg: draftCfg, term: Disc.category } });
  Disc.termSuggestions = r;
  Disc.selectedVariants = new Set(r.variants || []);
  Disc.selectedBrands = new Set(r.brands || []);
}

// --- Step 5: brand/term expansion (reuses term_expansion.py unchanged) ------
function discStep5(body) {
  const t = Disc.termSuggestions;
  if (!t || (!t.variants?.length && !t.brands?.length)) {
    body.innerHTML = `<p class="muted">No additional variants/brands suggested — you can add
      competitors later from the Source plan tab.</p>`;
    return;
  }
  const rows = (list, prefix, selectedSet) => list.map(v => `
    <label class="pick-row"><input type="checkbox" data-${prefix}="${esc(v)}" ${selectedSet.has(v) ? "checked" : ""} />
      <div class="pick-main"><div class="pick-name">${esc(v)}</div></div></label>`).join("");
  body.innerHTML = `
    ${t.variants?.length ? `<p>Product variants / real search terms to also track:</p><div class="pick-list">${rows(t.variants, "variant", Disc.selectedVariants)}</div>` : ""}
    ${t.brands?.length ? `<p>Real competitor brands found:</p><div class="pick-list">${rows(t.brands, "brand", Disc.selectedBrands)}</div>` : ""}`;
  body.querySelectorAll("[data-variant]").forEach(cb => cb.addEventListener("change", () => {
    if (cb.checked) Disc.selectedVariants.add(cb.dataset.variant); else Disc.selectedVariants.delete(cb.dataset.variant);
  }));
  body.querySelectorAll("[data-brand]").forEach(cb => cb.addEventListener("change", () => {
    if (cb.checked) Disc.selectedBrands.add(cb.dataset.brand); else Disc.selectedBrands.delete(cb.dataset.brand);
  }));
}

async function discAdvanceFrom5() { /* nothing to fetch — step 6 is the review/launch screen */ }

// --- Step 6: review & launch --------------------------------------------------
function discStep6(body) {
  const genericDomains = [...Disc.selectedDomains];
  body.innerHTML = `
    <div class="card">
      <p><b>Category:</b> ${esc(Disc.category)}</p>
      <p><b>Geo-scope:</b> ${esc(Disc.geoLevel)} — ${esc(Disc.geoValue)} (${esc(Disc.geoCountry)})</p>
      <p><b>Languages:</b> ${[...Disc.selectedLanguages].map(esc).join(", ")}</p>
      <p><b>Source types:</b> ${[...Disc.selectedSourceTypes].map(esc).join(", ")}</p>
      ${genericDomains.length ? `<p><b>Sites to collect from:</b> ${genericDomains.map(esc).join(", ")}</p>` : ""}
    </div>
    <label>Per-source volume cap <input id="d-volcap" type="number" min="10" value="${Disc.volumeCap}" /></label>
    <label><input type="checkbox" id="d-daily" ${Disc.runDaily ? "checked" : ""} style="width:auto;display:inline-block;margin-right:.4rem" />
      Also run this as a standing daily job</label>
    ${Disc.runDaily ? '<div class="note">Daily scheduling isn\'t wired up yet — this just records the intent; you\'ll need to re-run the backfill manually for now.</div>' : ""}
    ${genericDomains.length ? '<p class="muted">Clicking Launch confirms these sites into the shared site-intelligence ledger and starts a real backfill job in the background — you can watch its progress in the Run log tab once the study opens.</p>' : ""}`;
  el("d-daily").addEventListener("change", (e) => { Disc.runDaily = e.target.checked; });
}

async function discLaunch() {
  Disc.volumeCap = parseInt(el("d-volcap").value || "500", 10);
  const intake = {
    name: Disc.brand || Disc.category,
    market: { country: Disc.geoCountry, languages: [...Disc.selectedLanguages],
             geo_scope: discGeoScope() },
    product: { brand: Disc.brand, category: Disc.category, category_type: Disc.category_type },
    competitors: [...Disc.selectedBrands],
    keywords: { trend_terms: [] },
  };
  const payload = {
    intake, generic_site_domains: [...Disc.selectedDomains],
    keywords: [Disc.category, ...Disc.selectedVariants],
    volume_cap: Disc.volumeCap, run_daily: Disc.runDaily,
  };
  if (Disc.termSuggestions && (Disc.selectedVariants.size || Disc.selectedBrands.size)) {
    payload.term_expansion = { term: Disc.category, variants: [...Disc.selectedVariants],
      brands: [...Disc.selectedBrands], translations: Disc.termSuggestions.translations || {} };
  }
  const r = await api("/api/discovery/launch-study", { method: "POST", body: payload });
  el("discovery-modal").classList.add("hidden");
  State.projectId = r.project_id;
  toast(r.run_id ? `Study "${r.name}" launched — collection running in the background`
                : `Study "${r.name}" created`);
  await loadProjects();
  switchView(r.run_id ? "runlog" : "collect");
}

const discAdvancers = [discAdvanceFrom0, discAdvanceFrom1, discAdvanceFrom2, discAdvanceFrom3,
                       discAdvanceFrom4, discAdvanceFrom5];

el("disc-next").addEventListener("click", async () => {
  if (Disc.step === Disc.stepNames.length - 1) {
    discSetBusy(true);
    try { await discLaunch(); } catch (e) { discFail(e); }
    return;
  }
  discSetBusy(true);
  try {
    const before = Disc.step;
    await discAdvancers[Disc.step]();
    if (Disc.step === before) Disc.step++;  // an advancer may itself skip a step (see step 3)
    Disc.busy = false;
    renderDiscStep();
  } catch (e) { discFail(e); }
});

el("disc-back").addEventListener("click", () => {
  if (Disc.step === 0) return;
  Disc.step--;
  if (Disc.step === 4 && !Disc.sites.length && !discHasGenericSiteType()) Disc.step--;  // skip sites going back too
  renderDiscStep();
});

boot().catch(e => console.error(e));
