import { useEffect, useRef, useState } from 'react'
import { get, post, type Domain, type Title } from '../lib/api'
import { DOMAINS } from '../lib/domains'
import Cover from './Cover'
import { HeartFillIcon, MagnifierIcon, Spinner, XmarkIcon } from './Icons'

type Mark = 'love' | 'dislike'

const HEAD: Record<Domain, string> = {
  film: '哪些片你看过、而且喜欢？',
  book: '哪些书你读过、而且喜欢？',
  music: '哪些专辑你听过、而且喜欢？',
}

/** Cold start, step one: recognise rather than recall. Tap once for "喜欢",
 * twice for "不喜欢", a third time to clear. Works the user hasn't seen are
 * simply left alone — no answer is needed for them. */
export default function CoverWall({
  domain,
  onDone,
  onSkip,
  doneLabel = '继续',
}: {
  domain: Domain
  onDone: (marks: Record<string, Mark>) => void
  onSkip?: () => void
  doneLabel?: string
}) {
  const c = DOMAINS[domain]
  const [page, setPage] = useState(0)
  const [batch, setBatch] = useState<Title[] | null>(null)
  const [marks, setMarks] = useState<Record<string, Mark>>({})
  const [known, setKnown] = useState<Record<string, Title>>({})
  const [shownIds, setShownIds] = useState<string[]>([])
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<Title[]>([])
  const [searching, setSearching] = useState(false)
  const [saving, setSaving] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setBatch(null)
    const ex = shownIds.slice(-200).join(',')
    get<Title[]>(`/coldstart/wall?domain=${domain}&page=${page}&exclude=${encodeURIComponent(ex)}`)
      .then((b) => {
        setBatch(b)
        setShownIds((s) => [...s, ...b.map((t) => t.id)])
        setKnown((k) => ({ ...k, ...Object.fromEntries(b.map((t) => [t.id, t])) }))
        scroller.current?.scrollTo({ top: 0 })
      })
      .catch(() => setBatch([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domain, page])

  useEffect(() => {
    if (!q.trim()) {
      setHits([])
      return
    }
    const id = setTimeout(
      () => {
        setSearching(true)
        get<Title[]>(`/search?q=${encodeURIComponent(q)}&domain=${domain}`)
          .then((h) => {
            setHits(h.slice(0, 6))
            setKnown((k) => ({ ...k, ...Object.fromEntries(h.map((t) => [t.id, t])) }))
          })
          .catch(() => setHits([]))
          .finally(() => setSearching(false))
      },
      domain === 'film' ? 180 : 450
    )
    return () => clearTimeout(id)
  }, [q, domain])

  const tap = (id: string) =>
    setMarks((m) => {
      const n = { ...m }
      if (!n[id]) n[id] = 'love'
      else if (n[id] === 'love') n[id] = 'dislike'
      else delete n[id]
      return n
    })

  const loved = Object.values(marks).filter((m) => m === 'love').length
  const disliked = Object.values(marks).filter((m) => m === 'dislike').length
  const finish = async () => {
    setSaving(true)
    try {
      await post('/coldstart/marks', { domain, marks })
      onDone(marks)
    } finally {
      setSaving(false)
    }
  }
  const extra = Object.keys(marks).filter((id) => !batch?.some((t) => t.id === id))

  return (
    <div className="wall-stage">
      <div className="wall-scroll" ref={scroller}>
        <div className="wall-col">
          <h1 className="t26 onboard-h" style={{ textAlign: 'left', margin: 0 }}>
            {HEAD[domain]}
          </h1>
          <p className="secondary" style={{ margin: '8px 0 0' }}>
            点一下是喜欢，点两下是不喜欢。没{c.verb}过的不用管。挑出几{c.unit}就够，片刻会接着问你为什么。
          </p>
          <div className="wall-search">
            <MagnifierIcon size={14} />
            <input
              placeholder={`找不到想选的？搜${c.noun}名${domain === 'film' ? '' : domain === 'book' ? '或作者' : '或歌手'}`}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              data-wall-search
            />
            {searching && <Spinner size={12} />}
          </div>
          {hits.length > 0 && (
            <div className="wall-hits">
              {hits.map((h) => (
                <WallTile key={h.id} t={h} mark={marks[h.id]} onTap={() => tap(h.id)} small />
              ))}
            </div>
          )}
          {extra.length > 0 && (
            <div className="wall-picked">
              <span className="t13 secondary">已经选的：</span>
              {extra.map((id) =>
                known[id] ? (
                  <button key={id} className={`wall-chip ${marks[id]}`} onClick={() => tap(id)}>
                    {marks[id] === 'love' ? <HeartFillIcon size={11} /> : <XmarkIcon size={11} />}
                    {known[id].name}
                  </button>
                ) : null
              )}
            </div>
          )}
          <div className={`wall-grid wall-${domain}`}>
            {batch === null &&
              Array.from({ length: 18 }, (_, i) => (
                <div key={i} className="wall-tile sk-shimmer">
                  <span className="cover" style={{ aspectRatio: String(c.aspect), width: '100%', height: 'auto' }} />
                </div>
              ))}
            {batch?.map((t, i) => (
              <WallTile key={t.id} t={t} mark={marks[t.id]} onTap={() => tap(t.id)} delay={i * 18} />
            ))}
          </div>
          {batch && batch.length === 0 && (
            <div className="empty-note secondary">
              {domain === 'film' ? '片库没有准备好。' : '书库和曲库还没有生成，可以用上面的搜索框按名字找。'}
            </div>
          )}
        </div>
      </div>
      <div className="wall-bar">
        <div className="wall-bar-inner">
          <span className="t13 secondary" style={{ flex: 1 }}>
            {loved + disliked === 0
              ? `还没选。选 5 ${c.unit}左右最好。`
              : `喜欢 ${loved} ${c.unit}${disliked ? `，不喜欢 ${disliked} ${c.unit}` : ''}`}
          </span>
          <button className="pill-sm" onClick={() => setPage((p) => p + 1)} data-wall-more>
            换一批
          </button>
          {onSkip && (
            <button className="pill-sm dim" onClick={onSkip}>
              跳过
            </button>
          )}
          <button className="pill-accent" disabled={saving || loved + disliked === 0} onClick={finish} data-wall-done>
            {saving ? <Spinner size={14} /> : null}
            {doneLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

function WallTile({
  t,
  mark,
  onTap,
  delay = 0,
  small = false,
}: {
  t: Title
  mark?: Mark
  onTap: () => void
  delay?: number
  small?: boolean
}) {
  return (
    <button
      className={`wall-tile${mark ? ` ${mark}` : ''}${small ? ' small' : ''}`}
      onClick={onTap}
      style={{ animationDelay: `${delay}ms` }}
      aria-pressed={!!mark}
      aria-label={`${t.name}${mark === 'love' ? '，喜欢' : mark === 'dislike' ? '，不喜欢' : ''}`}
      data-wall={t.id}
    >
      <span className="wall-cover">
        <Cover t={t} width={small ? 72 : 120} />
        {mark && <span className="wall-badge">{mark === 'love' ? <HeartFillIcon size={14} /> : <XmarkIcon size={14} />}</span>}
      </span>
      <span className="wall-name">{t.name}</span>
      {!small && t.year ? <span className="wall-year">{t.year}</span> : null}
    </button>
  )
}
