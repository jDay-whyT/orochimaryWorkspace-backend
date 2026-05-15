export default function StatusBadge({ status }) {
  const s = (status || '').toLowerCase()
  const cls = s === 'work'     ? 'badge-work'
            : s === 'new'      ? 'badge-new'
            : s === 'inactive' ? 'badge-inactive'
            : 'badge-other'
  return <span className={`badge ${cls}`}>{status || '—'}</span>
}
