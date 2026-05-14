const MONTHS = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']

function formatDate(iso) {
  if (!iso) return '—'
  const [, m, d] = iso.split('-')
  return `${+d} ${MONTHS[+m - 1]}`
}

function statusClass(status) {
  const s = (status || '').toLowerCase()
  if (s === 'planned')    return 'shoot-status-planned'
  if (s === 'done')       return 'shoot-status-done'
  if (s === 'rescheduled')return 'shoot-status-rescheduled'
  if (s === 'cancelled')  return 'shoot-status-cancelled'
  return ''
}

export default function ShootsSection({ card }) {
  const shoots = card.shoots || []

  return (
    <div className="section">
      <div className="section-title">Shoots</div>
      {shoots.length === 0 ? (
        <p className="empty">No shoots</p>
      ) : (
        shoots.map((s, i) => (
          <div key={i} className="shoot-item">
            <div className="shoot-date">{formatDate(s.date)}</div>
            <div className="shoot-body">
              <div className={`shoot-status ${statusClass(s.status)}`}>{s.status}</div>
              {s.types?.length > 0 && (
                <div className="shoot-types">{s.types.join(', ')}</div>
              )}
            </div>
          </div>
        ))
      )}
    </div>
  )
}
