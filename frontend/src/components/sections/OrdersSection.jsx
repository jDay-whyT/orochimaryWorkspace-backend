const ORDER_LABELS = {
  custom:        'Custom',
  short:         'Short',
  'verif reddit':'Verif',
  call:          'Call',
  'ad request':  'Ad Req',
}

function monthLabel(yyyyMm) {
  if (!yyyyMm) return ''
  const [y, m] = yyyyMm.split('-')
  return new Date(+y, +m - 1, 1).toLocaleString('en', { month: 'short', year: 'numeric' })
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

export default function OrdersSection({ card }) {
  return (
    <div className="section">
      <div className="section-title">Orders</div>
      <div className="month-label">{monthLabel(card.current_month)}</div>
      <OrderRows orders={card.orders_current} />
      <div className="month-label">{monthLabel(card.prev_month)}</div>
      <OrderRows orders={card.orders_prev} />
    </div>
  )
}
