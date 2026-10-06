import { useEffect, useState } from 'react'
import { CheckDraw, CopyIcon } from './Icons'

/** Copies `text`; the icon turns into a check for a moment. With `label`
 *  it is a pill button, otherwise a bare icon beside what it copies. */
export default function CopyButton({ text, label, title = '拷贝' }: { text: string; label?: string; title?: string }) {
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (!done) return
    const t = setTimeout(() => setDone(false), 1400)
    return () => clearTimeout(t)
  }, [done])
  const copy = async () => {
    await window.pianke.copy(text)
    setDone(true)
  }
  if (label) {
    return (
      <button className="pill-sm" onClick={copy}>
        {done ? '已拷贝' : label}
      </button>
    )
  }
  return (
    <button className="copy-btn" onClick={copy} title={done ? '已拷贝' : title} aria-label={title}>
      {done ? <CheckDraw size={14} color="var(--accent)" /> : <CopyIcon size={14} />}
    </button>
  )
}
