function initData() {
  return window.Telegram?.WebApp?.initData || ''
}

function authHeader() {
  return { Authorization: `tma ${initData()}` }
}

export async function fetchModels() {
  const res = await fetch('/api/scout/models', {
    method: 'POST',
    headers: authHeader(),
  })
  if (res.status === 401) throw Object.assign(new Error('unauthorized'), { status: 401 })
  return res.json()
}

export async function fetchModelCard(name, signal) {
  const res = await fetch(`/api/scout/model/${encodeURIComponent(name)}`, {
    headers: authHeader(),
    signal,
  })
  if (res.status === 401) throw Object.assign(new Error('unauthorized'), { status: 401 })
  if (res.status === 403) throw Object.assign(new Error('forbidden'), { status: 403 })
  if (res.status === 404) throw Object.assign(new Error('not found'), { status: 404 })
  return res.json()
}
