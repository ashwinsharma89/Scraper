// Thin fetch wrapper over the FastAPI /api surface -- ported 1:1 from the old
// static/app.js `api()` helper. The backend is completely unchanged by the React
// rewrite; every endpoint below already existed before this file did.
export class ApiError extends Error {}

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  if (res.status === 401) {
    const err = new ApiError('auth required')
    err.status = 401
    throw err
  }
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch { /* non-JSON error body */ }
    throw new ApiError(detail)
  }
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}
