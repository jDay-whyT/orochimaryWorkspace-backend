const FIELDS = [
  { key: 'of_files',      label: 'OF' },
  { key: 'reddit_files',  label: 'Reddit' },
  { key: 'twitter_files', label: 'Twitter' },
  { key: 'fansly_files',  label: 'Fansly' },
  { key: 'social_files',  label: 'Social' },
  { key: 'request_files', label: 'Request' },
]

function monthLabel(yyyyMm) {
  if (!yyyyMm) return ''
  const [y, m] = yyyyMm.split('-')
  return new Date(+y, +m - 1, 1).toLocaleString('en', { month: 'short', year: 'numeric' })
}

function StatGrid({ data }) {
  const nonZero = FIELDS.filter((f) => (data?.[f.key] || 0) > 0)
  if (!nonZero.length) return <p className="empty">No data</p>
  return (
    <div className="stat-grid">
      {nonZero.map((f) => (
        <div key={f.key} className="stat-card">
          <div className="stat-label">{f.label}</div>
          <div className="stat-value">{data[f.key]}</div>
        </div>
      ))}
    </div>
  )
}

export default function ContentSection({ card }) {
  return (
    <div className="section">
      <div className="section-title">Content</div>
      <div className="month-label">{monthLabel(card.current_month)}</div>
      <StatGrid data={card.content_current} />
      <div className="month-label">{monthLabel(card.prev_month)}</div>
      <StatGrid data={card.content_prev} />
    </div>
  )
}
