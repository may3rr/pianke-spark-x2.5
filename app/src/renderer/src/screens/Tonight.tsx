import { useEffect, useRef, useState } from 'react'
import { enc, get, post, type Domain, type Item, type PassReason, type Pick, type RecResult, stream } from '../lib/api'
import { doubanUrl, greeting, kindLabel, nightLabel, runtimeLabel, votes } from '../lib/format'
import { DOMAINS } from '../lib/domains'
import { morph } from '../lib/vt'
import {
  BookFillIcon,
  BooksFillIcon,
  CheckDraw,
  CpuFillIcon,
  FilmFillIcon,
  LockFillIcon,
  MoonFillIcon,
  MusicNoteFillIcon,
  QuoteFillIcon,
  SparklesFillIcon,
  Spinner,
  Tile,
} from '../components/Icons'
import CheckinCard from '../components/CheckinCard'
import Cover from '../components/Cover'
import CopyButton from '../components/CopyButton'
import LogPanel from '../components/LogPanel'
import PassPanel from '../components/PassPanel'
import { models } from '../lib/models'
import { useDemo } from '../lib/demo'
import { Build, Interview } from './Onboarding'

export function domainIcon(d: Domain, size: number) {
  return d === 'film' ? <MoonFillIcon size={size} /> : d === 'book' ? <BookFillIcon size={size} /> : <MusicNoteFillIcon size={size} />
}

type StepKey = 'read' | 'direction' | 'search' | 'pick'
interface StepState {
  status: 'wait' | 'running' | 'done'
  detail?: string
}
interface Seed {
  name: string
  year: number | null
  status: 'verified' | 'seen' | 'missing'
  online?: boolean
}

export interface TonightState {
  phase: 'compose' | 'running' | 'result'
  text: string
  chips: Record<string, string>
  /** pick only from the user's own list */
  fromList?: boolean
  startedAt?: number
  /** when the result arrived; the sidebar marks a shelf whose result came in while the user was elsewhere */
  doneAt?: number
  steps?: Record<StepKey, StepState>
  seeds?: Seed[]
  pool?: number
  direction?: string
  error?: string
  result?: RecResult
}

const steps = (d: Domain): { key: StepKey; label: string; color: string; icon: React.ReactNode }[] => [
  { key: 'read', label: '读你的口味画像', color: 'var(--tile-purple)', icon: <SparklesFillIcon size={13} /> },
  { key: 'direction', label: d === 'film' ? '想今晚的方向' : '想想方向', color: 'var(--tile-indigo)', icon: <MoonFillIcon size={13} /> },
  { key: 'search', label: DOMAINS[d].verifyStep, color: 'var(--tile-teal)', icon: <BooksFillIcon size={13} /> },
  { key: 'pick', label: `挑出三${DOMAINS[d].unit}`, color: 'var(--tile-blue)', icon: <FilmFillIcon size={13} /> },
]

// one run per shelf; kept outside the component so 取消 still reaches a run
// started before the user looked at another shelf
const controllers: Partial<Record<Domain, AbortController>> = {}

const fresh = (): Record<StepKey, StepState> => ({
  read: { status: 'wait' },
  direction: { status: 'wait' },
  search: { status: 'wait' },
  pick: { status: 'wait' },
})

