import { useState } from 'react'
import StatusBadge from './StatusBadge'

const TABS = ['all', 'work', 'new', 'inactive']

export default function ModelList({ models, scout, onSelect }) {
  const [filter, setFilter] = useState('all')

  const counts = TABS.reduce((acc, s) => {
    acc[s] = s === 'all'
      ? models.length
      : models.filter(m => (m.status || '').toLowerCase() === s).length
    return acc
  }, {})

  const visibleTabs = TABS.filter(s => s === 'all' || counts[s] > 0)
  const showTabs = visibleTabs.length > 2

  const visible = filter === 'all'
    ? models
    : models.filter(m => (m.status || '').toLowerCase() === filter)

  return (
    <div className="screen">
      <div className="header">
        <div className="header-title">{scout || 'All Models'}</div>
        <span className="header-sub">
          {filter === 'all'
            ? `${models.length} models`
            : `${visible.length} / ${models.length}`}
        </span>
      </div>

      {showTabs && (
        <div className="filter-tabs">
          {visibleTabs.map(s => (
            <button
              key={s}
              className={`filter-tab${filter === s ? ` filter-tab--${s}` : ''}`}
              onClick={() => setFilter(s)}
            >
              {s === 'all' ? 'All' : s[0].toUpperCase() + s.slice(1)}
              {s !== 'all' && <span className="filter-tab-count"> {counts[s]}</span>}
            </button>
          ))}
        </div>
      )}

      {visible.length === 0 ? (
        <p className="empty">No models found</p>
      ) : (
        <div className="model-list">
          {visible.map(m => (
            <div key={m.name} className="model-item" onClick={() => onSelect(m.name)}>
              <div className="model-item-left">
                <div className="model-item-name">{m.name}</div>
                {m.project && <div className="model-item-meta">{m.project}</div>}
              </div>
              <StatusBadge status={m.status} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
