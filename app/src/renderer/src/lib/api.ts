/** Thin client for the local backend (127.0.0.1, per-launch token). */

export type Domain = 'film' | 'book' | 'music'

/** One work on any shelf. Film-only and book/album-only fields are optional. */
export interface Title {
  id: string
  domain: Domain
  kind: 'movie' | 'series' | 'miniseries' | 'book' | 'album'
  title: string
  original: string
  zh: string | null
  name: string
  year: number | null
  genres: string[]
  genres_zh: string[]
  // films
  end_year?: number | null
  runtime?: number | null
  rating?: number
  votes?: number
  directors?: string[]
  cast?: string[]
  // books and albums
  creators?: string[]
  lang?: string
  region?: string
  pages?: number | null
  tracks?: number | null
}

export interface Item {
  id: string
  domain: Domain
  status: 'watched' | 'dropped' | 'want' | 'rejected'
  rating: number | null
  origin: 'rec' | 'past' | 'onboard' | null
  done_on: string | null
  reason: string | null
  liked: string[]
  disliked: string[]
  context: { mood?: string; with?: string; when?: string }
  words: string
  source: string
  created: number
  updated: number
  title: Title | null
}

export interface Quote {
  id: string
  domain?: Domain
  stance?: string
  onboard?: boolean
  name: string
  words: string
  liked: string[]
  rating: number | null
}

export interface Pick extends Title {
  reason: string
  because: Quote[]
}

export interface RecResult {
  rec_id: number | null
  domain?: Domain
  direction: string
  picks: Pick[]
  stats: { seconds: number; prompt_tokens: number; pool: number; seeds: number; verified: number; gen_tps?: number }
}

export interface Claim {
  text: string
  evidence: string[]
  user?: boolean
}
export interface Section {
  key: string
  title: string
  claims: Claim[]
}
export interface Profile {
  version: number
  ts: number
  doc: { summary: string; sections: Section[] }
  stats: {
    reason?: string
    records?: number
    prompt_tokens?: number
    seconds?: number
    prompt_tps?: number
    gen_tps?: number
    diff?: { added: number; removed: number; kept: number }
  }
}

export interface ModelState {
  key: 'big' | 'small'
  name: string
  provider: 'local' | 'api'
  host: string
  file: string
  /** idle: local model not loaded yet, loads on first use */
  status: 'stopped' | 'idle' | 'loading' | 'ready' | 'missing' | 'error'
  error: string | null
  ctx: number
  size_bytes: number | null
  load_seconds: number | null
}

/** Which models answer; the API key itself never leaves the backend. */
export interface LlmSettings {
  mode: 'local' | 'api'
  base_url: string
  big_model: string
  small_model: string
  ctx: number
  has_key: boolean
  key_hint: string
  host: string
  /** false when the user's words go to a server off this Mac */
  on_device: boolean
}

export type Counts = Record<'watched' | 'dropped' | 'want' | 'rejected', number>

export interface PassReason {
  key: 'want' | 'not_interested' | 'not_my_taste' | 'not_now'
  label: string
  effect: 'want' | 'taste' | 'moment'
}

export interface Status {
  models: ModelState[]
  llm: LlmSettings
  catalog: { available: boolean; total?: string; with_zh?: string; built_at?: string; source?: string; count_movie?: string; count_series?: string; count_miniseries?: string }
  library: { available: boolean; count_book?: string; count_album?: string; built_at?: string; source?: string }
  onboarded: boolean
  domains_onboarded: Domain[]
  domain_counts: Record<Domain, Counts>
  covers_online: boolean
  pass_reasons: Record<Domain, PassReason[]>
  name: string
  counts: Counts
  profile_version: number | null
  stale: number
  data_path: string
}

let info: { baseUrl: string; token: string } | null = null

async function base() {
  if (!info) {
    const i = await window.pianke.getInfo()
    info = { baseUrl: i.baseUrl, token: i.token }
  }
  return info
}

export async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = await base()
  const r = await fetch(baseUrl + path, {
    ...init,
    headers: {
      'content-type': 'application/json',
      'x-pianke-token': token,
      ...(init.headers || {}),
    },
  })
  if (!r.ok) {
    let msg = `${r.status}`
    try {
      msg = (await r.json()).detail || msg
    } catch {
      /* keep status */
    }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

/** <img> src for a work's cover (served and cached by the local backend). */
export function coverSrc(id: string): string | null {
  if (!info) return null
  return `${info.baseUrl}/cover/${encodeURIComponent(id)}?t=${encodeURIComponent(info.token)}`
}

/** item ids may contain ':' (bk:Q…, mu:it…) */
export const enc = (id: string) => encodeURIComponent(id)

export const get = <T>(p: string) => req<T>(p)
export const post = <T>(p: string, body?: unknown) =>
  req<T>(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
export const put = <T>(p: string, body: unknown) =>
  req<T>(p, { method: 'PUT', body: JSON.stringify(body) })
export const del = <T>(p: string) => req<T>(p, { method: 'DELETE' })
export const patch = <T>(p: string, body: unknown) =>
  req<T>(p, { method: 'PATCH', body: JSON.stringify(body) })

/** POST that answers with server-sent events; calls onEvent per JSON event. */
export async function stream(
  path: string,
  body: unknown,
  onEvent: (ev: any) => void, // eslint-disable-line @typescript-eslint/no-explicit-any
  signal?: AbortSignal
): Promise<void> {
  const { baseUrl, token } = await base()
  const r = await fetch(baseUrl + path, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-pianke-token': token },
    body: JSON.stringify(body ?? {}),
    signal,
  })
  if (!r.ok || !r.body) throw new Error(`${r.status}`)
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    // sse-starlette separates events with CRLF CRLF
    buf += dec.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i)
      buf = buf.slice(i + 2)
      for (const line of chunk.split(/\r?\n/)) {
        if (line.startsWith('data:')) {
          const data = line.slice(5).trim()
          if (data) onEvent(JSON.parse(data))
        }
      }
    }
  }
}

export async function waitBackend(timeoutMs = 30_000): Promise<boolean> {
  const { baseUrl } = await base()
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const r = await fetch(baseUrl + '/health')
      if (r.ok) return true
    } catch {
      /* not yet */
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  return false
}
