export default function StatusBadge({ status }) {
  const s = (status || '').toLowerCase()
  const cls = s === 'work'     ? 'badge-work'
            : s === 'new'      ? 'badge-new'
            : s === 'inactive' ? 'badge-inactive'
            : s === 'stop'     ? 'badge-stop'
            : s === 'looted'   ? 'badge-looted'
            : 'badge-other'
  return <span className={`badge ${cls}`}>{status || '—'}</span>
}
