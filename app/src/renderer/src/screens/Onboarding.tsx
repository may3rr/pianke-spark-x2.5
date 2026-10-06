import { useEffect, useRef, useState } from 'react'
import RingField, { type FieldMode } from '../components/RingField'
import ShuffleTitle from '../components/ShuffleTitle'
import { post, put, stream, type Domain, type Profile, type Status } from '../lib/api'
import { DOMAINS, DOMAIN_ORDER } from '../lib/domains'
import CoverWall from '../components/CoverWall'
import {
  BookFillIcon,
  BooksFillIcon,
  CheckDraw,
  CpuFillIcon,
  LockFillIcon,
  MoonFillIcon,
  MusicNoteFillIcon,
  SparklesFillIcon,
  Spinner,
  Tile,
  WifiSlashFillIcon,
} from '../components/Icons'

const TAGLINE = 'Fewer films, better nights.'

// 0 intro · 1 privacy · 2 name · 3 shelves · 4 cover wall(s) · 5 talk · 6 build
type Step = 0 | 1 | 2 | 3 | 4 | 5 | 6

const DOMAIN_PITCH: Record<Domain, { icon: React.ReactNode; line: string }> = {
  film: { icon: <MoonFillIcon size={22} />, line: '电影和剧集。今晚看什么，只挑三部。' },
  book: { icon: <BookFillIcon size={22} />, line: '小说、散文、非虚构。下一本读什么。' },
  music: { icon: <MusicNoteFillIcon size={22} />, line: '整张专辑。工作、通勤、睡前听什么。' },
}

interface Msg {
  role: 'bot' | 'me'
  text: string
  q?: boolean
  live?: boolean
}

