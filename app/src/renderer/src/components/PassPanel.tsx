import { useState } from 'react'
import { enc, post, type Domain, type Item, type PassReason } from '../lib/api'
import { DOMAINS } from '../lib/domains'
import { Spinner } from './Icons'

const EFFECT_NOTE = {
  want: (list: string) => `放进${list}。过几天片刻会问你有没有顾上。`,
  taste: () => '记进口味画像，以后避开类似的。',
  moment: () => '只算这一次，不影响长期口味。',
}

/** "不想看": one tap on a reason records it. Each reason does something
 * different to memory, and the reason's tooltip and the line under the chips
 * say what. "多说一句" opens a box first for the user's own words. Saving
 * for later is its own button (先存着), not a reason here. */
export default function PassPanel({
  id,
  domain,
  reasons,
  recId,
  effects = ['taste', 'moment'],
  onDone,
  onCancel,
}: {
  id: string
  domain: Domain
  reasons: PassReason[]
  recId?: number | null
  effects?: PassReason['effect'][]
  onDone: (r: { item: Item; effect: PassReason['effect']; reason: string }) => void
  onCancel: () => void
}) {
  const c = DOMAINS[domain]
  const [hover, setHover] = useState<PassReason | null>(null)
  const [talk, setTalk] = useState(false)
  const [words, setWords] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const shown = reasons.filter((r) => effects.includes(r.effect))
  const submit = async (r: PassReason) => {
    if (busy) return
    setBusy(r.key)
    setErr(null)
    try {
      const out = await post<{ item: Item; effect: PassReason['effect']; reason: string }>(`/items/${enc(id)}/pass`, {
        reason: r.key,
        words: words.trim() || undefined,
        rec_id: recId ?? undefined,
      })
      onDone(out)
    } catch (e) {
      setErr(`没能记下来：${(e as Error).message}。再试一次。`)
      setBusy(null)
    }
  }
  return (
    <div className="fb-box pass-panel" onKeyDown={(e) => e.key === 'Escape' && onCancel()}>
      <div className="t13 secondary">为什么不想{c.verb}？点一下就记下。</div>
      {talk && (
        <textarea
          className="fb-input"
          style={{ marginTop: 8, minHeight: 48 }}
          placeholder="想多说一句也行。写完再点下面的原因。"
          value={words}
          autoFocus
          onChange={(e) => setWords(e.target.value)}
        />
      )}
      <div className="chip-row" style={{ marginTop: 8, flexWrap: 'wrap' }}>
        {shown.map((r) => (
          <button
            key={r.key}
            className={`chip${busy === r.key ? ' on' : ''}`}
            disabled={!!busy}
            onClick={() => submit(r)}
            onMouseEnter={() => setHover(r)}
            onMouseLeave={() => setHover(null)}
            onFocus={() => setHover(r)}
            onBlur={() => setHover(null)}
            data-pass={r.key}
          >
            {busy === r.key && <Spinner size={12} />}
            {r.label}
          </button>
        ))}
      </div>
      <div className="t13 secondary" style={{ marginTop: 8, minHeight: 20 }}>
        {hover ? EFFECT_NOTE[hover.effect](c.list) : ''}
      </div>
      {err && <div className="t13 danger">{err}</div>}
      <div className="fb-actions">
        {!talk && (
          <button className="pill-sm" onClick={() => setTalk(true)} disabled={!!busy}>
            多说一句
          </button>
        )}
        <button className="pill-sm dim" onClick={onCancel} disabled={!!busy}>
          算了
        </button>
      </div>
    </div>
  )
}