export default function Tonight({
  domain,
  state,
  setState,
  name,
  reasons,
  wantCount,
  talked,
  eta,
  onChanged,
}: {
  domain: Domain
  state: TonightState
  setState: React.Dispatch<React.SetStateAction<TonightState>>
  name: string
  reasons: PassReason[]
  wantCount: number
  talked: boolean
  eta: number | null
  onChanged: () => void
}) {
  const run = async (text: string, chips: Record<string, string>, fromList = false) => {
    controllers[domain]?.abort()
    const ctl = new AbortController()
    controllers[domain] = ctl
    morph(() =>
      setState({
        phase: 'running',
        text,
        chips,
        fromList,
        startedAt: Date.now(),
        steps: fresh(),
        seeds: [],
        pool: undefined,
        direction: undefined,
      })
    )
    let result: RecResult | null = null
    try {
      await stream('/recommend', { text, chips, domain, from_list: fromList }, (ev) => {
        if (ev.type === 'step') {
          setState((s) => ({
            ...s,
            steps: { ...(s.steps ?? fresh()), [ev.key]: { status: ev.status, detail: ev.detail } },
            ...(ev.direction ? { direction: ev.direction } : {}),
            ...(ev.pool ? { pool: ev.pool } : {}),
          }))
        } else if (ev.type === 'seed') {
          setState((s) => ({ ...s, seeds: [...(s.seeds ?? []), { name: ev.name, year: ev.year, status: ev.status, online: ev.online }] }))
        } else if (ev.type === 'result') {
          result = ev as RecResult
        } else if (ev.type === 'error') {
          setState((s) => ({ ...s, error: ev.message }))
        }
      }, ctl.signal)
    } catch (e) {
      if (ctl.signal.aborted) return
      setState((s) => ({ ...s, error: `挑片没有完成：${(e as Error).message}` }))
      return
    } finally {
      if (controllers[domain] === ctl) delete controllers[domain]
    }
    if (ctl.signal.aborted) return
    if (result) {
      const r = result
      // let the last check draw before the page turns
      setTimeout(() => {
        morph(() => setState((s) => (s.phase === 'running' ? { ...s, phase: 'result', result: r, doneAt: Date.now() } : s)))
        onChanged()
      }, 700)
    }
  }
  const back = () => {
    controllers[domain]?.abort()
    morph(() => setState((s) => ({ ...s, phase: 'compose', error: undefined })))
  }

  if (state.phase === 'compose')
    return (
      <Compose
        domain={domain}
        state={state}
        setState={setState}
        name={name}
        run={run}
        reasons={reasons}
        wantCount={wantCount}
        talked={talked}
        onChanged={onChanged}
      />
    )
  if (state.phase === 'running') return <Running domain={domain} state={state} eta={eta} back={back} />
  return (
    <Result
      domain={(state.result?.domain as Domain) ?? domain}
      state={state}
      reasons={reasons}
      rerun={() => run(state.text, state.chips, !!state.fromList)}
      onChanged={onChanged}
      newNight={() => morph(() => setState({ phase: 'compose', text: '', chips: {} }))}
    />
  )
}

// ------------------------------------------------------------ compose

