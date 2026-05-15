import { useState } from 'react'
import StatusBadge from './StatusBadge'

const TABS = ['all', 'work', 'new', 'inactive', 'stop', 'looted']

export default function ModelList({ models, scout, onSelect }) {
  const [filter, setFilter] = useState('all')
  const [scoutFilter, setScoutFilter] = useState('all')
  const [query, setQuery] = useState('')

  // Scout filter only makes sense in admin view (scout === null means all models)
  const isAdmin = scout === null
  const scouts = isAdmin
    ? ['all', ...Array.from(new Set(models.map(m => m.scout).filter(Boolean))).sort()]
    : []

  const q = query.trim().toLowerCase()

  // Scout-filtered base for accurate status counts
  const scoutFiltered = scoutFilter === 'all'
    ? models
    : models.filter(m => m.scout === scoutFilter)

  const counts = TABS.reduce((acc, s) => {
    acc[s] = s === 'all'
      ? scoutFiltered.length
      : scoutFiltered.filter(m => (m.status || '').toLowerCase() === s).length
    return acc
  }, {})

  const visibleTabs = TABS.filter(s => s === 'all' || counts[s] > 0)
  const showTabs = visibleTabs.length > 2

  const visible = scoutFiltered
    .filter(m => filter === 'all' || (m.status || '').toLowerCase() === filter)
    .filter(m => !q || m.name.toLowerCase().includes(q))

  return (
    <div className="screen">
      <div className="header">
        <div className="header-title">{scout || 'All Models'}</div>
        <span className="header-sub">
          {visible.length === models.length
            ? `${models.length} models`
            : `${visible.length} / ${models.length}`}
        </span>
      </div>

      <input
        className="search-input"
        type="search"
        placeholder="Search…"
        value={query}
        onChange={e => setQuery(e.target.value)}
      />

      {isAdmin && scouts.length > 2 && (
        <div className="filter-tabs scout-tabs">
          {scouts.map(s => (
            <button
              key={s}
              className={`filter-tab${scoutFilter === s ? ' filter-tab--all' : ''}`}
              onClick={() => setScoutFilter(s)}
            >
              {s === 'all' ? 'All scouts' : s}
            </button>
          ))}
        </div>
      )}

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
