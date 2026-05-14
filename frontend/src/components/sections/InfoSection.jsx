export default function InfoSection({ card }) {
  const rows = [
    card.language && { label: 'Language', value: card.language },
    card.anal     && { label: 'Anal',     value: card.anal },
    card.calls    && { label: 'Calls',    value: card.calls },
    {
      label: 'Rent',
      value: card.rent ? '✓ yes' : 'no',
    },
  ].filter(Boolean)

  return (
    <div className="section">
      <div className="section-title">Info</div>

      {rows.map((r) => (
        <div key={r.label} className="section-row">
          <span className="section-row-label">{r.label}</span>
          <span className="section-row-value">{r.value}</span>
        </div>
      ))}

      {card.traffic?.length > 0 && (
        <div className="section-row" style={{ alignItems: 'flex-start', flexDirection: 'column', gap: 8 }}>
          <span className="section-row-label">Traffic</span>
          <div className="tags">
            {card.traffic.map((t) => (
              <span key={t} className="tag">{t}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
