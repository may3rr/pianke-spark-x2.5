import type { PastRec } from '../App'
import type { Domain, Status } from '../lib/api'
import { DOMAINS, DOMAIN_ORDER } from '../lib/domains'
import { reltime } from '../lib/format'
import { BookFillIcon, GearFillIcon, MagnifierIcon, MoonFillIcon, MusicNoteFillIcon, SparklesFillIcon, Spinner } from './Icons'
import { modelDot, modelStatusLabel, shortName } from '../lib/models'
import { hasUpdate, useUpdate } from '../lib/update'
import { useDemo } from '../lib/demo'

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
  shelfState,
  onFind,
}: {
  view: View
  setView: (v: View) => void
  status: Status
  recs: PastRec[]
  openRec: (r: PastRec) => void
  activeRec: number | null
  /** a recommendation is running on the shelf, or finished while the user was elsewhere */
  shelfState: Record<Domain, 'running' | 'done' | null>
  onFind: () => void
}) {
  const update = useUpdate()
  const demo = useDemo()
  return (
    <aside className="glass-sidebar">
      <div className="drag-strip" style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 52 }} />
      <div className="side-inner">
        <div className="side-group">
          <button className="side-row side-find" onClick={onFind} data-nav="find">
            <span className="side-ic">
              <MagnifierIcon size={15} />
            </span>
            <span>找作品</span>
            <span className="side-key">⌘K</span>
          </button>
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
                {shelfState[d] === 'running' ? (
                  <span className="side-spin" title={`正在${c.pick3}`}>
                    <Spinner size={12} />
                  </span>
                ) : shelfState[d] === 'done' ? (
                  <span className="side-badge" title={`${c.pickTitle}挑好了`} data-shelf-done={d} />
                ) : fresh ? (
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
            {status.profile_auto ? (
              <span className="side-spin" title="正在整理画像">
                <Spinner size={12} />
              </span>
            ) : status.profile_unseen ? (
              <span className="side-badge" title="画像刚更新过" />
            ) : null}
          </button>
        </div>

        {recs.length > 0 && (
          <div className="side-group" style={{ minHeight: 0, overflowY: 'auto' }}>
            <div className="group-label" style={{ padding: '8px 10px 4px' }}>
              最近的推荐
            </div>
            {recs.slice(0, 10).map((r) => {
              const d = (r.domain ?? 'film') as Domain
              const said = [r.request.text, ...Object.values(r.request.chips || {})].filter(Boolean).join('，')
              const names = r.picks.map((p) => p.name).join('、')
              return (
                <button
                  key={r.id}
                  className={`hist-row${activeRec === r.id ? ' sel' : ''}`}
                  onClick={() => openRec(r)}
                  title={`${reltime(r.ts)}，${names}`}
                  style={{ padding: '6px 10px', display: 'flex', gap: 8, alignItems: 'flex-start' }}
                >
                  <span className="side-ic side-ic-hue" style={{ color: DOMAINS[d].color, marginTop: 3 }}>
                    {ICON[d](13)}
                  </span>
                  <span className="hist-row-main" style={{ display: 'block', minWidth: 0 }}>
                    <span className="hist-row-name t13" style={{ fontSize: 15 }}>
                      {said || names}
                    </span>
                    <span className="hist-dir">{said ? names : reltime(r.ts)}</span>
                  </span>
                </button>
              )
            })}
          </div>
        )}

        <div className="side-foot">
          {demo ? (
            status.models.map((m) => (
              <div key={m.key} className="model-chip" title={m.error ?? `${m.name}，${modelStatusLabel(m)}`}>
                <span className={`status-dot ${modelDot(m)}`} />
                <span className="truncate">{shortName(m.name)}</span>
                <span style={{ marginLeft: 'auto', flexShrink: 0 }}>{m.provider === 'api' ? '接口' : modelStatusLabel(m)}</span>
              </div>
            ))
          ) : (
            <ModelLine status={status} onOpen={() => setView('settings')} />
          )}
          <button
            className={`side-row${view === 'settings' ? ' sel' : ''}`}
            onClick={() => setView('settings')}
            data-nav="settings"
          >
            <span className="side-ic">
              <GearFillIcon size={17} />
            </span>
            <span>设置</span>
            {hasUpdate(update) && <span className="update-dot" title={`有新版本 ${update.version}`} data-update-dot />}
          </button>
        </div>
      </div>
    </aside>
  )
}

/** One quiet line: where the model runs, and whether it's usable. Details
 *  sit in the tooltip and in Settings. */
function ModelLine({ status, onOpen }: { status: Status; onOpen: () => void }) {
  const ms = status.models
  const bad = ms.find((m) => m.status === 'error' || m.status === 'missing' || (m.provider === 'api' && m.status !== 'ready'))
  const loading = ms.some((m) => m.status === 'loading')
  const api = status.llm?.mode === 'api'
  const dot = bad ? 'error' : loading ? 'loading' : ms.every((m) => m.status === 'ready') ? 'ready' : ''
  const label = bad ? (api ? '接口没配好' : '模型出错') : loading ? '模型加载中' : api ? '远程接口' : '本机模型'
  const tip = ms.map((m) => `${m.name}：${m.error ?? (m.provider === 'api' ? m.host : modelStatusLabel(m))}`).join('\n')
  return (
    <button className="model-chip model-line" title={tip} onClick={onOpen} data-model-line>
      <span className={`status-dot ${dot}`} />
      <span className="truncate">{label}</span>
    </button>
  )
}
