export default function StatusBadge({ status }) {
  const s = (status || '').toLowerCase()
  const cls = s === 'work' ? 'badge-work'
            : s === 'pause' ? 'badge-pause'
            : s === 'stop'  ? 'badge-stop'
            : 'badge-other'
  return <span className={`badge ${cls}`}>{status || '—'}</span>
}
