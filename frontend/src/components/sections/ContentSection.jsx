import { useState } from 'react'
import { monthLabel } from '../../utils'

const FIELDS = [
  { key: 'of_files',      label: 'OF' },
  { key: 'reddit_files',  label: 'Reddit' },
  { key: 'twitter_files', label: 'Twitter' },
  { key: 'fansly_files',  label: 'Fansly' },
  { key: 'social_files',  label: 'Social' },
  { key: 'request_files', label: 'Request' },
]


function totalFiles(data) {
  if (!data) return 0
  const sum = FIELDS.reduce((s, f) => s + (data[f.key] || 0), 0)
  return sum || (data.total || 0)
}

function StatGrid({ data }) {
  const nonZero = FIELDS.filter(f => (data?.[f.key] || 0) > 0)
  if (!nonZero.length) return <p className="empty">No data</p>
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

function HistoryMonth({ month, data }) {
  const [open, setOpen] = useState(false)
  const total = totalFiles(data)
  return (
    <div className="history-month">
      <button className="history-month-btn" onClick={() => setOpen(o => !o)}>
        <span className="history-month-name">{monthLabel(month)}</span>
        <span className="history-month-right">
          <span className="history-month-total">{total} files</span>
          <span className="history-chevron">{open ? '↑' : '↓'}</span>
        </span>
      </button>
      {open && <div className="history-month-body"><StatGrid data={data} /></div>}
    </div>
  )
}

export default function ContentSection({ card }) {
  const total = totalFiles(card.content_current)
  const history = card.content_history || []

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
        <StatGrid data={card.content_current} />
      </div>

      {history.length > 0 && (
        <>
          <div className="history-section-label">History</div>
          {history.map(h => (
            <HistoryMonth key={h.month} month={h.month} data={h.data} />
          ))}
        </>
      )}
    </div>
  )
}
