import { useState } from 'react'
import { coverSrc, type Domain, type Title } from '../lib/api'
import { DOMAINS, creatorLine, domainOf } from '../lib/domains'

/** A work's cover (poster / book jacket / album art), fetched once by the
 * backend and cached. While it loads, or when none exists, a typographic
 * cover in a hue derived from the title stands in. */
export default function Cover({
  t,
  id,
  name,
  width,
  domain,
  radius,
}: {
  t?: Title | null
  id?: string
  name?: string
  width: number
  domain?: Domain
  radius?: number
}) {
  const wid = t?.id ?? id ?? ''
  const dom = domain ?? t?.domain ?? domainOf(wid)
  const aspect = DOMAINS[dom].aspect
  const [state, setState] = useState<'loading' | 'ok' | 'fail'>('loading')
  const src = wid ? coverSrc(wid) : null
  const label = t?.name ?? name ?? ''
  const hue = [...label].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 17)
  const h = Math.round(width / aspect)
  return (
    <span
      className={`cover cover-${dom}`}
      style={{ width, height: h, borderRadius: radius ?? (dom === 'music' ? 6 : 4), ['--cover-hue' as string]: hue }}
      data-cover={wid}
    >
      {state !== 'ok' && (
        <span className="cover-type" aria-hidden={state === 'loading'}>
          <span className="cover-type-name film-name" style={{ fontSize: Math.max(11, Math.min(18, width / 7)) }}>
            {label}
          </span>
          {width >= 90 && t && <span className="cover-type-by">{creatorLine(t)}</span>}
        </span>
      )}
      {src && state !== 'fail' && (
        <img
          src={src}
          alt=""
          loading="lazy"
          draggable={false}
          onLoad={() => setState('ok')}
          onError={() => setState('fail')}
          style={{ opacity: state === 'ok' ? 1 : 0 }}
        />
      )}
    </span>
  )
}
