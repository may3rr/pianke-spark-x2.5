import { useState } from 'react'
import { enc, post, type Domain, type Item, type PassReason } from '../lib/api'
import { DOMAINS } from '../lib/domains'

const EFFECT_NOTE = {
  want: (list: string) => `放进${list}。过几天片刻会问你有没有顾上。`,
  taste: () => '会记进口味画像，以后避开类似的。',
  moment: () => '只算这一次，不影响长期口味。',
}

/** "没看": pick one reason. Each reason does something different to
 * memory, and the note under the chips says what. */
export default function PassPanel({
  id,
  domain,
  reasons,
  recId,
  onDone,
  onCancel,
}: {
  id: string
  domain: Domain
  reasons: PassReason[]
  recId?: number | null
  onDone: (r: { item: Item; effect: PassReason['effect']; reason: string }) => void
  onCancel: () => void
}) {
  const c = DOMAINS[domain]
  const [sel, setSel] = useState<PassReason | null>(null)
  const [words, setWords] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (r: PassReason) => {
    if (busy) return
    setBusy(true)
    try {
      const out = await post<{ item: Item; effect: PassReason['effect']; reason: string }>(`/items/${enc(id)}/pass`, {
        reason: r.key,
        words: words.trim() || undefined,
        rec_id: recId ?? undefined,
      })
      onDone(out)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="fb-box pass-panel" onKeyDown={(e) => e.key === 'Escape' && onCancel()}>
      <div className="t13 secondary">为什么没{c.verb}？</div>
      <div className="chip-row" style={{ marginTop: 8, flexWrap: 'wrap' }}>
        {reasons.map((r) => (
          <button
            key={r.key}
            className={`chip${sel?.key === r.key ? ' on' : ''}${r.effect === 'want' ? ' chip-want' : ''}`}
            onClick={() => setSel(r)}
            data-pass={r.key}
          >
            {r.label}
          </button>
        ))}
      </div>
      {sel && (
        <>
          <div className="t13 secondary" style={{ marginTop: 8 }}>
            {EFFECT_NOTE[sel.effect](c.list)}
          </div>
          {sel.effect !== 'want' && (
            <textarea
              className="fb-input"
              style={{ marginTop: 8, minHeight: 48 }}
              placeholder="想多说一句也行，可以不写。"
              value={words}
              autoFocus
              onChange={(e) => setWords(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && submit(sel)}
            />
          )}
        </>
      )}
      <div className="fb-actions">
        <button className="pill-accent" disabled={!sel || busy} onClick={() => sel && submit(sel)} data-pass-submit>
          记下
        </button>
        <button className="pill-sm dim" onClick={onCancel}>
          算了
        </button>
      </div>
    </div>
  )
}
