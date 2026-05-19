import { useState } from 'react'
import { monthLabel } from '../../utils'

const ORDER_LABELS = {
  custom:        'Custom',
  short:         'Short',
  'verif reddit':'Verif',
  call:          'Call',
  'ad request':  'Ad Req',
}



function totalOrders(orders) {
  if (!orders) return 0
  return Object.values(orders).reduce((sum, v) => sum + (v || 0), 0)
}

function OrderRows({ orders }) {
  const entries = Object.entries(orders || {}).filter(([, v]) => v > 0)
  if (!entries.length) return <p className="empty">No orders</p>
  return entries.map(([type, count]) => (
    <div key={type} className="section-row">
      <span className="section-row-label">{ORDER_LABELS[type] || type}</span>
      <span className="section-row-value">{count}</span>
    </div>
  ))
}

function HistoryMonth({ month, data }) {
  const [open, setOpen] = useState(false)
  const total = totalOrders(data)
  return (
    <div className="history-month">
      <button className="history-month-btn" onClick={() => setOpen(o => !o)}>
        <span className="history-month-name">{monthLabel(month)}</span>
        <span className="history-month-right">
          <span className="history-month-total">{total} orders</span>
          <span className="history-chevron">{open ? '↑' : '↓'}</span>
        </span>
      </button>
      {open && <div className="history-month-body"><OrderRows orders={data} /></div>}
    </div>
  )
}

export default function OrdersSection({ card }) {
  const total = totalOrders(card.orders_current)
  const history = card.orders_history || []

  return (
    <div className="section">
      <div className="section-title">Orders</div>

      <div className="history-month-current">
        <span className="history-month-name">{monthLabel(card.current_month)}</span>
        <span className="history-month-right">
          <span className="content-current-badge">current</span>
          <span className="history-month-total">{total} orders</span>
        </span>
      </div>
      <div className="history-month-body">
        <OrderRows orders={card.orders_current} />
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
