import { useRef, useState } from 'react'

const STAR = 'M12 2.6l2.8 6 6.6.7-4.9 4.5 1.4 6.5L12 17l-5.9 3.3 1.4-6.5-4.9-4.5 6.6-.7z'

function StarGlyph({ fill, size }: { fill: number; size: number }) {
  // fill: 0, 0.5 or 1
  return (
    <span className="star" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
        <path d={STAR} className="star-empty" />
      </svg>
      {fill > 0 && (
        <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden className="star-on" style={{ clipPath: fill < 1 ? 'inset(0 50% 0 0)' : undefined }}>
          <path d={STAR} />
        </svg>
      )}
    </span>
  )
}

/** 0–5 stars in half steps. Click, drag across, or use the arrow keys.
 * Dragging to the far left gives 0 stars, which is a rating; "未评分"
 * (null) is separate and reached with the clear button. */
export default function StarRating({
  value,
  onChange,
  size = 26,
}: {
  value: number | null
  onChange: (v: number | null) => void
  size?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<number | null>(null)
  const [drag, setDrag] = useState(false)
  const dragging = useRef(false)
  const shown = hover ?? value ?? 0

  const at = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect()
    const x = Math.min(Math.max(clientX - r.left, 0), r.width)
    // a little dead zone on the left edge means zero
    if (x < size * 0.18) return 0
    return Math.min(5, Math.ceil((x / r.width) * 10) / 2)
  }

  return (
    <div className="rating">
      <div
        ref={ref}
        className={`rating-stars${drag ? ' dragging' : ''}`}
        role="slider"
        tabIndex={0}
        aria-label="评分"
        aria-valuemin={0}
        aria-valuemax={5}
        aria-valuenow={value ?? undefined}
        aria-valuetext={value == null ? '未评分' : `${value} 星`}
        onPointerDown={(e) => {
          ref.current!.setPointerCapture(e.pointerId)
          dragging.current = true
          setDrag(true)
          setHover(at(e.clientX))
        }}
        onPointerMove={(e) => setHover(at(e.clientX))}
        onPointerUp={(e) => {
          if (dragging.current) onChange(at(e.clientX))
          dragging.current = false
          setDrag(false)
          setHover(null)
        }}
        onPointerLeave={() => !dragging.current && setHover(null)}
        onKeyDown={(e) => {
          const v = value ?? 0
          if (e.key === 'ArrowRight' || e.key === 'ArrowUp') onChange(Math.min(5, v + 0.5))
          else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') onChange(Math.max(0, v - 0.5))
          else if (e.key === 'Backspace' || e.key === 'Delete') onChange(null)
          else return
          e.preventDefault()
        }}
        data-rating
      >
        {[1, 2, 3, 4, 5].map((i) => (
          <StarGlyph key={i} size={size} fill={shown >= i ? 1 : shown >= i - 0.5 ? 0.5 : 0} />
        ))}
      </div>
      <span className="rating-label t13">
        {hover != null ? `${hover} 星` : value == null ? '拖动或点击打分' : `${value} 星`}
      </span>
      {value != null && hover == null && (
        <button className="link-quiet t13" onClick={() => onChange(null)}>
          不打分
        </button>
      )}
    </div>
  )
}

/** Read-only stars for lists. */
export function StarsView({ n, size = 13 }: { n: number | null; size?: number }) {
  if (n == null) return null
  return (
    <span className="stars-view" aria-label={`${n} 星`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <StarGlyph key={i} size={size} fill={n >= i ? 1 : n >= i - 0.5 ? 0.5 : 0} />
      ))}
    </span>
  )
}
