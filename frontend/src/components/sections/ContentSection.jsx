import { useState } from 'react'
import { monthLabel } from '../../utils'

// Known columns keep a fixed order/label; any other "<name>_files" column
// from Notion is shown after them automatically.
const KNOWN = [
  { key: 'of_files',      label: 'OF' },
  { key: 'reddit_files',  label: 'Reddit' },
  { key: 'twitter_files', label: 'Twitter' },
  { key: 'fansly_files',  label: 'Fansly' },
  { key: 'tango_files',   label: 'Tango' },
  { key: 'social_files',  label: 'Social' },
  { key: 'request_files', label: 'Request' },
]

function fields(data) {
  const known = new Set(KNOWN.map(f => f.key))
  const extra = Object.keys(data || {})
    .filter(k => k.endsWith('_files') && !known.has(k))
    .sort()
    .map(k => {
      const name = k.slice(0, -'_files'.length).replace(/_/g, ' ')
      return { key: k, label: name.charAt(0).toUpperCase() + name.slice(1) }
    })
  return [...KNOWN, ...extra]
}

function totalFiles(data) {
  if (!data) return 0
  const sum = fields(data).reduce((s, f) => s + (data[f.key] || 0), 0)
  return sum || (data.total || 0)
}

function StatGrid({ data, failed }) {
  if (failed) return <p className="empty section-failed">⚠ Failed to load</p>
  const nonZero = fields(data).filter(f => (data?.[f.key] || 0) > 0)
  if (!nonZero.length) {
    return data?.total > 0
      ? <p className="empty">{data.total} files (no breakdown)</p>
      : <p className="empty">No data</p>
  }
  return (
    <div className="stat-grid">
      {nonZero.map(f => (
        <div key={f.key} className="stat-card">
          <div className="stat-label">{f.label}</div>
          <div className="stat-value">{data[f.key]}</div>
        </div>
      ))}
    </div>
  )
}

function HistoryMonth({ month, data, failed }) {
  const [open, setOpen] = useState(false)
  const total = totalFiles(data)
  return (
    <div className="history-month">
      <button className="history-month-btn" onClick={() => setOpen(o => !o)}>
        <span className="history-month-name">{monthLabel(month)}</span>
        <span className="history-month-right">
          <span className="history-month-total">{failed ? '⚠' : `${total} files`}</span>
          <span className="history-chevron">{open ? '↑' : '↓'}</span>
        </span>
      </button>
      {open && <div className="history-month-body"><StatGrid data={data} failed={failed} /></div>}
    </div>
  )
}

export default function ContentSection({ card }) {
  const total = totalFiles(card.content_current)
  const history = card.content_history || []
  const failed = card.failed || []

  return (
    <div className="section">
      <div className="section-title">Content</div>

      <div className="history-month-current">
        <span className="history-month-name">{monthLabel(card.current_month)}</span>
        <span className="history-month-right">
          <span className="content-current-badge">current</span>
          <span className="history-month-total">{total} files</span>
        </span>
      </div>
      <div className="history-month-body">
        <StatGrid data={card.content_current} failed={failed.includes('content')} />
      </div>

      {history.length > 0 && (
        <>
          <div className="history-section-label">History</div>
          {history.map(h => (
            <HistoryMonth key={h.month} month={h.month} data={h.data} failed={failed.includes(`content:${h.month}`)} />
          ))}
        </>
      )}
    </div>
  )
}
