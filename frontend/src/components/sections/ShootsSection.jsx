import { useState } from 'react'
import { monthLabel } from '../../utils'

const MONTHS = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']

function formatDate(iso) {
  if (!iso) return '—'
  const [, m, d] = iso.split('-')
  return `${+d} ${MONTHS[+m - 1]}`
}


function statusClass(status) {
  const s = (status || '').toLowerCase()
  if (s === 'planned')     return 'shoot-status-planned'
  if (s === 'done')        return 'shoot-status-done'
  if (s === 'rescheduled') return 'shoot-status-rescheduled'
  if (s === 'cancelled')   return 'shoot-status-cancelled'
  return ''
}

function ShootList({ shoots }) {
  if (!shoots.length) return <p className="empty">No shoots</p>
  return shoots.map((s) => (
    <div key={`${s.date}-${s.status}`} className="shoot-item">
      <div className="shoot-date">{formatDate(s.date)}</div>
      <div className="shoot-body">
        <div className={`shoot-status ${statusClass(s.status)}`}>{s.status}</div>
        {s.types?.length > 0 && (
          <div className="shoot-types">{s.types.join(', ')}</div>
        )}
      </div>
    </div>
  ))
}

function HistoryShootMonth({ month, shoots }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="history-month">
      <button className="history-month-btn" onClick={() => setOpen(o => !o)}>
        <span className="history-month-name">{monthLabel(month)}</span>
        <span className="history-month-right">
          <span className="history-month-total">{shoots.length} shoots</span>
          <span className="history-chevron">{open ? '↑' : '↓'}</span>
        </span>
      </button>
      {open && <div className="history-month-body"><ShootList shoots={shoots} /></div>}
    </div>
  )
}

export default function ShootsSection({ card }) {
  const shoots = card.shoots || []
  const currentMonth = card.current_month || ''

  const grouped = {}
  for (const s of shoots) {
    const ym = (s.date || '').slice(0, 7)
    if (!ym) continue
    ;(grouped[ym] = grouped[ym] || []).push(s)
  }

  const currentShoots = grouped[currentMonth] || []
  const historyMonths = Object.keys(grouped)
    .filter(ym => ym !== currentMonth)
    .sort()
    .reverse()

  return (
    <div className="section">
      <div className="section-title">Shoots</div>

      <div className="history-month-current">
        <span className="history-month-name">{monthLabel(currentMonth)}</span>
        <span className="history-month-right">
          <span className="content-current-badge">current</span>
          <span className="history-month-total">{currentShoots.length} shoots</span>
        </span>
      </div>
      <div className="history-month-body">
        <ShootList shoots={currentShoots} />
      </div>

      {historyMonths.length > 0 && (
        <>
          <div className="history-section-label">History</div>
          {historyMonths.map(ym => (
            <HistoryShootMonth key={ym} month={ym} shoots={grouped[ym]} />
          ))}
        </>
      )}
    </div>
  )
}
