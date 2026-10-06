import type { PastRec } from '../App'
import type { Domain, Status } from '../lib/api'
import { DOMAINS, DOMAIN_ORDER } from '../lib/domains'
import { reltime } from '../lib/format'
import { BookFillIcon, GearFillIcon, MoonFillIcon, MusicNoteFillIcon, SparklesFillIcon } from './Icons'

export type View = Domain | 'profile' | 'settings'

const ICON: Record<Domain, (s: number) => React.ReactNode> = {
  film: (s) => <MoonFillIcon size={s} />,
  book: (s) => <BookFillIcon size={s} />,
  music: (s) => <MusicNoteFillIcon size={s} />,
}

export default function Sidebar({
  view,
  setView,
  status,
  recs,
  openRec,
  activeRec,
}: {
  view: View
  setView: (v: View) => void
  status: Status
  recs: PastRec[]
  openRec: (r: PastRec) => void
  activeRec: number | null
}) {
  return (
    <aside className="glass-sidebar">
      <div className="drag-strip" style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 52 }} />
      <div className="side-inner">
        <div className="side-group">
          {DOMAIN_ORDER.map((d) => {
            const c = DOMAINS[d]
            const n = status.domain_counts[d]
            const fresh = !status.domains_onboarded.includes(d)
            return (
              <button
                key={d}
                className={`side-row${view === d && activeRec === null ? ' sel' : ''}`}
                onClick={() => setView(d)}
                data-nav={d}
              >
                <span className="side-ic side-ic-hue" style={{ color: c.color }}>
                  {ICON[d](17)}
                </span>
                <span>{c.label}</span>
                {fresh ? (
                  <span className="side-new">认识一下</span>
                ) : n.want ? (
                  <span className="side-count" title={`${c.list}里有 ${n.want} ${c.unit}`}>
                    {n.want}
                  </span>
                ) : null}
              </button>
            )
          })}
          <button
            className={`side-row${view === 'profile' ? ' sel' : ''}`}
            onClick={() => setView('profile')}
            data-nav="profile"
            style={{ marginTop: 8 }}
          >
            <span className="side-ic side-ic-hue" style={{ color: 'var(--tile-purple)' }}>
              <SparklesFillIcon size={17} />
            </span>
            <span>口味画像</span>
            {status.stale >= 3 ? <span className="side-badge" aria-label="有新记录待整理" /> : null}
          </button>
        </div>

        {recs.length > 0 && (
          <div className="side-group" style={{ minHeight: 0, overflowY: 'auto' }}>
            <div className="group-label" style={{ padding: '8px 10px 4px' }}>
              最近的推荐
            </div>
            {recs.slice(0, 10).map((r) => {
              const d = (r.domain ?? 'film') as Domain
              return (
                <button
                  key={r.id}
                  className={`hist-row${activeRec === r.id ? ' sel' : ''}`}
                  onClick={() => openRec(r)}
                  style={{ padding: '6px 10px', display: 'flex', gap: 8, alignItems: 'flex-start' }}
                >
                  <span className="side-ic side-ic-hue" style={{ color: DOMAINS[d].color, marginTop: 3 }}>
                    {ICON[d](13)}
                  </span>
                  <span className="hist-row-main" style={{ display: 'block', minWidth: 0 }}>
                    <span className="hist-row-name t13" style={{ fontSize: 15 }}>
                      {r.picks.map((p) => p.name).join('、')}
                    </span>
                    <span className="hist-dir">{reltime(r.ts)}</span>
                  </span>
                </button>
              )
            })}
          </div>
        )}

        <div className="side-foot">
          {status.models.map((m) => (
            <div key={m.key} className="model-chip" title={m.error ?? undefined}>
              <span
                className={`status-dot ${m.status === 'ready' ? 'ready' : m.status === 'loading' ? 'loading' : m.status === 'stopped' ? '' : 'error'}`}
              />
              <span>{m.name.replace('Spark-X2.5-', 'Spark ')}</span>
              <span style={{ marginLeft: 'auto' }}>
                {m.status === 'ready' ? '本机' : m.status === 'loading' ? '加载中' : m.status === 'missing' ? '缺文件' : m.status === 'error' ? '出错' : '未启动'}
              </span>
            </div>
          ))}
          <button
            className={`side-row${view === 'settings' ? ' sel' : ''}`}
            onClick={() => setView('settings')}
            data-nav="settings"
          >
            <span className="side-ic">
              <GearFillIcon size={17} />
            </span>
            <span>设置</span>
          </button>
        </div>
      </div>
    </aside>
  )
}
