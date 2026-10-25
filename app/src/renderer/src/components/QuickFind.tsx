import { useEffect, useRef, useState } from 'react'
import { enc, get, post, type Domain, type Item, type Title } from '../lib/api'
import { DOMAINS, DOMAIN_ORDER } from '../lib/domains'
import { metaLine } from '../lib/format'
import { toast } from '../lib/toast'
import Cover from './Cover'
import LogPanel from './LogPanel'
import { MagnifierIcon, Spinner } from './Icons'

/** ⌘K: find any work by name and, right there, log it or put it on the list.
 *  For "I just watched X" and "a friend told me about Y" without going
 *  through a shelf's tabs. */
export default function QuickFind({
  domain: initial,
  onClose,
  onChanged,
}: {
  domain: Domain
  onClose: () => void
  onChanged: () => void
}) {
  const [domain, setDomain] = useState<Domain>(initial)
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<Title[]>([])
  const [busy, setBusy] = useState(false)
  const [mine, setMine] = useState<Record<string, Item['status']>>({})
  const [logging, setLogging] = useState<Title | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const c = DOMAINS[domain]

  useEffect(() => {
    get<Item[]>(`/items?domain=${domain}`)
      .then((its) => setMine(Object.fromEntries(its.map((i) => [i.id, i.status]))))
      .catch(() => setMine({}))
    input.current?.focus()
  }, [domain])

  useEffect(() => {
    if (!q.trim()) {
      setHits([])
      return
    }
    const id = setTimeout(
      () => {
        setBusy(true)
        get<Title[]>(`/search?q=${encodeURIComponent(q)}&domain=${domain}`)
          .then((h) => setHits(h.slice(0, 8)))
          .catch(() => setHits([]))
          .finally(() => setBusy(false))
      },
      domain === 'film' ? 160 : 400
    )
    return () => clearTimeout(id)
  }, [q, domain])

  const want = async (t: Title) => {
    await post(`/items/${enc(t.id)}/status`, { status: 'want', source: 'manual' })
    setMine((m) => ({ ...m, [t.id]: 'want' }))
    toast({ text: `已放进${c.list}：《${t.name}》` })
    onChanged()
  }

  const stateLabel = (s?: Item['status']) =>
    s === 'want' ? `在${c.list}里` : s === 'watched' ? c.done : s === 'dropped' ? c.dropped : s === 'rejected' ? `不想${c.verb}` : ''

  return (
    <div className="qf-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-quickfind>
      <div className="qf" role="dialog" aria-label="找作品" onKeyDown={(e) => e.key === 'Escape' && onClose()}>
        <div className="qf-head">
          <MagnifierIcon size={15} />
          <input
            ref={input}
            className="qf-input"
            placeholder={`找一${c.unit}${c.noun}：${domain === 'film' ? '片名、导演或演员' : domain === 'book' ? '书名或作者' : '专辑名或歌手'}`}
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setLogging(null)
            }}
            data-qf-input
          />
          {busy && <Spinner size={12} />}
          <div className="seg seg-sm" role="radiogroup">
            {DOMAIN_ORDER.map((d) => (
              <button
                key={d}
                className={d === domain ? 'on' : undefined}
                role="radio"
                aria-checked={d === domain}
                onClick={() => {
                  setDomain(d)
                  setLogging(null)
                }}
              >
                {DOMAINS[d].label}
              </button>
            ))}
          </div>
        </div>
        <div className="qf-body">
          {!q.trim() && <div className="t13 secondary qf-note">刚{c.verb}完想记一笔，或者听说了一{c.unit}想先存着，都可以在这里找。</div>}
          {q.trim() && !busy && hits.length === 0 && (
            <div className="t13 secondary qf-note">没找到。换个写法，或试试原名。</div>
          )}
          {hits.map((h) =>
            logging?.id === h.id ? (
              <div key={h.id} className="qf-row open">
                <Cover t={h} width={36} radius={3} />
                <div className="qf-main">
                  <div className="film-name qf-name">{h.name}</div>
                  <LogPanel
                    id={h.id}
                    name={h.name}
                    domain={domain}
                    origin="past"
                    onCancel={() => setLogging(null)}
                    onDone={() => {
                      setLogging(null)
                      setMine((m) => ({ ...m, [h.id]: 'watched' }))
                      onChanged()
                    }}
                  />
                </div>
              </div>
            ) : (
              <div key={h.id} className="qf-row" data-qf-hit={h.id}>
                <Cover t={h} width={36} radius={3} />
                <div className="qf-main">
                  <div className="film-name qf-name">{h.name}</div>
                  <div className="t13 secondary truncate">
                    {h.original && h.original !== h.name ? `${h.original}，` : ''}
                    {metaLine(h)}
                  </div>
                </div>
                {mine[h.id] && <span className="t13 secondary">{stateLabel(mine[h.id])}</span>}
                <span className="qf-actions">
                  {mine[h.id] !== 'want' && mine[h.id] !== 'watched' && (
                    <button className="pill-sm" onClick={() => want(h)} data-qf-want>
                      先存着
                    </button>
                  )}
                  <button className="pill-sm" onClick={() => setLogging(h)} data-qf-log>
                    {mine[h.id] === 'watched' ? '改记录' : `${c.done}了`}
                  </button>
                </span>
              </div>
            )
          )}
        </div>
      </div>
    </div>
  )
}
