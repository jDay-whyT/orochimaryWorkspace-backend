import { useState, useEffect } from 'react'
import { fetchModelCard } from '../api'
import StatusBadge from './StatusBadge'
import InfoSection from './sections/InfoSection'
import ContentSection from './sections/ContentSection'
import OrdersSection from './sections/OrdersSection'
import ShootsSection from './sections/ShootsSection'

export default function ModelCard({ name, onBack }) {
  const [card, setCard] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchModelCard(name)
      .then(setCard)
      .catch((e) => setError(e.message))
  }, [name])

  if (error) {
    return (
      <div className="screen">
        <div className="header">
          <button className="header-back" onClick={onBack}>← Back</button>
        </div>
        <p className="empty">Failed to load: {error}</p>
      </div>
    )
  }

  if (!card) {
    return <div className="center"><div className="spinner" /></div>
  }

  return (
    <div className="screen">
      <div className="header">
        <button className="header-back" onClick={onBack}>← Back</button>
      </div>

      <div className="card-header">
        <div className="card-name">{card.model_name}</div>
        <div className="card-meta">
          <StatusBadge status={card.status} />
          {card.project && <span>{card.project}</span>}
          {card.assist && <span>{card.assist}</span>}
        </div>
      </div>

      <InfoSection card={card} />
      <ContentSection card={card} />
      <OrdersSection card={card} />
      <ShootsSection card={card} />
    </div>
  )
}
