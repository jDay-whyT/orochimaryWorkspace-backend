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
  if (s === 'scheduled')   return 'shoot-status-scheduled'
  if (s === 'stuck')       return 'shoot-status-stuck'
  return ''
}

function ShootList({ shoots, emptyText = 'No shoots' }) {
  if (!shoots.length) return <p className="empty">{emptyText}</p>
  return shoots.map((s, i) => (
    <div key={s.id || `${s.date}-${i}`} className="shoot-item">
      <div className="shoot-date">
        {formatDate(s.date)}
        {s.time && <div className="shoot-time">{s.time}</div>}
      </div>
      <div className="shoot-body">
        <div className={`shoot-status ${statusClass(s.status)}`}>{s.status}</div>
        {(s.types?.length > 0 || s.location) && (
          <div className="shoot-types">
            {[s.types?.join(', '), s.location].filter(Boolean).join(' · ')}
          </div>
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
  const today = card.today || ''
  const failed = (card.failed || []).includes('shoots')

  // ISO dates compare correctly as strings.
  const upcoming = shoots.filter(s => s.date > today)
  const past = shoots.filter(s => s.date <= today)
  const currentShoots = past.filter(s => s.date.startsWith(currentMonth))
  const historyMonths = card.history_months || []

  return (
    <div className="section">
      <div className="section-title">Shoots</div>

      {failed ? (
        <p className="empty section-failed">⚠ Failed to load</p>
      ) : (
        <>
          <div className="history-month-current">
            <span className="history-month-name">Upcoming</span>
            <span className="history-month-right">
              <span className="history-month-total">{upcoming.length} shoots</span>
            </span>
          </div>
          <div className="history-month-body">
            <ShootList shoots={upcoming} emptyText="Nothing planned" />
          </div>

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
                <HistoryShootMonth
                  key={ym}
                  month={ym}
                  shoots={past.filter(s => s.date.startsWith(ym))}
                />
              ))}
            </>
          )}
        </>
      )}
    </div>
  )
}
