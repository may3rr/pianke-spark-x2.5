import { useCallback, useEffect, useMemo, useState } from 'react'
import { get, waitBackend, type Domain, type RecResult, type Status } from './lib/api'
import { morph } from './lib/vt'
import { DOMAIN_ORDER } from './lib/domains'
import Sidebar, { type View } from './components/Sidebar'
import Onboarding from './screens/Onboarding'
import type { TonightState } from './screens/Tonight'
import DomainView, { type Tab } from './screens/DomainView'
import ProfilePage from './screens/ProfilePage'
import Settings from './screens/Settings'
import { syncModels } from './lib/models'
import QuickFind from './components/QuickFind'
import Toast from './components/Toast'

export interface PastRec extends RecResult {
  id: number
  ts: number
  request: { text: string; chips: Record<string, string>; domain?: Domain }
}

const blank = (): TonightState => ({ phase: 'compose', text: '', chips: {} })
const isDomain = (v: View): v is Domain => v === 'film' || v === 'book' || v === 'music'

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [bootError, setBootError] = useState<string | null>(null)
  const [view, setViewRaw] = useState<View>('film')
  // onboarding can still open Settings (model missing → switch to an API)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [tabs, setTabs] = useState<Record<Domain, Tab>>({ film: 'rec', book: 'rec', music: 'rec' })
  const [nights, setNights] = useState<Record<Domain, TonightState>>({ film: blank(), book: blank(), music: blank() })
  const [recs, setRecs] = useState<PastRec[]>([])
  const [finding, setFinding] = useState(false)
  // when the user last looked at each shelf: a result that came in after
  // that gets a dot in the sidebar
  const [lookedAt, setLookedAt] = useState<Record<Domain, number>>({ film: 0, book: 0, music: 0 })
  const setNight = (d: Domain) => (u: React.SetStateAction<TonightState>) =>
    setNights((n) => ({ ...n, [d]: typeof u === 'function' ? (u as (s: TonightState) => TonightState)(n[d]) : u }))
  const setTab = (d: Domain, t: Tab) => morph(() => setTabs((x) => ({ ...x, [d]: t })))

  const refresh = useCallback(async () => {
    try {
      const s = await get<Status>('/status')
      syncModels(s)
      setStatus(s)
    } catch {
      /* backend restarting; next poll */
    }
  }, [])
  const refreshRecs = useCallback(async () => {
    try {
      const r = await get<Array<Omit<PastRec, 'rec_id'>>>('/recs')
      setRecs(r.map((x) => ({ ...x, rec_id: x.id })))
    } catch {
      /* ignore */
    }
  }, [])

  const boot = useCallback(async () => {
    const ok = await waitBackend()
    if (!ok) {
      const i = await window.pianke.getInfo()
      setBootError(i.backendError || '本地服务没有启动')
      return
    }
    await refresh()
    await refreshRecs()
  }, [refresh, refreshRecs])

  useEffect(() => {
    const off = window.pianke.onBackendError((m) => {
      setBootError(m)
      // the main process restarted the backend and it is healthy again
      if (m === null) void boot()
    })
    void boot()
    return off
  }, [boot])

  // poll while models load; slow heartbeat afterwards keeps counts fresh
  useEffect(() => {
    if (!status) return
    const loading = status.models.some((m) => m.status === 'loading' || m.status === 'stopped')
    const id = setTimeout(refresh, loading ? 1000 : 5000)
    return () => clearTimeout(id)
  }, [status, refresh])

  useEffect(() => {
    const off = window.pianke.onFocus((f) =>
      document.documentElement.setAttribute('data-window-focus', String(f))
    )
    return off
  }, [])

  const setView = useCallback((v: View) => morph(() => setViewRaw(v)), [])

  useEffect(() => {
    if (isDomain(view)) setLookedAt((l) => ({ ...l, [view]: Date.now() }))
  }, [view, nights.film.doneAt, nights.book.doneAt, nights.music.doneAt])

  const shelfState = useMemo(() => {
    const out = {} as Record<Domain, 'running' | 'done' | null>
    for (const d of DOMAIN_ORDER) {
      const n = nights[d]
      out[d] =
        n.phase === 'running' && !n.error ? 'running' : n.phase === 'result' && (n.doneAt ?? 0) > lookedAt[d] && view !== d ? 'done' : null
    }
    return out
  }, [nights, lookedAt, view])

  // typical time per shelf, from the last few recommendations
  const eta = useMemo(() => {
    const out = {} as Record<Domain, number | null>
    for (const d of DOMAIN_ORDER) {
      const xs = recs
        .filter((r) => (r.domain ?? 'film') === d && r.stats?.seconds)
        .slice(0, 5)
        .map((r) => r.stats.seconds)
        .sort((a, b) => a - b)
      out[d] = xs.length ? xs[Math.floor(xs.length / 2)] : null
    }
    return out
  }, [recs])

  useEffect(
    () =>
      window.pianke.onMenu((cmd) => {
        morph(() => {
          if (cmd === 'tonight') {
            // a running recommendation is left alone; this only opens the page
            setNights((n) => (n.film.phase === 'running' ? n : { ...n, film: blank() }))
            setTabs((x) => ({ ...x, film: 'rec' }))
            setViewRaw('film')
          } else if (cmd === 'find') {
            setFinding(true)
          } else if (cmd === 'want' || cmd === 'watched') {
            setTabs((x) => ({ ...x, film: cmd === 'want' ? 'want' : 'records' }))
            setViewRaw('film')
          } else setViewRaw(cmd)
        })
      }),
    []
  )

  if (bootError) {
    return (
      <div className="h-full flex flex-col items-center justify-center" style={{ background: 'var(--bg)' }}>
        <div className="drag-strip" style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 52 }} />
        <div className="t26" style={{ fontWeight: 600 }}>片刻没能启动</div>
        <div className="secondary" style={{ marginTop: 8, maxWidth: 480, textAlign: 'center' }}>
          本地服务出了问题：{bootError}。退出后重新打开片刻；如果还不行，检查 backend 目录和 Python 环境。
        </div>
      </div>
    )
  }
  if (!status) {
    return <div className="h-full drag-strip" style={{ background: 'var(--bg)' }} />
  }
  // onboarding can still open Settings (model missing → switch to an API),
  // so the first run never dead-ends
  if (!status.onboarded) {
    return (
      <>
        {settingsOpen && (
          <div className="h-full relative">
            <div
              className="drag-strip bar-solid"
              style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 52, zIndex: 5, display: 'flex', alignItems: 'center', paddingLeft: 20, gap: 4 }}
            >
              <button className="t13" onClick={() => setSettingsOpen(false)} data-ob-back>
                ‹ 返回引导
              </button>
            </div>
            <main className="main-area" style={{ top: 52, left: 0 }}>
              <Settings status={status} onReset={refresh} embedded />
            </main>
          </div>
        )}
        {/* stays mounted while Settings is open, so coming back lands on the same step */}
        <div className="h-full" style={settingsOpen ? { display: 'none' } : undefined}>
          <Onboarding
            status={status}
            onOpenSettings={() => setSettingsOpen(true)}
            onDone={async () => {
              const s = await get<Status>('/status')
              setStatus(s)
              morph(() => setViewRaw(DOMAIN_ORDER.find((d) => s.domains_onboarded.includes(d)) ?? 'film'))
            }}
          />
        </div>
      </>
    )
  }

  const openRec = (r: PastRec) =>
    morph(() => {
      const d = (r.domain ?? r.request.domain ?? 'film') as Domain
      setNights((n) => ({ ...n, [d]: { phase: 'result', text: r.request.text, chips: r.request.chips || {}, result: r } }))
      setTabs((x) => ({ ...x, [d]: 'rec' }))
      setViewRaw(d)
    })
  const activeRec =
    isDomain(view) && tabs[view] === 'rec' && nights[view].phase === 'result' ? nights[view].result?.rec_id ?? null : null

  return (
    <div className="h-full relative">
      <Sidebar
        view={view}
        setView={setView}
        status={status}
        recs={recs}
        openRec={openRec}
        activeRec={activeRec}
        shelfState={shelfState}
        onFind={() => setFinding(true)}
      />
      <main className="main-area">
        {isDomain(view) && (
          <DomainView
            key={view}
            domain={view}
            tab={tabs[view]}
            setTab={(t) => setTab(view, t)}
            status={status}
            tonight={nights[view]}
            setTonight={setNight(view)}
            eta={eta[view]}
            onChanged={() => {
              refresh()
              refreshRecs()
            }}
          />
        )}
        {view === 'profile' && <ProfilePage status={status} onChanged={refresh} />}
        {view === 'settings' && <Settings status={status} onReset={refresh} />}
      </main>
      {finding && (
        <QuickFind
          domain={isDomain(view) ? view : 'film'}
          onClose={() => setFinding(false)}
          onChanged={() => {
            refresh()
            refreshRecs()
          }}
        />
      )}
      <Toast />
    </div>
  )
}
