import { useCallback, useEffect, useState } from 'react'
import { get, put, stream, type Claim, type Profile, type Status, type Title } from '../lib/api'
import { reltime } from '../lib/format'
import { morph } from '../lib/vt'
import { CheckDraw, PencilFillIcon, PlusIcon, SparklesFillIcon, Spinner, Tile, XmarkIcon } from '../components/Icons'
import { models, shortName } from '../lib/models'

interface Data {
  profile: Profile | null
  history: { version: number; ts: number; stats: Profile['stats'] }[]
  titles: Record<string, Title>
}

interface RunStep {
  key: string
  status: 'running' | 'done'
  detail?: string
}

/** The taste profile as a document the user can read and correct. Each
 * claim cites the records it came from; anything the user edits is kept
 * verbatim through later consolidations. */
export default function ProfilePage({ status, onChanged }: { status: Status; onChanged: () => void }) {
  const [data, setData] = useState<Data | null>(null)
  const [editing, setEditing] = useState<string | null>(null) // "sec:idx" or "sec:new"
  const [draft, setDraft] = useState('')
  const [running, setRunning] = useState<RunStep[] | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    setData(await get<Data>('/profile'))
  }, [])
  useEffect(() => {
    load().catch(() => {})
  }, [load])

  const save = async (doc: Profile['doc']) => {
    await put('/profile', { doc })
    await load()
    onChanged()
  }

  const commitEdit = async () => {
    if (!data?.profile || !editing) return
    const [key, idx] = editing.split(':')
    const doc: Profile['doc'] = JSON.parse(JSON.stringify(data.profile.doc))
    const sec = doc.sections.find((s) => s.key === key)!
    const text = draft.trim()
    if (idx === 'new') {
      if (text) sec.claims.push({ text, evidence: [], user: true })
    } else {
      const c = sec.claims[Number(idx)]
      if (!text) sec.claims.splice(Number(idx), 1)
      else if (c.text !== text) sec.claims[Number(idx)] = { ...c, text, user: true }
    }
    setEditing(null)
    await save(doc)
  }

  const remove = async (key: string, i: number) => {
    if (!data?.profile) return
    const doc: Profile['doc'] = JSON.parse(JSON.stringify(data.profile.doc))
    doc.sections.find((s) => s.key === key)!.claims.splice(i, 1)
    await save(doc)
  }

  const consolidate = async () => {
    setErr(null)
    setRunning([])
    try {
      await stream('/profile/consolidate', {}, (ev) => {
        if (ev.type === 'step') {
          setRunning((r) => {
            const rest = (r ?? []).filter((s) => s.key !== ev.key)
            return [...rest, { key: ev.key, status: ev.status, detail: ev.detail }]
          })
        } else if (ev.type === 'error') setErr(ev.message)
      })
    } catch (e) {
      setErr((e as Error).message)
    }
    setTimeout(async () => {
      await load()
      morph(() => setRunning(null))
      onChanged()
    }, 600)
  }

  const p = data?.profile
  return (
    <>
      <div className="top-strip drag-strip bar-solid" />
      <div className="page">
        <div className="rise-in">
          <span className="page-icon">
            <Tile color="var(--tile-purple)" size={56} icon={<SparklesFillIcon size={30} />} />
          </span>
          <div className="title-row">
            <h1 className="page-title">你的口味</h1>
            {p && !running && (
              <button className="pill-sm" onClick={consolidate} data-consolidate>
                重新整理
              </button>
            )}
          </div>
          {p && (
            <div className="pick-props" style={{ marginTop: 16 }}>
              <div className="prop-row">
                <span className="prop-label">版本</span>
                <span className="prop-value">第 {p.version} 版，{reltime(p.ts)}</span>
              </div>
              {p.stats.records !== undefined && (
                <div className="prop-row">
                  <span className="prop-label">依据</span>
                  <span className="prop-value">
                    {p.stats.records} 条记录
                    {p.stats.prompt_tokens ? `，读入 ${p.stats.prompt_tokens.toLocaleString()} 个 token` : ''}
                    {p.stats.seconds ? `，用时 ${p.stats.seconds} 秒` : ''}
                  </span>
                </div>
              )}
              <div className="prop-row">
                <span className="prop-label">存放</span>
                <span className="prop-value">只在这台 Mac 上</span>
              </div>
            </div>
          )}
        </div>

        {running && (
          <div className="steps consolidating rise-in">
            {[
              { key: 'read', label: '读完全部记录' },
              { key: 'write', label: '重写口味画像' },
            ].map((s) => {
              const st = running.find((r) => r.key === s.key)
              return (
                <div key={s.key} className={`step-row ${st?.status ?? 'wait'}`}>
                  <Tile color="var(--tile-purple)" icon={<SparklesFillIcon size={13} />} />
                  <div className="step-main">
                    <div className="step-label">{s.label}</div>
                    {st?.detail && <div className="step-detail">{st.detail}</div>}
                  </div>
                  <span className="step-state">
                    {st?.status === 'running' ? <Spinner /> : st?.status === 'done' ? <CheckDraw /> : null}
                  </span>
                </div>
              )
            })}
            {err && <div className="t13 danger" style={{ padding: '4px 16px 8px' }}>{err}</div>}
          </div>
        )}

        {!p && data && (
          <div className="empty-note secondary">还没有口味画像。看完、读完或听完几部，打个分、说说感受后，点“重新整理”。</div>
        )}

        {p && !running && status.stale > 0 && (
          <div className="callout stale-bar">
            <span className="said-ic" style={{ marginTop: 3 }}>
              <SparklesFillIcon size={15} />
            </span>
            <div style={{ flex: 1 }}>
              有 {status.stale} 条新记录还没整理进画像。整理时，{shortName(models().big)} 会把全部记录完整读一遍。
            </div>
            <button className="link-accent t13" onClick={consolidate}>
              现在整理
            </button>
          </div>
        )}

        {p && (
          <div key={p.version}>
            <div className="summary-line rise-in">{p.doc.summary}</div>
            {p.doc.sections.map((sec, si) => (
              <section key={sec.key} className="rise-in" style={{ animationDelay: `${80 + si * 80}ms` }}>
                <h2 className="section-h">{sec.title}</h2>
                {sec.claims.length === 0 && editing !== `${sec.key}:new` && (
                  <div className="secondary" style={{ padding: '6px 0' }}>
                    {sec.key === 'shift' ? '还看不出明显的变化。' : '暂时没有。'}
                  </div>
                )}
                {sec.claims.map((c, i) =>
                  editing === `${sec.key}:${i}` ? (
                    <EditLine key={i} draft={draft} setDraft={setDraft} commit={commitEdit} cancel={() => setEditing(null)} />
                  ) : (
                    <ClaimRow
                      key={`${i}-${c.text}`}
                      c={c}
                      titles={data!.titles}
                      onEdit={() => {
                        setDraft(c.text)
                        setEditing(`${sec.key}:${i}`)
                      }}
                      onRemove={() => remove(sec.key, i)}
                    />
                  )
                )}
                {editing === `${sec.key}:new` ? (
                  <EditLine draft={draft} setDraft={setDraft} commit={commitEdit} cancel={() => setEditing(null)} />
                ) : (
                  <button
                    className="add-claim"
                    onClick={() => {
                      setDraft('')
                      setEditing(`${sec.key}:new`)
                    }}
                  >
                    <PlusIcon size={13} />
                    添加一条
                  </button>
                )}
              </section>
            ))}
            {data!.history.length > 1 && (
              <div className="t13 secondary" style={{ marginTop: 48 }}>
                画像一共整理过 {data!.history.length} 次。
                {p.stats.diff ? `这一版新增 ${p.stats.diff.added} 条，去掉 ${p.stats.diff.removed} 条。` : ''}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}

function ClaimRow({
  c,
  titles,
  onEdit,
  onRemove,
}: {
  c: Claim
  titles: Record<string, Title>
  onEdit: () => void
  onRemove: () => void
}) {
  return (
    <div className="claim">
      <span className="claim-bullet" />
      <div className="claim-body">
        <div className="claim-text">{c.text}</div>
        {(c.evidence.length > 0 || c.user) && (
          <div className="claim-ev">
            {c.user && <span className="mine">你改过</span>}
            {c.evidence.map((e) => (
              <span key={e} className="ev-chip">
                {titles[e]?.name ?? e}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="claim-tools">
        <button className="icon-btn" aria-label="修改" onClick={onEdit}>
          <PencilFillIcon size={13} />
        </button>
        <button className="icon-btn" aria-label="删除" onClick={onRemove}>
          <XmarkIcon size={13} />
        </button>
      </div>
    </div>
  )
}

function EditLine({
  draft,
  setDraft,
  commit,
  cancel,
}: {
  draft: string
  setDraft: (s: string) => void
  commit: () => void
  cancel: () => void
}) {
  return (
    <div className="claim" style={{ background: 'var(--fill)' }}>
      <span className="claim-bullet" />
      <div className="claim-body">
        <textarea
          className="claim-edit"
          rows={1}
          autoFocus
          value={draft}
          placeholder="用你自己的话写一条"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              commit()
            }
            if (e.key === 'Escape') cancel()
          }}
        />
      </div>
    </div>
  )
}