export default function Onboarding({ status, onDone }: { status: Status; onDone: () => void }) {
  const driven = window.pianke.driven
  const [step, setStep] = useState<Step>(0)
  const [beat, setBeat] = useState(driven ? 2 : 0)
  const [shuffle, setShuffle] = useState(driven)
  const [leaving, setLeaving] = useState(false)
  const [name, setName] = useState(status.name)
  const [domains, setDomains] = useState<Domain[]>([])
  const [wallIdx, setWallIdx] = useState(0)
  const lockRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (step !== 0 || shuffle) return
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
    const a = setTimeout(() => setBeat((b) => Math.max(b, 1)), reduced ? 0 : 700)
    const b = setTimeout(() => setShuffle(true), reduced ? 0 : 1700)
    return () => {
      clearTimeout(a)
      clearTimeout(b)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step])

  const mode: FieldMode = leaving
    ? { kind: 'burst' }
    : step === 0
      ? beat === 0
        ? { kind: 'scatter' }
        : { kind: 'rings' }
      : step === 1
        ? { kind: 'orbit', anchor: () => lockRef.current?.getBoundingClientRect() ?? null, radius: 40, tight: true }
        : step === 6
          ? { kind: 'rings' }
          : { kind: 'halo' }

  const finish = () => {
    setLeaving(true)
    setTimeout(onDone, 640)
  }

  return (
    <div className="onboard relative h-full overflow-hidden" style={{ background: 'var(--bg)' }}>
      {step !== 4 && step !== 5 && <RingField mode={mode} />}
      <div className="drag-strip" style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 52, zIndex: 3 }} />

      {step === 0 && (
        <div className={`onboard-stage${leaving ? ' leaving' : ''}`}>
          <div className={`onboard-intro${beat >= 2 ? ' on' : ''}`}>
            <ShuffleTitle
              className="onboard-shuffle"
              text={TAGLINE}
              play={shuffle}
              onSettled={() => setTimeout(() => setBeat(2), 420)}
            />
            <div className="t26 onboard-rise film-name" style={{ marginTop: 24 }}>
              片刻
            </div>
            <div className="secondary onboard-rise" style={{ marginTop: 8 }}>
              不刷信息流。只推荐三部，每一部都懂你。
            </div>
            <button className="pill-accent onboard-rise" style={{ marginTop: 32, alignSelf: 'center' }} onClick={() => setStep(1)} data-ob-start>
              认识一下
            </button>
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="onboard-stage" key="s1">
          <div className="onboard-panel" style={{ width: 520 }}>
            <div ref={lockRef} className="onboard-lock">
              <Tile size={40} color="var(--tile-indigo)" icon={<LockFillIcon size={22} />} />
            </div>
            <h1 className="t26 onboard-h" style={{ textAlign: 'center' }}>
              你的口味只留在这台 Mac 上
            </h1>
            <p className="secondary onboard-sub" style={{ textAlign: 'center' }}>
              片刻会记住你说过的每一句话，所以它不能住在别人的服务器上。
            </p>
            <div className="local-rows">
              <div className="local-row">
                <Tile color="var(--tile-blue)" icon={<CpuFillIcon size={13} />} />
                <div className="min-w-0" style={{ flex: 1 }}>
                  <div className="font-semibold">两个模型在本机运行</div>
                  <div className="t13 secondary">Spark-X2.5-4B 负责理解你和挑片，1.7B 负责整理你说的话。</div>
                  {status.models.map((m) => (
                    <div key={m.key} className="model-line">
                      <span className={`status-dot ${m.status === 'ready' ? 'ready' : m.status === 'loading' ? 'loading' : m.status === 'stopped' ? '' : 'error'}`} />
                      {m.name}
                      <span style={{ marginLeft: 'auto' }}>
                        {m.status === 'ready' ? `已就绪${m.load_seconds ? `，加载用了 ${m.load_seconds} 秒` : ''}` : m.status === 'loading' ? '正在加载' : m.error ?? '未启动'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="local-row">
                <Tile color="var(--tile-teal)" icon={<BooksFillIcon size={13} />} />
                <div>
                  <div className="font-semibold">片库、书库和曲库也在本机</div>
                  <div className="t13 secondary">
                    {status.catalog.available
                      ? `${Number(status.catalog.total).toLocaleString()} 部影视来自 IMDb，`
                      : '没有找到片库文件，'}
                    {status.library.available
                      ? `${Number(status.library.count_book ?? 0).toLocaleString()} 本书和 ${Number(status.library.count_album ?? 0).toLocaleString()} 张专辑来自 Wikidata。`
                      : '书库和曲库还没有生成。'}
                    模型提到的每一部作品都要先核实，查不到的不会出现在你面前。
                  </div>
                </div>
              </div>
              <div className="local-row">
                <Tile color="var(--tile-purple)" icon={<WifiSlashFillIcon size={13} />} />
                <div>
                  <div className="font-semibold">没有账号，你的话不出这台 Mac</div>
                  <div className="t13 secondary">
                    联网只做两件事：按作品名查封面，按书名、专辑名核实作品是否存在。请求里只有作品名，没有任何关于你的信息。
                  </div>
                </div>
              </div>
            </div>
            <div className="onboard-nav">
              <button className="pill" onClick={() => setStep(0)}>
                返回
              </button>
              <button
                className="pill-accent"
                disabled={!status.models.every((m) => m.status === 'ready')}
                onClick={() => setStep(2)}
                data-ob-next
              >
                {status.models.every((m) => m.status === 'ready') ? '继续' : '等模型加载'}
              </button>
            </div>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="onboard-stage" key="s2">
          <div className="onboard-panel" style={{ width: 440, textAlign: 'center' }}>
            <h1 className="t26 onboard-h">怎么称呼你</h1>
            <p className="secondary onboard-sub">接下来先认出几部你熟悉的作品，再聊四个问题，大概三分钟。</p>
            <input
              className="name-input"
              placeholder="你的名字或昵称"
              value={name}
              autoFocus
              onChange={(e) => setName(e.target.value)}
              onKeyDown={async (e) => {
                if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
                  await put('/name', { name })
                  setStep(3)
                }
              }}
              data-ob-name
            />
            <div className="onboard-nav">
              <button className="pill" onClick={() => setStep(1)}>
                返回
              </button>
              <button
                className="pill-accent"
                onClick={async () => {
                  await put('/name', { name })
                  setStep(3)
                }}
                data-ob-name-next
              >
                继续
              </button>
            </div>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="onboard-stage" key="s3">
          <div className="onboard-panel" style={{ width: 560, textAlign: 'center' }}>
            <h1 className="t26 onboard-h">你想让片刻帮你挑什么</h1>
            <p className="secondary onboard-sub">可以多选。没选的以后点开时再认识，不着急。</p>
            <div className="domain-picks">
              {DOMAIN_ORDER.map((d) => {
                const on = domains.includes(d)
                return (
                  <button
                    key={d}
                    className={`domain-pick${on ? ' on' : ''}`}
                    aria-pressed={on}
                    onClick={() => setDomains((x) => (on ? x.filter((y) => y !== d) : DOMAIN_ORDER.filter((y) => y === d || x.includes(y))))}
                    data-ob-domain={d}
                  >
                    <Tile color={DOMAINS[d].color} size={40} icon={DOMAIN_PITCH[d].icon} />
                    <span className="domain-pick-label">{DOMAINS[d].label}</span>
                    <span className="t13 secondary">{DOMAIN_PITCH[d].line}</span>
                    <span className="domain-pick-check">{on ? <CheckDraw size={16} color="var(--accent)" /> : null}</span>
                  </button>
                )
              })}
            </div>
            <div className="onboard-nav">
              <button className="pill" onClick={() => setStep(2)}>
                返回
              </button>
              <button
                className="pill-accent"
                disabled={!domains.length}
                onClick={() => {
                  setWallIdx(0)
                  setStep(4)
                }}
                data-ob-domains-next
              >
                {domains.length ? '继续' : '至少选一个'}
              </button>
            </div>
          </div>
        </div>
      )}

      {step === 4 && domains[wallIdx] && (
        <CoverWall
          key={domains[wallIdx]}
          domain={domains[wallIdx]}
          doneLabel={wallIdx < domains.length - 1 ? `下一步：${DOMAINS[domains[wallIdx + 1]].label}` : '接着聊几句'}
          onSkip={() => (wallIdx < domains.length - 1 ? setWallIdx(wallIdx + 1) : setStep(5))}
          onDone={() => (wallIdx < domains.length - 1 ? setWallIdx(wallIdx + 1) : setStep(5))}
        />
      )}
      {step === 5 && <Interview name={name} domains={domains} onComplete={() => setStep(6)} />}
      {step === 6 && <Build onDone={finish} leaving={leaving} />}

      {step > 0 && step < 4 && !leaving && (
        <div className="onboard-dots" aria-label={`第 ${step} 步`}>
          {[1, 2, 3, 4, 5].map((i) => (
            <span key={i} className={i === step ? 'on' : undefined} />
          ))}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------ interview

export function Interview({
  name,
  domains,
  onComplete,
  greet = true,
}: {
  name: string
  domains: Domain[]
  onComplete: () => void
  greet?: boolean
}) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [answered, setAnswered] = useState(0)
  const [total, setTotal] = useState(5)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(true)
  const [done, setDone] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    post<{ next_question: string; total: number }>('/interview/start', { domains }).then((s) => {
      setTotal(s.total)
      setMsgs([
        {
          role: 'bot',
          text: greet
            ? `${name ? `${name}，你好。` : '你好。'}我是片刻。接着聊几句，你说的话我只记在这台 Mac 上。`
            : `再聊两句${DOMAINS[domains[0]].label === '书' ? '读书' : DOMAINS[domains[0]].label === '音乐' ? '听歌' : '看片'}的事。`,
        },
        { role: 'bot', text: s.next_question, q: true },
      ])
      setBusy(false)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
    if (!busy) input.current?.focus()
  }, [msgs, busy])

  const send = async (raw?: string) => {
    const t = (raw ?? text).trim()
    if (!t || busy) return
    setText('')
    setBusy(true)
    setMsgs((m) => [...m, { role: 'me', text: t }, { role: 'bot', text: '', live: true }])
    await stream('/interview/answer', { text: t }, (ev) => {
      if (ev.type === 'delta') {
        setMsgs((m) => {
          const c = [...m]
          const last = c[c.length - 1]
          c[c.length - 1] = { ...last, text: last.text + ev.text }
          return c
        })
      } else if (ev.type === 'question') {
        setMsgs((m) => {
          const c = m.map((x) => ({ ...x, live: false }))
          return [...c, { role: 'bot', text: ev.text, q: true }]
        })
      } else if (ev.type === 'complete') {
        setMsgs((m) => m.map((x) => ({ ...x, live: false })))
        setDone(true)
      } else if (ev.type === 'error') {
        setMsgs((m) => [...m.map((x) => ({ ...x, live: false })), { role: 'bot', text: `出了点问题：${ev.message}` }])
      }
    }).catch((e) =>
      setMsgs((m) => [...m.map((x) => ({ ...x, live: false })), { role: 'bot', text: `出了点问题：${(e as Error).message}` }])
    )
    setAnswered((a) => a + 1)
    setBusy(false)
  }

  return (
    <div className="chat-stage">
      <div className="chat-scroll" ref={scroller}>
        <div className="chat-col">
          {msgs.map((m, i) =>
            m.role === 'me' ? (
              <div key={i} className="msg-me">
                {m.text}
              </div>
            ) : (
              <div key={i} className={`msg-bot${m.q ? ' q' : ''}`}>
                {m.text}
                {m.live && <span className="caret" />}
              </div>
            )
          )}
          {done && (
            <div className="rise-in" style={{ marginTop: 8 }}>
              <button className="pill-accent" onClick={onComplete} data-ob-build>
                整理我的口味
              </button>
            </div>
          )}
        </div>
      </div>
      {!done && (
        <div className="chat-bar">
          <div className="chat-progress" aria-label={`第 ${Math.min(answered + 1, total)} 题，共 ${total} 题`}>
            {Array.from({ length: total }, (_, i) => (
              <span key={i} className={i < answered ? 'on' : undefined} />
            ))}
          </div>
          <div className="chat-bar-inner">
            <textarea
              ref={input}
              className="chat-input"
              rows={1}
              placeholder={busy ? '片刻在听' : '想到什么说什么，回车发送'}
              value={text}
              disabled={busy}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  send()
                }
              }}
              data-ob-input
            />
            <button className="pill-sm dim" disabled={busy} onClick={() => send('这题跳过')}>
              跳过
            </button>
            <button className="pill-accent" style={{ height: 44, padding: '0 18px' }} disabled={busy || !text.trim()} onClick={() => send()} data-ob-send>
              发送
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------ build

interface BuildStep {
  key: string
  label: string
  status: 'wait' | 'running' | 'done'
  detail?: string
}

export function Build({ onDone, leaving, doneLabel = '开始' }: { onDone: () => void; leaving: boolean; doneLabel?: string }) {
  const [steps, setSteps] = useState<BuildStep[]>([
    { key: 'extract', label: '听懂你说的作品', status: 'wait' },
    { key: 'resolve', label: '逐一核实', status: 'wait' },
    { key: 'read', label: '读入全部记录', status: 'wait' },
    { key: 'write', label: '写出口味画像', status: 'wait' },
  ])
  const [titles, setTitles] = useState<{ name: string; found: boolean; year?: number }[]>([])
  const [profile, setProfile] = useState<Profile | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    stream('/interview/finish', {}, (ev) => {
      if (ev.type === 'step') {
        setSteps((s) => s.map((x) => (x.key === ev.key ? { ...x, status: ev.status, detail: ev.detail } : x)))
      } else if (ev.type === 'title') {
        setTitles((t) => [...t, { name: ev.name, found: ev.found, year: ev.year }])
      } else if (ev.type === 'profile') {
        setProfile(ev.profile)
      } else if (ev.type === 'error') {
        setErr(ev.message)
      }
    }).catch((e) => setErr((e as Error).message))
  }, [])

  return (
    <div className={`onboard-stage${leaving ? ' leaving' : ''}`} key="s4">
      <div className="onboard-panel" style={{ width: 560, textAlign: 'center' }}>
        <h1 className="t26 onboard-h">{profile ? '这是我对你的第一印象' : '正在整理你的口味'}</h1>
        <p className="secondary onboard-sub">
          {profile ? '以后每看完、读完、听完一部，打个分、说一句感受，它都会更准。你也可以随时去改。' : '在这台 Mac 上运行，你说的话不会离开它。'}
        </p>
        <div className="build-titles">
          {titles.map((t, i) => (
            <span key={i} className={`build-title${t.found ? '' : ' miss'}`} style={{ animationDelay: `${i * 80}ms` }}>
              {t.found ? <CheckDraw size={14} /> : null}
              <span className="film-name">{t.name}</span>
              {t.found ? (t.year ? <span className="t13 secondary">{t.year}</span> : null) : <span className="t13">没查到</span>}
            </span>
          ))}
        </div>
        {!profile && (
          <div className="steps" style={{ marginTop: 24, textAlign: 'left' }}>
            {steps.map((s) => (
              <div key={s.key} className={`step-row ${s.status}`}>
                <Tile color="var(--tile-purple)" icon={<SparklesFillIcon size={13} />} />
                <div className="step-main">
                  <div className="step-label">{s.label}</div>
                  {s.detail && <div className="step-detail">{s.detail}</div>}
                </div>
                <span className="step-state">
                  {s.status === 'running' ? <Spinner /> : s.status === 'done' ? <CheckDraw /> : null}
                </span>
              </div>
            ))}
          </div>
        )}
        {err && <div className="t13 danger" style={{ marginTop: 12 }}>{err}</div>}
        {profile && (
          <div className="summary-card">
            <div className="summary-line" style={{ marginTop: 0 }}>
              {profile.doc.summary}
            </div>
            {profile.doc.sections
              .filter((s) => s.claims.length)
              .slice(0, 3)
              .map((s) => (
                <div key={s.key} style={{ marginTop: 12 }}>
                  <div className="t13 secondary">{s.title}</div>
                  {s.claims.slice(0, 2).map((c, i) => (
                    <div key={i} style={{ marginTop: 2 }}>
                      {c.text}
                    </div>
                  ))}
                </div>
              ))}
          </div>
        )}
        {profile && (
          <button className="pill-accent rise-in" style={{ marginTop: 32, alignSelf: 'center' }} onClick={onDone} data-ob-done>
            {doneLabel}
          </button>
        )}
      </div>
    </div>
  )
}
