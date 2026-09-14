// Small, shared presentational pieces used across every view -- kept dependency-free
// (no prop-types lib, no styling lib) to match the rest of this codebase's philosophy
// of using only what's needed. Icons are lucide-react throughout, for one consistent
// icon language instead of ad hoc emoji (kept only where they already read as a
// deliberate convention, e.g. ✨ for AI-assisted actions).
import { Inbox } from 'lucide-react'

export function Card({ title, headExtra, className = '', children }) {
  return (
    <div className={`card ${className}`.trim()}>
      {title && (
        <div className="card-head">
          <h2>{title}</h2>
          {headExtra}
        </div>
      )}
      {children}
    </div>
  )
}

export function Stat({ lbl, num, icon: Icon, tone = 'primary' }) {
  return (
    <div className="stat">
      {Icon && <div className={`stat-icon tone-${tone}`}><Icon size={16} strokeWidth={2.2} /></div>}
      <div className="num">{num}</div>
      <div className="lbl">{lbl}</div>
    </div>
  )
}

export function Badge({ kind = 'neu', children }) {
  return <span className={`badge ${kind}`}>{children}</span>
}

// A single, consistent "nothing here yet" treatment instead of a bare <p class="muted">
// scattered ad hoc per view -- this is exactly the kind of finishing touch that was
// missing (real feedback: "too plain / not enough visual polish").
export function EmptyState({ icon: Icon = Inbox, title, hint }) {
  return (
    <div className="empty-state">
      <Icon size={28} strokeWidth={1.6} />
      <div className="empty-title">{title}</div>
      {hint && <div className="muted">{hint}</div>}
    </div>
  )
}

// Shimmering placeholder blocks instead of a plain "Loading…" line. `rows` renders
// that many full-width lines; `grid` renders stat-tile-shaped blocks instead.
export function Skeleton({ rows = 3, grid = false }) {
  if (grid) {
    return (
      <div className="grid">
        {Array.from({ length: rows }).map((_, i) => <div className="skeleton skeleton-tile" key={i} />)}
      </div>
    )
  }
  return (
    <div className="skeleton-stack">
      {Array.from({ length: rows }).map((_, i) => <div className="skeleton skeleton-line" key={i} />)}
    </div>
  )
}

const HELP = {
  overview: 'Your study at a glance. Follow the four numbered steps above — they must be done in order.',
  sources: '<b>Step 1.</b> Tell MarketLens <i>where</i> to look: paste RSS / e-commerce / forum URLs, edit the per-language keyword slots, then <b>Save config</b>. This does <b>not</b> collect anything — that happens in Collect.',
  collect: '<b>Step 2.</b> Run scrapers to gather data. Channels tagged <span class="ready-badge">ready</span> work immediately; others need a key or URLs. Jobs run one at a time. Start with News, Reddit, and GDELT.',
  runlog: 'The full audit trail of every run — including honest failures (blocked sites, rate limits). Nothing is ever fabricated.',
  results: 'Where the data actually came from and how reliable it\'s been: volume by channel and by site, sources currently paused after repeated failures, and what the cross-project site-intelligence ledger has learned so far for this category.',
  items: 'Every collected item, one row each, with its analysis tags. Search and filter here — e.g. set <b>Brand focus = target brand</b> to hide off-topic noise, or <b>Sentiment = negative</b> to read complaints.',
  analysis: '<b>Step 3.</b> Tag every collected item with sentiment, an English summary, purchase drivers, and themes. <b>Requires ANTHROPIC_API_KEY.</b> Safe to click again — already-tagged items are skipped.',
  intel: 'Human-entered market facts (size, share, GDP…). Every entry needs a full citation. Optional, but it enriches the report\'s Market Overview.',
  manual: 'Ad-library research for platforms that block automation: open the pre-built deep links, then record what you see. Tier-3 platforms are documented as gaps.',
  schedules: 'Automate recurring collection (e.g. a weekly news pull). Each run is a normal, audited run.',
  export: '<b>Step 4.</b> Build the client Excel workbook and the report draft. Do <b>Collect + Analyze first</b> — without analysis the workbook has raw items but no sentiment/summary columns.',
}

export function HelpBox({ view }) {
  const html = HELP[view]
  if (!html) return null
  // eslint-disable-next-line react/no-danger -- fixed, developer-authored strings only
  return <div className="help" dangerouslySetInnerHTML={{ __html: html }} />
}

export function esc(s) {
  return String(s == null ? '' : s)
}
