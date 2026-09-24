import { useState } from 'react'
import { monthLabel, formatDay, daysBetween } from '../../utils'

const ORDER_LABELS = {
  custom:        'Custom',
  short:         'Short',
  'verif reddit':'Verif',
  call:          'Call',
  'ad request':  'Ad Req',
}

const STATUS_CLASS = {
  open:     'shoot-status-planned',
  done:     'shoot-status-done',
  canceled: 'shoot-status-cancelled',
}

function typeLabel(type) {
  return ORDER_LABELS[type] || type || '—'
}

function totalOrders(orders) {
  if (!orders) return 0
  return Object.values(orders).reduce((sum, v) => sum + (v || 0), 0)
}

function Summary({ counts }) {
  const entries = Object.entries(counts || {}).filter(([, v]) => v > 0)
  if (!entries.length) return null
  return (
    <div className="tags order-summary">
      {entries.map(([type, n]) => (
        <span key={type} className="tag">{typeLabel(type)} · {n}</span>
      ))}
    </div>
  )
}

function OrderItem({ order, today }) {
  const canceled = order.status === 'canceled'
  const isOpen = order.status === 'open'
  const age = isOpen ? daysBetween(order.in, today) : null
  const took = !isOpen && order.out ? daysBetween(order.in, order.out) : null

  let dates = order.in ? `in ${formatDay(order.in)}` : ''
  if (order.out) dates += `${dates ? ' → ' : ''}out ${formatDay(order.out)}`
  if (took !== null && took >= 0) dates += ` · ${took}d`
  if (age !== null && age >= 0) dates += ` · open ${age}d`

  const qty = order.count > 1
    ? ` ×${order.count}${order.received != null && order.received !== order.count ? ` (got ${order.received})` : ''}`
    : ''

  return (
    <div className={`shoot-item${canceled ? ' order-canceled' : ''}`}>
      <div className="shoot-date">{formatDay(order.out || order.in)}</div>
      <div className="shoot-body">
        <div className="order-head">
          <span className="order-type">{typeLabel(order.type)}{qty}</span>
          <span className={`shoot-status ${STATUS_CLASS[order.status] || ''}`}>{order.status || '—'}</span>
        </div>
        {order.title && <div className="shoot-types">{order.title}</div>}
        {dates && <div className="shoot-types">{dates}</div>}
      </div>
    </div>
  )
}

function OrderList({ items, today, failed, emptyText = 'No orders' }) {
  if (failed) return <p className="empty section-failed">⚠ Failed to load</p>
  if (!items?.length) return <p className="empty">{emptyText}</p>
  return items.map(o => <OrderItem key={o.id} order={o} today={today} />)
}

function HistoryMonth({ month, counts, items, today, failed }) {
  const [open, setOpen] = useState(false)
  const total = totalOrders(counts)
  return (
    <div className="history-month">
      <button className="history-month-btn" onClick={() => setOpen(o => !o)}>
        <span className="history-month-name">{monthLabel(month)}</span>
        <span className="history-month-right">
          <span className="history-month-total">{failed ? '⚠' : `${total} orders`}</span>
          <span className="history-chevron">{open ? '↑' : '↓'}</span>
        </span>
      </button>
      {open && (
        <div className="history-month-body">
          {!failed && <Summary counts={counts} />}
          <OrderList items={items} today={today} failed={failed} />
        </div>
      )}
    </div>
  )
}

export default function OrdersSection({ card }) {
  const failed = card.failed || []
  const today = card.today || ''
  const openOrders = card.orders_open || []
  const history = card.orders_history || []
  const total = totalOrders(card.orders_current)
  const allFailed = failed.includes('orders')

  return (
    <div className="section">
      <div className="section-title">Orders</div>

      {!allFailed && (
        <>
          <div className="history-month-current">
            <span className="history-month-name">Open</span>
            <span className="history-month-right">
              <span className="history-month-total">{openOrders.length} open</span>
            </span>
          </div>
          <div className="history-month-body">
            <OrderList items={openOrders} today={today} emptyText="No open orders" />
          </div>
        </>
      )}

      <div className="history-month-current">
        <span className="history-month-name">{monthLabel(card.current_month)}</span>
        <span className="history-month-right">
          <span className="content-current-badge">current</span>
          <span className="history-month-total">{allFailed ? '⚠' : `${total} orders`}</span>
        </span>
      </div>
      <div className="history-month-body">
        {!allFailed && <Summary counts={card.orders_current} />}
        <OrderList items={card.orders_current_items} today={today} failed={allFailed} />
      </div>

      {history.length > 0 && (
        <>
          <div className="history-section-label">History</div>
          {history.map(h => (
            <HistoryMonth
              key={h.month}
              month={h.month}
              counts={h.data}
              items={h.items}
              today={today}
              failed={failed.includes(`orders:${h.month}`)}
            />
          ))}
        </>
      )}
    </div>
  )
}
