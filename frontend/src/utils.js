export function monthLabel(yyyyMm) {
  if (!yyyyMm) return ''
  const [y, m] = yyyyMm.split('-')
  return new Date(+y, +m - 1, 1).toLocaleString('en', { month: 'short', year: 'numeric' })
}

const MONTHS_SHORT = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']

export function formatDay(iso) {
  if (!iso) return '—'
  const [, m, d] = iso.split('-')
  return `${+d} ${MONTHS_SHORT[+m - 1]}`
}

export function daysBetween(fromIso, toIso) {
  if (!fromIso || !toIso) return null
  return Math.round((Date.parse(toIso) - Date.parse(fromIso)) / 86400000)
}
