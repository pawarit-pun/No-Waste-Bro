const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError('Could not reach the server.', 0)
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status}).`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) detail = body.detail[0].msg
    } catch {
      // body ไม่ใช่ JSON
    }
    throw new ApiError(detail, res.status)
  }
  return res.json() as Promise<T>
}

/** GET จาก FastAPI (VITE_API_BASE_URL) error จะเป็น ApiError */
export function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, init)
}

/** POST JSON ไป FastAPI */
export function apiPost<T>(path: string, body: unknown, init?: RequestInit): Promise<T> {
  return request<T>(path, { ...init, method: 'POST', body: JSON.stringify(body) })
}

export const errorMessage = (err: unknown, fallback = 'Something went wrong.') =>
  err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback
