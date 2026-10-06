import { useCallback, useEffect, useState } from 'react'
import { enc, get, post, type Domain, type PassReason, type Title } from '../lib/api'
import { DOMAINS } from '../lib/domains'
import Cover from './Cover'
import LogPanel from './LogPanel'
import PassPanel from './PassPanel'

interface Checkin {
  id: string
  domain: Domain
  rec_id: number
  ts: number
  on_list: boolean
  title: Title
}

function when(ts: number, domain: Domain): string {
  const d = new Date(ts * 1000)
  const now = new Date()
  const days = Math.round(
    (new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() -
      new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) /
      86400_000
  )
  const night = d.getHours() >= 18 || d.getHours() < 4
  if (days <= 0) return domain === 'music' ? '早些时候' : '今天早些时候'
  if (days === 1) return night ? '昨晚' : '昨天'
  if (days === 2) return '前天'
  return `${days} 天前`
}

/** The day-after question: "昨晚的《无间道》看了吗？" — asked once per pick,
 * for picks the user put on the list or the latest night left untouched. */
export default function CheckinCard({
  domain,
  reasons,
  onChanged,
}: {
  domain: Domain
  reasons: PassReason[]
  onChanged: () => void
}) {
  const [items, setItems] = useState<Checkin[]>([])
  const [open, setOpen] = useState<{ id: string; mode: 'log' | 'pass' } | null>(null)
  const [gone, setGone] = useState<Record<string, string>>({})
  const c = DOMAINS[domain]

  const load = useCallback(() => {
    get<Checkin[]>(`/checkins?domain=${domain}`).then(setItems).catch(() => setItems([]))
  }, [domain])
  useEffect(load, [load])

  const visible = items.filter((x) => !gone[x.id] || gone[x.id] !== 'hidden')
  if (!visible.length) return null

  const done = (id: string, note: string) => {
    setOpen(null)
    setGone((g) => ({ ...g, [id]: note }))
    setTimeout(() => setGone((g) => ({ ...g, [id]: 'hidden' })), 1600)
    onChanged()
  }

  return (
    <div className="checkin rise-in" data-checkin>
      {visible.map((x) => {
        const note = gone[x.id]
        return (
          <div key={x.id} className="checkin-row">
            <Cover t={x.title} width={44} />
            <div className="checkin-main">
              {note ? (
                <div className="checkin-q secondary">{note}</div>
              ) : (
                <div className="checkin-q">
                  {when(x.ts, domain)}的<span className="film-name">《{x.title.name}》</span>
                  {c.verb}了吗？
                </div>
              )}
              {!note && open?.id === x.id && open.mode === 'log' && (
                <LogPanel
                  id={x.id}
                  name={x.title.name}
                  domain={domain}
                  origin="rec"
                  onCancel={() => setOpen(null)}
                  onDone={() => done(x.id, '记下了，谢谢。')}
                />
              )}
              {!note && open?.id === x.id && open.mode === 'pass' && (
                <PassPanel
                  id={x.id}
                  domain={domain}
                  reasons={reasons.filter((r) => !(x.on_list && r.effect === 'want'))}
                  recId={x.rec_id}
                  onCancel={() => setOpen(null)}
                  onDone={(r) => done(x.id, r.effect === 'want' ? `留在${c.list}里了。` : '记下了。')}
                />
              )}
            </div>
            {!note && open?.id !== x.id && (
              <div className="checkin-actions">
                <button className="pill-sm" onClick={() => setOpen({ id: x.id, mode: 'log' })} data-checkin-yes>
                  {c.verb}了
                </button>
                <button className="pill-sm" onClick={() => setOpen({ id: x.id, mode: 'pass' })}>
                  没{c.verb}
                </button>
                <button
                  className="pill-sm dim"
                  onClick={async () => {
                    await post(`/checkins/${enc(x.id)}/dismiss`)
                    done(x.id, x.on_list ? `还在${c.list}里，不再追问。` : '好，不再追问。')
                  }}
                >
                  还没顾上
                </button>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
