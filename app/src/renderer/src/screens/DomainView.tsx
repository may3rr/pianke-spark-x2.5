import { useState } from 'react'
import type { Domain, Status } from '../lib/api'
import { DOMAINS } from '../lib/domains'
import CoverWall from '../components/CoverWall'
import Tonight, { type TonightState } from './Tonight'
import Shelf from './Shelf'
import { Build } from './Onboarding'
import { post } from '../lib/api'

export type Tab = 'rec' | 'want' | 'records'

/** One shelf: 推荐 | 片单 | 看过 (wording per shelf). A shelf the user
 * didn't choose at first run opens on its own short cold start. */
export default function DomainView({
  domain,
  tab,
  setTab,
  status,
  tonight,
  setTonight,
  eta,
  onChanged,
}: {
  domain: Domain
  tab: Tab
  setTab: (t: Tab) => void
  status: Status
  tonight: TonightState
  setTonight: React.Dispatch<React.SetStateAction<TonightState>>
  /** typical seconds a recommendation on this shelf takes */
  eta: number | null
  onChanged: () => void
}) {
  const c = DOMAINS[domain]
  const counts = status.domain_counts[domain]
  const skipKey = `pianke.skipOnboard.${domain}`
  const [skipped, setSkipped] = useState(() => {
    try {
      return localStorage.getItem(skipKey) === '1'
    } catch {
      return false
    }
  })
  const needsOnboard = !status.domains_onboarded.includes(domain) && !skipped
  const tabs: { key: Tab; label: string; n?: number }[] = [
    { key: 'rec', label: '推荐' },
    { key: 'want', label: c.list, n: counts.want },
    { key: 'records', label: c.done, n: counts.watched + counts.dropped },
  ]
  return (
    <>
      <div className="top-strip drag-strip bar-solid tabbar">
        <div className="tabbar-inner">
          <span className="tabbar-title">{c.label}</span>
          {!needsOnboard &&
            tabs.map((t) => (
              <button key={t.key} className={`tab${tab === t.key ? ' on' : ''}`} onClick={() => setTab(t.key)} data-tab={t.key}>
                {t.label}
                {t.n ? <span className="tab-n">{t.n}</span> : null}
              </button>
            ))}
        </div>
      </div>
      {needsOnboard ? (
        <DomainOnboard
          key={domain}
          domain={domain}
          onSkip={() => {
            try {
              localStorage.setItem(skipKey, '1')
            } catch {
              /* fine: it will ask again next launch */
            }
            setSkipped(true)
          }}
          onDone={onChanged}
        />
      ) : tab === 'rec' ? (
        <Tonight
          domain={domain}
          state={tonight}
          setState={setTonight}
          name={status.name}
          reasons={status.pass_reasons[domain]}
          wantCount={counts.want}
          talked={status.talked}
          eta={eta}
          onChanged={onChanged}
        />
      ) : (
        <Shelf key={`${domain}-${tab}`} domain={domain} kind={tab} onChanged={onChanged} />
      )}
    </>
  )
}

function DomainOnboard({
  domain,
  onSkip,
  onDone,
}: {
  domain: Domain
  onSkip: () => void
  onDone: () => void
}) {
  const [stage, setStage] = useState<'wall' | 'build'>('wall')
  return (
    <div className="domain-onboard">
      {stage === 'wall' && (
        <CoverWall
          domain={domain}
          doneLabel="整理我的口味"
          onSkip={onSkip}
          onDone={async () => {
            await post('/interview/start', { domains: [domain] }).catch(() => {})
            setStage('build')
          }}
        />
      )}
      {stage === 'build' && <Build onDone={onDone} leaving={false} doneLabel={`去${DOMAINS[domain].pick3}`} />}
    </div>
  )
}
