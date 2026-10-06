import { useEffect, useRef, useState } from 'react'
import { enc, post, type Domain, type Item } from '../lib/api'
import { DOMAINS } from '../lib/domains'
import { Spinner } from './Icons'
import StarRating, { StarsView } from './StarRating'

export interface LogOut {
  item: Item
  extracted: {
    status: string
    rating: number
    liked: string[]
    disliked: string[]
    mood: string
    with: string
  }
  quote: string
  stale: number
}

const today = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** "看过了": finished or not, stars (draggable, half steps), a review in
 * the user's own words, and when. Stars are what the user says they are;
 * the 1.7B model only reads the review for aspects, mood and company. */
export default function LogPanel({
  id,
  name,
  domain,
  origin,
  askOrigin = false,
  initialRating = null,
  onDone,
  onCancel,
}: {
  id: string
  name: string
  domain: Domain
  origin?: 'rec' | 'past'
  askOrigin?: boolean
  initialRating?: number | null
  onDone: (out: LogOut) => void
  onCancel: () => void
}) {
  const c = DOMAINS[domain]
  const [status, setStatus] = useState<'watched' | 'dropped'>('watched')
  const [org, setOrg] = useState<'rec' | 'past'>(origin ?? 'past')
  const [rating, setRating] = useState<number | null>(initialRating)
  const [text, setText] = useState('')
  const [day, setDay] = useState(today())
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<LogOut | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    ref.current?.focus({ preventScroll: true })
  }, [])

  const submit = async () => {
    if (busy) return
    setBusy(true)
    setErr(null)
    try {
      const r = await post<LogOut>(`/items/${enc(id)}/log`, {
        status,
        rating,
        text,
        origin: org,
        done_on: day,
      })
      setOut(r)
      setTimeout(() => onDone(r), text.trim() ? 1600 : 700)
    } catch (e) {
      setErr(`没能记下来：${(e as Error).message}。再试一次。`)
      setBusy(false)
    }
  }

  if (out) {
    const x = out.extracted
    return (
      <div className="fb-box log-panel" data-fb-done>
        <div className="t13 secondary">{text.trim() ? '记下了。这是片刻听到的：' : '记下了。'}</div>
        <div className="tags">
          {out.item.rating != null && (
            <span className="tag">
              <StarsView n={out.item.rating} size={12} />
            </span>
          )}
          {x.liked.map((l, i) => (
            <span key={`l${i}`} className="tag tag-like" style={{ animationDelay: `${i * 60}ms` }}>
              {l}
            </span>
          ))}
          {x.disliked.map((l, i) => (
            <span key={`d${i}`} className="tag tag-dislike" style={{ animationDelay: `${(x.liked.length + i) * 60}ms` }}>
              {l}
            </span>
          ))}
          {[x.mood, x.with].filter(Boolean).map((v, i) => (
            <span key={`c${i}`} className="tag tag-ctx">
              {v}
            </span>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="fb-box log-panel" onKeyDown={(e) => e.key === 'Escape' && onCancel()}>
      <div className="log-row">
        <div className="seg" role="radiogroup">
          {(['watched', 'dropped'] as const).map((s) => (
            <button key={s} className={status === s ? 'on' : undefined} onClick={() => setStatus(s)} role="radio" aria-checked={status === s}>
              {s === 'watched' ? c.finished : c.dropped}
            </button>
          ))}
        </div>
        {askOrigin && (
          <div className="seg" role="radiogroup">
            {(['rec', 'past'] as const).map((o) => (
              <button key={o} className={org === o ? 'on' : undefined} onClick={() => setOrg(o)} role="radio" aria-checked={org === o}>
                {o === 'rec' ? `按推荐${c.verb}的` : `以前就${c.done}`}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="log-row" style={{ marginTop: 14 }}>
        <StarRating value={rating} onChange={setRating} />
      </div>
      <textarea
        ref={ref}
        className="fb-input"
        style={{ marginTop: 12 }}
        placeholder={`《${name}》怎么样？写几句评语，喜欢哪里、哪里不对胃口、和谁${c.verb}的。可以不写。`}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit()
        }}
        disabled={busy}
        data-fb-input
      />
      {err && <div className="t13 danger" style={{ marginTop: 6 }}>{err}</div>}
      <div className="fb-actions">
        <button className="pill-accent" onClick={submit} disabled={busy} data-fb-submit>
          {busy ? (
            <>
              <Spinner size={14} />
              {text.trim() ? '正在整理' : '正在记下'}
            </>
          ) : (
            '记下来'
          )}
        </button>
        <button className="pill-sm dim" onClick={onCancel} disabled={busy}>
          取消
        </button>
        <label className="log-date t13 secondary">
          {status === 'watched' ? `${c.finished}于` : '记于'}
          <input type="date" value={day} max={today()} onChange={(e) => setDay(e.target.value || today())} />
        </label>
        {busy && text.trim() && <span className="t13 secondary">Spark 1.7B 正在本机整理你的话</span>}
      </div>
    </div>
  )
}