function Compose({
  domain,
  state,
  setState,
  name,
  run,
  reasons,
  wantCount,
  talked,
  onChanged,
}: {
  domain: Domain
  state: TonightState
  setState: React.Dispatch<React.SetStateAction<TonightState>>
  name: string
  run: (t: string, c: Record<string, string>, fromList?: boolean) => void
  reasons: PassReason[]
  wantCount: number
  talked: boolean
  onChanged: () => void
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  // empty is allowed: the backend reads it as "no special request" and picks from the profile
  const listOk = wantCount >= 3
  const go = () => run(state.text.trim(), state.chips, listOk && !!state.fromList)
  const c = DOMAINS[domain]
  const [talk, setTalk] = useState<'talk' | 'build' | null>(null)
  const [later, setLater] = useState(() => {
    try {
      return localStorage.getItem('pianke.talkLater') === '1'
    } catch {
      return false
    }
  })
  if (talk)
    return (
      <div className="domain-onboard">
        {talk === 'talk' ? (
          <Interview name={name} domains={[domain]} greet={false} onComplete={() => setTalk('build')} onLeave={() => setTalk(null)} />
        ) : (
          <Build
            leaving={false}
            doneLabel={`回去${c.pick3}`}
            onDone={() => {
              setTalk(null)
              onChanged()
            }}
          />
        )}
      </div>
    )
  return (
    <>
      <div className="compose rise-in">
        <CheckinCard domain={domain} reasons={reasons} onChanged={onChanged} />
        {!talked && !later && (
          <div className="callout talk-card" data-talk-card>
            <span className="said-ic" style={{ marginTop: 3 }}>
              <SparklesFillIcon size={15} />
            </span>
            <div style={{ flex: 1 }}>
              多聊两句，推荐会更准。说说喜欢的作品打动你的地方、平时什么时候{c.verb}、有什么绝对不碰，大概两分钟。
            </div>
            <span className="flex" style={{ gap: 8, flex: 'none' }}>
              <button className="pill-sm" onClick={() => setTalk('talk')} data-talk-start>
                聊两句
              </button>
              <button
                className="pill-sm dim"
                onClick={() => {
                  try {
                    localStorage.setItem('pianke.talkLater', '1')
                  } catch {
                    /* asks again next launch */
                  }
                  setLater(true)
                }}
              >
                以后再说
              </button>
            </span>
          </div>
        )}
        <Tile color={c.color} size={44} icon={domainIcon(domain, 24)} />
        <h1 className="t26" style={{ fontWeight: 600, margin: '24px 0 0' }}>
          {domain === 'film' ? greeting(name) : `${greeting(name)}。${c.ask}？`}
        </h1>
        <div className="secondary" style={{ marginTop: 8 }}>
          {c.composeHint}
        </div>
        <div className="compose-box">
          <textarea
            ref={ref}
            className="compose-input"
            placeholder={c.placeholder}
            value={state.text}
            onChange={(e) => setState((s) => ({ ...s, text: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) go()
            }}
            data-compose
          />
          <div className="chip-rows">
            {c.chips.map((row) => (
              <div key={row.key} className="chip-row">
                <span className="chip-label">{row.key}</span>
                {row.options.map((o) => (
                  <button
                    key={o}
                    className={`chip${state.chips[row.key] === o ? ' on' : ''}`}
                    onClick={() =>
                      setState((s) => {
                        const c = { ...s.chips }
                        if (c[row.key] === o) delete c[row.key]
                        else c[row.key] = o
                        return { ...s, chips: c }
                      })
                    }
                    data-chip={o}
                  >
                    {o}
                  </button>
                ))}
              </div>
            ))}
            {listOk && (
              <div className="chip-row">
                <span className="chip-label">{c.list}</span>
                <button
                  className={`chip${state.fromList ? ' on' : ''}`}
                  onClick={() => setState((s) => ({ ...s, fromList: !s.fromList }))}
                  data-chip-list
                >
                  只从{c.list}里挑，{wantCount} {c.unit}
                </button>
              </div>
            )}
          </div>
          <div className="compose-actions">
            <span className="offline-note">
              <LockFillIcon size={13} />
              {models().onDevice ? '你的话和记录只在这台 Mac 上，由本机模型处理' : `你的话会发给 ${models().host} 上的模型处理，记录只存在这台 Mac 上`}
            </span>
            <button className="pill-accent" onClick={go} data-go>
              {c.pick3}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

// ------------------------------------------------------------ running

function Running({ domain, state, eta, back }: { domain: Domain; state: TonightState; eta: number | null; back: () => void }) {
  const st0 = state.steps ?? fresh()
  const c = DOMAINS[domain]
  const seeds = state.seeds ?? []
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (state.error) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [state.error])
  const spent = state.startedAt ? Math.max(0, Math.round((now - state.startedAt) / 1000)) : 0
  return (
    <>
      <div className="run">
        <h1 className="t26" style={{ fontWeight: 600, margin: 0 }}>
          {state.error ? '这次没挑成' : domain === 'film' ? '正在为你挑片' : `正在为你挑${c.noun}`}
        </h1>
        <div className="run-dir secondary" key={state.direction ?? 'none'} style={{ animation: 'cc-fade 240ms var(--ease) both' }}>
          {state.error ?? state.direction ?? (state.text ? `“${state.text}”` : '先读一下你的口味画像。')}
        </div>
        {!state.error && (
          <div className="t13 secondary run-time" data-run-time>
            已经 {spent} 秒{eta ? `，通常要 ${etaLabel(eta)}` : ''}。可以先去别处，挑好了侧栏这里会亮一个点。
          </div>
        )}
        <button className="pill" style={{ marginTop: 24 }} onClick={back} data-run-cancel>
          {state.error ? '返回' : '取消'}
        </button>
        <div className="run-grid">
          <div className={`reel${seeds.length ? '' : ' sk-shimmer'}`}>
            {seeds.length === 0 && (
              <>
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="seed seed-ph" style={{ opacity: 0.5, animation: 'none' }}>
                    <span className="sk-bar" style={{ width: `${40 + i * 9}%`, height: 6 }} />
                  </div>
                ))}
              </>
            )}
            {seeds.map((s, i) => (
              <div key={i} data-seed className={`seed${s.status === 'verified' ? '' : ' dim'}`} style={{ animationDelay: `${i * 80}ms` }}>
                <span className="seed-name film-name">{s.name}</span>
                {s.year ? <span className="t13 secondary">{s.year}</span> : null}
                <span className="seed-state">
                  {s.status === 'verified' ? (
                    <>
                      <CheckDraw size={14} />
                      {domain === 'film' ? '片库核实' : s.online ? '网上查到' : '书库核实'.replace('书库', domain === 'book' ? '书库' : '曲库')}
                    </>
                  ) : s.status === 'seen' ? (
                    `你${c.done}了`
                  ) : domain === 'film' ? (
                    '片库里没有，不用它'
                  ) : (
                    '查不到，不用它'
                  )}
                </span>
              </div>
            ))}
            {state.pool ? (
              <div className="pool-note">
                再按{domain === 'film' ? '今晚' : '这次'}的条件找了一些，一共 {state.pool} {c.unit}候选。
              </div>
            ) : null}
          </div>
          <div className="steps">
            {steps(domain).map((s) => {
              const st = st0[s.key]
              return (
                <div key={s.key} className={`step-row ${st.status}`}>
                  <Tile color={s.color} icon={s.icon} />
                  <div className="step-main">
                    <div className="step-label">{s.label}</div>
                    {st.detail && s.key !== 'direction' && <div className="step-detail">{st.detail}</div>}
                  </div>
                  <span className="step-state">
                    {st.status === 'running' ? <Spinner /> : st.status === 'done' ? <CheckDraw /> : null}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </>
  )
}

function etaLabel(sec: number): string {
  if (sec < 50) return `${Math.max(10, Math.round(sec / 10) * 10)} 秒左右`
  const m = Math.round(sec / 30) / 2
  return m <= 1 ? '一分钟左右' : m === 1.5 ? '一分半左右' : `${m} 分钟左右`
}

// ------------------------------------------------------------ result

type Acted = 'want' | 'rejected' | 'watched' | 'dropped' | 'skipped'

function Result({
  domain,
  state,
  reasons,
  rerun,
  onChanged,
  newNight,
}: {
  domain: Domain
  state: TonightState
  reasons: PassReason[]
  rerun: () => void
  onChanged: () => void
  newNight: () => void
}) {
  const r = state.result!
  const c = DOMAINS[domain]
  const demo = useDemo()
  const [acted, setActed] = useState<Record<string, Acted>>({})
  const [chosen, setChosen] = useState<string | null>(r.chosen ?? null)
  useEffect(() => setChosen(r.chosen ?? null), [r])
  // a result reopened from the sidebar is a night that has passed: "看过了" then means "watched it since"
  const ts = (state.result as RecResult & { ts?: number }).ts
  const past = !!ts && Date.now() / 1000 - ts > 4 * 3600
  useEffect(() => {
    get<Item[]>(`/items?domain=${domain}`)
      .then((its) => {
        const m: Record<string, Acted> = {}
        for (const it of its) if (r.picks.some((p) => p.id === it.id)) m[it.id] = it.status
        setActed(m)
      })
      .catch(() => {})
  }, [r, domain])
  const choose = async (id: string) => {
    if (r.rec_id == null) return
    setChosen(id)
    await post(`/recs/${r.rec_id}/choose`, { item_id: id }).catch(() => setChosen(null))
    onChanged()
  }
  return (
    <>
      <div className="page">
        <div className="result-head rise-in">
          <span className="page-icon">
            <Tile color={c.color} size={56} icon={domainIcon(domain, 30)} />
          </span>
          <div className="t13 secondary">{nightLabel(ts)}</div>
          <h1 className="page-title" style={{ marginTop: 4 }}>
            {c.pickTitle}
          </h1>
          {(state.text || Object.keys(state.chips).length > 0) && (
            <div className="secondary page-sub">
              你说：{[state.text, ...Object.values(state.chips)].filter(Boolean).join('，')}
            </div>
          )}
          <div className="callout callout-moon">
            <span className="said-ic" style={{ marginTop: 4 }}>
              {domainIcon(domain, 16)}
            </span>
            <div className="callout-text">{r.direction}</div>
          </div>
        </div>
        {r.picks.map((p, i) => (
          <PickBlock
            key={p.id}
            p={p}
            i={i}
            domain={domain}
            reasons={reasons}
            recId={r.rec_id}
            acted={acted[p.id]}
            chosen={chosen === p.id}
            anyChosen={!!chosen}
            past={past}
            choose={() => choose(p.id)}
            setActed={(a) => {
              setActed((m) => ({ ...m, [p.id]: a }))
              onChanged()
            }}
          />
        ))}
        <div className="result-foot rise-in" style={{ animationDelay: '480ms' }}>
          <span className="offline-note">
            <CpuFillIcon size={14} />
            {models().onDevice
              ? demo
                ? `由这台 Mac 上的 ${models().big} 挑选，用时 ${r.stats.seconds} 秒。你的记录没有离开这台 Mac。`
                : '在这台 Mac 上挑选，你的记录没有离开它。'
              : demo
                ? `由 ${models().host} 上的 ${models().big} 挑选，用时 ${r.stats.seconds} 秒。`
                : `由 ${models().host} 上的模型挑选，记录只存在这台 Mac 上。`}
          </span>
          <span className="flex" style={{ gap: 8 }}>
            <CopyButton label={`拷贝这三${c.unit}`} text={picksText(r.picks)} />
            <button className="pill-sm" onClick={newNight}>
              换个说法
            </button>
            <button className="pill-sm" onClick={rerun} data-rerun>
              再{c.pick3}
            </button>
          </span>
        </div>
      </div>
    </>
  )
}

function pickProps(p: Pick): [string, string][] {
  if (p.domain === 'book') {
    return [
      ...(p.creators?.length ? [['作者', p.creators.slice(0, 2).join('、')] as [string, string]] : []),
      ...(p.year ? [[/^bk:(db|it)/.test(p.id) ? '版本' : '出版', `${p.year} 年`] as [string, string]] : []),
      ...(p.genres_zh.length ? [['类型', p.genres_zh.join('，')] as [string, string]] : []),
      ...(p.lang ? [['原文', p.lang] as [string, string]] : []),
      ...(p.pages ? [['篇幅', `约 ${p.pages} 页`] as [string, string]] : []),
    ]
  }
  if (p.domain === 'music') {
    return [
      ...(p.creators?.length ? [['音乐人', p.creators.slice(0, 2).join('、')] as [string, string]] : []),
      ...(p.year ? [['发行', `${p.year} 年`] as [string, string]] : []),
      ...(p.genres_zh.length ? [['风格', p.genres_zh.join('，')] as [string, string]] : []),
      ...(p.region ? [['地区', p.region] as [string, string]] : []),
      ...(p.tracks ? [['曲目', `${p.tracks} 首`] as [string, string]] : []),
    ]
  }
  return [
    ['类型', [kindLabel(p), ...p.genres_zh].join('，')],
    ['时长', runtimeLabel(p)],
    ...(p.directors?.length ? [['导演', p.directors.slice(0, 2).join('、')] as [string, string]] : []),
    ...(p.cast?.length ? [['主演', p.cast.slice(0, 3).join('、')] as [string, string]] : []),
    ...(p.rating ? [['IMDb', `${p.rating.toFixed(1)} 分，${votes(p.votes ?? 0)}`] as [string, string]] : []),
  ]
}

function externalUrl(p: Pick): { label: string; url: string } {
  const q = encodeURIComponent(p.zh || p.title)
  if (p.domain === 'book') return { label: '在豆瓣读书查看', url: `https://search.douban.com/book/subject_search?search_text=${q}` }
  if (p.domain === 'music')
    return { label: '在 Apple Music 查看', url: `https://music.apple.com/search?term=${encodeURIComponent(`${p.title} ${p.creators?.[0] ?? ''}`)}` }
  return { label: '在豆瓣查看', url: doubanUrl(p) }
}

function PickBlock({
  p,
  i,
  domain,
  reasons,
  recId,
  acted,
  chosen,
  anyChosen,
  past,
  choose,
  setActed,
}: {
  p: Pick
  i: number
  domain: Domain
  reasons: PassReason[]
  recId: number | null
  acted?: Acted
  chosen: boolean
  anyChosen: boolean
  past: boolean
  choose: () => void
  setActed: (a: Acted) => void
}) {
  const c = DOMAINS[domain]
  const [panel, setPanel] = useState<'log' | 'pass' | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const save = async () => {
    setSaving(true)
    try {
      await post(`/items/${enc(p.id)}/pass`, { reason: 'want', rec_id: recId ?? undefined })
      setActed('want')
    } finally {
      setSaving(false)
    }
  }
  const ext = externalUrl(p)
  const props = pickProps(p)
  return (
    <section className="pick rise-in" style={{ animationDelay: `${120 + i * 120}ms` }} data-pick={i}>
      <div className="pick-top">
        <Cover t={p} width={domain === 'music' ? 132 : 112} />
        <div className="pick-head">
          <div className="pick-num">
            第 {i + 1} {c.unit}
            {p.on_list ? `，在你的${c.list}里` : ''}
          </div>
          <div className="pick-name-row">
            <h2 className="pick-name film-name">{p.name}</h2>
            <CopyButton text={p.name} title={`拷贝${c.noun}名`} />
          </div>
          <div className="pick-orig secondary">
            {p.original && p.original !== p.name ? `${p.original}，` : ''}
            {p.year}
            {p.kind !== 'movie' && p.end_year ? `–${p.end_year}` : ''}
          </div>
          <div className="pick-props">
            {props.map(([k, v]) => (
              <div key={k} className="prop-row">
                <span className="prop-label">{k}</span>
                <span className="prop-value">{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      {p.reason && <p className="pick-reason">{p.reason}</p>}
      {p.because.map((q) => {
        const words = q.words || (q.liked.length ? `喜欢${q.liked.join('、')}` : '')
        const stanceLine = q.onboard ? `第一次认识时，你在封面墙上点了${q.stance || '喜欢'}` : q.stance ? `你说过${q.stance}` : ''
        if (!words && !stanceLine) return null
        return (
          <div key={q.id} className="said">
            <span className="said-ic">
              <QuoteFillIcon size={14} />
            </span>
            <div>
              <div className="said-words">{words || stanceLine}</div>
              <div className="said-src">{words ? `你说《${q.name}》的话` : `关于《${q.name}》`}</div>
            </div>
          </div>
        )
      })}
      {panel === 'log' ? (
        <LogPanel
          id={p.id}
          name={p.name}
          domain={domain}
          origin={chosen || past ? 'rec' : 'past'}
          onCancel={() => setPanel(null)}
          onDone={(out) => {
            setPanel(null)
            setActed(out.item.status as Acted)
          }}
        />
      ) : panel === 'pass' ? (
        <PassPanel
          id={p.id}
          domain={domain}
          reasons={reasons}
          recId={recId}
          onCancel={() => setPanel(null)}
          onDone={(r) => {
            setPanel(null)
            setNote(r.reason)
            setActed(r.effect === 'taste' ? 'rejected' : 'skipped')
          }}
        />
      ) : (
        <div className="pick-actions">
          {acted === 'watched' || acted === 'dropped' ? (
            <span className="pick-state">已记下</span>
          ) : acted === 'rejected' ? (
            <span className="pick-state">{note ?? '不想' + c.verb}，不会再推荐</span>
          ) : acted === 'skipped' ? (
            <span className="pick-state">{c.when}先不{c.verb}，以后可能再推荐</span>
          ) : (
            <>
              {chosen ? (
                <span className="pick-state pick-chosen" data-chosen={i}>
                  <CheckDraw size={14} />
                  {c.when}就{c.verb}它
                </span>
              ) : (
                <button className={anyChosen ? 'pill-sm' : 'pill-accent'} onClick={choose} disabled={recId == null} data-choose={i}>
                  就{c.verb}这{c.unit}
                </button>
              )}
              {acted === 'want' ? (
                <span className="pick-state">已在{c.list}</span>
              ) : (
                !chosen && (
                  <button className="pill-sm" onClick={save} disabled={saving} data-save={i}>
                    先存着
                  </button>
                )
              )}
              <button className="pill-sm" onClick={() => setPanel('log')} data-seen={i}>
                {chosen || past ? `${c.verb}完了` : `${c.done}了`}
              </button>
              {!chosen && (
                <button className="pill-sm dim" onClick={() => setPanel('pass')} data-pass-open={i}>
                  不想{c.verb}
                </button>
              )}
            </>
          )}
          <button className="link-quiet t13" style={{ marginLeft: 8 }} onClick={() => window.pianke.openExternal(ext.url)}>
            {ext.label}
          </button>
        </div>
      )}
    </section>
  )
}

/** The three picks as plain text: names to search on a streaming site or a
 *  bookshop, with the reasons to send to a friend. */
function picksText(picks: Pick[]): string {
  return picks
    .map((p, i) => {
      const by = (p.directors ?? p.creators ?? [])[0]
      const meta = [p.year, by].filter(Boolean).join('，')
      return `${i + 1}. 《${p.name}》${meta ? `（${meta}）` : ''}${p.reason ? `\n${p.reason}` : ''}`
    })
    .join('\n\n')
}
