import { useCallback, useEffect, useRef, useState } from 'react'
import { del, enc, get, patch, type Domain, type Item, type PassReason, type Title } from '../lib/api'
import { DOMAINS } from '../lib/domains'
import { metaLine, reltime } from '../lib/format'
import { morph } from '../lib/vt'
import Cover from '../components/Cover'
import LogPanel from '../components/LogPanel'
import StarRating, { StarsView } from '../components/StarRating'
import { ChevronLeftIcon, GridIcon, ListIcon, PlusIcon, Spinner, XmarkIcon } from '../components/Icons'
import { models, shortName } from '../lib/models'

type Kind = 'want' | 'records'

/** 片单 / 书单 / 歌单 (want) and 看过 / 读过 / 听过 (records). Records are a
 * personal log first — gallery or table, each opening a page the user can
 * edit — and recommendation signal second. */
export default function Shelf({
  domain,
  kind,
  onChanged,
}: {
  domain: Domain
  kind: Kind
  reasons?: PassReason[]
  onChanged: () => void
}) {
  const c = DOMAINS[domain]
  const [items, setItems] = useState<Item[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [page, setPage] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [layout, setLayout] = useState<'gallery' | 'table'>(() => {
    try {
      return (localStorage.getItem('pianke.records.layout') as 'gallery' | 'table') || 'gallery'
    } catch {
      return 'gallery'
    }
  })
  const [filter, setFilter] = useState<'all' | 'watched' | 'dropped'>('all')

  const load = useCallback(async () => {
    const all = await get<Item[]>(`/items?domain=${domain}`)
    const keep = all.filter((i) => (kind === 'want' ? i.status === 'want' : i.status === 'watched' || i.status === 'dropped'))
    if (kind === 'records') {
      keep.sort((a, b) => (b.done_on ?? '').localeCompare(a.done_on ?? '') || b.updated - a.updated)
    }
    setItems(keep)
  }, [domain, kind])
  useEffect(() => {
    setPage(null)
    load().catch(() => setItems([]))
  }, [load])

  const setLay = (l: 'gallery' | 'table') => {
    setLayout(l)
    try {
      localStorage.setItem('pianke.records.layout', l)
    } catch {
      /* per-viewer convenience only */
    }
  }

  if (page) {
    const it = items?.find((i) => i.id === page)
    if (it)
      return (
        <RecordPage
          it={it}
          back={() => morph(() => setPage(null))}
          onChanged={() => {
            load()
            onChanged()
          }}
          onDeleted={() => {
            morph(() => {
              setPage(null)
              load()
            })
            onChanged()
          }}
        />
      )
  }

  const shown = (items ?? []).filter((i) => filter === 'all' || i.status === filter)
  return (
    <>
      <div className="page page-wide">
        <div className="rise-in">
          <div className="title-row" style={{ marginTop: 8 }}>
            <div className="secondary page-sub" style={{ marginTop: 0 }}>
              {kind === 'want'
                ? `${c.verb}完点一下，打个分、写几句，片刻就记住了。`
                : `你写下的每句话都原样留在这台 Mac 上，口味画像从这里整理出来。`}
            </div>
            {kind === 'records' && !adding && (
              <button className="pill-sm" onClick={() => setAdding(true)} data-add>
                <PlusIcon size={14} />
                补记一{c.unit}
              </button>
            )}
          </div>
          {kind === 'records' && (items?.length ?? 0) > 0 && (
            <div className="view-bar">
              <div className="seg seg-sm">
                {(['all', 'watched', 'dropped'] as const).map((f) => (
                  <button key={f} className={filter === f ? 'on' : undefined} onClick={() => setFilter(f)}>
                    {f === 'all' ? '全部' : f === 'watched' ? c.finished : c.dropped}
                  </button>
                ))}
              </div>
              <div className="seg seg-sm seg-icons">
                <button className={layout === 'gallery' ? 'on' : undefined} onClick={() => setLay('gallery')} aria-label="画廊">
                  <GridIcon size={14} />
                </button>
                <button className={layout === 'table' ? 'on' : undefined} onClick={() => setLay('table')} aria-label="表格">
                  <ListIcon size={14} />
                </button>
              </div>
            </div>
          )}
        </div>

        {adding && (
          <AddRecord
            domain={domain}
            onCancel={() => setAdding(false)}
            onDone={() => {
              setAdding(false)
              load()
              onChanged()
            }}
          />
        )}

        <div style={{ marginTop: 16 }}>
          {items && items.length === 0 && !adding && (
            <div className="empty-note secondary">
              {kind === 'want'
                ? `${c.list}还是空的。推荐给你的${c.noun}，点“没${c.verb}”再选“想${c.verb}，先存着”就会放进来。`
                : `还没有记录。${c.verb}完一${c.unit}，回来打个分、说说感受。`}
            </div>
          )}
          {kind === 'want' &&
            items?.map((it, idx) => (
              <WantRow
                key={it.id}
                it={it}
                idx={idx}
                open={open === it.id}
                setOpen={(o) => setOpen(o ? it.id : null)}
                onDone={() => {
                  morph(() => {
                    setOpen(null)
                    load()
                  })
                  onChanged()
                }}
                onDelete={async () => {
                  await del(`/items/${enc(it.id)}`)
                  morph(() => load())
                  onChanged()
                }}
              />
            ))}
          {kind === 'records' && layout === 'gallery' && (
            <div className={`gallery gallery-${domain}`}>
              {shown.map((it, idx) => (
                <button
                  key={it.id}
                  className="gal-card"
                  style={{ animationDelay: `${Math.min(idx, 16) * 25}ms` }}
                  onClick={() => morph(() => setPage(it.id))}
                  data-record={it.id}
                >
                  <Cover t={it.title} id={it.id} width={domain === 'music' ? 150 : 132} />
                  <span className="gal-name film-name">{it.title?.name ?? it.id}</span>
                  <span className="gal-meta">
                    {it.rating != null ? <StarsView n={it.rating} size={11} /> : <span className="secondary">未评分</span>}
                    {it.status === 'dropped' && <span className="secondary">{c.dropped}</span>}
                  </span>
                  {it.words && <span className="gal-words">{it.words.split('\n').slice(-1)[0]}</span>}
                </button>
              ))}
            </div>
          )}
          {kind === 'records' && layout === 'table' && (
            <div className="rtable" role="table">
              <div className="rtable-row rtable-head" role="row">
                <span>名称</span>
                <span>评分</span>
                <span>日期</span>
                <span>评语</span>
              </div>
              {shown.map((it) => (
                <button key={it.id} className="rtable-row" role="row" onClick={() => morph(() => setPage(it.id))}>
                  <span className="rtable-name">
                    <Cover t={it.title} id={it.id} width={22} radius={3} />
                    <span className="film-name">{it.title?.name ?? it.id}</span>
                    {it.status === 'dropped' && <span className="tag tag-ctx">{c.dropped}</span>}
                  </span>
                  <span>{it.rating != null ? <StarsView n={it.rating} size={11} /> : <span className="secondary">—</span>}</span>
                  <span className="secondary">{it.done_on ?? reltime(it.updated)}</span>
                  <span className="rtable-words">{it.words.split('\n').slice(-1)[0]}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// ------------------------------------------------------------ want list

function WantRow({
  it,
  idx,
  open,
  setOpen,
  onDone,
  onDelete,
}: {
  it: Item
  idx: number
  open: boolean
  setOpen: (o: boolean) => void
  onDone: () => void
  onDelete: () => void
}) {
  const t = it.title
  const c = DOMAINS[it.domain]
  const name = t?.name ?? it.id
  return (
    <div className={`shelf-row${open ? ' open' : ''}`} style={{ animationDelay: `${Math.min(idx, 10) * 30}ms` }} data-row={it.id}>
      <Cover t={t} id={it.id} width={52} />
      <div className="shelf-main">
        <div className="shelf-name film-name">{name}</div>
        <div className="shelf-meta">
          {t ? metaLine(t) : ''}，{reltime(it.updated)}加入
        </div>
        {open && (
          <LogPanel
            id={it.id}
            name={name}
            domain={it.domain}
            origin={it.source === 'rec' ? 'rec' : 'past'}
            onCancel={() => setOpen(false)}
            onDone={onDone}
          />
        )}
      </div>
      {!open && (
        <div className="shelf-actions">
          <button className="pill-sm" onClick={() => setOpen(true)} data-done={it.id}>
            {c.finished}
          </button>
          <button className="icon-btn" aria-label={`从${c.list}移除`} onClick={onDelete}>
            <XmarkIcon size={14} />
          </button>
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------ record page

function RecordPage({
  it,
  back,
  onChanged,
  onDeleted,
}: {
  it: Item
  back: () => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const c = DOMAINS[it.domain]
  const t = it.title
  const [cur, setCur] = useState<Item>(it)
  const [words, setWords] = useState(it.words)
  const [saving, setSaving] = useState<null | 'words' | 'field'>(null)
  const [confirm, setConfirm] = useState(false)
  const area = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight + 2}px`
  }, [words])

  const save = async (body: Record<string, unknown>, what: 'words' | 'field' = 'field') => {
    setSaving(what)
    try {
      const next = await patch<Item>(`/items/${enc(it.id)}`, body)
      setCur(next)
      if (what === 'words') setWords(next.words)
      onChanged()
    } finally {
      setSaving(null)
    }
  }
  const ctx = [cur.context?.mood, cur.context?.with].filter(Boolean) as string[]
  const origin =
    cur.origin === 'rec' ? `按片刻的推荐${c.verb}的` : cur.origin === 'onboard' ? '第一次认识时在封面墙上点的' : cur.origin === 'past' ? `以前就${c.done}` : '—'

  return (
    <div className="page record-page">
      <button className="back-link t13" onClick={back}>
        <ChevronLeftIcon size={12} />
        {c.done}
      </button>
      <div className="record-top rise-in">
        <Cover t={t} id={it.id} width={it.domain === 'music' ? 180 : 156} />
        <div className="record-head">
          <h1 className="page-title film-name">{t?.name ?? it.id}</h1>
          <div className="secondary" style={{ marginTop: 4 }}>
            {t ? [t.original !== t.name ? t.original : '', metaLine(t)].filter(Boolean).join('，') : ''}
          </div>
          <div className="pick-props record-props">
            <div className="prop-row">
              <span className="prop-label">状态</span>
              <span className="prop-value">
                <span className="seg seg-sm">
                  {(['watched', 'dropped'] as const).map((s) => (
                    <button key={s} className={cur.status === s ? 'on' : undefined} onClick={() => save({ status: s })}>
                      {s === 'watched' ? c.finished : c.dropped}
                    </button>
                  ))}
                </span>
              </span>
            </div>
            <div className="prop-row">
              <span className="prop-label">评分</span>
              <span className="prop-value">
                <StarRating
                  value={cur.rating}
                  size={20}
                  onChange={(v) => save(v == null ? { clear_rating: true } : { rating: v })}
                />
              </span>
            </div>
            <div className="prop-row">
              <span className="prop-label">日期</span>
              <span className="prop-value">
                <input
                  type="date"
                  className="prop-date"
                  value={cur.done_on ?? ''}
                  onChange={(e) => e.target.value && save({ done_on: e.target.value })}
                />
              </span>
            </div>
            <div className="prop-row">
              <span className="prop-label">来由</span>
              <span className="prop-value">{origin}</span>
            </div>
            {(cur.liked.length > 0 || cur.disliked.length > 0 || ctx.length > 0) && (
              <div className="prop-row">
                <span className="prop-label">片刻听到</span>
                <span className="prop-value">
                  <span className="tags" style={{ marginTop: 0 }}>
                    {cur.liked.map((l, i) => (
                      <span key={`l${i}`} className="tag tag-like">
                        {l}
                      </span>
                    ))}
                    {cur.disliked.map((l, i) => (
                      <span key={`d${i}`} className="tag tag-dislike">
                        {l}
                      </span>
                    ))}
                    {ctx.map((v, i) => (
                      <span key={`c${i}`} className="tag tag-ctx">
                        {v}
                      </span>
                    ))}
                  </span>
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      <h2 className="section-h">评语</h2>
      <textarea
        ref={area}
        className="record-words"
        placeholder={`写点什么。喜欢哪里，哪里不对胃口，和谁一起${c.verb}的，${c.verb}的时候是什么状态。`}
        value={words}
        onChange={(e) => setWords(e.target.value)}
        onBlur={() => words.trim() !== (cur.words ?? '').trim() && save({ words }, 'words')}
        data-record-words
      />
      <div className="t13 secondary record-save">
        {saving === 'words' ? (
          <>
            <Spinner size={12} />
            {shortName(models().small)} 正在{models().onDevice ? '本机' : ''}重读你的评语
          </>
        ) : saving === 'field' ? (
          '正在保存'
        ) : (
          '离开输入框时自动保存。原话逐字保存，片刻只在旁边加标签。'
        )}
      </div>

      <div className="record-foot">
        {confirm ? (
          <span className="flex" style={{ gap: 8 }}>
            <button className="pill-sm dim" onClick={() => setConfirm(false)}>
              取消
            </button>
            <button
              className="pill-sm danger"
              onClick={async () => {
                await del(`/items/${enc(it.id)}`)
                onDeleted()
              }}
            >
              确认删除这条记录
            </button>
          </span>
        ) : (
          <button className="pill-sm dim" onClick={() => setConfirm(true)}>
            删除记录
          </button>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------ add a record

function AddRecord({ domain, onCancel, onDone }: { domain: Domain; onCancel: () => void; onDone: () => void }) {
  const c = DOMAINS[domain]
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<Title[]>([])
  const [busy, setBusy] = useState(false)
  const [picked, setPicked] = useState<Title | null>(null)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    ref.current?.focus()
  }, [])
  useEffect(() => {
    if (!q.trim()) {
      setHits([])
      return
    }
    const id = setTimeout(
      () => {
        setBusy(true)
        get<Title[]>(`/search?q=${encodeURIComponent(q)}&domain=${domain}`)
          .then(setHits)
          .catch(() => setHits([]))
          .finally(() => setBusy(false))
      },
      domain === 'film' ? 160 : 400
    )
    return () => clearTimeout(id)
  }, [q, domain])

  if (picked) {
    return (
      <div className="shelf-row open" style={{ marginTop: 24 }}>
        <Cover t={picked} width={52} />
        <div className="shelf-main">
          <div className="shelf-name film-name">{picked.name}</div>
          <div className="shelf-meta">{metaLine(picked)}</div>
          <LogPanel id={picked.id} name={picked.name} domain={domain} origin="past" onCancel={onCancel} onDone={onDone} />
        </div>
      </div>
    )
  }
  return (
    <div className="search-wrap rise-in">
      <input
        ref={ref}
        className="search-input"
        placeholder={domain === 'film' ? '在本机片库里搜片名、导演或演员' : `搜${c.noun}名或${domain === 'book' ? '作者' : '歌手'}，书库里没有的会到网上按名字查`}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && onCancel()}
        data-search
      />
      {busy && hits.length === 0 && (
        <div className="t13 secondary" style={{ padding: '8px 4px' }}>
          正在查找
        </div>
      )}
      <div className="search-results">
        {hits.map((h) => (
          <button key={h.id} className="search-hit search-hit-cover" onClick={() => setPicked(h)} data-hit={h.id}>
            <Cover t={h} width={32} radius={3} />
            <span style={{ minWidth: 0 }}>
              <span className="film-name" style={{ fontSize: 17, display: 'block' }}>
                {h.name}
              </span>
              <span className="t13 secondary">
                {h.original && h.original !== h.name ? `${h.original}，` : ''}
                {metaLine(h)}
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
