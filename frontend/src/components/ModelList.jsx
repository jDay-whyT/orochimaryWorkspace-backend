import StatusBadge from './StatusBadge'

export default function ModelList({ models, scout, onSelect }) {
  return (
    <div className="screen">
      <div className="header">
        <div className="header-title">
          {scout ? scout : 'All Models'}
        </div>
        <span className="header-sub">{models.length} models</span>
      </div>

      {models.length === 0 ? (
        <p className="empty">No models found</p>
      ) : (
        <div className="model-list">
          {models.map((m) => (
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
