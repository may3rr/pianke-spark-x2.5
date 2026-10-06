import { useState } from 'react'
import type { Domain, Status } from '../lib/api'
import { DOMAINS } from '../lib/domains'
import { morph } from '../lib/vt'
import CoverWall from '../components/CoverWall'
import Tonight, { type TonightState } from './Tonight'
import Shelf from './Shelf'
import { Build, Interview } from './Onboarding'

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
  onChanged,
}: {
  domain: Domain
  tab: Tab
  setTab: (t: Tab) => void
  status: Status
  tonight: TonightState
  setTonight: React.Dispatch<React.SetStateAction<TonightState>>
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
              <button
                key={t.key}
                className={`tab${tab === t.key ? ' on' : ''}`}
                onClick={() => {
                  if (t.key === 'rec' && tab === 'rec' && tonight.phase === 'result') {
                    morph(() => setTonight({ phase: 'compose', text: '', chips: {} }))
                  } else setTab(t.key)
                }}
                data-tab={t.key}
              >
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
          name={status.name}
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
  name,
  onSkip,
  onDone,
}: {
  domain: Domain
  name: string
  onSkip: () => void
  onDone: () => void
}) {
  const [stage, setStage] = useState<'wall' | 'talk' | 'build'>('wall')
  return (
    <div className="domain-onboard">
      {stage === 'wall' && (
        <CoverWall domain={domain} doneLabel="接着聊两句" onSkip={onSkip} onDone={() => setStage('talk')} />
      )}
      {stage === 'talk' && <Interview name={name} domains={[domain]} greet={false} onComplete={() => setStage('build')} />}
      {stage === 'build' && <Build onDone={onDone} leaving={false} doneLabel={`开始${DOMAINS[domain].pick3}`} />}
    </div>
  )
}
