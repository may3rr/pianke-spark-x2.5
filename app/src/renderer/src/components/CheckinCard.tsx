import { useCallback, useEffect, useState } from 'react'
import { enc, get, post, type Domain, type PassReason, type Title } from '../lib/api'
import { DOMAINS } from '../lib/domains'
import Cover from './Cover'
import LogPanel from './LogPanel'
import PassPanel from './PassPanel'

interface ItemCheckin {
  kind: 'item'
  id: string
  domain: Domain
  rec_id: number
  ts: number
  on_list: boolean
  chosen: boolean
  title: Title
}
interface NightCheckin {
  kind: 'night'
  id: string
  domain: Domain
  rec_id: number
  ts: number
  titles: Title[]
}
type Checkin = ItemCheckin | NightCheckin

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

/** The day-after question. It asks about the pick the user chose (就看这部)
 * or saved for later; a night they did nothing with gets one question about
 * the night, with its three covers to tap, instead of one per pick. */
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
  const [open, setOpen] = useState<{ id: string; mode: 'log' | 'pass'; work?: Title } | null>(null)
  const [gone, setGone] = useState<Record<string, string>>({})
  const c = DOMAINS[domain]

  const load = useCallback(() => {
    get<Checkin[]>(`/checkins?domain=${domain}`).then(setItems).catch(() => setItems([]))
  }, [domain])
  useEffect(load, [load])

  const visible = items.filter((x) => gone[x.id] !== 'hidden')
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
        if (x.kind === 'night') {
          const logging = open?.id === x.id && open.work
          return (
            <div key={x.id} className="checkin-row checkin-night">
              <div className="checkin-main">
                {note ? (
                  <div className="checkin-q secondary">{note}</div>
                ) : (
                  <>
                    <div className="checkin-q">
                      {when(x.ts, domain)}挑的三{c.unit}，{c.verb}了其中一{c.unit}吗？
                      {!logging && <span className="secondary">点它的封面记一下。</span>}
                    </div>
                    {!logging && (
                      <div className="checkin-covers">
                        {x.titles.map((t) => (
                          <button
                            key={t.id}
                            className="checkin-cover"
                            onClick={() => setOpen({ id: x.id, mode: 'log', work: t })}
                            data-checkin-pick={t.id}
                          >
                            <Cover t={t} width={56} />
                            <span className="checkin-cover-name film-name">{t.name}</span>
                          </button>
                        ))}
                      </div>
                    )}
                    {logging && open.work && (
                      <LogPanel
                        id={open.work.id}
                        name={open.work.name}
                        domain={domain}
                        origin="rec"
                        onCancel={() => setOpen(null)}
                        onDone={() => done(x.id, '记下了，谢谢。')}
                      />
                    )}
                  </>
                )}
              </div>
              {!note && !logging && (
                <div className="checkin-actions">
                  <button
                    className="pill-sm"
                    onClick={async () => {
                      await post(`/checkins/night/${x.rec_id}/dismiss`)
                      done(x.id, '好，这次就算了。')
                    }}
                    data-checkin-none
                  >
                    都没{c.verb}
                  </button>
                </div>
              )}
            </div>
          )
        }
        const lead = x.chosen ? `${when(x.ts, domain)}选的` : x.on_list ? `存进${c.list}的` : `${when(x.ts, domain)}的`
        return (
          <div key={x.id} className="checkin-row">
            <Cover t={x.title} width={44} />
            <div className="checkin-main">
              {note ? (
                <div className="checkin-q secondary">{note}</div>
              ) : (
                <div className="checkin-q">
                  {lead}
                  <span className="film-name">《{x.title.name}》</span>
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
                  reasons={reasons}
                  effects={['taste']}
                  recId={x.rec_id}
                  onCancel={() => setOpen(null)}
                  onDone={() => done(x.id, x.on_list ? `从${c.list}里拿掉了。` : '记下了。')}
                />
              )}
            </div>
            {!note && open?.id !== x.id && (
              <div className="checkin-actions">
                <button className="pill-sm" onClick={() => setOpen({ id: x.id, mode: 'log' })} data-checkin-yes>
                  {c.verb}了
                </button>
                <button
                  className="pill-sm"
                  onClick={async () => {
                    const r = await post<{ again: boolean; days?: number }>(`/checkins/${enc(x.id)}/snooze`)
                    done(x.id, r.again ? `好，过 ${r.days} 天再问。` : x.on_list ? `还在${c.list}里，不再追问。` : '好，不再追问。')
                  }}
                  data-checkin-later
                >
                  过几天再问
                </button>
                <button className="pill-sm dim" onClick={() => setOpen({ id: x.id, mode: 'pass' })}>
                  不想{c.verb}了
                </button>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
