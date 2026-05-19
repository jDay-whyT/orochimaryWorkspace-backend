export function monthLabel(yyyyMm) {
  if (!yyyyMm) return ''
  const [y, m] = yyyyMm.split('-')
  return new Date(+y, +m - 1, 1).toLocaleString('en', { month: 'short', year: 'numeric' })
}
